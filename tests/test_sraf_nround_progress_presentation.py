"""N-round audit is count-only and identical in actual Word and Markdown."""
from __future__ import annotations

import copy
import json

import pytest

from api.core.presenters.evidence_usage import (
    evidence_usage_rows, safe_evidence_usage,
)
from api.core.presenters.nround_progress import (
    nround_progress_rows, safe_nround_progress,
)
from test_sraf_evidence_usage_presentation import _usage, _output, _render_both


def sample():
    return {
        "schema": "sraf_nround_coordinator_progress_v1",
        "phase": "TERMINAL", "termination": "SUFFICIENT",
        "round": 2, "completed_rounds": 2,
        "es_calls_admitted_this_round": 1,
        "ready_for_external_report_generation": True,
        "live_es": "NOT_EXECUTED_BY_COORDINATOR",
        "report_job": "NOT_INTEGRATED",
        "checkpoint_resume": "NOT_IMPLEMENTED",
        "canonical_evidence_history": [
            {
                "round": 1, "candidate_sources": 3,
                "parser_output": 4, "validated_rows": 3, "fallback": 1,
                "verified_in_round": 2, "new_verified": 2,
                "new_sources": 1, "cumulative_verified": 2,
                "cumulative_sources": 1, "complete": True,
                "request_wide_attested": True,
            },
            {
                "round": 2, "candidate_sources": 2,
                "parser_output": 3, "validated_rows": 2, "fallback": 1,
                "verified_in_round": 2, "new_verified": 1,
                "new_sources": 1, "cumulative_verified": 3,
                "cumulative_sources": 2, "complete": True,
                "request_wide_attested": True,
            },
        ],
    }


def test_sanitized_nround_audit_in_word_and_openwebui_markdown():
    usage = {**_usage(), "nround_progress": sample()}
    md, paragraphs = _render_both(_output(usage))
    rendered = "\n".join(paragraphs)
    clean = safe_nround_progress(sample())
    assert clean["completed_rounds"] == 2
    assert clean["canonical_evidence_history"][1]["new_verified"] == 1
    rows = nround_progress_rows(sample())
    assert len(rows) >= 6
    assert ("第 2 輪 Evidence", rows[2][1]) in rows
    assert any("真正新增 1 段／新增來源 1 篇" in value
               for _, value in rows)
    assert "Word 已產出或通過驗收" in str(rows)
    assert "不是實際 ES 召回率" in str(rows)
    assert not any("私人" in value for _, value in rows)
    for label, value in evidence_usage_rows(usage):
        assert f"{label}：{value}" in md
        assert f"{label}：{value}" in rendered
    assert "多輪智慧檢索歷程" in rendered
    assert "多輪智慧檢索歷程" in md


def test_real_offline_coordinator_progress_passes_shared_word_contract():
    from test_sraf_nround_coordinator import coordinator, finish
    from test_sraf_shared_evidence_budget import _hit
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    finish(c, [_hit(2, "PRIVATE-SOURCE", inner=False)], sufficient=True)
    progress = c.safe_progress()
    cleaned = safe_nround_progress(progress)
    assert cleaned["ready_for_external_report_generation"]
    assert cleaned["canonical_evidence_history"][0]["new_verified"] == 2
    usage = {**_usage(), "nround_progress": progress}
    md, doc = _render_both(_output(usage))
    text = md + "\n".join(doc)
    assert "第 1 輪 Evidence" in text
    for private in ("PRIVATE-SOURCE", "2023-08-24", "甲軸", "E1"):
        assert private not in text.split("多輪智慧檢索歷程", 1)[-1]


def test_private_unknown_values_are_never_copied_to_word_or_markdown():
    raw = sample()
    raw["original_question"] = "PRIVATE-QUESTION"
    raw["source_id"] = "PRIVATE-ES-ID"
    raw["canonical_evidence_history"][0]["raw_text"] = "PRIVATE-RAW-EVIDENCE"
    raw["canonical_evidence_history"][1]["event_ids"] = ["PRIVATE-EVENT"]
    usage = {**_usage(), "nround_progress": raw,
             "private_extra": "PRIVATE-META"}
    sanitized = safe_evidence_usage(usage)
    serialized = json.dumps(sanitized, ensure_ascii=False)
    assert "PRIVATE" not in serialized
    assert set(sanitized["nround_progress"]) == set(sample())
    source_output = _output(usage)
    unchanged = copy.deepcopy(source_output)
    md, doc = _render_both(source_output)
    assert source_output == unchanged  # rendering must not mutate caller JSON
    assert "PRIVATE" not in md + "\n".join(doc)
    assert len(nround_progress_rows(raw)) > 0


def test_no_nround_payload_preserves_existing_word_and_markdown():
    md, paragraphs = _render_both(_output(_usage()))
    assert "多輪智慧檢索歷程" not in md
    assert "多輪智慧檢索歷程" not in "\n".join(paragraphs)
    assert "Evidence 選取模式" in md
    assert "Evidence 選取模式" in "\n".join(paragraphs)


@pytest.mark.parametrize("change", [
    lambda p: p.update({"phase": ["TERMINAL"]}),
    lambda p: p.update({"termination": {"private": "SECRET"}}),
    lambda p: p.update({"phase": "PRIVATE-ROLE"}),
    lambda p: p.update({"round": True}),
    lambda p: p.update({"completed_rounds": 3}),
    lambda p: p.update({"ready_for_external_report_generation": "yes"}),
    lambda p: p.update({"live_es": "LIVE_PASSED"}),
    lambda p: p.update({"checkpoint_resume": "YES"}),
    lambda p: p["canonical_evidence_history"][0].update(
        {"parser_output": 2}),
    lambda p: p["canonical_evidence_history"][1].update(
        {"new_verified": 8}),
    lambda p: p["canonical_evidence_history"][1].update(
        {"new_verified": 0, "cumulative_verified": 2}),

    lambda p: p["canonical_evidence_history"][0].update(
        {"new_verified": 1, "cumulative_verified": 1}),
    lambda p: [
        row.update({"candidate_sources": 0, "new_sources": 0,
                    "cumulative_sources": 0})
        for row in p["canonical_evidence_history"]
    ],
    lambda p: p["canonical_evidence_history"][1].update(
        {"candidate_sources": True}),
    lambda p: p["canonical_evidence_history"][1].update(
        {"fallback": 3}),
    lambda p: p["canonical_evidence_history"][1].update(
        {"cumulative_verified": 5}),
    lambda p: p["canonical_evidence_history"][1].update(
        {"cumulative_sources": 3}),
    lambda p: p["canonical_evidence_history"][1].update(
        {"request_wide_attested": False}),
    lambda p: p["canonical_evidence_history"][0].update(
        {"complete": False}),
    lambda p: p["canonical_evidence_history"].append(
        copy.deepcopy(p["canonical_evidence_history"][1])),
])
def test_untrusted_counts_fail_closed_without_echoing_raw_data(change):
    data = sample()
    change(data)
    assert safe_nround_progress(data) == {}
    assert nround_progress_rows(data) == []
    usage = {**_usage(), "nround_progress": data}
    clean = safe_evidence_usage(usage)
    assert "nround_progress" not in clean
    md, doc = _render_both(_output(usage))
    text = md + "\n".join(doc)
    assert "多輪智慧檢索歷程" not in text
    assert "Evidence 選取模式" in text


def test_source_growth_requires_at_least_one_new_verified_evidence_per_new_source():
    raw = sample()
    raw["canonical_evidence_history"][1].update({
        "new_verified": 0, "cumulative_verified": 2,
        # new_sources=1, cumulative_sources=2 already in the fixture.
    })
    assert safe_nround_progress(raw) == {}
    usage = {**_usage(), "nround_progress": raw}
    md, word = _render_both(_output(usage))
    assert "多輪智慧檢索歷程" not in md + "\n".join(word)


def test_round_verified_union_and_source_provenance_never_fake_word_readiness():
    union = sample()
    union["canonical_evidence_history"][0].update({
        "new_verified": 1, "cumulative_verified": 1,
        # verified_in_round still 2; impossible under set union.
    })
    union["canonical_evidence_history"][1]["cumulative_verified"] = 2
    no_sources = sample()
    for row in no_sources["canonical_evidence_history"]:
        row.update({
            "candidate_sources": 0, "new_sources": 0,
            "cumulative_sources": 0,
        })
    for invalid in (union, no_sources):
        assert safe_nround_progress(invalid) == {}
        assert nround_progress_rows(invalid) == []
        usage = {**_usage(), "nround_progress": invalid}
        md, paragraphs = _render_both(_output(usage))
        assert "多輪智慧檢索歷程" not in md + "\\n".join(paragraphs)


def test_terminal_incomplete_snapshot_is_visible_but_never_report_ready():
    data = sample()
    data["phase"] = "TERMINAL"
    data["termination"] = "SAME_PLAN_SEARCH_INCOMPLETE"
    data["ready_for_external_report_generation"] = False
    data["canonical_evidence_history"][1]["complete"] = False
    safe = safe_nround_progress(data)
    assert safe["completed_rounds"] == 2
    rows = nround_progress_rows(data)
    assert "尚未確認整輪完整性" in str(rows)
    assert "不代表 Word 已產出" in str(rows)


def test_sanitizer_is_no_side_effect_and_does_not_reflect_ids():
    raw = sample()
    copy_before = copy.deepcopy(raw)
    one = safe_nround_progress(raw)
    two = safe_nround_progress(raw)
    assert raw == copy_before
    assert one == two
    assert one is not raw
    assert one["canonical_evidence_history"] is not raw[
        "canonical_evidence_history"
    ]
    assert json.dumps(one, ensure_ascii=False).count("PRIVATE") == 0
