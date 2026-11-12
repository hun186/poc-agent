"""Private, opt-in count-only observability of report Evidence sent to the LLM.

All inputs to the emitted log are numeric counts and a bool determined at the
callsite; no source identifiers, dates, queries, notes or prompts are logged.
"""
from __future__ import annotations

import json
import logging
import os
import secrets

_LOG = logging.getLogger("sraf.report_evidence_trace")


def emit_report_evidence_trace(
    *, incoming: int, strong: int, weak: int,
    picked: int, compressed: int, llm_input: int,
    max_for_llm: int, prompt_chars: int,
    truncated_notes: int = 0, truncated_titles: int = 0,
    skipped_incomplete: bool = False,
) -> None:
    """One invocation per report attempt, before its report LLM request.

    Counts are measured by caller from the actual lists after each stage.
    Character counts are NOT token counts; this does not audit LLM completion.
    """
    if os.environ.get("SRAF_EVIDENCE_TRACE") != "1":
        return
    raw_counts = {
        "incoming": incoming,
        "strong": strong,
        "weak": weak,
        "picked": picked,
        "compressed": compressed,
        "llm_input": llm_input,
        "max_for_llm": max_for_llm,
        "prompt_chars": prompt_chars,
        "truncated_notes": truncated_notes,
        "truncated_titles": truncated_titles,
    }
    # No user-controlled content or data fields are accepted by this logger.
    counts = {key: max(0, int(value)) for key, value in raw_counts.items()}
    counters = {
        **counts,
        "strong_or_weak_unselected": max(0, counts["incoming"] - counts["picked"]),
        "removed_during_compression": max(0, counts["picked"] - counts["compressed"]),
        "removed_after_field_selection": max(0, counts["compressed"] - counts["llm_input"]),
    }
    payload = {
        "schema": "sraf_report_evidence_counts_v1",
        "scope": "single_report_pre_llm_not_final_report_or_token_count",
        "trace_id": secrets.token_hex(8),
        "report_llm_skipped_incomplete_search": bool(skipped_incomplete),
        "counters": counters,
    }
    _LOG.warning("SRAF_REPORT_EVIDENCE_TRACE=%s", json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ))
