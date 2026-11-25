"""Bounded ARC observation: real parser/date logic with synthetic ES rows."""
import json
import logging

from agent.es.evidence_core.group_frequency import (
    MAX_HITS, MAX_ROWS, MAX_ROWS_PER_HIT, MAX_TERMS, observe_group_frequency,
)
from agent.es.evidence_core.models import HitDoc
from test_sraf_bounded_evidence_rescue import _build, _hit


def _observed(caplog):
    prefix = "SRAF_ARC_GROUP_FREQUENCY="
    rows = [json.loads(r.getMessage().split(prefix, 1)[1])
            for r in caplog.records if r.getMessage().startswith(prefix)]
    assert len(rows) == 1
    return rows[0]


def test_shadow_counts_once_per_source_hit_and_excludes_invalid_date(monkeypatch, caplog):
    axes = [{"美國", "USA"}, {"出口管制"}, {"設備"}, {"中國"}]
    hits = [
        _hit(["美國 USA 出口管制 設備", "美國 USA 設備"], uuid="private-doc-1", docid="1"),
        _hit(["美國 中國 設備"], uuid="private-doc-2", docid="2"),
        _hit(["美國 中國 出口管制"], uuid="private-doc-3", docid="3", date="2023-09-24"),
    ]
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    expected = _build(hits, axes=axes)
    assert not any("SRAF_ARC_GROUP_FREQUENCY=" in r.getMessage() for r in caplog.records)
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    with caplog.at_level(logging.WARNING, logger="sraf.arc.group_frequency"):
        assert _build(hits, axes=axes) == expected
    record = _observed(caplog)
    assert record["status"] == "observed_sample"
    assert record["eligible_hits"] == 2
    assert [g["sample_hit_frequency"] for g in record["groups"]] == [2, 1, 2, 1]
    assert record["groups"][0]["idf_milli"] == 0
    assert record["groups"][1]["idf_milli"] > 0
    serialized = json.dumps(record, ensure_ascii=False)
    for private in ("private-doc", "美國", "USA", "出口管制", "2023-08-24"):
        assert private not in serialized


def test_shadow_limits_scan_and_handles_unsupported_groups(monkeypatch, caplog):
    hits = [_hit(["甲軸乙軸丙軸"] * (MAX_ROWS_PER_HIT + 1),
                 uuid=f"d-{i}", docid=str(i)) for i in range(MAX_HITS + 1)]
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    _build(hits)
    r = _observed(caplog)
    assert r["sample_limited"] is True
    assert r["scanned_hits"] <= MAX_HITS
    assert r["inspected_rows"] <= MAX_ROWS
    assert r["eligible_hits"] <= r["scanned_hits"]
    assert all(g["sample_hit_frequency"] <= r["eligible_hits"] for g in r["groups"])
    r = observe_group_frequency([], [{str(i) for i in range(MAX_TERMS + 1)}],
                                date_from=None, date_to=None, allowed_years=None)
    assert r["status"] == "unsupported_groups"
    assert r["groups"] == []


def test_no_eligible_sample_is_not_zero_idf():
    r = observe_group_frequency([], [{"甲軸"}], date_from=None, date_to=None, allowed_years=None)
    assert r["status"] == "no_date_eligible_sample"
    assert r["groups"][0]["idf_milli"] is None


def test_arc_operator_budget_is_bounded_and_rejects_malformed_env(monkeypatch):
    from agent.es.evidence_core.group_frequency import GroupFrequencyBudget, MAX_CHARS
    prefix = "SRAF_ARC_GROUP_FREQUENCY_MAX_"
    monkeypatch.setenv(prefix + "HITS", "3")
    monkeypatch.setenv(prefix + "CHARS", "999999999")
    monkeypatch.setenv(prefix + "ROWS", "-1")
    monkeypatch.setenv(prefix + "TERMS", "0")
    monkeypatch.setenv(prefix + "ROW_CHARS", "１２")
    monkeypatch.setenv(prefix + "GROUPS", "9" * 100)
    b = GroupFrequencyBudget.from_env()
    assert b.hits == 3
    assert b.chars == MAX_CHARS
    assert b.rows == MAX_ROWS
    assert b.terms == MAX_TERMS
    assert b.row_chars == GroupFrequencyBudget().row_chars
    assert b.groups == GroupFrequencyBudget().groups


def test_arc_lower_observation_budget_does_not_change_evidence(monkeypatch, caplog):
    hits = [_hit(["甲軸乙軸丙軸"] * 3, uuid=f"d-{i}", docid=str(i))
            for i in range(3)]
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    expected = _build(hits)
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY_MAX_HITS", "2")
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY_MAX_ROWS", "2")
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY_MAX_ROWS_PER_HIT", "1")
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY_MAX_CHARS", "10")
    assert _build(hits) == expected
    r = _observed(caplog)
    assert r["effective_budget"]["chars"] == 10
    assert r["effective_budget"]["rows_per_hit"] == 1
    assert r["scanned_hits"] <= 2
    assert r["inspected_rows"] <= 2
    assert r["text_chars"] <= 10
    assert r["sample_limited"] is True


def test_arc_budget_shares_request_limit_across_rounds_and_isolates_reports():
    from agent.es.arc_request_budget import ArcUnits, ArcRequestBudget
    budget = ArcRequestBudget(request_limit=ArcUnits(slices=3, chars=100),
                              round_limit=ArcUnits(slices=2, chars=70))
    assert budget.reserve(1, ArcUnits(slices=1, chars=60))
    assert not budget.reserve(1, ArcUnits(slices=1, chars=11))
    assert budget.reserve(2, ArcUnits(slices=1, chars=40))
    assert not budget.reserve(3, ArcUnits(slices=1, chars=1))
    assert budget.snapshot()[0] == ArcUnits(slices=2, chars=100)
    another = ArcRequestBudget()
    assert another.snapshot()[0] == ArcUnits()
    budget.seal()
    assert not budget.reserve(3, ArcUnits(slices=1))


def test_arc_budget_concurrent_reservations_are_atomic():
    from concurrent.futures import ThreadPoolExecutor
    from agent.es.arc_request_budget import ArcUnits, ArcRequestBudget
    budget = ArcRequestBudget(request_limit=ArcUnits(slices=4, hits=4),
                              round_limit=ArcUnits(slices=4, hits=4))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: budget.reserve(1, ArcUnits(slices=1, hits=1)),
                                range(32)))
    assert sum(results) == 4
    total, rounds = budget.snapshot()
    assert total == ArcUnits(slices=4, hits=4)
    assert rounds[1] == total
    rounds.clear()
    assert budget.snapshot()[1][1] == total


def test_arc_budget_rejects_invalid_limits_units_and_rounds():
    import pytest
    from agent.es.arc_request_budget import ArcUnits, ArcRequestBudget, MAX_ROUNDS
    for invalid in (-1, True, 1.5):
        with pytest.raises(ValueError):
            ArcUnits(chars=invalid)
    with pytest.raises(ValueError):
        ArcRequestBudget(request_limit=ArcUnits(slices=9))
    with pytest.raises(ValueError):
        ArcRequestBudget(request_limit=ArcUnits(slices=1))
    budget = ArcRequestBudget()
    for invalid in (0, True, MAX_ROUNDS + 1):
        assert not budget.reserve(invalid, ArcUnits(slices=1))
    assert not budget.reserve(1, ArcUnits())
    assert budget.snapshot()[0] == ArcUnits()
