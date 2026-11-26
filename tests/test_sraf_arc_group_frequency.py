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


def _tighten_record(caplog):
    prefix = "SRAF_ARC_TIGHTEN_SHADOW="
    rows = [json.loads(r.getMessage().split(prefix, 1)[1])
            for r in caplog.records if r.getMessage().startswith(prefix)]
    assert len(rows) == 1
    return rows[0]


def test_arc_a5_candidate_count_distinguishes_exact_lower_bound_and_partial():
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    response = {"timed_out": False, "_shards": {"total": 2, "successful": 2, "failed": 0},
                "hits": {"total": {"relation": "eq", "value": 1000}, "hits": [{}]}}
    assert CandidatePressure.from_primary(response) == CandidatePressure("eq", 1000, 1)
    response["hits"]["total"]["relation"] = "gte"
    assert CandidatePressure.from_primary(response) == CandidatePressure("gte", 1000, 1)
    for changed in ({**response, "timed_out": True},
                    {**response, "_shards": {"total": 2, "successful": 1, "failed": 1}},
                    {**response, "_clusters": {}},
                    {**response, "hits": {"total": 1000, "hits": [{}]}},
                    {**response, "hits": {"total": {"relation": "eq", "value": 0}, "hits": [{}]}}):
        assert CandidatePressure.from_primary(changed) == CandidatePressure(returned=1)


def test_arc_a5_high_candidates_do_not_tighten_sparse_evidence():
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure, observe_tightening
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        r = observe_tightening([], [{"美國"}, {"政策"}, {"出口管制"}, {"半導體"}],
                               original_question="主題：美國",
                               pressure=CandidatePressure("gte", 10000, 100))
    assert r["candidate_status"] == "high_lower_bound"
    assert r["status"] == "strict_not_high"
    assert budget.snapshot()[0] == ArcUnits()
    r = observe_tightening([], [], original_question=None,
                           pressure=CandidatePressure("gte", 10, 10))
    assert r["candidate_status"] == "unknown_or_lower_bound_below_threshold"


def test_arc_a5_tightening_counterfactual_keeps_anchor_and_original_output(monkeypatch, caplog):
    from agent.es.evidence_core.builder import build_hits_and_evidence
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.arc_native_rank_receipt import NativeRankFrequency
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    groups = [{"美國"}, {"政策"}, {"出口管制"}, {"半導體"}]
    hits = []
    for i, text in enumerate(
        ["美國 政策 出口管制 半導體"] * 20
        + ["美國 政策 出口管制"] * 20
        + ["政策 出口管制 半導體"] * 10
    ):
        hits.append(_hit([text], uuid=f"private-{i}", docid=str(i)))
    # One out-of-window document cannot enter strict or counterfactual Evidence.
    hits.append(_hit(["美國 政策 出口管制 半導體"], uuid="private-invalid", docid="invalid",
                     date="2023-09-24"))
    kw = dict(date_from="2023-08-24", date_to="2023-08-24",
              effective_terms=["美國", "政策", "出口管制", "半導體"], term_groups=groups,
              query_for_snippet="美國 政策 出口管制 半導體",
              original_question="主題：美國")
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_TIGHTEN", raising=False)
    monkeypatch.delenv("SRAF_ARC_RANK_NATIVE", raising=False)
    baseline = build_hits_and_evidence(hits, **kw)
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_TIGHTEN", "shadow")
    receipt = NativeRankFrequency(tuple(map(frozenset, groups)), "2023-08-24",
                                  "2023-08-24", 10000, (8000, 7000, 100, 5000))
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        assert build_hits_and_evidence(
            hits, **kw, native_rank_frequency=receipt,
            arc_candidate_pressure=CandidatePressure("eq", 1000, 51)) == baseline
    r = _tighten_record(caplog)
    assert r["status"] == "observed_tightening"
    assert r["strict_count"] == 50 and r["candidate_status"] == "high_exact"
    strategies = {row["strategy"]: row for row in r["strategies"]}
    assert strategies["all_text_axes"]["retained_prefix_rows"] == 20
    assert strategies["anchor_plus_local_discriminative_axis"]["retained_prefix_rows"] == 20
    assert strategies["anchor_plus_native_discriminative_axis"]["retained_prefix_rows"] == 40
    assert all(row["sample_floor_met"] for row in strategies.values())
    assert budget.snapshot()[0] == ArcUnits(slices=2, hits=128, rows=384, chars=262144)
    serialized = json.dumps(r, ensure_ascii=False)
    for private in ("private-", "美國", "政策", "出口管制", "半導體", "2023-08-24"):
        assert private not in serialized


def test_arc_a5_abstains_without_anchor_or_shared_budget():
    from agent.es.evidence_core.arc_tighten_shadow import observe_tightening
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.es.evidence_core.models import EvidenceSnippet
    groups = [{"美國"}, {"政策"}, {"出口管制"}, {"半導體"}]
    rows = [EvidenceSnippet(uuid="private", text="美國 政策 出口管制",
                            date_iso="2023-08-24", article_date_iso="2023-08-24",
                            source_hit_ordinal=i, group_hits=3) for i in range(40)]
    assert observe_tightening(rows, groups, original_question="研究美國政策")["status"] == "no_trusted_anchor"
    assert observe_tightening(rows, groups, original_question="主題：美國")["status"] == "missing_shared_budget"
    b = ArcRequestBudget(request_limit=ArcUnits(slices=1), round_limit=ArcUnits(slices=1))
    with bind_arc_budget((b, 1)):
        assert observe_tightening(rows, groups, original_question="主題：美國")["status"] == "shared_budget_exhausted"
    assert b.snapshot()[0] == ArcUnits()


def _relax_record(caplog):
    prefix = "SRAF_ARC_RELAX_SHADOW="
    rows = [json.loads(r.getMessage().split(prefix, 1)[1])
            for r in caplog.records if r.getMessage().startswith(prefix)]
    assert len(rows) == 1
    return rows[0]


def test_arc_a6_distinguishes_date_topic_and_content_rejections(monkeypatch, caplog):
    from agent.es.evidence_core.builder import build_hits_and_evidence
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    monkeypatch.setenv("SRAF_ARC_RELAX", "shadow")
    groups = [{"美國"}, {"政策"}, {"半導體"}, {"出口管制"}]
    hits = [
        _hit(["美國 政策 半導體"], uuid="private-strict", docid="1"),
        _hit(["美國 出口管制", "美國 出口管制"], uuid="private-direct", docid="2"),
        _hit(["政策 半導體"], uuid="private-unanchored", docid="3"),
        _hit(["美國 政策"], uuid="private-date", docid="4", date="2023-09-24"),
    ]
    kw = dict(date_from="2023-08-24", date_to="2023-08-24",
              term_groups=groups, effective_terms=["美國","政策","半導體","出口管制"],
              query_for_snippet="美國 政策 半導體 出口管制", original_question="主題：美國")
    monkeypatch.delenv("SRAF_ARC_RELAX")
    baseline = build_hits_and_evidence(hits, **kw)
    monkeypatch.setenv("SRAF_ARC_RELAX", "shadow")
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        assert build_hits_and_evidence(hits, **kw, arc_candidate_pressure=CandidatePressure("eq", 500, 4)) == baseline
    r = _relax_record(caplog)
    assert r["status"] == "observed_relaxation"
    assert r["strict_count"] == 1 and r["date_rejected"] == 1
    assert r["canonical_eligible"] == r["strict_count"] + r["topic_rejected"]
    assert r["new_candidate_rows"] == 1
    assert r["candidate_source_hits"] == 1 and r["hypothetical_add_cap"] == 1
    assert budget.snapshot()[0] == ArcUnits(slices=1, hits=128, rows=128, chars=131072)
    serialized = json.dumps(r, ensure_ascii=False)
    for private in ("private-", "美國", "政策", "2023-08-24"):
        assert private not in serialized


def test_arc_a6_zero_strict_remains_shadow_even_if_legacy_relaxes(monkeypatch, caplog):
    from agent.es.evidence_core.builder import build_hits_and_evidence
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    groups = [{"美國"}, {"政策"}, {"出口管制"}]
    hits = [_hit(["美國 政策"], uuid="private-1", docid="1"),
            _hit(["美國 出口管制"], uuid="private-2", docid="2"),
            _hit(["政策 出口管制"], uuid="private-3", docid="3")]
    kw = dict(date_from="2023-08-24", date_to="2023-08-24", term_groups=groups,
              effective_terms=["美國","政策","出口管制"], query_for_snippet="美國 政策 出口管制",
              original_question="必要主題：美國")
    monkeypatch.delenv("SRAF_ARC_RELAX", raising=False)
    baseline = build_hits_and_evidence(hits, **kw)
    assert len(baseline[1]) == 3
    monkeypatch.setenv("SRAF_ARC_RELAX", "shadow")
    with bind_arc_budget((ArcRequestBudget(), 1)):
        assert build_hits_and_evidence(hits, **kw,
                    arc_candidate_pressure=CandidatePressure("eq", 3, 3)) == baseline
    r = _relax_record(caplog)
    assert r["strict_count"] == 0 and r["topic_rejected"] == 3
    assert r["new_candidate_rows"] == 2 and r["hypothetical_add_cap"] == 2


def test_arc_a6_diagnostic_only_abstention_and_count_certainty():
    from agent.es.evidence_core.arc_relax_shadow import StrictSliceCounts, observe_low_volume
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    groups = [{"美國"}, {"政策"}, {"半導體"}]
    def observe(counts, pressure, question="主題：美國", axes=groups):
        return observe_low_volume([], [], axes, counts=counts, pressure=pressure,
                                  original_question=question, date_from=None, date_to=None,
                                  allowed_years=None)
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        assert observe(StrictSliceCounts(), CandidatePressure("eq", 0, 0))["status"] == "primary_exact_zero"
        assert observe(StrictSliceCounts(), CandidatePressure())["status"] == "primary_empty_unconfirmed"
        assert observe(StrictSliceCounts(), CandidatePressure("eq", 20, 20))["status"] == "no_parsed_citations"
        assert observe(StrictSliceCounts(inspected=2, date_rejected=2),
                       CandidatePressure("eq", 20, 20))["status"] == "all_parsed_date_rejected"
        assert observe(StrictSliceCounts(inspected=2, other_rejected=2),
                       CandidatePressure("eq", 20, 20))["status"] == "no_canonical_eligible"
        rejected = StrictSliceCounts(inspected=2, canonical_eligible=2, topic_rejected=2)
        assert observe(rejected, CandidatePressure("eq", 20, 20), "研究美國")["status"] == "no_trusted_anchor"
        assert observe(rejected, CandidatePressure("eq", 20, 20),
                       axes=[{"美國"}, {"政策"}])["status"] == "unsupported_groups"
        assert observe(rejected, CandidatePressure("eq", 20, 20),
                       axes=[{"美國"}, {"政策","USA"}, {"半導體","usa"}])["status"] == "ambiguous_groups"
    assert budget.snapshot()[0] == ArcUnits()
    limited = ArcRequestBudget(request_limit=ArcUnits(slices=1), round_limit=ArcUnits(slices=1))
    with bind_arc_budget((limited, 1)):
        assert observe(rejected, CandidatePressure("eq", 20, 20))["status"] == "shared_budget_exhausted"
    assert limited.snapshot()[0] == ArcUnits()


def _a7_low(**overrides):
    return dict({"schema": "sraf_arc_relax_shadow_v1",
                 "scope": "first_primary_strict_parser_slice",
                 "status": "observed_relaxation",
                 "parsed_citations": 8, "canonical_eligible": 6,
                 "date_rejected": 2, "other_rejected": 0,
                 "strict_count": 1, "topic_rejected": 5,
                 "hypothetical_add_cap": 0, "sample_limited": False}, **overrides)


def _a7_high():
    return {"schema": "sraf_arc_tighten_shadow_v1",
            "scope": "strict_parser_prefix_only", "status": "observed_tightening",
            "prefix_limited": False, "prefix_count": 60, "strict_count": 60,
            "strategies": [
                {"strategy": "all_text_axes", "retained_prefix_rows": 25,
                 "retained_source_hits": 10, "sample_floor_met": True},
                {"strategy": "anchor_plus_local_discriminative_axis", "retained_prefix_rows": 40,
                 "retained_source_hits": 12, "sample_floor_met": True},
                {"strategy": "anchor_plus_native_discriminative_axis", "retained_prefix_rows": 60,
                 "retained_source_hits": 20, "sample_floor_met": True}]}


def test_arc_a7_route_abstains_for_incomplete_or_already_resolved():
    from agent.es.arc_strategy_shadow import route_strategy
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    base = dict(pressure=CandidatePressure("eq", 100, 50), low=_a7_low(),
                high=None, final_count=1, strong_count=1, refill=None, manual=False)
    assert route_strategy(**base) == (
        "semantic_low_review", ("keep_original", "review_aliases", "review_topic_scope"))
    for change, reason in [
        ({"final_count": 3}, "keep_original"),
        ({"manual": True}, "unsupported_scope"),
        ({"pressure": CandidatePressure(returned=50)}, "unconfirmed_primary"),
        ({"refill": {"pages_fetched": 2, "incomplete_due_to_scan_limit": False}},
         "refill_or_incomplete"),
        ({"refill": {"pages_fetched": 1, "incomplete_due_to_scan_limit": True}},
         "refill_or_incomplete"),
        ({"low": _a7_low(hypothetical_add_cap=1)}, "evaluate_existing_relaxation"),
        ({"low": _a7_low(sample_limited=True)}, "limited_low_sample"),
        ({"low": _a7_low(parsed_citations=99)}, "missing_low_diagnostics"),
        ({"low": _a7_low(status="shared_budget_exhausted")}, "low_diagnostics_abstained"),
        ({"low": _a7_low(status="no_trusted_anchor")}, "semantic_anchor_review"),
    ]:
        actual, choices = route_strategy(**{**base, **change})
        assert actual == reason
        if reason != "semantic_anchor_review":
            assert not choices
        else:
            assert choices == ("keep_original", "review_topic_scope")


def test_arc_a7_high_review_requires_multiple_viable_reductions():
    from agent.es.arc_strategy_shadow import route_strategy
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    base = dict(pressure=CandidatePressure("gte", 10000, 60), low=None,
                high=_a7_high(), final_count=60, strong_count=60, refill=None, manual=False)
    assert route_strategy(**base) == (
        "semantic_high_review", ("keep_original", "review_all_axes", "review_local_discrimination"))
    assert route_strategy(**{**base, "strong_count": 10}) == ("keep_original", ())
    assert route_strategy(**{**base, "high": {**_a7_high(), "prefix_limited": True}}) == (
        "missing_high_diagnostics", ())
    high = _a7_high()
    high["strategies"][1]["retained_source_hits"] = 2
    assert route_strategy(**{**base, "high": high}) == ("evaluate_existing_tightening", ())


def test_arc_a7_model_choice_is_enum_only_no_retries_and_no_private_logs(monkeypatch, caplog):
    from agent.es import arc_strategy_shadow as shadow
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    kw = dict(pressure=CandidatePressure("eq", 100, 50), diagnostics={"low": _a7_low()},
              final_count=1, strong_count=1, refill=None, manual=False,
              original_question="PRIVATE_QUESTION", groups=[{"PRIVATE_TERM"}])
    calls = []
    for raw, expected in [
        ('{"choice":"review_aliases"}', "observed_advice"),
        ('{"choice":"keep_original","choice":"review_aliases"}', "invalid_proposal"),
        ('{"choice":"review_aliases","query":"PRIVATE_DSL"}', "invalid_proposal"),
        ('{"choice":"DELETE_PRIVATE"}', "invalid_proposal"),
        ('{"choice":true}', "invalid_proposal"),
    ]:
        caplog.clear()
        def llm(prompt, **kwargs):
            calls.append(json.loads(prompt))
            assert kwargs["timeout"] == 15
            assert kwargs["extra_params"]["options"]["num_predict"] == 128
            return raw
        monkeypatch.setattr(shadow, "call_llm", llm)
        budget = ArcRequestBudget()
        with bind_arc_budget((budget, 1)):
            shadow.observe_strategy(**kw)
            shadow.observe_strategy(**kw)
        rows = [json.loads(r.getMessage().split("SRAF_ARC_STRATEGY=", 1)[1])
                for r in caplog.records if r.getMessage().startswith("SRAF_ARC_STRATEGY=")]
        assert [r["status"] for r in rows] == [expected, "shared_budget_exhausted"]
        assert rows[0]["choice"] == ("review_aliases" if expected == "observed_advice" else "keep_original")
        assert "PRIVATE_" not in caplog.text
        assert budget.snapshot()[0] == ArcUnits(llm_calls=1)
    assert len(calls) == 5
    assert calls[0]["query"] == "PRIVATE_QUESTION"
    assert calls[0]["allowed"] == ["keep_original", "review_aliases", "review_topic_scope"]


def test_arc_a7_does_not_spend_llm_on_deterministic_routes(monkeypatch):
    from agent.es import arc_strategy_shadow as shadow
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    calls = []
    monkeypatch.setattr(shadow, "call_llm", lambda *a, **k: calls.append(1))
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        for final in (0, 3, 39):
            shadow.observe_strategy(
                pressure=CandidatePressure("eq", 0, 0), diagnostics={},
                final_count=final, strong_count=final, refill=None, manual=False,
                original_question="PRIVATE_QUERY", groups=[{"PRIVATE_TERM"}])
    assert not calls and budget.snapshot()[0] == ArcUnits()


def test_arc_priority_selects_low_alias_or_strategy_and_abstains_for_deterministic_routes():
    from agent.es.arc_llm_priority import choose_llm_work
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    base = dict(pressure=CandidatePressure("eq", 100, 50),
                diagnostics={"low": _a7_low()}, final_count=1, strong_count=1,
                refill=None, manual=False, bilingual_enabled=True, strategy_enabled=True)
    assert choose_llm_work(**base) == ("semantic_low_review", "bilingual")
    assert choose_llm_work(**{**base, "bilingual_enabled": False}) == (
        "semantic_low_review", "strategy")
    assert choose_llm_work(**{**base, "diagnostics": {"low": _a7_low(status="no_trusted_anchor")}}) == (
        "semantic_anchor_review", "strategy")
    assert choose_llm_work(**{**base, "diagnostics": {"high": _a7_high()},
                              "final_count": 60, "strong_count": 60}) == (
        "semantic_high_review", "strategy")
    for change, expected in [
        ({"final_count": 3}, "keep_original"),
        ({"pressure": CandidatePressure("eq", 0, 0), "final_count": 0, "strong_count": 0},
         "review_query_scope"),
        ({"diagnostics": {"low": _a7_low(hypothetical_add_cap=1)}},
         "evaluate_existing_relaxation"),
        ({"diagnostics": {"low": _a7_low(sample_limited=True)}}, "limited_low_sample"),
        ({"refill": {"pages_fetched": 2, "incomplete_due_to_scan_limit": False}},
         "refill_or_incomplete"),
        ({"pressure": CandidatePressure(returned=50)}, "unconfirmed_primary"),
        ({"manual": True}, "unsupported_scope"),
        ({"diagnostics": {"low": _a7_low(status="no_trusted_anchor")},
          "strategy_enabled": False}, "semantic_anchor_review"),
    ]:
        assert choose_llm_work(**{**base, **change}) == (expected, "none")


def test_arc_priority_real_observers_share_one_call_without_fallback(monkeypatch, caplog):
    from agent.es import arc_llm_priority as priority
    from agent.es import arc_bilingual_shadow as a2, arc_strategy_shadow as a7
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    monkeypatch.setenv("SRAF_ARC_LLM_PRIORITY", "shadow")
    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    base = dict(pressure=CandidatePressure("eq", 100, 50),
                diagnostics={"low": _a7_low()}, final_count=1, strong_count=1,
                refill=None, manual=False, original_question="PRIVATE_QUERY",
                groups=[{"PRIVATE_TERM"}])
    calls = []
    def alias_fail(*args, **kwargs):
        calls.append("bilingual")
        raise RuntimeError("PRIVATE_FAILURE")
    def strategy(*args, **kwargs):
        calls.append("strategy")
        return '{"choice":"keep_original"}'
    monkeypatch.setattr(a2, "call_llm", alias_fail)
    monkeypatch.setattr(a7, "call_llm", strategy)
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        priority.observe_allocated_llm(**base)
        priority.observe_allocated_llm(**{**base, "diagnostics": {"low": _a7_low(status="no_trusted_anchor")}})
    assert calls == ["bilingual"]
    assert budget.snapshot()[0] == ArcUnits(llm_calls=1)
    assert "PRIVATE_" not in caplog.text
    assert "deferred_by_priority" in caplog.text
    assert "shared_budget_exhausted" in caplog.text
    assert '"choice":"bilingual"' in caplog.text
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        priority.observe_allocated_llm(**{**base, "diagnostics": {"high": _a7_high()},
                                         "final_count": 60, "strong_count": 60})
    assert calls == ["bilingual", "strategy"]
    assert budget.snapshot()[0] == ArcUnits(llm_calls=1)
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        priority.observe_allocated_llm(**{**base, "final_count": 3})
        priority.observe_allocated_llm(**{**base, "manual": True})
    assert budget.snapshot()[0] == ArcUnits()
    assert calls == ["bilingual", "strategy"]


def test_arc_deep_native_rank_scope_is_distinct_and_unchanged_output(monkeypatch, caplog):
    from agent.es.arc_native_rank_receipt import DeepNativeRankFrequency, DEEP_SCOPE
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
    monkeypatch.delenv("SRAF_ARC_RANK_DEEP", raising=False)
    baseline = build_hits_and_evidence(hits, **kw)
    record = {"schema":"sraf_arc_deep_frequency_shadow_v1", "scope":DEEP_SCOPE,
              "status":"observed_counts", "eligible_documents":10000,
              "groups":[{"group_ordinal":i, "document_frequency":df}
                        for i, df in enumerate((8000,7000,5000,50), 1)]}
    args = dict(groups=tuple(map(frozenset, groups)), date_from=kw["date_from"], date_to=kw["date_to"])
    receipt = DeepNativeRankFrequency.from_record(record, **args)
    assert receipt is not None
    assert DeepNativeRankFrequency.from_record({**record, "scope":"wrong"}, **args) is None
    assert DeepNativeRankFrequency.from_record({**record, "eligible_documents":True}, **args) is None
    assert receipt.for_builder(list(reversed(groups)), date_from=kw["date_from"],
                               date_to=kw["date_to"], allowed_years=None) is None
    monkeypatch.setenv("SRAF_ARC_RANK_DEEP", "shadow")
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        assert build_hits_and_evidence(hits, **kw, deep_rank_frequency=receipt) == baseline
    result = _rank_record(caplog)
    assert result["status"] == "observed_rank"
    assert result["scope"] == "same_round_pit_native_df_strict_first_prefix"
    assert result["snapshot_consistency"] == "same_round_pit"
    assert result["rarity_only_top_k_replaced"] == 1
    assert budget.snapshot()[0] == ArcUnits(slices=1, rows=128, chars=131072)


def _a9_rank_replay_case():
    from agent.es.arc_frequency_plan import SCOPE
    groups = [["美國"], ["政策"], ["出口管制"], ["半導體"]]
    rows = [{"text":"美國 政策 出口管制","source":i,"group_hits":3,
             "weak":False,"direct_anchor":True,"gold":"unrelated"} for i in range(24)]
    rows.append({"text":"美國 政策 半導體","source":24,"group_hits":3,
                 "weak":False,"direct_anchor":True,"gold":"relevant"})
    return {"groups":groups,"frequency":{
        "schema":"sraf_arc_native_rank_frequency_v1","scope":SCOPE,
        "status":"exact_es_query_counts","eligible_documents":10000,
        "groups":[{"group_ordinal":i,"document_frequency":df}
                  for i,df in enumerate((8000,7000,5000,50),1)]},"rows":rows}


def test_a9_rank_replay_matches_actual_shadow_and_evaluates_top20():
    from agent.es.evidence_core.arc_rank_replay import replay_rank_cases
    from agent.es.evidence_core.arc_rank_shadow import observe_rank_shadow
    from agent.es.evidence_core.models import EvidenceSnippet
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    case = _a9_rank_replay_case()
    result = replay_rank_cases([case])
    evidence = [EvidenceSnippet(uuid="", text=r["text"], date_iso="", article_date_iso="",
                group_hits=r["group_hits"],weak_evidence=r["weak"],source_hit_ordinal=r["source"])
                for r in case["rows"]]
    with bind_arc_budget((ArcRequestBudget(),1)):
        actual = observe_rank_shadow(evidence,[set(g) for g in case["groups"]],case["frequency"])
    assert actual["rarity_only_top_k_replaced"] == 1
    cf = result["comparison"]
    assert cf["full_selection"]["net_relevant_change"] == 0
    assert cf["top_20"]["net_relevant_change"] == 1
    assert cf["top_20"]["candidate"]["known_label_precision"]["value"] == 1/20
    assert result["frequency_scope_cases"] == {actual["scope"]:1}
    assert "美國" not in repr(result)
    assert "ordinal" not in repr(result)


def test_a9_rank_replay_rejects_invalid_or_partial_fixtures():
    from copy import deepcopy
    from agent.es.evidence_core.arc_rank_replay import replay_rank_cases
    for key, value in [("source", True),("group_hits",5),("weak",0),
                       ("gold","missing"),("text","x"*4097)]:
        c = _a9_rank_replay_case()
        c["rows"][0][key] = value
        assert replay_rank_cases([c]) is None
    for change in ("short","duplicate_group_term","bad_scope","extra_text","bad_frequency"):
        c = _a9_rank_replay_case()
        if change == "short":
            c["rows"] = c["rows"][:20]
        elif change == "duplicate_group_term":
            c["groups"][0].append(c["groups"][0][0])
        elif change == "bad_scope":
            c["frequency"]["scope"] = "PRIVATE"
        elif change == "extra_text":
            c["question"] = "PRIVATE"
        else:
            c["frequency"]["groups"][0]["document_frequency"] = 10001
        assert replay_rank_cases([c]) is None


def test_a9_rank_replay_cli_privacy(tmp_path, capsys):
    import json
    from agent.es.evidence_core.arc_eval_cli import main
    p = tmp_path / "PRIVATE_REPLAY.json"
    p.write_text(json.dumps([_a9_rank_replay_case()],ensure_ascii=False),encoding="utf-8")
    assert main(["rank-replay",str(p)]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["result"]["comparison"]["top_20"]["net_relevant_change"] == 1
    assert "PRIVATE" not in out.out and "美國" not in out.out and not out.err


def _a9_measured(status="completed", elapsed=100, es=1, llm=0, prompt=0, completion=0):
    return {"status":status,"elapsed_ms":elapsed,"es_calls":es,
            "llm_calls":llm,"prompt_tokens":prompt,"completion_tokens":completion}


def test_arc_a9_resources_pairs_actual_observations_and_retains_failures():
    from agent.es.evidence_core.arc_resource_eval import evaluate_resource_cases
    cases = [
        {"baseline":_a9_measured(elapsed=100),"candidate":_a9_measured(elapsed=120,llm=1,prompt=40,completion=10)},
        {"baseline":_a9_measured(elapsed=200),"candidate":_a9_measured(elapsed=160)},
        {"baseline":_a9_measured(elapsed=300),"candidate":_a9_measured(status="timed_out",elapsed=500,llm=1,prompt=None,completion=None)},
    ]
    result = evaluate_resource_cases(cases)
    assert result["both_completed_cases"] == 2
    assert result["status_transitions"]["completed"]["timed_out"] == 1
    elapsed = result["all_attempts"]["elapsed_ms"]
    assert elapsed["baseline_total"] == 600 and elapsed["candidate_total"] == 780
    assert elapsed["delta_total"] == 180
    assert elapsed["relative_delta"]["value"] == .3
    assert elapsed["baseline_p50"] == 200 and elapsed["candidate_p95"] == 500
    assert elapsed["paired_delta_p95"] == 200
    assert elapsed["candidate_higher_cases"] == 2 and elapsed["candidate_lower_cases"] == 1
    assert result["both_completed"]["elapsed_ms"]["delta_total"] == -20
    tokens = result["all_attempts"]["prompt_tokens"]
    assert tokens["paired_cases"] == 2 and tokens["missing_candidate"] == 1
    assert tokens["candidate_total"] == 40 and tokens["relative_delta"]["value"] is None
    assert result["all_attempts"]["llm_calls"]["candidate_total"] == 2


def test_arc_a9_resources_missing_values_and_no_joint_success_are_not_zero_cost():
    from agent.es.evidence_core.arc_resource_eval import evaluate_resource_cases
    result = evaluate_resource_cases([
        {"baseline":_a9_measured(status="failed",elapsed=None,prompt=None),
         "candidate":_a9_measured(status="cancelled",elapsed=50,prompt=40)}
    ])
    assert result["both_completed_cases"] == 0
    assert result["all_attempts"]["elapsed_ms"]["paired_cases"] == 0
    assert result["all_attempts"]["elapsed_ms"]["candidate_total"] is None
    assert result["all_attempts"]["prompt_tokens"]["baseline_p95"] is None
    assert result["both_completed"]["llm_calls"]["baseline_total"] is None


def test_arc_a9_resources_rejects_estimates_malformed_and_private_fields():
    from agent.es.evidence_core.arc_resource_eval import evaluate_resource_cases
    row = _a9_measured()
    for invalid in ([], [{"baseline":row,"candidate":{**row,"status":"unknown"}}],
                    [{"baseline":row,"candidate":{**row,"elapsed_ms":True}}],
                    [{"baseline":row,"candidate":{**row,"llm_calls":-1}}],
                    [{"baseline":row,"candidate":{**row,"prompt_tokens":1.5}}],
                    [{"baseline":row,"candidate":{**row,"es_calls":10**12+1}}],
                    [{"baseline":row,"candidate":{**row,"reserved":1}}],
                    [{"baseline":row,"candidate":{**row,"private_prompt":"PRIVATE"}}],
                    [{"baseline":row,"candidate":row,"case_id":"PRIVATE"}],
                    [{"baseline":row,"candidate":row}]*33):
        assert evaluate_resource_cases(invalid) is None


def test_arc_a9_resource_eval_cli_aggregate_only(tmp_path,capsys):
    import json
    from agent.es.evidence_core.arc_eval_cli import main
    p = tmp_path / "PRIVATE_RESOURCE_CASES.json"
    p.write_text(json.dumps([{"baseline":_a9_measured(elapsed=100),
                              "candidate":_a9_measured(elapsed=120,llm=1,prompt=None)}]),
                 encoding="utf-8")
    assert main(["resources",str(p)]) == 0
    out = capsys.readouterr()
    obj = json.loads(out.out)
    assert obj["status"] == "EVALUATED_OFFLINE"
    assert obj["result"]["all_attempts"]["elapsed_ms"]["delta_total"] == 20
    assert obj["result"]["all_attempts"]["prompt_tokens"]["paired_cases"] == 0
    assert not out.err and "PRIVATE_RESOURCE_CASES" not in out.out
    p.write_text(json.dumps([{"baseline":_a9_measured(),"candidate":{**_a9_measured(),"private_text":"PRIVATE"}}]),encoding="utf-8")
    assert main(["resources",str(p)]) == 2
    out = capsys.readouterr()
    assert not out.out and json.loads(out.err)["status"] == "INVALID_OR_UNREADABLE_FIXTURE"
