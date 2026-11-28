"""Provenance-bound N-round coordinator bridge (no actual ES, LLM or Job)."""
from __future__ import annotations

import json

import pytest

from agent.adaptive_retrieval.coverage_evaluator import (
    EvidenceFacetWitness, RequestWideCoverageEvaluator,
)
from agent.adaptive_retrieval.evidence_ledger import observe_canonical_round
from test_sraf_nround_coordinator import coordinator, scope
from test_sraf_shared_evidence_budget import _hit


def _witnesses(c, hits, *, target_indexes=(0, 1)):
    observation = observe_canonical_round(
        hits,
        date_from=c._constraints.event_date.start,
        date_to=c._constraints.event_date.end,
        term_groups=list(c._groups),
        effective_terms=list(c._effective),
        query_for_snippet="甲軸乙軸丙軸",
        original_question=c._constraints.question,
        complete=True,
    )
    return tuple(EvidenceFacetWitness(index, ev, src)
                 for index in target_indexes
                 for ev, src in sorted(observation.evidence_source_pairs))


def _assess(c, evaluator, hits, *, witnesses=None, sufficient=True,
            attested=True, complete=True, verifier=lambda *_: True):
    return c.complete_round(
        hits, query_for_snippet="甲軸乙軸丙軸",
        complete=complete, request_wide_attested=attested,
        missing_aspects=(), coverage_sufficient=sufficient,
        coverage_evaluator=evaluator,
        coverage_witnesses=(_witnesses(c, hits) if witnesses is None
                            else witnesses),
        semantic_verifier=verifier,
    )


def test_two_rounds_real_canonical_coverage_overrides_spoofed_sufficient_boolean():
    c, budget, calls = coordinator()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=("後續影響",),
    )
    assert c.start() and c.admit_es_call()
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    first = _assess(c, evaluator, a, sufficient=True)
    assert first.request_wide is True
    assert first.coverage_sufficient is False  # one source only
    assert len(first.missing_aspects) == 2
    assert first.known_sources == 1
    assert c.safe_progress()["phase"] == "ASSESSED"
    assert c.safe_progress()["ready_for_external_report_generation"] is False

    admitted = c.plan_next_round()
    assert admitted.approved
    assert admitted.plan is c._approved_plan
    assert calls == ["planner"]
    assert c.admit_es_call()
    b = [_hit(2, "PRIVATE_DOC_B", inner=False)]
    second = _assess(c, evaluator, b, sufficient=False)
    assert second.coverage_sufficient is True  # both targets, two sources
    assert second.missing_aspects == ()
    assert second.verified_evidence == 4
    assert second.known_sources == 2
    assert second.newly_verified_evidence == 2
    progress = c.safe_progress()
    assert progress["termination"] == "SUFFICIENT"
    assert progress["ready_for_external_report_generation"] is True
    assert progress["report_job"] == "NOT_INTEGRATED"
    assert budget.rounds_started == 2
    audit = json.dumps(progress, ensure_ascii=False)
    for forbidden in ("PRIVATE_DOC", "甲軸", "後續影響", "news_test", "2023-08-24"):
        assert forbidden not in audit


def test_missing_second_aspect_keeps_planner_eligible_after_completed_round():
    c, _, calls = coordinator()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=("後續影響",),
        min_sources_per_target=1, min_evidence_per_target=1,
    )
    assert c.start() and c.admit_es_call()
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    first = _assess(c, evaluator, a,
                    witnesses=_witnesses(c, a, target_indexes=(0,)))
    assert first.coverage_sufficient is False
    assert first.missing_aspects == ("後續影響",)
    assert c.safe_progress()["phase"] == "ASSESSED"
    assert c.plan_next_round().approved
    assert calls == ["planner"]


def test_no_semantic_verifier_rejects_and_does_not_authorize_next_round():
    c, _, calls = coordinator()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=())
    assert c.start() and c.admit_es_call()
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    with pytest.raises(ValueError, match="round_assessment_failed"):
        _assess(c, evaluator, a, verifier=None)
    assert c.safe_progress()["termination"] == "EVIDENCE_VALIDATION_FAILED"
    assert c.safe_progress()["completed_rounds"] == 0
    assert not c.admit_es_call()
    assert calls == []


def test_unbound_or_wrong_scope_evaluator_is_fail_closed():
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    another_scope = scope()
    assert another_scope == c._constraints and another_scope is not c._constraints
    evaluator = RequestWideCoverageEvaluator(
        constraints=another_scope, target_aspects=())
    with pytest.raises(ValueError, match="round_assessment_failed"):
        _assess(c, evaluator, a)
    assert c.safe_progress()["termination"] == "EVIDENCE_VALIDATION_FAILED"


def test_forged_evidence_source_pair_cancels_planning():
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=())
    a, b = [_hit(2, "PRIVATE_DOC_A", inner=False)], [_hit(2, "PRIVATE_DOC_B", inner=False)]
    original = _witnesses(c, a, target_indexes=(0,))[0]
    wrong_source = _witnesses(c, b, target_indexes=(0,))[0]
    witness = EvidenceFacetWitness(
        0, original.evidence_digest, wrong_source.source_digest)
    with pytest.raises(ValueError, match="round_assessment_failed"):
        _assess(c, evaluator, a, witnesses=(witness,))
    assert c.safe_progress()["completed_rounds"] == 0
    assert c.safe_progress()["termination"] == "EVIDENCE_VALIDATION_FAILED"


def test_missing_request_wide_attestation_cannot_claim_sufficient():
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=(),
        min_evidence_per_target=1, min_sources_per_target=1)
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    record = _assess(c, evaluator, a, attested=False, sufficient=True)
    assert record.result_incomplete is False
    assert record.request_wide is False
    assert record.coverage_sufficient is False
    assert c.safe_progress()["termination"] == "REQUEST_LEVEL_ASSESSMENT_REQUIRED"
    assert not c.safe_progress()["ready_for_external_report_generation"]


def test_incomplete_round_does_not_invoke_semantic_verifier():
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=())
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    calls = []
    record = _assess(
        c, evaluator, a, complete=False,
        verifier=lambda *_: calls.append(1) or True,
    )
    assert not record.coverage_sufficient
    assert record.result_incomplete
    assert c.safe_progress()["termination"] == "SAME_PLAN_SEARCH_INCOMPLETE"
    assert calls == []


def test_cancel_during_semantic_verifier_cannot_append_to_ledger():
    c, _, calls = coordinator()
    assert c.start() and c.admit_es_call()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=())
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    def cancel(*_):
        assert c.cancel()
        return True
    with pytest.raises(ValueError, match="round_assessment_failed"):
        _assess(c, evaluator, a, verifier=cancel)
    assert c.safe_progress()["termination"] == "CANCELLED"
    assert c.safe_progress()["completed_rounds"] == 0
    assert calls == []


def test_legacy_path_cannot_silently_drop_new_witnesses():
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    with pytest.raises(ValueError, match="round_assessment_failed"):
        c.complete_round(
            a, query_for_snippet="甲軸乙軸丙軸", complete=True,
            request_wide_attested=True,
            coverage_witnesses=_witnesses(c, a, target_indexes=(0,)),
        )
    assert c.safe_progress()["termination"] == "EVIDENCE_VALIDATION_FAILED"


def test_zero_witnesses_without_verifier_is_dependency_failure_not_coverage_gap():
    c, _, calls = coordinator()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=("後續影響",))
    assert c.start() and c.admit_es_call()
    with pytest.raises(ValueError, match="round_assessment_failed"):
        _assess(c, evaluator, [], witnesses=(), verifier=None)
    assert c.safe_progress()["termination"] == "EVIDENCE_VALIDATION_FAILED"
    assert c.safe_progress()["completed_rounds"] == 0
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    assert not c.admit_es_call()
    assert calls == []


def test_zero_witnesses_with_live_verifier_is_legitimate_coverage_gap():
    c, _, calls = coordinator()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=("後續影響",))
    assert c.start() and c.admit_es_call()
    record = _assess(
        c, evaluator, [], witnesses=(), verifier=lambda *_: False,
    )
    assert not record.coverage_sufficient
    assert record.request_wide
    assert c.safe_progress()["phase"] == "ASSESSED"
    assert c.plan_next_round().approved
    assert calls == ["planner"]


def _deep_strategy_records(caplog):
    return [json.loads(item.getMessage().split("SRAF_ARC_DEEP_STRATEGY=", 1)[1])
            for item in caplog.records
            if item.getMessage().startswith("SRAF_ARC_DEEP_STRATEGY=")]


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_arc_deep_strategy_uses_actual_coverage_and_preserves_plan(monkeypatch, caplog, mode):
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", mode)
    c, budget, calls = coordinator()
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=("PRIVATE_TARGET",))
    assert c.start() and c.admit_es_call()
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    first = _assess(c, evaluator, a)
    assert not first.coverage_sufficient
    assert calls == []
    admitted = c.plan_next_round()
    assert admitted.approved
    assert admitted.plan.optional_terms == ("不同地區回應",)
    assert admitted.plan.constraints is c._constraints
    assert calls == ["planner"]
    assert c.admit_es_call()
    second = _assess(c, evaluator, [_hit(2, "PRIVATE_DOC_B", inner=False)])
    assert second.coverage_sufficient
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    assert budget.rounds_started == 2
    rows = _deep_strategy_records(caplog)
    if mode == "off":
        assert rows == []
    else:
        assert [r["advice"] for r in rows] == [
            "inspect_low_incremental_gain", "coverage_sufficient"]
        assert rows[0]["canonical_evidence_this_round"] == 2
        assert rows[1]["cumulative_canonical_evidence"] == 4
        assert rows[1]["cumulative_semantically_supported_evidence"] == 4
        assert rows[1]["missing_targets"] == 0
        assert "PRIVATE_" not in json.dumps(rows)
        assert "甲軸" not in json.dumps(rows, ensure_ascii=False)


@pytest.mark.parametrize("scenario,expected", [
    ("semantic_gap", "inspect_semantic_support_gap"),
    ("repeated", "inspect_repeated_evidence"),
    ("locked", "user_keywords_locked"),
    ("unattested", "none"),
])
def test_arc_deep_strategy_distinguishes_observed_failure_modes(monkeypatch, caplog, scenario, expected):
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    c, _, calls = coordinator(locked=scenario == "locked")
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=("PRIVATE_TARGET",))
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    assert c.start() and c.admit_es_call()
    _assess(c, evaluator, a, attested=scenario != "unattested",
            verifier=lambda *_: scenario != "semantic_gap")
    if scenario == "repeated":
        assert c.plan_next_round().approved
        assert c.admit_es_call()
        _assess(c, evaluator, a)
    row = _deep_strategy_records(caplog)[-1]
    assert row["advice"] == expected
    if scenario == "semantic_gap":
        assert row["canonical_evidence_this_round"] == 2
        assert row["cumulative_semantically_supported_evidence"] == 0
    if scenario == "unattested":
        assert row["status"] == "unattested_or_incomplete"
        assert "candidate_sources" not in row
    assert len(calls) == int(scenario == "repeated")
    assert "PRIVATE_" not in json.dumps(row)


def test_arc_deep_strategy_legacy_boolean_path_is_not_a_signal(monkeypatch, caplog):
    from test_sraf_nround_coordinator import finish
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    c, _, calls = coordinator()
    assert c.start() and c.admit_es_call()
    finish(c, [_hit(2, "PRIVATE_DOC_A", inner=False)], sufficient=True)
    assert _deep_strategy_records(caplog) == []
    assert calls == []


@pytest.mark.parametrize("case", ["pilot", "shadow_only", "off", "revoked", "legacy", "expired", "locked"])
def test_arc_deep_planner_hint_is_private_opt_in_and_reuses_existing_call(monkeypatch, caplog, case):
    from test_sraf_nround_coordinator import finish
    from test_sraf_adaptive_planner_contract import response
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "off" if case == "off" else "shadow")
    prompts, clock = [], [0.0]

    def llm(prompt, **kwargs):
        prompts.append(json.loads(prompt.split("\n", 1)[1]))
        return response(terms=["不同地區回應"], aspects=["後續影響"])

    c, budget, calls = coordinator(llm=llm, clock=clock, locked=case == "locked",
        _arc_deep_hint_enabled=case != "shadow_only")
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=("PRIVATE_TARGET",))
    assert c.start() and c.admit_es_call()
    hits = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    if case == "legacy":
        finish(c, hits)
    else:
        _assess(c, evaluator, hits)
    assert not calls
    if case == "revoked":
        monkeypatch.setenv("SRAF_ARC_STRATEGY", "off")
    if case == "expired":
        clock[0] = 1800
    admitted = c.plan_next_round()
    if case in ("expired", "locked"):
        assert not admitted.approved
        assert not calls
    else:
        assert admitted.approved and admitted.plan.constraints is c._constraints
        assert calls == ["planner"] and len(prompts) == 1
        hint = prompts[0].get("arc_advisory_read_only")
        if case == "pilot":
            assert hint == {
                "scope": "advisory_only_no_constraint_changes", "round": 1,
                "advice": "inspect_low_incremental_gain", "candidate_sources": 1,
                "canonical_evidence_this_round": 2,
                "cumulative_semantically_supported_evidence": 2,
                "cumulative_semantically_supported_sources": 1,
                "missing_aspect_deficits": [
                    {"missing_aspect_position": position,
                     "additional_evidence_needed": 0,
                     "additional_distinct_sources_needed": 1,
                     "focus": "independent_sources"}
                    for position in range(2)
                ],
            }
            assert "PRIVATE" not in json.dumps(hint)
        else:
            assert hint is None
        assert prompts[0]["hard_constraints_read_only"]["event_date"]["start"] == c._constraints.event_date.start
    assert c._arc_hint is None
    assert "arc_advisory_read_only" not in json.dumps(c.safe_progress())
    assert "PRIVATE" not in caplog.text


def test_arc_pilot_missing_facets_distinguish_sources_from_evidence_and_update(monkeypatch, caplog):
    from test_sraf_adaptive_planner_contract import response
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    prompts = []

    def llm(prompt, **kwargs):
        prompts.append(json.loads(prompt.split("\n", 1)[1]))
        return response(terms=["不同地區回應" if len(prompts) == 1 else "其他外交資料"],
                        aspects=["後續影響"])

    c, _, calls = coordinator(llm=llm, _arc_deep_hint_enabled=True)
    evaluator = RequestWideCoverageEvaluator(
        constraints=c._constraints, target_aspects=("PRIVATE_TARGET",))
    assert c.start() and c.admit_es_call()
    a = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    first = _assess(c, evaluator, a, witnesses=_witnesses(c, a, target_indexes=(0,)))
    assert len(first.missing_aspects) == 2
    assert c.plan_next_round().approved
    first_hint = prompts[0]["arc_advisory_read_only"]["missing_aspect_deficits"]
    assert [(d["additional_evidence_needed"], d["additional_distinct_sources_needed"], d["focus"])
            for d in first_hint] == [(0, 1, "independent_sources"),
                                    (2, 2, "supporting_evidence_and_independent_sources")]
    assert c.admit_es_call()
    b = [_hit(1, "PRIVATE_DOC_B", inner=False)]
    second = _assess(c, evaluator, b, witnesses=_witnesses(c, b, target_indexes=(0, 1)))
    assert second.missing_aspects == ("PRIVATE_TARGET",)
    assert c.plan_next_round().approved
    second_hint = prompts[1]["arc_advisory_read_only"]["missing_aspect_deficits"]
    assert second_hint == [{"missing_aspect_position": 0,
                            "additional_evidence_needed": 1,
                            "additional_distinct_sources_needed": 1,
                            "focus": "supporting_evidence_and_independent_sources"}]
    assert len(calls) == 2
    assert "PRIVATE" not in json.dumps(first_hint + second_hint)
    assert "missing_aspect_deficits" not in json.dumps(c.safe_progress())
    assert "missing_aspect_deficits" not in json.dumps(evaluator.safe_audit())
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize("mode", ["pilot", "shadow_only", "revoked", "small_sample"])
def test_arc_deep_local_group_advisory_uses_actual_parser_sample(monkeypatch, caplog, mode):
    from test_sraf_adaptive_planner_contract import response
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_RANK", "shadow")
    prompts = []
    def llm(prompt, **kwargs):
        prompts.append(json.loads(prompt.split("\n", 1)[1]))
        return response(terms=["不同地區回應"], aspects=["後續影響"])
    c, _, calls = coordinator(llm=llm, _arc_deep_hint_enabled=mode != "shadow_only")
    ev = RequestWideCoverageEvaluator(constraints=c._constraints, target_aspects=("PRIVATE_TARGET",))
    assert c.start() and c.admit_es_call()
    hits = [_hit(2, "PRIVATE_DOC_" + str(i), inner=False)
            for i in range(4 if mode == "small_sample" else 24)]
    with bind_arc_budget((ArcRequestBudget(), 1)):
        record = _assess(c, ev, hits, witnesses=())
    assert not record.coverage_sufficient
    if mode == "revoked":
        monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "off")
    assert c.plan_next_round().approved
    assert calls == ["planner"]
    advisory = prompts[0].get("arc_advisory_read_only", {})
    if mode == "pilot":
        assert advisory["local_group_discrimination"] == {
            "scope": "ordered_date_valid_parser_sample_not_corpus_df",
            "eligible_hits": 24, "group_count": 3,
            "common_groups_at_least_80pct": 3,
            "uncommon_groups_positive_at_most_20pct": 0,
            "unobserved_groups_not_rarity": 0, "sample_limited": False}
        assert "PRIVATE" not in json.dumps(advisory)
    else:
        assert "local_group_discrimination" not in advisory
        assert "local_rank_comparison" not in advisory
    assert "local_group_discrimination" not in json.dumps(c.safe_progress())
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize("case", ["valid", "bad_count", "bad_ordinal", "native", "small", "bad_rank"])
def test_arc_deep_local_summary_does_not_misrepresent_unobserved_or_native_counts(monkeypatch, case):
    from agent.adaptive_retrieval.arc_deep_local_advisory import summarize_local_advisory
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    freq = {"schema": "sraf_arc_group_frequency_v1",
            "scope": "ordered_parser_slice_date_valid_sample_text_only",
            "status": "observed_sample", "eligible_hits": 20, "sample_limited": True,
            "groups": [{"group_ordinal": i, "sample_hit_frequency": n}
                       for i, n in enumerate((18, 2, 0, 9), 1)]}
    rank = {"schema": "sraf_arc_rank_shadow_v1",
            "scope": "same_parser_slice_ordered_sample_strict_prefix",
            "status": "observed_rank", "top_k": 20, "prefix_count": 40,
            "prefix_limited": False, "frequency_sample_limited": True,
            "top_k_replaced": 3, "rarity_only_top_k_replaced": 1,
            "original_source_hits": 8, "shadow_source_hits": 10,
            "original_strong": 18, "shadow_strong": 19}
    if case == "bad_count":
        freq["groups"][0]["sample_hit_frequency"] = 21
    elif case == "bad_ordinal":
        freq["groups"][0]["group_ordinal"] = True
    elif case == "native":
        freq["schema"] = "sraf_arc_deep_rank_frequency_v1"
    elif case == "small":
        freq["eligible_hits"] = 10
    elif case == "bad_rank":
        rank["top_k_replaced"] = 21
    result = summarize_local_advisory({"frequency": freq, "rank": rank})
    if case not in ("valid", "bad_rank"):
        assert result is None
    else:
        payload = result.payload()
        group = payload["local_group_discrimination"]
        assert (group["common_groups_at_least_80pct"],
                group["uncommon_groups_positive_at_most_20pct"],
                group["unobserved_groups_not_rarity"]) == (1, 1, 1)
        assert group["sample_limited"] is True
        assert ("local_rank_comparison" in payload) is (case == "valid")


@pytest.mark.parametrize("case", ["low", "high", "flag_off", "revoked", "no_anchor", "no_budget"])
def test_deep_pressure_advisory_uses_actual_canonical_parser(monkeypatch, caplog, case):
    from dataclasses import replace
    from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
    from agent.adaptive_retrieval.planner import AdaptiveRetrievalPlanner
    from agent.adaptive_retrieval.request_budget import RequestAdmissionBudget
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    from test_sraf_adaptive_planner_contract import response
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("SRAF_ARC_TIGHTEN", "shadow" if case != "flag_off" else "off")
    monkeypatch.setenv("SRAF_ARC_RELAX", "shadow" if case != "flag_off" else "off")
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "off")
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "off")
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "0")
    original = scope()
    question = original.question if case == "no_anchor" else "主題：甲軸\n" + original.question
    constraints = replace(original, question=question,
        original_core_terms=("甲軸", "乙軸", "丙軸", "丁軸"))
    prompts = []
    def llm(prompt, *, system_prompt):
        prompts.append(json.loads(prompt.split("\n", 1)[1]))
        return response(terms=["不同地區回應"], aspects=["後續影響"])
    c = AdaptiveRequestCoordinator(constraints=constraints,
        term_groups=(("甲軸",), ("乙軸",), ("丙軸",), ("丁軸",)),
        effective_terms=("甲軸", "乙軸", "丙軸", "丁軸"),
        budget=RequestAdmissionBudget(clock=lambda: 0.0),
        planner=AdaptiveRetrievalPlanner(llm, _arc_deep_hint_enabled=True))
    ev = RequestWideCoverageEvaluator(constraints=constraints, target_aspects=("後續影響",))
    assert c.start() and c.admit_es_call()
    if case == "high":
        hits = [_hit(2, "PRIVATE_" + str(i), inner=False) for i in range(24)]
        for i, hit in enumerate(hits):
            for j, row in enumerate(hit["_source"]["multidim_event_json"][0]["evidence_snippets"]):
                row["text"] = ("甲軸乙軸丙軸丁軸" if i < 12 else "甲軸乙軸丙軸") + f"資料{i}-{j}"
    else:
        hits = [_hit(2, "PRIVATE_A", inner=False)]
        hits[0]["_source"]["multidim_event_json"][0]["evidence_snippets"][1]["text"] = "甲軸乙軸其他候選"
    with bind_arc_budget(None if case == "no_budget" else (ArcRequestBudget(), 1)):
        record = _assess(c, ev, hits, witnesses=())
    assert not record.coverage_sufficient
    if case == "revoked":
        monkeypatch.setenv("SRAF_ARC_RELAX", "off")
    assert c.plan_next_round().approved and len(prompts) == 1
    advisory = prompts[0]["arc_advisory_read_only"]
    assert ("local_relaxation_counterfactual" in advisory) == (case == "low")
    assert ("local_tightening_counterfactual" in advisory) == (case == "high")
    if case == "low":
        assert record.verified_evidence == 1
        assert advisory["local_relaxation_counterfactual"]["hypothetical_add_cap"] == 1
    if case == "high":
        assert record.verified_evidence == 48
        assert advisory["local_tightening_counterfactual"]["options"] == [
            {"strategy": "all_text_axes", "retained_rows": 24, "retained_source_hits": 12}]
    assert "PRIVATE_" not in json.dumps(advisory)
    assert "local_relaxation_counterfactual" not in json.dumps(c.safe_progress())
    assert "local_tightening_counterfactual" not in json.dumps(c.safe_progress())


@pytest.mark.parametrize("case", ["valid", "limited", "bad_count", "bad_floor", "native"])
def test_deep_pressure_projection_fails_closed_on_invalid_or_limited_counterfactual(monkeypatch, case):
    from agent.adaptive_retrieval.arc_deep_local_advisory import summarize_pressure_advisory
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    raw = {"schema": "sraf_arc_tighten_shadow_v1", "scope": "strict_parser_prefix_only",
           "status": "observed_tightening", "prefix_count": 48, "strict_count": 48,
           "prefix_limited": False, "strategies": [
              {"strategy": "all_text_axes", "retained_prefix_rows": 24,
               "retained_source_hits": 12, "sample_floor_met": True}]}
    if case == "limited":
        raw["prefix_limited"] = True
    elif case == "bad_count":
        raw["strategies"][0]["retained_source_hits"] = 25
    elif case == "bad_floor":
        raw["strategies"][0]["retained_source_hits"] = 7
    elif case == "native":
        raw["strategies"][0]["strategy"] = "anchor_plus_native_discriminative_axis"
    summary = summarize_pressure_advisory({"high": raw})
    payload = summary.payload(candidate_sources=24, canonical_count=48) if summary is not None else {}
    assert ("local_tightening_counterfactual" in payload) == (case == "valid")
