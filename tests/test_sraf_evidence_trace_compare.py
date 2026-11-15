"""Offline count comparison: privacy, ambiguity, bounds, CLI and schema."""
from __future__ import annotations

import json
import os

import pytest

from tools.sraf_evidence_trace_compare import (
    compare_count_traces, main, read_count_trace,
)


def _trace(trace_id, *, picked=2, sources=1, llm_input=2, prompt_chars=530):
    counters = {
        "incoming": 5, "strong": 4, "weak": 1,
        "picked": picked, "compressed": picked, "llm_input": llm_input,
        "max_for_llm": 120, "prompt_chars": prompt_chars,
        "truncated_notes": 0, "truncated_titles": 0,
        "incoming_identified_sources": 3,
        "picked_identified_sources": sources,
        "llm_input_identified_sources": sources,
        "strong_or_weak_unselected": 5 - picked,
        "removed_during_compression": 0,
        "removed_after_field_selection": picked - llm_input,
    }
    return {
        "schema": "sraf_report_evidence_counts_v1",
        "scope": "single_report_pre_llm_not_final_report_or_token_count",
        "trace_id": trace_id,
        "report_llm_skipped_incomplete_search": False,
        "counters": counters,
    }


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(
        "other log line with SENSITIVE-RAW-EVIDENCE\n"
        "2026-11-15 WARNING SRAF_REPORT_EVIDENCE_TRACE="
        + json.dumps(payload) + "\n", encoding="utf-8"
    )
    return str(path)


def test_count_comparison_is_numeric_and_does_not_output_sensitive_data(
        tmp_path, capsys):
    before = _write(tmp_path, "before.txt", _trace("a" * 16))
    after = _write(tmp_path, "after.txt", _trace(
        "b" * 16, picked=3, sources=2, llm_input=3, prompt_chars=600
    ))
    assert main(["--baseline", before, "--candidate", after]) == 0
    output = capsys.readouterr().out
    obj = json.loads(output.partition("SRAF_EVIDENCE_TRACE_COMPARISON=")[2])
    assert obj["status"] == "PASS_PARTIAL"
    assert obj["delta_after_minus_before"]["picked"] == 1
    assert obj["delta_after_minus_before"]["llm_input_identified_sources"] == 1
    assert obj["delta_after_minus_before"]["prompt_chars"] == 70
    assert "prompt_chars_are_not_tokens" in obj["warnings"]
    for private in ("SENSITIVE", "RAW-EVIDENCE", "before.txt", "a" * 16, "b" * 16):
        assert private not in output


def test_ambiguous_multiple_traces_fails_closed_without_raw_output(
        tmp_path, capsys):
    path = tmp_path / "ambiguous"
    record = "SRAF_REPORT_EVIDENCE_TRACE=" + json.dumps(_trace("a" * 16))
    path.write_text(record + "\n" + record + "\n", encoding="utf-8")
    assert main(["--baseline", str(path), "--candidate", str(path)]) == 2
    output = capsys.readouterr().out
    assert '"status": "INCOMPLETE"' in output
    assert "a" * 16 not in output


@pytest.mark.parametrize("mutation", ["bad_schema", "negative", "boolean", "extra", "bad_counts"])
def test_invalid_or_untrusted_schema_rejected(tmp_path, mutation):
    obj = _trace("c" * 16)
    if mutation == "bad_schema":
        obj["schema"] = "future_unsupported_schema"
    elif mutation == "negative":
        obj["counters"]["picked"] = -1
    elif mutation == "boolean":
        obj["counters"]["picked"] = True
    elif mutation == "extra":
        obj["raw_prompt"] = "PRIVATE!"
    else:
        obj["counters"]["picked"] = 999
    path = _write(tmp_path, "bad", obj)
    with pytest.raises(ValueError):
        read_count_trace(path)


def test_missing_oversized_and_symlink_inputs_are_rejected(tmp_path):
    huge = tmp_path / "huge"
    huge.write_text("x" * 70_000, encoding="utf-8")
    with pytest.raises(ValueError):
        read_count_trace(str(huge))
    with pytest.raises(OSError):
        read_count_trace(str(tmp_path / "nonexistent"))
    if hasattr(os, "symlink"):
        link = tmp_path / "linked"
        try:
            link.symlink_to(huge)
        except (OSError, NotImplementedError):
            pass
        else:
            with pytest.raises((ValueError, OSError)):
                read_count_trace(str(link))


def test_comparison_refuses_same_trace_without_implying_quality():
    obj = {"trace_id": "a" * 16, "counts": {"incoming": 1}, "skipped": False}
    with pytest.raises(ValueError):
        compare_count_traces(obj, obj)
