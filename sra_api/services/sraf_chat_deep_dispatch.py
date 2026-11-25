"""Opt-in automatic deep admission after the ordinary report is delivered internally.

No additional model calls in the HTTP request; only independent scope
compilation, a bounded SQLite lookup/insert and authenticated status links.
The ordinary scope receipt is never serialized. A missing or mismatched
receipt cannot create a Job; a previously accepted exact turn can be replayed.
"""
from __future__ import annotations

from api.security.models import AuthPrincipal
from agent.es.ordinary_scope_receipt import OrdinaryScopeReceipt
from api.services.turn_execution import AgentTurnResult
from api.services.sraf_chat_deep_turn import (
    ChatDeepTurn, prepare_chat_deep_turn, replay_chat_deep_turn, resolve_deep_admission,
    DeepRuntimeUnavailable,
)
from api.services.sraf_deep_scope_policy import compile_deep_question, DeepScopeDenied
from api.services.sraf_adaptive_job_runtime import create_adaptive_job
from api.services.sraf_deep_startup_config import validate_chat_public_base
from api.services.report_job_service import browser_status_url

_STATUS = {
    "queued": "排隊中",
    "running": "執行中",
    "completed": "已完成（登入後可下載）",
    "failed": "執行失敗",
    "interrupted": "已中斷",
    "cancelled": "已取消",
}


def prepare_auto_chat(state, principal: AuthPrincipal, *, turn_tokens: tuple[str, ...],
                      fmt: str) -> ChatDeepTurn | None:
    """Return an optional private admission context; never fail ordinary chat."""
    if (getattr(state, "deep_chat_auto_base_url", None) is None
            or type(principal) is not AuthPrincipal or principal.kind != "user"
            or fmt != "markdown"):
        return None
    try:
        validate_chat_public_base(state.deep_chat_auto_base_url)
        return prepare_chat_deep_turn(state, principal, turn_tokens=turn_tokens)
    except Exception:
        return None


def _scope_matches(receipt: OrdinaryScopeReceipt | None, constraints) -> bool:
    # Exact literal index, date and core terms. No inference from output,
    # router metadata or LLM-rewritten question. Requiring identical scope
    # may abstain when a grant includes more indexes than the ordinary search.
    return (
        type(receipt) is OrdinaryScopeReceipt
        and receipt.indexes == constraints.allowed_indexes
        and (receipt.date_from, receipt.date_to) ==
            (constraints.event_date.start, constraints.event_date.end)
        and receipt.core_terms == constraints.original_core_terms
        and constraints.analysis_date.source == "none"
        and not constraints.fixed_fields
        and not constraints.required_entities
        and constraints.keyword_policy == "flexible"
    )


def admit_after_ordinary(state, identity: ChatDeepTurn, ordinary: AgentTurnResult):
    """Trusted post-response builder; return only a verified persisted Job."""
    if (type(identity) is not ChatDeepTurn or type(ordinary) is not AgentTurnResult
            or ordinary.output.get("mode") != "SRA_REPORT"):
        raise DeepScopeDenied("deep_chat_scope_unverified")
    if getattr(state, "deep_chat_auto_base_url", None) is None:
        raise DeepRuntimeUnavailable("deep_runtime_unavailable")
    validate_chat_public_base(state.deep_chat_auto_base_url)
    prompt = ordinary.user_message
    existing = replay_chat_deep_turn(state, identity, prompt=prompt)
    if existing is not None:
        return existing, False
    policy, store = resolve_deep_admission(state)
    if policy is not identity.policy or store is not identity.store:
        raise DeepRuntimeUnavailable("deep_runtime_unavailable")
    grant, binding = policy._verified_principal(identity.principal)
    if binding != identity.account_binding:
        raise DeepScopeDenied("deep_owner_denied")
    intent = compile_deep_question(prompt, grant.indexes)
    if not _scope_matches(ordinary.ordinary_scope, intent.constraints):
        raise DeepScopeDenied("deep_chat_scope_unverified")
    if policy._verified_principal(identity.principal) != (grant, binding):
        raise DeepScopeDenied("deep_owner_denied")
    job, created = create_adaptive_job(
        store, intent=intent, owner_id=identity.principal.subject,
        owner_binding=binding, idempotency_key=identity.key,
        max_active_jobs=policy.max_active_jobs,
    )
    # Includes same-transaction checkpoint and current owner/scope validation.
    verified = replay_chat_deep_turn(state, identity, prompt=prompt)
    if verified is None or verified.job_id != job.job_id:
        raise DeepScopeDenied("deep_chat_replay_unverified")
    return verified, created


def append_deep_chat_status(response: dict, state, identity, ordinary) -> None:
    """Called only after ordinary rendering, snapshots/session save and trace.

    A failure (including queue-full, invalid scope, storage or URL error)
    must leave ordinary answer and Word intact, without a fake Job ID.
    """
    if identity is None or ordinary.output.get("mode") != "SRA_REPORT":
        return
    try:
        base = validate_chat_public_base(state.deep_chat_auto_base_url)
        message = response["choices"][0]["message"]
        if type(message.get("content")) is not str or type(message.get("context")) is not dict:
            return
        job, created = admit_after_ordinary(state, identity, ordinary)
        relative = browser_status_url(job.job_id)
        if relative is None or job.status not in _STATUS:
            raise ValueError("invalid_deep_status")
        url = base + relative
        prefix = "已建立" if created else "沿用同一訊息先前建立的"
        suffix = (
            "\n\n---\n\n**深度多輪報告（另行執行）**\n\n"
            "上方 Word 為一般版單輪報告。"
            + prefix + "深度報告任務，目前狀態：" + _STATUS[job.status] + "。\n\n"
            + "[查看深度版進度／完成後下載 Word](" + url + ")\n\n"
            "可關閉此頁，稍後以相同 SRAF 帳號登入查看；未完成時不提供深度 Word。"
        )
        message["content"] += suffix
        message["context"]["deep_report"] = {
            "job_id": job.job_id, "status": job.status, "browser_status_url": url,
        }
    except Exception:
        # Fixed message only. Never expose internal prompt, scope, index, token
        # or claim that admission succeeded if its verification failed.
        try:
            response["choices"][0]["message"]["content"] += (
                "\n\n深度版本次無法自動確認任務；上方一般版報告不受影響。"
            )
        except Exception:
            pass
