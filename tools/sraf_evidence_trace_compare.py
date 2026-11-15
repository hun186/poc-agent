#!/usr/bin/env python3
"""Compare two opt-in SRAF report Evidence count traces without accessing data.

Stdlib-only; read-only inputs; numeric-only output. Does not establish that two
reports have comparable questions, times, indices, model behavior or quality.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
from typing import Any

_MARKER = "SRAF_REPORT_EVIDENCE_TRACE="
_MAX_FILE_BYTES = 65_536
_MAX_COUNT = 1_000_000_000
_SCOPE = "single_report_pre_llm_not_final_report_or_token_count"
_SCHEMA = "sraf_report_evidence_counts_v1"
_COUNTER_FIELDS = {
    "incoming", "strong", "weak", "picked", "compressed", "llm_input",
    "max_for_llm", "prompt_chars", "truncated_notes", "truncated_titles",
    "incoming_identified_sources", "picked_identified_sources",
    "llm_input_identified_sources", "strong_or_weak_unselected",
    "removed_during_compression", "removed_after_field_selection",
}
_COMPARE_FIELDS = (
    "incoming", "picked", "compressed", "llm_input",
    "incoming_identified_sources", "picked_identified_sources",
    "llm_input_identified_sources", "prompt_chars",
)
_OUTER_FIELDS = {
    "schema", "scope", "trace_id",
    "report_llm_skipped_incomplete_search", "counters",
}


def _read_limited_regular_file(path: str) -> str:
    """Open a bounded regular file without following symlinks on POSIX."""
    if not hasattr(os, "O_NOFOLLOW") and os.path.islink(path):
        raise ValueError("untrusted_file")
    # O_NONBLOCK is essential: opening a FIFO with no writer otherwise hangs
    # before fstat can reject a non-regular file.
    flags = (os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    fd = os.open(path, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > _MAX_FILE_BYTES:
            raise ValueError("untrusted_file")
        chunks: list[bytes] = []
        remaining = _MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _MAX_FILE_BYTES:
            raise ValueError("untrusted_file")
        return raw.decode("utf-8")
    finally:
        os.close(fd)


def read_count_trace(path: str) -> dict[str, Any]:
    """Return only validated numeric data and one non-output correlation ID."""
    lines = _read_limited_regular_file(path).splitlines()
    matches = [line.split(_MARKER, 1)[1].strip()
               for line in lines if _MARKER in line]
    if len(matches) != 1:
        raise ValueError("ambiguous_trace")
    payload = json.loads(matches[0])
    if not isinstance(payload, dict) or set(payload) != _OUTER_FIELDS:
        raise ValueError("invalid_trace")
    if payload["schema"] != _SCHEMA or payload["scope"] != _SCOPE:
        raise ValueError("invalid_trace")
    if not isinstance(payload["report_llm_skipped_incomplete_search"], bool):
        raise ValueError("invalid_trace")
    trace_id = payload["trace_id"]
    if not isinstance(trace_id, str) or not re.fullmatch(r"[0-9a-f]{16}", trace_id):
        raise ValueError("invalid_trace")
    counters = payload["counters"]
    if not isinstance(counters, dict) or set(counters) != _COUNTER_FIELDS:
        raise ValueError("invalid_trace")
    for value in counters.values():
        if type(value) is not int or not 0 <= value <= _MAX_COUNT:
            raise ValueError("invalid_trace")
    if (
        counters["strong"] + counters["weak"] != counters["incoming"]
        or not counters["llm_input"] <= counters["compressed"]
            <= counters["picked"] <= counters["incoming"]
        or counters["picked"] > counters["max_for_llm"]
        or counters["incoming_identified_sources"] > counters["incoming"]
        or counters["picked_identified_sources"] > counters["picked"]
        or counters["llm_input_identified_sources"] > counters["llm_input"]
    ):
        raise ValueError("invalid_trace")
    return {
        "trace_id": trace_id,
        "skipped": payload["report_llm_skipped_incomplete_search"],
        "counts": {name: counters[name] for name in _COMPARE_FIELDS},
    }


def compare_count_traces(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Never include trace IDs, paths, user questions or raw evidence."""
    if before["trace_id"] == after["trace_id"]:
        raise ValueError("same_trace")
    old, new = before["counts"], after["counts"]
    warnings = [
        "not_verified_same_question_time_index_or_corpus",
        "source_counts_exclude_unidentified_documents",
        "prompt_chars_are_not_tokens",
        "not_private_es_llm_docx_or_report_quality_acceptance",
    ]
    if before["skipped"] or after["skipped"]:
        warnings.append("at_least_one_report_llm_skipped_incomplete_search")
    return {
        "schema": "sraf_report_evidence_comparison_v1",
        "status": "PASS_PARTIAL",
        "scope": "offline_count_comparison_only",
        "baseline": old,
        "candidate": new,
        "delta_after_minus_before": {
            field: new[field] - old[field] for field in _COMPARE_FIELDS
        },
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only numeric SRAF Report Evidence trace comparison"
    )
    parser.add_argument("--baseline", required=True, help="One sanitized report trace")
    parser.add_argument("--candidate", required=True, help="One sanitized report trace")
    args = parser.parse_args(argv)
    try:
        before = read_count_trace(args.baseline)
        after = read_count_trace(args.candidate)
        result = compare_count_traces(before, after)
    except (OSError, ValueError, UnicodeError, TypeError, KeyError):
        # No file path, raw payload, or internal exception is exposed.
        result = {
            "schema": "sraf_report_evidence_comparison_v1",
            "status": "INCOMPLETE",
            "reason": "invalid_or_ambiguous_trace_input",
        }
        print("SRAF_EVIDENCE_TRACE_COMPARISON=" + json.dumps(
            result, ensure_ascii=True, sort_keys=True
        ))
        return 2
    print("SRAF_EVIDENCE_TRACE_COMPARISON=" + json.dumps(
        result, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
