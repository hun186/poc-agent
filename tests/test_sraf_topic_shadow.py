"""#406: offline count-only topic 3->2 shadow; NEVER evidence admission.

Synthetic structured ES cases only. No Elasticsearch, SQL or LLM calls.
"""
from __future__ import annotations

import json
import logging

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.models import Citation, HitDoc
from agent.es.evidence_core.topic_shadow import (
    MAX_SHADOW_CITATIONS, observe_topic_shadow,
)


GROUPS = [
    {"加薩"}, {"停火"}, {"人道援助"}, {"醫療"}, {"聯合國"},
]


def _hit() -> dict:
    return {
        "_index": "news_test", "_id": "PRIVATE-ES-ID",
        "_source": {
            "uuid": "PRIVATE-UUID",
            "communication": {"subject": "PRIVATE-TITLE"},
            "multidim_event_json": [{
                "article_title": "PRIVATE-ARTICLE",
                "article_date_iso": "2026-11-15",
                "Event": [
                    {"event_id": "E1", "time_iso": "2023-08-24", "time_precision": "day"},
                    {"event_id": "E2", "time_iso": "2023-08-25", "time_precision": "day"},
                ],
                "Event_Timeline": [],
                "evidence_snippets": [
                    {"text": "加薩 停火 人道援助 STRONG-SECRET", "event_ids": ["E1"]},
                    {"text": "加薩 醫療 RELEVANT-SECRET", "event_ids": ["E1"]},
                    {"text": "聯合國 人道援助 OTHER-EVENT-SECRET", "event_ids": ["E1"]},
                    {"text": "加薩 醫療 WRONG-DATE-SECRET", "event_ids": ["E2"]},
                ],
            }],
        },
    }


def _build(rows: list[dict], *, groups=GROUPS, original_question=None):
    return build_hits_and_evidence(
        rows, date_from="2023-08-24", date_to="2023-08-24",
        effective_terms=["加薩", "停火", "人道援助"],
        term_groups=groups, query_for_snippet="PRIVATE-QUERY",
        original_question=original_question,
    )


def _trace(caplog):
    records = [
        json.loads(r.message.partition("SRAF_EVIDENCE_TRACE=")[2])
        for r in caplog.records if r.name == "sraf.evidence_trace"
        and r.message.startswith("SRAF_EVIDENCE_TRACE=")
    ]
    assert len(records) == 1
    return records[0]


def test_shadow_observes_low_nonzero_strict_without_promoting_or_leaking(monkeypatch, caplog):
    for flag in ("SRAF_EVIDENCE_TRACE", "SRAF_EVIDENCE_RESCUE",
                 "SRAF_EVIDENCE_SOURCE_REFILL",
                 "SRAF_EVIDENCE_SHARED_SOURCE_BUDGET",
                 "SRAF_EVIDENCE_VALID_FAIR_BUDGET"):
        monkeypatch.delenv(flag, raising=False)
    hit = _hit()
    baseline = _build([hit])
    assert len(baseline[1]) == 1
    assert baseline[1][0]["match_policy"] == "strict"
    assert not caplog.records or not any(
        r.name == "sraf.evidence_trace" for r in caplog.records
    )

    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        traced = _build([hit])
    assert traced == baseline
    trace = _trace(caplog)
    counters = trace["counters"]
    assert counters["shadow_3to2.inspected"] == 4
    assert counters["shadow_3to2.date_eligible"] == 3
    assert counters["shadow_3to2.strict_in_sample"] == 1
    # Both the relevant short snippet and a non-Gaza generic one are
    # visible as *UNANCHORED* hypothetical matches, never selected.
    assert counters["shadow_3to2.unanchored_text_two_group_only"] == 2
    assert trace["output_evidence"] == trace["strict_accepted"] == 1
    raw = json.dumps(trace, ensure_ascii=False)
    for secret in ("PRIVATE-", "STRONG-SECRET", "RELEVANT-SECRET",
                   "OTHER-EVENT-SECRET", "WRONG-DATE-SECRET",
                   "加薩", "停火", "2023-08-24"):
        assert secret not in raw


def test_shadow_skipped_for_fewer_than_four_groups(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _build([_hit()], groups=GROUPS[:3])
    assert not any(k.startswith("shadow_3to2.") for k in _trace(caplog)["counters"])


def test_shadow_respects_citation_cap_and_never_asserts_full_recall():
    rows = [Citation(text="加薩 醫療", date_iso="2023-08-24")
            for _ in range(MAX_SHADOW_CITATIONS + 44)]
    hit = HitDoc(
        uuid="synthetic", subject=None, article_title=None, score=0.0,
        raw_content="", citations=rows,
    )
    result = observe_topic_shadow(
        [hit], date_from="2023-08-24", date_to="2023-08-24",
        allowed_years=None, term_groups=GROUPS,
    )
    assert result is not None
    assert result.inspected == MAX_SHADOW_CITATIONS
    assert result.uninspected_by_cap == 44
    assert result.date_eligible == MAX_SHADOW_CITATIONS
    assert result.unanchored_text_two_group_only == MAX_SHADOW_CITATIONS


def test_shadow_excludes_meta_only_and_bounded_oversized_text():
    hit = HitDoc(
        uuid="synthetic", subject="加薩 醫療", article_title=None,
        score=1.0, raw_content="", citations=[
            Citation(text="unrelated", date_iso="2023-08-24"),
            Citation(text="加薩 醫療 " + ("X" * 5000), date_iso="2023-08-24"),
        ],
    )
    result = observe_topic_shadow(
        [hit], date_from="2023-08-24", date_to="2023-08-24",
        allowed_years=None, term_groups=GROUPS,
    )
    assert result is not None
    assert result.meta_only_two_group_only == 1
    assert result.oversized_or_over_budget == 1
    assert result.date_eligible == 1
    assert result.unanchored_text_two_group_only == 0



def test_explicit_original_subject_shadow_is_count_only_and_keeps_output(monkeypatch, caplog):
    """A text anchor is a count, NOT an authorization to admit a weak snippet."""
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    for flag in ("SRAF_EVIDENCE_RESCUE", "SRAF_EVIDENCE_SOURCE_REFILL",
                 "SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "SRAF_EVIDENCE_VALID_FAIR_BUDGET"):
        monkeypatch.delenv(flag, raising=False)
    rows = [_hit()]
    question = "主題：加薩\n請分析2023年的停火、醫療與人道援助 PRIVATE-QUESTION"
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        baseline = _build(rows)
    no_anchor = _trace(caplog)["counters"]
    assert no_anchor["shadow_3to2.explicit_subject_available"] == 0
    assert no_anchor["shadow_3to2.explicit_subject_direct_two_group_only"] == 0
    assert no_anchor["shadow_3to2.explicit_subject_not_direct_two_group_only"] == 0

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        observed = _build(rows, original_question=question)
    assert observed == baseline
    trace = _trace(caplog)
    count = trace["counters"]
    assert count["shadow_3to2.explicit_subject_available"] == 1
    assert count["shadow_3to2.explicit_subject_direct_two_group_only"] == 1
    assert count["shadow_3to2.explicit_subject_not_direct_two_group_only"] == 1
    assert count["shadow_3to2.strict_in_sample"] == 1
    assert count["shadow_3to2.date_eligible"] == 3
    # The E2 citation from the next day was excluded BEFORE direct matching.
    assert count["shadow_3to2.unanchored_text_two_group_only"] == 2
    serialized = json.dumps(trace, ensure_ascii=False)
    for secret in ("PRIVATE-", "加薩", "停火", "2023-08-24", "人道援助"):
        assert secret not in serialized


def test_rewritten_query_or_ambiguous_original_never_establishes_shadow_anchor(
    monkeypatch, caplog,
):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    for original in (
        None,
        "請分析加薩停火議題",  # natural prose not explicitly labeled
        "主題：加薩\n主題：蘇丹",
        "主題：加薩\n排除 加薩",
        "X" * 8193,
    ):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
            _build([_hit()], original_question=original)
        count = _trace(caplog)["counters"]
        assert count["shadow_3to2.explicit_subject_available"] == 0
        assert count["shadow_3to2.explicit_subject_direct_two_group_only"] == 0
        assert count["shadow_3to2.explicit_subject_not_direct_two_group_only"] == 0


def test_shadow_does_not_infer_subject_from_metadata_only():
    from agent.es.evidence_core.question_anchor import derive_explicit_question_anchor

    anchor = derive_explicit_question_anchor("主題：加薩", GROUPS)
    assert anchor is not None
    hit = HitDoc(
        uuid="synthetic", subject="加薩 停火 醫療", article_title=None, score=1.0,
        raw_content="", citations=[
            Citation(text="聯合國 人道援助", date_iso="2023-08-24"),
        ],
    )
    shadow = observe_topic_shadow(
        [hit], date_from="2023-08-24", date_to="2023-08-24",
        allowed_years=None, term_groups=GROUPS, explicit_anchor=anchor,
    )
    assert shadow is not None
    # A metadata-only topical anchor never substitutes for an actual
    # literal subject mention in the text, even when other axes match.
    assert shadow.explicit_subject_direct_two_group_only == 0
