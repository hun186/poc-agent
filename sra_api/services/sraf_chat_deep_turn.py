"""Private chat turn identity and replay gate, before automatic dispatch.

No client-supplied owner, session ID, prompt-derived key or service-key
impersonation. A client adapter must supply a stable, per-turn token on
retries. This module does not submit a job or modify a chat response.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

from api.security.models import AuthPrincipal
from api.services.report_job_store import (
    ADAPTIVE_JOB_OPTION, ADAPTIVE_OWNER_BINDING, CHAT_DEEP_KEY_PREFIX,
    ReportJobStore, IdempotencyConflict,
)
from api.services.report_job_service import normalized_hash, DEFAULT_REPORT_MODEL
from api.services.sraf_adaptive_job_runtime import AdaptiveJobRuntime, AdaptiveJobIntent
from api.services.sraf_deep_scope_policy import DeepScopePolicy, DeepScopeDenied
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from api.services.sraf_session_namespace import ScopedChatSession, scoped_session_owned


class DeepRuntimeUnavailable(ValueError):
    """Fixed unavailable reason."""


def resolve_deep_admission(state):
    """One exact composition check for explicit and future chat admission."""
    from api.services.report_job_worker import ReportJobWorker
    policy = getattr(state, "deep_scope_policy", None)
    worker = getattr(state, "report_job_worker", None)
    store = getattr(state, "report_job_store", None)
    runtime = getattr(worker, "adaptive_runtime", None)
    if (type(policy) is not DeepScopePolicy or type(store) is not ReportJobStore
            or type(worker) is not ReportJobWorker or worker.store is not store
            or type(runtime) is not AdaptiveJobRuntime
            or runtime.check_owner_index != policy.check_owner_index
            or runtime.check_question_branches != policy.check_question_branches):
        raise DeepRuntimeUnavailable("deep_runtime_unavailable")
    return policy, store


_TOKEN = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")


@dataclass(frozen=True, repr=False)
class ChatDeepTurn:
    principal: AuthPrincipal
    account_binding: str
    key: str
    session_key: str
    policy: DeepScopePolicy = field(compare=False)
    store: ReportJobStore = field(compare=False)


def prepare_chat_deep_turn(state, principal: AuthPrincipal, *, turn_tokens: tuple[str, ...],
                           scoped_session: ScopedChatSession):
    """Trusted HTTP caller passes all Idempotency-Key header values.

    Missing or duplicate header, malformed value, non-user identity or
    revoked/ungranted account must never create or reuse a deep job.
    Token is an idempotency hint, never a credential or ownership proof.
    """
    if (type(turn_tokens) is not tuple or len(turn_tokens) != 1
            or type(turn_tokens[0]) is not str or not _TOKEN.fullmatch(turn_tokens[0])):
        raise DeepScopeDenied("deep_chat_turn_key_invalid")
    if type(scoped_session) is not ScopedChatSession or not scoped_session_owned(scoped_session.key, principal):
        raise DeepScopeDenied("deep_chat_session_unverified")
    policy, store = resolve_deep_admission(state)
    _, binding = policy._verified_principal(principal)
    # Intentionally exclude prompt and access token from the key: same turn
    # with changed prompt must conflict, while a refreshed JWT can replay.
    raw = json.dumps(["scoped-turn-v2", principal.subject, binding, scoped_session.key, turn_tokens[0]],
                     ensure_ascii=False, separators=(",", ":")).encode()
    key = CHAT_DEEP_KEY_PREFIX + hashlib.sha256(raw).hexdigest()
    return ChatDeepTurn(principal, binding, key, scoped_session.key, policy, store)


def replay_chat_deep_turn(state, turn: ChatDeepTurn, *, prompt: str):
    """Look up an already-persisted exact turn; never creates or retries work.

    Needed because ordinary session history may exist on HTTP retry, so a
    new receipt cannot be required merely to retrieve the prior accepted job.
    Revalidate owner generation, current policy, stored scope and request
    hash, and the persistent checkpoint before returning a job.
    """
    if type(turn) is not ChatDeepTurn:
        raise DeepScopeDenied("deep_chat_turn_invalid")
    policy, store = resolve_deep_admission(state)
    if policy is not turn.policy or store is not turn.store:
        raise DeepRuntimeUnavailable("deep_runtime_unavailable")
    _, binding = policy._verified_principal(turn.principal)
    if binding != turn.account_binding or not scoped_session_owned(turn.session_key, turn.principal):
        raise DeepScopeDenied("deep_owner_denied")
    job = store.get_chat_deep_replay(owner_id=turn.principal.subject, key=turn.key)
    if job is None:
        return None
    if job.prompt != prompt:
        raise IdempotencyConflict("Idempotency-Key was already used for a different request")
    if (job.owner_kind != "user" or job.owner_id != turn.principal.subject
            or job.idempotency_key != turn.key or job.model != DEFAULT_REPORT_MODEL
            or job.filename is not None or job.metadata != {ADAPTIVE_OWNER_BINDING: binding}
            or ADAPTIVE_JOB_OPTION not in job.options):
        raise DeepScopeDenied("deep_chat_replay_unverified")
    intent = AdaptiveJobIntent.from_options(job.options, job.prompt)
    expected_hash = normalized_hash({
        "prompt": job.prompt, "filename": None, "session_id": None,
        "model": job.model, "options": job.options, "metadata": job.metadata,
    })
    if (expected_hash != job.request_hash
            or not policy.check_question_branches(job, intent.constraints, ("CANONICAL_MAIN",))
            or not all(policy.check_owner_index(job, i) for i in intent.constraints.allowed_indexes)
            or NroundCheckpointStore(store.db_path).get_public(job.job_id) is None
            or policy._verified_principal(turn.principal)[1] != binding):
        raise DeepScopeDenied("deep_chat_replay_unverified")
    return job
