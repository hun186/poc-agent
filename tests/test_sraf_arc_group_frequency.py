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


def test_arc_shared_budget_exhaustion_preserves_evidence(monkeypatch, caplog):
    from agent.es.arc_request_budget import (
        ArcRequestBudget, ArcUnits, bind_arc_budget,
    )
    hits = [_hit(["甲軸乙軸丙軸"], uuid="private-doc", docid="1")]
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    expected = _build(hits)
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        for _ in range(5):
            assert _build(hits) == expected
    prefix = "SRAF_ARC_GROUP_FREQUENCY="
    rows = [json.loads(r.getMessage().split(prefix, 1)[1])
            for r in caplog.records if r.getMessage().startswith(prefix)]
    assert len(rows) == 5
    assert all(r["status"] == "observed_sample" for r in rows[:4])
    assert rows[4]["status"] == "shared_budget_exhausted"
    assert rows[4]["sample_limited"] and rows[4]["groups"] == []
    assert rows[4]["scanned_hits"] == rows[4]["inspected_rows"] == rows[4]["text_chars"] == 0
    assert budget.snapshot()[0] == ArcUnits(
        slices=4, hits=512, rows=1024, chars=524288,
    )


def _rank_record(caplog):
    prefix = "SRAF_ARC_RANK_SHADOW="
    records = [json.loads(r.getMessage().split(prefix, 1)[1])
               for r in caplog.records if r.getMessage().startswith(prefix)]
    assert len(records) == 1
    return records[0]


def test_arc_a4_rank_shadow_preserves_output_and_measures_rarity_displacement(monkeypatch, caplog):
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    axes = [{"美國"}, {"政策"}, {"出口管制"}, {"半導體"}]
    hits = [
        _hit(["美國 政策 出口管制"], uuid=f"private-{i}", docid=str(i))
        for i in range(24)
    ] + [_hit(["美國 政策 半導體"], uuid="private-rare", docid="rare")]
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_RANK", raising=False)
    expected = _build(hits, axes=axes)
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_RANK", "shadow")
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        assert _build(hits, axes=axes) == expected
    r = _rank_record(caplog)
    assert r["status"] == "observed_rank"
    assert r["strict_count"] == 25
    assert r["top_k_replaced"] == r["rarity_only_top_k_replaced"] == 1
    assert r["original_source_hits"] == r["shadow_source_hits"] == 20
    assert r["original_strong"] == r["shadow_strong"] == 20
    assert budget.snapshot()[0] == ArcUnits(slices=2, hits=128, rows=384, chars=262144)
    serialized = json.dumps(r, ensure_ascii=False)
    for private in ("private-", "美國", "政策", "半導體", "出口管制"):
        assert private not in serialized


def test_arc_a4_no_rarity_override_of_strong_or_coverage_and_zero_df_is_neutral():
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    from agent.es.evidence_core.arc_rank_shadow import observe_rank_shadow
    from agent.es.evidence_core.models import EvidenceSnippet
    groups = [{"甲"}, {"乙"}, {"丙"}, {"丁"}]
    frequency = {"schema": "sraf_arc_group_frequency_v1",
                 "scope": "ordered_parser_slice_date_valid_sample_text_only",
                 "status": "observed_sample", "eligible_hits": 32,
                 "groups": [{"group_ordinal": i, "sample_hit_frequency": df}
                            for i, df in enumerate((32, 32, 1, 0), 1)]}

    def row(i, text, count, weak=False):
        return EvidenceSnippet(uuid=f"private-{i}", text=text, date_iso="2023-08-24",
                               article_date_iso="2023-08-24", group_hits=count,
                               match_scope="text", weak_evidence=weak,
                               source_hit_ordinal=i)

    strong = [row(i, "甲乙丁", 3) for i in range(20)]
    # A rare group cannot outweigh the existing higher total coverage or strong tier.
    candidates = strong + [row(20, "甲丙", 2), row(21, "甲乙丙丁", 4, True)]
    with bind_arc_budget((ArcRequestBudget(), 1)):
        r = observe_rank_shadow(candidates, groups, frequency)
    assert r["status"] == "observed_rank" and r["top_k_replaced"] == 0
    # An unseen group gets neutral weight, not an invented maximal rarity score.
    frequency["groups"][2]["sample_hit_frequency"] = 32
    candidates = [row(i, "甲乙丙", 3) for i in range(20)] + [row(20, "甲乙丁", 3)]
    with bind_arc_budget((ArcRequestBudget(), 1)):
        r = observe_rank_shadow(candidates, groups, frequency)
    assert r["top_k_replaced"] == 0


def test_arc_a4_rank_skips_when_sample_or_budget_insufficient(monkeypatch, caplog):
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    hits = [_hit(["甲軸乙軸丙軸"] * 2, uuid=f"d-{i}", docid=str(i)) for i in range(20)]
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_RANK", "shadow")
    budget = ArcRequestBudget(
        request_limit=ArcUnits(slices=1, hits=128, rows=256, chars=131072),
        round_limit=ArcUnits(slices=1, hits=128, rows=256, chars=131072),
    )
    with bind_arc_budget((budget, 1)):
        _build(hits)
    assert _rank_record(caplog)["status"] == "shared_budget_exhausted"
    caplog.clear()
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY_MAX_HITS", "2")
    with bind_arc_budget((ArcRequestBudget(), 1)):
        _build(hits)
    assert _rank_record(caplog)["status"] == "insufficient_sample"


def test_arc_native_rank_receipt_checks_exact_groups_and_dates():
    from agent.es.arc_native_rank_receipt import NativeRankFrequency
    from agent.es.arc_frequency_plan import SCOPE
    groups = [{"甲", "A"}, {"乙"}]
    obs = {"scope": SCOPE, "status": "exact_es_query_counts",
           "eligible_documents": 1000, "groups": [
               {"group_ordinal": 1, "document_frequency": 500},
               {"group_ordinal": 2, "document_frequency": 20}]}
    receipt = NativeRankFrequency.from_observation(
        obs, groups=groups, date_from="2023-08-24", date_to="2023-08-24")
    kw = dict(date_from="2023-08-24", date_to="2023-08-24", allowed_years=None)
    assert receipt.for_builder(groups, **kw)["eligible_documents"] == 1000
    assert receipt.for_builder(list(reversed(groups)), **kw) is None
    assert receipt.for_builder(groups, **{**kw, "allowed_years": {2023}}) is None
    assert receipt.for_builder(groups, **{**kw, "date_to": "2023-08-25"}) is None
    groups[0].add("B")
    assert receipt.for_builder(groups, **kw) is None
    assert NativeRankFrequency.from_observation(
        {**obs, "status": "incomplete"}, groups=groups,
        date_from="2023-08-24", date_to="2023-08-24") is None


def test_arc_native_rank_uses_native_df_without_local_scan(monkeypatch, caplog):
    from agent.es.arc_native_rank_receipt import NativeRankFrequency
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.es.evidence_core.builder import build_hits_and_evidence
    groups = [{"美國"}, {"政策"}, {"出口管制"}, {"半導體"}]
    hits = [_hit(["美國 政策 出口管制"], uuid=f"d-{i}", docid=str(i))
            for i in range(24)]
    hits += [_hit(["美國 政策 半導體"], uuid="d-rare", docid="rare")]
    kw = dict(date_from="2023-08-24", date_to="2023-08-24",
              effective_terms=["美國", "政策", "出口管制", "半導體"],
              term_groups=groups, query_for_snippet="美國 政策 出口管制 半導體")
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_RANK_NATIVE", raising=False)
    baseline = build_hits_and_evidence(hits, **kw)
    receipt = NativeRankFrequency(tuple(map(frozenset, groups)), "2023-08-24",
                                  "2023-08-24", 10000, (8000, 7000, 5000, 50))
    monkeypatch.setenv("SRAF_ARC_RANK_NATIVE", "shadow")
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        assert build_hits_and_evidence(hits, **kw, native_rank_frequency=receipt) == baseline
    r = _rank_record(caplog)
    assert r["status"] == "observed_rank"
    assert r["scope"] == "same_search_native_df_strict_first_prefix_not_pit"
    assert r["snapshot_consistency"] == "not_pit"
    assert r["rarity_only_top_k_replaced"] == 1
    assert budget.snapshot()[0] == ArcUnits(slices=1, rows=128, chars=131072)
