"""Optional post-retrieval allocation of existing ARC shadow LLM work.

The shared budget remains the authority for atomic consumption. This policy
only chooses which of the currently wired observations should attempt it.
A8 is not callable here until a separately authorized live caller exists.
"""
from __future__ import annotations

from agent.arc_mode import arc_shadow_enabled

import json
import logging
import os

from .arc_bilingual_shadow import bilingual_shadow_enabled, observe_bilingual_proposal
from .arc_strategy_shadow import route_strategy, strategy_enabled, observe_strategy
from .arc_bilingual_proposal import build_proposal_input
from .arc_request_budget import current_arc_budget
from .evidence_core.arc_tighten_shadow import CandidatePressure
from .ordinary_scope_receipt import current_ordinary_scope_capture

_LOG = logging.getLogger("sraf.arc.llm_priority")


def llm_priority_enabled():
    return arc_shadow_enabled("SRAF_ARC_LLM_PRIORITY")


def choose_llm_work(*, pressure, diagnostics, final_count, strong_count, refill,
                    manual, bilingual_enabled, strategy_enabled):
    """Return a bounded reason and one currently supported advisory task.

    The same A7 route is reused, not an independent interpretation of
    A5/A6 counts. Zero candidates, date/source attrition, existing safe
    alternatives, incomplete retrieval and adequate volume are not reasons
    to spend an extra model call. A2 is preferred only for the explicit
    unresolved low-volume alias review route; A7 handles other ambiguity.
    """
    if (type(pressure) is not CandidatePressure or type(diagnostics) is not dict
            or type(bilingual_enabled) is not bool or type(strategy_enabled) is not bool):
        return "unconfirmed_primary", "none"
    reason, choices = route_strategy(
        pressure=pressure, low=diagnostics.get("low"), high=diagnostics.get("high"),
        final_count=final_count, strong_count=strong_count, refill=refill, manual=manual,
    )
    if not choices:
        return reason, "none"
    if reason == "semantic_low_review" and "review_aliases" in choices and bilingual_enabled:
        return reason, "bilingual"
    if strategy_enabled:
        return reason, "strategy"
    return reason, "none"


def observe_allocated_llm(*, pressure, diagnostics, final_count, strong_count, refill,
                          original_question, groups, manual):
    """At most one attempted existing model task; no fallback on failure.

    A7 may still record its deterministic decision without model access.
    A2/A7 retain their own input, scope, budget and response validation.
    No Evidence text is passed here; no A8 call or new retrieval action.
    """
    if not llm_priority_enabled():
        return
    from agent.external_capabilities import requirement_acceptance_active

    record = {"schema": "sraf_arc_llm_priority_shadow_v1", "status": "unavailable",
              "choice": "none"}
    try:
        if (requirement_acceptance_active() or current_ordinary_scope_capture() is not None
                or manual is not False or current_arc_budget() is None):
            record["status"] = "unsupported_scope"
            return
        a2 = bilingual_shadow_enabled()
        a7 = strategy_enabled()
        reason, choice = choose_llm_work(
            pressure=pressure, diagnostics=diagnostics, final_count=final_count,
            strong_count=strong_count, refill=refill, manual=manual,
            bilingual_enabled=a2, strategy_enabled=a7,
        )
        record.update(status="observed_priority", reason=reason)
        if choice != "none":
            if not os.getenv("TOPIC_LLM_URL"):
                record["status"] = "provider_unavailable"
                choice = "none"
            else:
                payload = build_proposal_input(original_question, groups)
                if payload is None or len(payload.encode("utf-8")) > 64000:
                    record["status"] = "unsupported_input"
                    choice = "none"
        record["choice"] = choice
        if a7:
            observe_strategy(
                pressure=pressure, diagnostics=diagnostics, final_count=final_count,
                strong_count=strong_count, refill=refill, original_question=original_question,
                groups=groups, manual=manual, allow_model=choice == "strategy",
            )
        if choice == "bilingual":
            observe_bilingual_proposal(original_question=original_question,
                                       groups=groups, manual=manual)
    except Exception:
        # Optional observations never change the formal output.
        record["status"] = "unavailable"
    finally:
        _LOG.warning("SRAF_ARC_LLM_PRIORITY=%s",
                     json.dumps(record, sort_keys=True, separators=(",", ":")))
