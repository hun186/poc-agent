"""Natural prose subject proposals are safe SHADOW measurements, not admission."""
from __future__ import annotations

import json
import logging
import pytest

from agent.es.evidence_core.prose_anchor import propose_prose_shadow_anchor
from agent.es.evidence_core.topic_audit import bind_sink, summary
from api.core.presenters.evidence_usage import evidence_usage_rows, safe_topic_adaptive

from test_sraf_topic_shadow import _hit, _build, GROUPS


@pytest.mark.parametrize("question", [
    "請分析加薩的停火情勢",
    "請整理2023年加薩的醫療情況",
    "分析加薩停火情勢",
    "評估加薩：醫療供應",
])
def test_natural_question_proposals_only_are_uniquely_front_anchored(question):
    anchor = propose_prose_shadow_anchor(question, GROUPS)
    assert anchor is not None
    assert anchor.literal == "加薩"
    assert anchor.axis_index == 0


@pytest.mark.parametrize("question", [
    None, "", "X" * 8193, "請分析加薩",
    "近期新聞涉及加薩的醫療",
    "請分析加薩與蘇丹的人道援助",
    "請比較加薩與蘇丹",
    "請分析美國對加薩的政策",
    "請分析加薩的停火，但排除加薩",
    "請分析加薩的停火，以下為逐字稿",
    "主題：加薩\n請分析加薩停火",
    "以下是新聞資料\n請分析加薩的停火情況",
    "請整理加薩",
    "請分析加薩被引用的新聞",
])
def test_ambiguous_negative_or_unanchored_prose_abstains(question):
    assert propose_prose_shadow_anchor(question, GROUPS) is None


def test_prose_ambiguous_semantic_groups_abstains():
    assert propose_prose_shadow_anchor(
        "請分析加薩停火情勢",
        [{"加薩"}, {"加薩停火"}, {"醫療"}, {"援助"}],
    ) is None
    assert propose_prose_shadow_anchor(
        "請分析加薩的停火",
        [{"加薩"}, {"加薩", "加沙"}, {"醫療"}, {"停火"}],
    ) is None
    assert propose_prose_shadow_anchor(
        "請分析加薩的停火", [set(map(str, range(33)))] + GROUPS,
    ) is None


def test_shadow_observes_prose_without_adding_or_leaking(monkeypatch, caplog):
    for flag in ("SRAF_EVIDENCE_RESCUE", "SRAF_EVIDENCE_SOURCE_REFILL",
                 "SRAF_EVIDENCE_SHARED_SOURCE_BUDGET",
                 "SRAF_EVIDENCE_VALID_FAIR_BUDGET"):
        monkeypatch.delenv(flag, raising=False)
    question = "請分析加薩的停火情勢 PRIVATE-QUESTION"
    monkeypatch.delenv("SRAF_TOPIC_MATCH_ADAPTIVE", raising=False)
    baseline = _build([_hit()], original_question=question)
    assert len(baseline[1]) == 1
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "shadow")
    sink = []
    with bind_sink(sink), caplog.at_level(logging.WARNING):
        result = _build([_hit()], original_question=question)
    assert result == baseline
    meta = summary(sink, mode="shadow")
    assert meta["prose_shadow_slices"] == 1
    assert meta["proposed"] == 2 and meta["selected"] == 0
    clean = safe_topic_adaptive(meta)
    assert clean["prose_shadow_slices"] == 1
    formatted = dict(evidence_usage_rows({
        "schema": "sraf_report_evidence_usage_v1",
        "selection_mode": "strong_first", "llm_skipped_incomplete": False,
        **dict.fromkeys((
            "incoming", "strong", "weak", "picked", "compressed", "llm_input",
            "incoming_identified_sources", "picked_identified_sources",
            "llm_input_identified_sources", "max_for_llm", "prompt_chars",
            "truncated_notes", "truncated_titles",
        ), 0),
        "topic_adaptive": meta,
    }))
    assert "自然語句主題推估（僅觀察）" in formatted
    assert "不會讓這些候選自動加入正式報告" in formatted["自然語句主題推估（僅觀察）"]
    log = "\n".join(x.message for x in caplog.records
                    if x.name == "sraf.topic_adaptive")
    assert "anchor_source=prose" in log
    assert "PRIVATE-QUESTION" not in (log + json.dumps(meta, ensure_ascii=False))
    assert "加薩" not in (log + json.dumps(meta, ensure_ascii=False))


def test_on_never_uses_prose_and_still_requires_explicit_authority(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "on")
    question = "請分析加薩的停火情勢"
    with caplog.at_level(logging.WARNING):
        _, evidence, _ = _build([_hit()], original_question=question)
    assert len(evidence) == 1
    assert evidence[0]["match_policy"] == "strict"
    assert any("anchor_source=none" in x.message and
               "status=no_trusted_anchor" in x.message for x in caplog.records
               if x.name == "sraf.topic_adaptive")


def test_explicit_label_still_works_without_prose_in_shadow(monkeypatch):
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "shadow")
    sink = []
    with bind_sink(sink):
        _, evidence, _ = _build([
            _hit()
        ], original_question="主題：加薩\n分析停火")
    assert len(evidence) == 1
    assert summary(sink, mode="shadow")["prose_shadow_slices"] == 0
    assert summary(sink, mode="shadow")["proposed"] == 2
