"""Optional A2b bilingual LLM proposal observation; never changes retrieval.

The existing configured topic LLM provider is used only inside an explicitly
enabled report budget scope. This is a structural candidate count, not a
semantic equivalence verdict or a recall/precision measurement.
"""
from __future__ import annotations

from agent.arc_mode import arc_shadow_enabled

import json
import logging
import os

from agent.llm_utils.ollama_client import call_llm
from .arc_bilingual_proposal import SYSTEM_PROMPT, build_proposal_input, parse_proposal
from .arc_request_budget import ArcUnits, current_arc_budget
from .ordinary_scope_receipt import current_ordinary_scope_capture

_LOG = logging.getLogger("sraf.arc.bilingual")
MAX_INPUT_BYTES = 64000
REQUEST_TIMEOUT_SECONDS = 15
MAX_PREDICT_TOKENS = 1536


def bilingual_shadow_enabled() -> bool:
    return arc_shadow_enabled("SRAF_ARC_BILINGUAL")


def observe_bilingual_proposal(*, original_question, groups, manual) -> None:
    if not bilingual_shadow_enabled():
        return
    record = {"schema": "sraf_arc_bilingual_shadow_v1", "status": "unavailable"}
    try:
        from agent.external_capabilities import requirement_acceptance_active
        # Do not add a model call in acceptance, automatic-deep scope receipts,
        # manual entity mode or contexts without an original report question.
        if (requirement_acceptance_active()
                or current_ordinary_scope_capture() is not None
                or manual is not False
                or not os.getenv("TOPIC_LLM_URL")):
            record["status"] = "unsupported_scope"
            return
        scope = current_arc_budget()
        if scope is None:
            record["status"] = "missing_shared_budget"
            return
        payload = build_proposal_input(original_question, groups)
        if payload is None or len(payload.encode("utf-8")) > MAX_INPUT_BYTES:
            record["status"] = "unsupported_input"
            return
        budget, ordinal = scope
        if not budget.model_window_open():
            record["status"] = "model_deadline_or_scope_closed"
            return
        if not budget.reserve(ordinal, ArcUnits(llm_calls=1)):
            record["status"] = "shared_budget_exhausted"
            return
        raw = call_llm(payload, system_prompt=SYSTEM_PROMPT,
                       timeout=REQUEST_TIMEOUT_SECONDS,
                       extra_params={"options": {"num_predict": MAX_PREDICT_TOKENS}})
        if not budget.model_window_open(admission=False):
            record["status"] = "model_deadline_or_scope_closed"
            return
        proposed = parse_proposal(raw, groups)
        if proposed is None:
            record["status"] = "invalid_proposal"
            return
        record["status"] = "observed_candidates"
        record["groups"] = [
            {"group_ordinal": idx, "original_count": len(old),
             "candidate_added_count": len(new - old)}
            for idx, (old, new) in enumerate(zip(groups, proposed), 1)
        ]
    except Exception:
        # Model/transport failure is not a reason to change original results.
        record = {"schema": "sraf_arc_bilingual_shadow_v1", "status": "unavailable"}
    finally:
        _LOG.warning("SRAF_ARC_BILINGUAL=%s",
                     json.dumps(record, sort_keys=True, separators=(",", ":")))
