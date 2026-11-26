"""Optional A8 review of a deep round's report-approved canonical rows.

No new authority for Evidence selection or semantic coverage. The trusted
executor alone invokes this helper after its existing assessor has approved
the exact per-round report rows. A separate live source/egress policy must
approve the dedicated HTTPS endpoint and all candidate source IDs.
"""
from __future__ import annotations

from agent.arc_mode import arc_shadow_enabled

import json
import logging
import os

from agent.es.arc_request_budget import ArcUnits, current_arc_budget
from agent.es.arc_semantic_review_transport import observe_semantic_review
from agent.es.evidence_core.arc_semantic_review import (
    MAX_PREFIX, MAX_ROW_CHARS, build_semantic_review_batch,
)
from agent.es.evidence_core.models import EvidenceSnippet
from .evidence_ledger import CanonicalReportEvidence, _es_source_keys
from .private_semantic_binding import CanonicalSemanticGrant
from .round_query_execution import FrozenSingleQueryPlan, CompletedSingleQueryRound
from .worker_scope_binding import WorkerScopeBinding

_LOG = logging.getLogger("sraf.arc.deep_review")
MIN_REPORT_ROWS = 40
MAX_HITS = 128
MIN_ELIGIBLE = 4


def deep_review_enabled():
    return (arc_shadow_enabled("SRAF_ARC_REVIEW_DEEP")
            and arc_shadow_enabled("SRAF_ARC_REVIEW")
            and os.getenv("SRAF_ARC_REVIEW_EGRESS") == "approved")


def observe_deep_review(*, plan, binding, fetched, grant):
    if not deep_review_enabled() or type(binding) is not WorkerScopeBinding:
        return
    from agent.external_capabilities import requirement_acceptance_active

    if requirement_acceptance_active():
        return
    record = {"schema": "sraf_arc_deep_review_admission_v1", "status": "unavailable"}
    try:
        if (type(plan) is not FrozenSingleQueryPlan
                or type(fetched) is not CompletedSingleQueryRound
                or type(grant) is not CanonicalSemanticGrant
                or binding._check_review_egress is None
                or plan._owner_binding_token is not binding._binding_token
                or fetched._execution_token is not plan._execution_token
                or fetched.round_number != plan.round_number
                or fetched.query_plan_complete is not True
                or grant.observation.complete is not True
                or len(plan.constraints.allowed_indexes) != 1
                or not 1 <= len(fetched.hits) <= MAX_HITS):
            record["status"] = "unsupported_scope"
            return
        if len(grant._report_rows) < MIN_REPORT_ROWS:
            record["status"] = "below_review_pressure"
            return
        index = plan.constraints.allowed_indexes[0]
        if index != os.getenv("SRAF_ARC_REVIEW_VERIFIED_INDEX"):
            record["status"] = "unverified_index"
            return
        progress = plan.coordinator.safe_progress()
        remaining = plan.coordinator._budget.snapshot()
        if (progress["phase"] != "SEARCHING" or progress["round"] != plan.round_number
                or remaining.remaining_seconds - remaining.generation_reserve_seconds < 25):
            record["status"] = "not_current_or_insufficient_time"
            return
        scope = current_arc_budget()
        if scope is None or scope[1] != plan.round_number:
            record["status"] = "missing_shared_budget"
            return
        budget, ordinal = scope
        if not budget.reserve(ordinal, ArcUnits(slices=1, hits=MAX_HITS,
                                                rows=MAX_PREFIX, chars=MAX_PREFIX * MAX_ROW_CHARS)):
            record["status"] = "shared_budget_exhausted"
            return
        keys = _es_source_keys(list(fetched.hits))
        if (frozenset(keys) != grant.observation.candidate_sources
                or any(h.get("_index") != index for h in fetched.hits)):
            record["status"] = "source_scope_mismatch"
            return
        source_positions = {key: i for i, key in enumerate(keys)}
        prefix = grant._report_rows[:MAX_PREFIX]
        evidence = []
        approved_sources = set()
        for row in prefix:
            if (type(row) is not CanonicalReportEvidence
                    or row.pair not in grant.observation.evidence_source_pairs
                    or row.pair[1] not in source_positions):
                record["status"] = "source_scope_mismatch"
                return
            text = row.passage.text
            if (row.match_policy != "strict" or row.structured is not True
                    or not row.passage.matched_event_times or not row.doc_id
                    or type(text) is not str or not 0 < len(text) <= MAX_ROW_CHARS
                    or not text.strip() or row.scope not in ("text", "meta", "mixed")
                    or type(row.weak) is not bool):
                continue
            i = source_positions[row.pair[1]]
            approved_sources.add(fetched.hits[i]["_id"])
            evidence.append(EvidenceSnippet(uuid="", text=text, date_iso="", article_date_iso="",
                            match_policy="strict", match_scope=row.scope,
                            weak_evidence=row.weak, source_hit_ordinal=i))
        if (len(evidence) < MIN_ELIGIBLE
                or not any(e.weak_evidence or e.match_scope in ("meta", "mixed") for e in evidence)):
            record["status"] = "no_bounded_ambiguity"
            return
        batch = build_semantic_review_batch(plan.constraints.question,
                    [set(g) for g in plan.coordinator._groups], evidence)
        if batch is None or batch.count < MIN_ELIGIBLE:
            record["status"] = "unsupported_batch"
            return
        # The independent policy sees all possible batch source IDs, not
        # guessed UUIDs; conservative superset approval avoids a second
        # copy of the private per-row model selection contract.
        source_ids = tuple(sorted(approved_sources))
        observe_semantic_review(batch, index=index, authorize=lambda endpoint:
            binding.check_optional_review_egress(plan, index=index,
                source_ids=source_ids, approved=endpoint))
        record["status"] = "transport_observation_requested"
    except Exception:
        pass
    finally:
        _LOG.warning("SRAF_ARC_DEEP_REVIEW_ADMISSION=%s",
                     json.dumps(record, sort_keys=True, separators=(",", ":")))
