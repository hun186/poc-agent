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


def _a9_screen_case():
    rows = [{"ordinal":1,"source":0,"gold":"relevant","direct_anchor":True,"strong":True,
             "baseline_rank":1,"candidate_rank":1},
            {"ordinal":2,"source":1,"gold":"unrelated","direct_anchor":False,"strong":False,
             "baseline_rank":2,"candidate_rank":None},
            {"ordinal":3,"source":2,"gold":"relevant","direct_anchor":False,"strong":False,
             "baseline_rank":None,"candidate_rank":2}]
    return {"selection":rows,"resources":{"baseline":_a9_measured(elapsed=100),
                         "candidate":_a9_measured(elapsed=120)}}


def _a9_screen_fixture():
    return {"policy":{"minimum_cases":2,"min_full_precision_delta_bps":0,
                       "min_top20_precision_delta_bps":0,"min_net_relevant_gain":2,
                       "max_elapsed_increase_ms":20,"max_es_call_increase":0,
                       "max_llm_call_increase":0,"max_prompt_token_increase":0,
                       "max_completion_token_increase":0},
            "cases":[_a9_screen_case(),_a9_screen_case()]}


def test_arc_a9_acceptance_screen_requires_per_case_quality_and_resources():
    from agent.es.evidence_core.arc_acceptance_screen import screen_selection_acceptance
    fixture=_a9_screen_fixture()
    result=screen_selection_acceptance(fixture)
    assert result["status"]=="MEETS_OFFLINE_THRESHOLDS"
    assert result["production_authorized"] is False
    assert result["quality"]["full_selection"]["net_relevant_change"]==2
    assert not result["blockers"] and not result["incomplete"]
    # An extra-fast case cannot hide the regression of a different case.
    fixture["cases"][0]["resources"]["candidate"]["elapsed_ms"]=1
    fixture["cases"][1]["resources"]["candidate"]["elapsed_ms"]=121
    result=screen_selection_acceptance(fixture)
    assert result["status"]=="BLOCKED"
    assert result["blockers"]["elapsed_ms_increase_above_policy"]==1


def test_arc_a9_acceptance_screen_never_offsets_protected_loss_or_hides_failed_attempt():
    from agent.es.evidence_core.arc_acceptance_screen import screen_selection_acceptance
    fixture=_a9_screen_fixture()
    first=fixture["cases"][0]
    first["selection"][0]["candidate_rank"]=None
    first["selection"][2]["candidate_rank"]=1
    first["resources"]["candidate"]["status"]="timed_out"
    result=screen_selection_acceptance(fixture)
    assert result["status"]=="BLOCKED"
    assert result["blockers"]["full_relevant_removed"]==1
    assert result["blockers"]["full_relevant_anchor_loss"]==1
    assert result["blockers"]["full_relevant_source_loss"]==1
    assert result["blockers"]["attempt_not_jointly_completed"]==1
    assert result["production_authorized"] is False


def test_arc_a9_acceptance_screen_unknown_measurements_and_uncertainty_abstain():
    from agent.es.evidence_core.arc_acceptance_screen import screen_selection_acceptance
    fixture=_a9_screen_fixture()
    fixture["policy"]["minimum_cases"]=3
    fixture["cases"][0]["resources"]["candidate"]["prompt_tokens"]=None
    fixture["cases"][0]["selection"].append({"ordinal":4,"source":3,"gold":"uncertain",
        "direct_anchor":False,"strong":False,"baseline_rank":None,"candidate_rank":3})
    result=screen_selection_acceptance(fixture)
    assert result["status"]=="INCOMPLETE"
    assert result["incomplete"]["minimum_case_count_not_met"]==1
    assert result["incomplete"]["prompt_tokens_not_measured"]==1
    assert result["incomplete"]["full_uncertain_selection_changed"]==1
    assert result["production_authorized"] is False
    fixture["policy"]["minimum_cases"]=True
    assert screen_selection_acceptance(fixture) is None


def test_arc_a9_acceptance_screen_explicit_precision_tolerance_and_cli(tmp_path,capsys):
    import json
    from agent.es.evidence_core.arc_eval_cli import main
    from agent.es.evidence_core.arc_acceptance_screen import screen_selection_acceptance
    fixture=_a9_screen_fixture()
    # Retain the existing unrelated row and add another unrelated row.
    # Baseline precision 1/2; candidate precision 2/4, exactly unchanged.
    case=fixture["cases"][0]
    case["selection"][1]["candidate_rank"]=3
    case["selection"].append({"ordinal":4,"source":3,"gold":"unrelated",
        "direct_anchor":False,"strong":False,"baseline_rank":None,"candidate_rank":4})
    assert screen_selection_acceptance(fixture)["status"]=="MEETS_OFFLINE_THRESHOLDS"
    fixture["policy"]["min_full_precision_delta_bps"]=1
    assert screen_selection_acceptance(fixture)["blockers"]["full_precision_delta_below_policy"]==1
    path=tmp_path/"PRIVATE_SCREEN.json"
    path.write_text(json.dumps(fixture),encoding="utf-8")
    assert main(["acceptance",str(path)])==0
    out=capsys.readouterr()
    assert json.loads(out.out)["result"]["status"]=="BLOCKED"
    assert "PRIVATE_SCREEN" not in out.out and not out.err


def test_arc_release_env_example_covers_runtime_settings_and_safe_defaults():
    import ast
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / ".env.example").read_text(encoding="utf-8")
    assignments = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\s*(#\s*)?(SRAF_ARC_[A-Z0-9_]+)=(.*)", line)
        if match:
            commented, name, value = match.groups()
            # Ignore commented alternative values, but retain documented
            # optional settings when there is no active assignment.
            assignments.setdefault(name, []).append((bool(commented), value))
    from agent.arc_mode import SHADOW_FLAGS, LOCAL_SHADOW_FLAGS
    required = set(SHADOW_FLAGS)
    for folder in ("agent", "api", "sra_api"):
        for source in (root / folder).rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                key = None
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "arc_shadow_enabled" and node.args):
                    key = node.args[0]
                    if isinstance(key, ast.Constant):
                        assert key.value in SHADOW_FLAGS
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("getenv", "get", "setdefault")
                        and node.args):
                    key = node.args[0]
                elif (isinstance(node, ast.Subscript)
                      and isinstance(node.value, ast.Attribute)
                      and node.value.attr == "environ"):
                    key = node.slice
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and key.value.startswith("SRAF_ARC_")):
                    required.add(key.value)
                    if key.value in SHADOW_FLAGS:
                        assert isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "arc_shadow_enabled", str(source)
    from dataclasses import asdict
    from agent.es.evidence_core.group_frequency import GroupFrequencyBudget
    for key, value in asdict(GroupFrequencyBudget()).items():
        name = "SRAF_ARC_GROUP_FREQUENCY_MAX_" + key.upper()
        required.add(name)
        assert (True, str(value)) in assignments.get(name, [])
    assert required
    assert not required.difference(assignments), sorted(required.difference(assignments))
    for name, entries in assignments.items():
        active = [value for commented, value in entries if not commented]
        if name in LOCAL_SHADOW_FLAGS:
            assert not active and (True, "off") in entries, name
        elif name.startswith("SRAF_ARC_GROUP_FREQUENCY_MAX_"):
            assert not active
        else:
            assert len(active) == 1, name
            if (name.endswith("_INDEX") or name.startswith("SRAF_ARC_CAPTURE_")
                    or name in {"SRAF_ARC_REVIEW_ENDPOINT", "SRAF_ARC_REVIEW_MODEL",
                                "SRAF_ARC_REVIEW_CA_FILE"}):
                assert active == [""], name
            else:
                assert active == ["off"], name
    assert set(assignments) == required


def test_arc_master_mode_legacy_shadow_override_and_fail_closed(monkeypatch):
    from agent.arc_mode import arc_shadow_enabled, SHADOW_FLAGS, LOCAL_SHADOW_FLAGS
    for flag in SHADOW_FLAGS | {"SRAF_ARC_MODE"}:
        monkeypatch.delenv(flag, raising=False)
    assert not any(arc_shadow_enabled(flag) for flag in SHADOW_FLAGS)
    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
    assert arc_shadow_enabled("SRAF_ARC_BILINGUAL")
    monkeypatch.delenv("SRAF_ARC_BILINGUAL")
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    assert {flag for flag in SHADOW_FLAGS if arc_shadow_enabled(flag)} == LOCAL_SHADOW_FLAGS
    monkeypatch.setenv("SRAF_ARC_RANK", "off")
    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW", "on")
    assert not arc_shadow_enabled("SRAF_ARC_RANK")
    assert arc_shadow_enabled("SRAF_ARC_BILINGUAL")
    assert not arc_shadow_enabled("SRAF_ARC_REVIEW")
    assert not arc_shadow_enabled("SRAF_ARC_REVIEW_EGRESS")
    for mode in ("off", "on", "", "SHADOW", "unknown"):
        monkeypatch.setenv("SRAF_ARC_MODE", mode)
        for flag in SHADOW_FLAGS:
            monkeypatch.setenv(flag, "shadow")
        assert not any(arc_shadow_enabled(flag) for flag in SHADOW_FLAGS)
    # Resolution must not erase explicit overrides from the environment.
    import os
    assert os.getenv("SRAF_ARC_BILINGUAL") == "shadow"


def test_arc_master_shadow_external_features_remain_independently_gated(monkeypatch):
    from agent.arc_mode import SHADOW_FLAGS
    from agent.es.arc_bilingual_shadow import bilingual_shadow_enabled
    from agent.es.arc_frequency_shadow import native_frequency_enabled
    from agent.es.arc_strategy_shadow import strategy_enabled
    from agent.adaptive_retrieval.arc_deep_frequency_transport import deep_frequency_enabled
    from agent.adaptive_retrieval.arc_deep_review import deep_review_enabled
    from agent.es.arc_review_scope import review_scope_enabled
    for flag in SHADOW_FLAGS:
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    assert not any(f() for f in (bilingual_shadow_enabled, native_frequency_enabled,
                                strategy_enabled, deep_frequency_enabled, deep_review_enabled))
    assert not review_scope_enabled("news_test")
    monkeypatch.setenv("SRAF_ARC_REVIEW_DEEP", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW", "shadow")
    assert deep_review_enabled()
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "off")
    assert not deep_review_enabled()
    for flag in SHADOW_FLAGS:
        monkeypatch.setenv(flag, "shadow")
    monkeypatch.setenv("SRAF_ARC_MODE", "off")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    assert not any(f() for f in (bilingual_shadow_enabled, native_frequency_enabled,
                                strategy_enabled, deep_frequency_enabled, deep_review_enabled))
    assert not review_scope_enabled("news_test")


def test_arc_config_doctor_local_preset_and_explicit_override(monkeypatch):
    from agent.arc_mode import SHADOW_FLAGS, LOCAL_SHADOW_FLAGS
    from agent.arc_config_doctor import configuration_report
    for name in SHADOW_FLAGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    report = configuration_report()
    assert report["mode"] == "shadow"
    assert {k for k, v in report["features"].items() if v["enabled_by_mode"]} == LOCAL_SHADOW_FLAGS
    assert not report["formal_arc_selection_enabled"]
    assert not report["runtime_authorization_verified"]
    assert not report["live_connectivity_verified"]
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "off")
    report = configuration_report()
    assert report["status"] == "CONFIG_ATTENTION"
    assert report["features"]["SRAF_ARC_GROUP_FREQUENCY"]["reasons"] == ["explicit_local_override"]
    assert report["features"]["SRAF_ARC_RANK"]["status"] == "configuration_blocked"
    assert report["features"]["SRAF_ARC_RANK"]["reasons"] == ["group_frequency_disabled"]


def test_arc_config_doctor_optional_dependencies_and_privacy(monkeypatch, capsys):
    import json
    from agent.arc_mode import SHADOW_FLAGS
    from agent.arc_config_doctor import main
    for name in SHADOW_FLAGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_ES_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_ES_FREQUENCY_VERIFIED_INDEX", "private_index")
    monkeypatch.setenv("SRAF_ARC_RANK_NATIVE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_DEEP", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "private_index")
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "https://private.example/api/chat")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL", "private_model")
    monkeypatch.setenv("SRAF_ARC_REVIEW_CA_FILE", "/private/ca.pem")
    monkeypatch.setenv("SRAF_ARC_CAPTURE_ES_PASSWORD", "PRIVATE_PASSWORD")
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY_MAX_CHARS", "999999")
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY_MAX_ROWS", "PRIVATE_INVALID")
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "on")
    assert main([]) == 2
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["features"]["SRAF_ARC_ES_FREQUENCY"]["status"] == "requires_runtime_scope"
    assert report["features"]["SRAF_ARC_REVIEW_DEEP"]["status"] == "requires_runtime_scope"
    assert report["budget_notes"] == {"chars":"clamped_to_ceiling", "rows":"invalid_uses_default"}
    assert report["group_frequency_budget"]["chars"] == 131072
    assert report["legacy_topic_adaptive_can_change_selection"]
    assert all(value not in out for value in ("private_index", "private.example", "private_model", "/private/ca.pem", "PRIVATE_PASSWORD", "PRIVATE_INVALID", "999999"))
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "http://private.example/api/chat")
    assert main([]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["features"]["SRAF_ARC_REVIEW"]["status"] == "configuration_blocked"
    monkeypatch.setenv("SRAF_ARC_MODE", "on")
    assert main([]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "unsupported"
    assert not any(v["enabled_by_mode"] for v in report["features"].values())


def test_a9_rank_replay_actual_report_count_cap_distinguishes_top20():
    from agent.es.evidence_core.arc_rank_replay import replay_rank_cases
    small = _a9_rank_replay_case()
    small["report_selection"] = {"scope":"complete_report_input_strong_first","limit":20}
    all_rows = _a9_rank_replay_case()
    all_rows["report_selection"] = {"scope":"complete_report_input_strong_first","limit":120}
    for case, expected_gain, selected in ((small,1,20),(all_rows,0,25)):
        result = replay_rank_cases([case])
        assert result["comparison"]["top_20"]["net_relevant_change"] == 1
        comp = result["report_selection_comparison"]["full_selection"]
        assert comp["baseline"]["selected"] == comp["candidate"]["selected"] == selected
        assert comp["net_relevant_change"] == expected_gain
        assert result["report_selection_limit_cases"] == {str(case["report_selection"]["limit"]):1}
    assert replay_rank_cases([_a9_rank_replay_case()])["report_selection_comparison"] is None


def test_a9_rank_report_cap_respects_legacy_strong_first():
    from agent.es.evidence_core.arc_rank_replay import replay_rank_cases
    case = _a9_rank_replay_case()
    for row in case["rows"][:5]:
        row["weak"] = True
    # Relevant rare evidence is weak and cannot displace strong evidence.
    case["rows"][-1]["weak"] = True
    case["report_selection"] = {"scope":"complete_report_input_strong_first","limit":19}
    result = replay_rank_cases([case])
    comp = result["report_selection_comparison"]["full_selection"]
    assert comp["baseline"]["selected"] == comp["candidate"]["selected"] == 19
    assert comp["baseline"]["gold_counts"]["relevant"] == comp["candidate"]["gold_counts"]["relevant"] == 0
    assert comp["net_relevant_change"] == 0


import pytest


@pytest.mark.parametrize("selection", [None, {}, {"scope":"complete_report_input_strong_first","limit":True},
    {"scope":"complete_report_input_strong_first","limit":129},
    {"scope":"prefix","limit":20}, {"scope":"source_diverse","limit":20},
    {"scope":"complete_report_input_strong_first","limit":20,"private":"PRIVATE"}])
def test_a9_rank_report_cap_requires_explicit_complete_input_scope(selection):
    from agent.es.evidence_core.arc_rank_replay import replay_rank_cases
    case = _a9_rank_replay_case()
    case["report_selection"] = selection
    assert replay_rank_cases([case]) is None


def test_shared_strong_first_report_selection_keeps_exact_legacy_behavior():
    from agent.utils.report_evidence_selection import select_strong_first_evidence
    rows = [{"text":str(i), **({"weak_evidence": True} if i in (0,3) else {})} for i in range(6)]
    for limit in (-1,0,1,3,5,6,120):
        strong = [e for e in rows if not e.get("weak_evidence")]
        weak = [e for e in rows if e.get("weak_evidence")]
        expected = strong[:limit]
        if len(expected)<limit:
            expected += weak[:limit-len(expected)]
        picked = select_strong_first_evidence(rows,limit)
        assert picked == expected
        assert all(a is b for a,b in zip(picked,expected))
    assert [row["text"] for row in rows] == [str(i) for i in range(6)]


def test_a5_report_replay_distinguishes_real_cap_from_full_prefix_loss():
    from test_sraf_bounded_evidence_rescue import _a9_tighten_replay_case
    from agent.es.evidence_core.arc_tighten_replay import replay_tightening_cases
    for limit, lost, selected in ((20, 0, 20), (120, 10, 50)):
        case = _a9_tighten_replay_case()
        case["report_selection"] = {"scope":"complete_report_input_strong_first","limit":limit}
        result = replay_tightening_cases([case])
        assert result["report_selection_limit_cases"] == {str(limit):1}
        for strategy in result["strategies"].values():
            assert strategy["comparison"]["full_selection"]["removed"]["relevant"] == 10
            assert strategy["report_selection_cases"] == 1
            assert strategy["report_floor_fallback_cases"] == 0
            comp = strategy["report_selection_comparison"]["full_selection"]
            assert comp["baseline"]["selected"] == selected
            assert comp["candidate"]["selected"] == 20
            assert comp["removed"]["relevant"] == lost
            assert comp["baseline_relevant_source_loss"]["numerator"] == lost
        assert "美國" not in repr(result)


def test_a5_report_replay_retains_baseline_when_candidate_floor_fails():
    from test_sraf_bounded_evidence_rescue import _a9_tighten_replay_case
    from agent.es.evidence_core.arc_tighten_replay import replay_tightening_cases
    case = _a9_tighten_replay_case()
    for row in case["rows"][:20]:
        row["weak"] = True
    case["report_selection"] = {"scope":"complete_report_input_strong_first","limit":120}
    result = replay_tightening_cases([case])
    for strategy in result["strategies"].values():
        assert strategy["sample_floor_met_cases"] == 0
        assert strategy["comparison"]["full_selection"]["candidate"]["selected"] == 0
        assert strategy["report_floor_fallback_cases"] == 1
        comp = strategy["report_selection_comparison"]["full_selection"]
        assert comp["baseline"] == comp["candidate"]
        assert comp["candidate"]["selected"] == 50
        assert comp["removed"]["relevant"] == 0


@pytest.mark.parametrize("selection", [None, {}, {"scope":"prefix","limit":20},
    {"scope":"source_diverse","limit":20},
    {"scope":"complete_report_input_strong_first","limit":True},
    {"scope":"complete_report_input_strong_first","limit":0},
    {"scope":"complete_report_input_strong_first","limit":129}])
def test_a5_report_replay_requires_explicit_complete_report_scope(selection):
    from test_sraf_bounded_evidence_rescue import _a9_tighten_replay_case
    from agent.es.evidence_core.arc_tighten_replay import replay_tightening_cases
    case = _a9_tighten_replay_case()
    case["report_selection"] = selection
    assert replay_tightening_cases([case]) is None


def test_a5_report_replay_legacy_fixture_retains_counterfactual_only():
    from test_sraf_bounded_evidence_rescue import _a9_tighten_replay_case
    from agent.es.evidence_core.arc_tighten_replay import replay_tightening_cases
    result = replay_tightening_cases([_a9_tighten_replay_case()])
    assert result["report_selection_limit_cases"] == {}
    for strategy in result["strategies"].values():
        assert strategy["report_selection_cases"] == 0
        assert strategy["report_selection_comparison"] is None


def test_arc_priority_selected_review_never_requires_topic_provider_or_falls_back(monkeypatch, caplog):
    from agent.es import arc_llm_priority as priority
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    monkeypatch.setenv("SRAF_ARC_LLM_PRIORITY", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
    monkeypatch.delenv("TOPIC_LLM_URL", raising=False)
    calls = []
    monkeypatch.setattr(priority, "observe_strategy", lambda **kw: calls.append(kw["allow_model"]))
    monkeypatch.setattr(priority, "observe_bilingual_proposal", lambda **kw: pytest.fail("unexpected A2"))
    with bind_arc_budget((ArcRequestBudget(), 1)):
        priority.observe_allocated_llm(
            pressure=CandidatePressure("eq", 100, 50), diagnostics={"high": _a7_high()},
            final_count=60, strong_count=60, refill=None, manual=False,
            original_question="PRIVATE_QUERY", groups=[{"PRIVATE_TERM"}], review_selected=True)
    assert calls == [False]
    assert '"choice":"semantic_review"' in caplog.text
    assert "provider_unavailable" not in caplog.text
    assert "PRIVATE_" not in caplog.text


@pytest.mark.parametrize("deadline", [None, 125, 124.99, 100, float("nan"), float("inf"), True, "125", 10**500])
def test_arc_shared_model_deadline_atomic_admission(monkeypatch, deadline):
    from agent.es import arc_request_budget as arc
    monkeypatch.setattr(arc, "monotonic", lambda: 100)
    budget = arc.ArcRequestBudget(model_deadline_monotonic=deadline)
    expected = deadline is None or type(deadline) is int and deadline == 125
    assert budget.reserve(1, arc.ArcUnits(slices=1))
    assert budget.model_window_open() is expected
    assert budget.reserve(1, arc.ArcUnits(llm_calls=1)) is expected
    assert budget.snapshot()[0].llm_calls == int(expected)


def test_arc_shared_model_deadline_spans_rounds_and_is_not_refunded(monkeypatch):
    from agent.es import arc_request_budget as arc
    clock = [100]
    monkeypatch.setattr(arc, "monotonic", lambda: clock[0])
    budget = arc.ArcRequestBudget(model_deadline_monotonic=140)
    assert budget.reserve(1, arc.ArcUnits(llm_calls=1))
    clock[0] = 116
    assert not budget.reserve(2, arc.ArcUnits(llm_calls=1))
    assert budget.model_window_open(admission=False)
    clock[0] = 140
    assert not budget.model_window_open(admission=False)
    assert budget.snapshot()[0].llm_calls == 1
    assert budget.reserve(2, arc.ArcUnits(slices=1))
    budget.seal()
    assert not budget.model_window_open(admission=False)


@pytest.mark.parametrize("task", ["bilingual", "strategy"])
@pytest.mark.parametrize("timing", ["insufficient", "expires_in_call", "on_time"])
def test_arc_topic_model_observers_share_deadline(monkeypatch, caplog, task, timing):
    from agent.es import arc_request_budget as arc, arc_bilingual_shadow as a2, arc_strategy_shadow as a7
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    clock = [100]
    monkeypatch.setattr(arc, "monotonic", lambda: clock[0])
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("TOPIC_LLM_URL", "http://topic.invalid")
    calls = []
    def model(*args, **kwargs):
        calls.append(task)
        if timing == "expires_in_call":
            clock[0] = 150
        return '{"choice":"keep_original"}'
    monkeypatch.setattr(a2, "call_llm", model)
    monkeypatch.setattr(a7, "call_llm", model)
    monkeypatch.setattr(a2, "parse_proposal", lambda raw, groups: groups)
    budget = arc.ArcRequestBudget(model_deadline_monotonic=124 if timing == "insufficient" else 150)
    with arc.bind_arc_budget((budget, 1)):
        if task == "bilingual":
            a2.observe_bilingual_proposal(original_question="PRIVATE_QUESTION", groups=[{"PRIVATE_TERM"}], manual=False)
        else:
            a7.observe_strategy(pressure=CandidatePressure("eq", 100, 50),
                diagnostics={"low": _a7_low()}, final_count=1, strong_count=1,
                refill=None, manual=False, original_question="PRIVATE_QUESTION",
                groups=[{"PRIVATE_TERM"}])
    assert calls == ([] if timing == "insufficient" else [task])
    assert budget.snapshot()[0].llm_calls == len(calls)
    assert ("model_deadline_or_scope_closed" in caplog.text) == (timing != "on_time")
    assert ("observed_candidates" in caplog.text or "observed_advice" in caplog.text) == (timing == "on_time")
    assert "PRIVATE_" not in caplog.text
