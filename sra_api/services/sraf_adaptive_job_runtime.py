"""Explicit server-owned deep-job intent and actual ReportJobWorker dispatch.

The existing public API cannot submit this intent. A trusted future admission
boundary must derive it from the original question and independently establish
real user/index and complete-query authorization. Runtime composition is
deliberately mandatory; no permissive defaults, new queue or fallback.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Callable

from agent.adaptive_retrieval.contracts import DateWindow, QueryConstraints, _bounded_text
from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
from agent.adaptive_retrieval.coverage_evaluator import RequestWideCoverageEvaluator
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from agent.adaptive_retrieval.planner import AdaptiveRetrievalPlanner
from agent.adaptive_retrieval.request_budget import RequestAdmissionBudget
from api.services.report_job_store import ADAPTIVE_JOB_OPTION, ADAPTIVE_OWNER_BINDING, ReportJob, ReportJobStore
from api.services.report_job_service import DEFAULT_REPORT_MODEL, create_job
from api.services.sraf_nround_claimed_job_runner import execute_claimed_nround_job


@dataclass(frozen=True, repr=False)
class AdaptiveJobIntent:
    constraints: QueryConstraints
    term_groups: tuple[tuple[str, ...], ...]
    effective_terms: tuple[str, ...]
    target_aspects: tuple[str, ...]

    def __post_init__(self):
        c = self.constraints
        if (type(c) is not QueryConstraints or c.fixed_fields
                or c.analysis_date.source != "none" or not c.original_core_terms
                or type(self.term_groups) is not tuple
                or not 1 <= len(self.term_groups) <= 32
                or type(self.effective_terms) is not tuple
                or not 1 <= len(self.effective_terms) <= 64
                or type(self.target_aspects) is not tuple):
            raise ValueError("unsupported_adaptive_intent")
        for group in self.term_groups:
            if type(group) is not tuple or not 1 <= len(group) <= 32:
                raise ValueError("unsupported_adaptive_intent")
            terms = [_bounded_text(term, limit=100) for term in group]
            if len(set(terms)) != len(terms):
                raise ValueError("unsupported_adaptive_intent")
        for term in self.effective_terms:
            _bounded_text(term, limit=100)
        RequestWideCoverageEvaluator(constraints=c, target_aspects=self.target_aspects)

    def options(self) -> dict:
        # JSON-normalized private intent is part of the existing request hash.
        import json
        return {ADAPTIVE_JOB_OPTION: json.loads(json.dumps(asdict(self), ensure_ascii=False))}

    @classmethod
    def from_options(cls, options: dict, prompt: str) -> AdaptiveJobIntent:
        try:
            if type(options) is not dict or set(options) != {ADAPTIVE_JOB_OPTION}:
                raise ValueError
            item = options[ADAPTIVE_JOB_OPTION]
            if type(item) is not dict or set(item) != {
                "constraints", "term_groups", "effective_terms", "target_aspects"
            }:
                raise ValueError
            raw = dict(item["constraints"])
            if raw.get("question") != prompt:
                raise ValueError
            for key in ("event_date", "analysis_date"):
                raw[key] = DateWindow(**raw[key])
            for key in ("allowed_indexes", "required_entities", "original_core_terms"):
                raw[key] = tuple(raw[key])
            raw["fixed_fields"] = tuple(tuple(p) for p in raw["fixed_fields"])
            intent = cls(QueryConstraints(**raw),
                         tuple(tuple(g) for g in item["term_groups"]),
                         tuple(item["effective_terms"]), tuple(item["target_aspects"]))
            # Reject coercion, unknown keys, malformed array types or drift.
            if intent.options() != options:
                raise ValueError
            return intent
        except Exception:
            raise ValueError("adaptive_intent_unverified") from None


def create_adaptive_job(store: ReportJobStore, *, intent: AdaptiveJobIntent,
                        owner_id: str, idempotency_key: str,
                        max_active_jobs: int, filename: str | None = None,
                        owner_binding: str | None = None):
    """Trusted internal admission only, not a principal authenticator.

    Caller MUST verify the actual user and scope BEFORE calling this helper.
    Service/shared-key identities are not accepted as individual users.
    """
    if (type(intent) is not AdaptiveJobIntent or type(owner_id) is not str
            or not owner_id.strip() or owner_id != owner_id.strip()
            or type(idempotency_key) is not str or not idempotency_key.strip()
            or type(max_active_jobs) is not int or not 1 <= max_active_jobs <= 10000
            or (owner_binding is not None and (type(owner_binding) is not str
                or re.fullmatch(r"[0-9a-f]{64}", owner_binding) is None))):
        raise ValueError("adaptive_admission_unverified")
    return create_job(store, prompt=intent.constraints.question, filename=filename,
                      session_id=None, model=DEFAULT_REPORT_MODEL, options=intent.options(),
                      metadata=({ADAPTIVE_OWNER_BINDING: owner_binding} if owner_binding is not None else {}),
                      idempotency_key=idempotency_key, owner_kind="user",
                      owner_id=owner_id, max_active_jobs=max_active_jobs,
                      register_adaptive=True)


@dataclass(frozen=True, repr=False)
class AdaptiveJobRuntime:
    """Installed only by trusted composition, not HTTP data or model output."""

    es_client_factory: Callable[[], Any]
    planner_call: Callable[..., str]
    semantic_assessor: Callable[..., bool]
    check_owner_index: Callable[[ReportJob, str], bool]
    check_question_branches: Callable[[ReportJob, QueryConstraints, tuple[str, ...]], bool]
    report_call: Callable[..., str]
    # Explicit server-selected model for the production composition. None is
    # retained only for existing internal callers using the shared model ID.
    report_model_id: str | None = None

    def __post_init__(self):
        if not all(callable(v) for v in (
            self.es_client_factory, self.planner_call, self.semantic_assessor,
            self.check_owner_index, self.check_question_branches, self.report_call,
        )):
            raise ValueError("adaptive_runtime_unverified")
        if self.report_model_id is not None:
            from api.services.sraf_nround_local_models import _model_name
            if not _model_name(self.report_model_id):
                raise ValueError("adaptive_runtime_model_invalid")

    def execute(self, store: ReportJobStore, job: ReportJob, reports_root: Path) -> None:
        intent = AdaptiveJobIntent.from_options(job.options, job.prompt)
        c = intent.constraints
        if (job.owner_kind != "user" or not job.owner_id
                or job.model != DEFAULT_REPORT_MODEL or job.status != "running"
                or job.phase != "agent_execution"):
            raise ValueError("adaptive_claim_unverified")
        checkpoint = NroundCheckpointStore(store.db_path)
        # Admission registered this row in the SAME transaction as queue creation.
        # Never auto-create missing intent/checkpoint on a claimed job.
        public = checkpoint.get_public(job.job_id)
        if public is None or public["state"] != "QUEUED":
            raise ValueError("adaptive_checkpoint_unverified")
        budget = RequestAdmissionBudget()
        def policy_check():
            live = store.get(job.job_id)
            if (live is None or live != job
                    or not all(self.check_owner_index(live, i) is True for i in c.allowed_indexes)
                    or self.check_question_branches(live, c, ("CANONICAL_MAIN",)) is not True):
                raise ValueError("adaptive_policy_denied")
        policy_check()
        def guarded_planner(prompt: str, *, system_prompt: str) -> str:
            policy_check()
            remaining = budget.snapshot()
            timeout = remaining.remaining_seconds - remaining.generation_reserve_seconds
            if timeout < 1:
                raise ValueError("adaptive_planner_deadline")
            result = self.planner_call(prompt, system_prompt=system_prompt, timeout=min(timeout, 60))
            policy_check()
            if budget.snapshot().remaining_seconds <= remaining.generation_reserve_seconds:
                raise ValueError("adaptive_planner_deadline")
            return result
        def guarded_semantic(target, evidence) -> bool:
            policy_check()
            remaining = budget.snapshot()
            timeout = remaining.remaining_seconds - remaining.generation_reserve_seconds
            if timeout < 1:
                raise ValueError("adaptive_semantic_deadline")
            result = self.semantic_assessor(target, evidence, timeout=min(timeout, 60))
            policy_check()
            if budget.snapshot().remaining_seconds <= remaining.generation_reserve_seconds:
                raise ValueError("adaptive_semantic_deadline")
            return result
        coordinator = AdaptiveRequestCoordinator(
            constraints=c, term_groups=intent.term_groups, effective_terms=intent.effective_terms,
            budget=budget, planner=AdaptiveRetrievalPlanner(guarded_planner),
        )
        evaluator = RequestWideCoverageEvaluator(constraints=c, target_aspects=intent.target_aspects)
        outcome = execute_claimed_nround_job(
            report_store=store, checkpoint_store=checkpoint, claimed_job=job,
            coordinator=coordinator, constraints=c, evaluator=evaluator,
            authorized_indexes=c.allowed_indexes, es_client=self.es_client_factory(),
            semantic_assessor=guarded_semantic, check_owner_index=self.check_owner_index,
            report_call=self.report_call, report_model_id=self.report_model_id,
            check_question_branches=self.check_question_branches,
            query_for_snippet=c.question[:2048],
        )
        outcome.generate_and_publish_word(reports_root)
