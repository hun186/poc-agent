"""#397 P1-d: source-diverse selection stays bounded, deterministic and opt-in."""
from __future__ import annotations

from agent.utils.report_evidence_selection import select_source_diverse_evidence


def _s(doc, ordinal, *, weak=False, **extra):
    return {
        "uuid": doc, "text": f"{doc}:{ordinal}",
        "date_iso": "2023-08-24", "weak_evidence": weak,
        **extra,
    }


def test_one_source_cannot_exhaust_small_cap_when_other_sources_exist():
    source = [_s("A", i) for i in range(20)] + [_s("B", 0), _s("C", 0)]
    out = select_source_diverse_evidence(source, 4)
    assert [(e["uuid"], e["text"]) for e in out] == [
        ("A", "A:0"), ("B", "B:0"), ("C", "C:0"), ("A", "A:1"),
    ]
    assert len(source) == 22
    assert all("ref_no" not in s for s in source)


def test_strong_remains_before_weak_even_if_weak_source_is_new():
    source = [_s("A", i) for i in range(4)] + [_s("B", 0, weak=True)]
    assert [e["text"] for e in select_source_diverse_evidence(source, 3)] == [
        "A:0", "A:1", "A:2",
    ]
    assert [e["text"] for e in select_source_diverse_evidence(source, 5)] == [
        "A:0", "A:1", "A:2", "A:3", "B:0",
    ]


def test_zero_empty_and_unknown_ids_do_not_collapse_into_one_source():
    assert select_source_diverse_evidence([], 5) == []
    source = [
        {"text": "no-id-1", "weak_evidence": False},
        {"text": "no-id-2", "weak_evidence": False},
        _s("A", 0),
    ]
    assert [s["text"] for s in select_source_diverse_evidence(source, 2)] == [
        "no-id-1", "no-id-2",
    ]
    assert select_source_diverse_evidence(source, 0) == []
    assert select_source_diverse_evidence(source, -3) == []


def test_500_candidates_120_cap_deterministic_and_inputs_unchanged():
    source = [_s(f"D{i:02d}", j) for i in range(20) for j in range(25)]
    before = [dict(s) for s in source]
    out = select_source_diverse_evidence(source, 120)
    assert len(out) == 120
    assert len({e["uuid"] for e in out}) == 20
    assert [e["uuid"] for e in out[:20]] == [f"D{i:02d}" for i in range(20)]
    assert out == select_source_diverse_evidence(source, 120)
    assert source == before


def test_event_time_provenance_preserved_and_no_invalid_date_rescue():
    # Selection cannot change event dates/IDs. Date filtering is the caller's
    # separate safety responsibility; this helper must not manufacture dates.
    first = _s("A", 0, matched_event_time_candidates=[{
        "event_id": "E1", "date_start": "2023-08-24",
        "date_end": "2023-08-24", "source": "event",
    }])
    second = _s("B", 0, matched_event_time_candidates=[{
        "event_id": "E2", "date_start": "2023-08-25",
        "date_end": "2023-08-25", "source": "timeline",
    }])
    out = select_source_diverse_evidence([first, second], 2)
    assert out == [first, second]
    assert out[0] is first and out[1] is second


def test_report_agent_flag_selects_diverse_sources_without_changing_default(
        monkeypatch):
    from test_sraf_report_evidence_trace import _snippet, _stub_report

    snippets = [
        _snippet(1, text="doc-a-0"),
        _snippet(1, text="doc-a-1"),
        _snippet(1, text="doc-a-2"),
        _snippet(2, text="doc-b-0"),
        _snippet(3, text="doc-c-0"),
    ]
    monkeypatch.setenv("REPORT_MAX_EVIDENCE_SNIPS", "3")
    monkeypatch.delenv("SRAF_REPORT_DIVERSE_EVIDENCE", raising=False)
    report, calls = _stub_report(monkeypatch, [dict(s) for s in snippets])
    report.ask_with_report("synth")
    assert [e["id"] for e in calls[-1]["ev"]] == [
        "SENSITIVE-UUID-1", "SENSITIVE-UUID-1", "SENSITIVE-UUID-1",
    ]

    monkeypatch.setenv("SRAF_REPORT_DIVERSE_EVIDENCE", "1")
    report, calls = _stub_report(monkeypatch, [dict(s) for s in snippets])
    report.ask_with_report("synth")
    assert {e["id"] for e in calls[-1]["ev"]} == {
        "SENSITIVE-UUID-1", "SENSITIVE-UUID-2", "SENSITIVE-UUID-3",
    }
