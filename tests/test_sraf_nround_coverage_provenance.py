"""No-I/O request-wide coverage: verified canonical evidence, never raw hit claims."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from agent.adaptive_retrieval.contracts import DateWindow, QueryConstraints
from agent.adaptive_retrieval.coverage_evaluator import (
    EvidenceFacetWitness, RequestWideCoverageEvaluator,
)
from agent.adaptive_retrieval.evidence_ledger import (
    RoundObservation, observe_canonical_round,
)
from test_sraf_shared_evidence_budget import _hit, D0


def _scope():
    return QueryConstraints(
        question="PRIVATE_QUESTION_甲軸乙軸丙軸_政策分析",
        event_date=DateWindow(D0, D0, "day", "explicit_user", D0),
        analysis_date=DateWindow(),
        allowed_indexes=("news_test",),
        required_entities=("PRIVATE_REQUIRED_甲軸",),
        original_core_terms=("甲軸", "乙軸", "丙軸"),
    )


def _observe(doc, *, complete=True, other_date_every=0):
    return observe_canonical_round(
        [_hit(2, doc, inner=False, other_date_every=other_date_every)],
        date_from=D0, date_to=D0,
        term_groups=[{"甲軸"}, {"乙軸"}, {"丙軸"}],
        effective_terms=["甲軸", "乙軸", "丙軸"],
        original_question="PRIVATE_QUESTION_甲軸乙軸丙軸_政策分析",
        query_for_snippet="甲軸乙軸丙軸",
        complete=complete,
    )


def _witnesses(obs, target_index):
    return tuple(
        EvidenceFacetWitness(target_index, ev, source)
        for ev, source in sorted(obs.evidence_source_pairs)
    )


def _accept(target, witness):
    return True


def test_canonical_builder_binds_evidence_to_real_origin_and_event_date():
    observation = _observe("PRIVATE_DOC_A", other_date_every=2)
    assert len(observation.evidence_source_pairs) == 1
    assert len(observation.verified_evidence) == 1
    assert all(evidence in observation.verified_evidence
               and src in observation.verified_sources
               for evidence, src in observation.evidence_source_pairs)
    other = observe_canonical_round(
        [_hit(2, "PRIVATE_DOC_B", inner=False)],
        date_from="2024-01-01", date_to="2024-12-31",
        term_groups=[{"甲軸"}, {"乙軸"}, {"丙軸"}],
        effective_terms=["甲軸", "乙軸", "丙軸"],
        original_question="PRIVATE_QUESTION_甲軸乙軸丙軸_政策分析",
        query_for_snippet="甲軸乙軸丙軸", complete=True,
    )
    assert other.evidence_source_pairs == frozenset()
    assert other.verified_evidence == frozenset()


def test_cross_round_two_source_aspect_coverage_and_no_raw_audit():
    scope = _scope()
    evaluator = RequestWideCoverageEvaluator(
        constraints=scope, target_aspects=("PRIVATE_ASPECT_政策影響",))
    a = _observe("PRIVATE_DOC_A")
    first = evaluator.assess_round(
        round_number=1, observation=a,
        witnesses=_witnesses(a, 0) + _witnesses(a, 1),
        semantic_verifier=_accept, request_wide_attested=True,
    )
    assert not first.coverage_sufficient
    assert len(first.missing_aspects) == 2
    assert first.verified_sources == 1
    b = _observe("PRIVATE_DOC_B")
    second = evaluator.assess_round(
        round_number=2, observation=b,
        witnesses=_witnesses(b, 0) + _witnesses(b, 1),
        semantic_verifier=_accept, request_wide_attested=True,
    )
    assert second.coverage_sufficient
    assert second.missing_aspects == ()
    assert second.verified_sources == 2
    assert second.verified_evidence == 4
    assert second.required_targets == 2
    summary = json.dumps(evaluator.safe_audit(), ensure_ascii=False)
    for private in ("PRIVATE_", "news_test", D0,
                    next(iter(a.verified_evidence)),
                    next(iter(a.verified_sources))):
        assert private not in summary
    assert evaluator.safe_audit()["missing_targets"] == 0
    assert evaluator.safe_audit()["required_targets"] == 2
    assert evaluator.safe_audit()["live_job"] == "NOT_INTEGRATED"


def test_repeating_exact_same_source_cannot_manufacture_diversity():
    evaluator = RequestWideCoverageEvaluator(
        constraints=_scope(), target_aspects=(),
        min_evidence_per_target=2, min_sources_per_target=2,
    )
    a = _observe("PRIVATE_DOC_A")
    first = evaluator.assess_round(
        round_number=1, observation=a,
        witnesses=_witnesses(a, 0),
        semantic_verifier=_accept, request_wide_attested=True,
    )
    assert first.verified_evidence == 2
    second = evaluator.assess_round(
        round_number=2, observation=a,
        witnesses=_witnesses(a, 0),
        semantic_verifier=_accept, request_wide_attested=True,
    )
    assert not second.coverage_sufficient
    assert second.verified_sources == 1
    assert second.verified_evidence == first.verified_evidence


def test_missing_aspect_stays_missing_even_with_many_verified_sources():
    evaluator = RequestWideCoverageEvaluator(
        constraints=_scope(), target_aspects=("PRIVATE_ASPECT_回應",),
        min_evidence_per_target=1, min_sources_per_target=1,
    )
    a = _observe("PRIVATE_DOC_A")
    result = evaluator.assess_round(
        round_number=1, observation=a,
        witnesses=_witnesses(a, 0), semantic_verifier=_accept,
        request_wide_attested=True,
    )
    assert result.missing_aspects == ("PRIVATE_ASPECT_回應",)
    assert result.coverage_sufficient is False


def test_semantic_verifier_negative_and_no_witnesses_never_sufficient():
    evaluator = RequestWideCoverageEvaluator(
        constraints=_scope(), target_aspects=(), min_evidence_per_target=1,
        min_sources_per_target=1,
    )
    a = _observe("PRIVATE_DOC_A")
    result = evaluator.assess_round(
        round_number=1, observation=a, witnesses=_witnesses(a, 0),
        semantic_verifier=lambda *_: False, request_wide_attested=True,
    )
    assert not result.coverage_sufficient
    assert result.verified_evidence == 0

    other = RequestWideCoverageEvaluator(constraints=_scope(),
                                         target_aspects=(),
                                         min_evidence_per_target=1,
                                         min_sources_per_target=1)
    empty = other.assess_round(
        round_number=1, observation=a, witnesses=(),
        semantic_verifier=None, request_wide_attested=True,
    )
    assert not empty.coverage_sufficient
    assert empty.missing_aspects


def test_forged_source_pair_is_rejected_before_semantic_verifier():
    evaluator = RequestWideCoverageEvaluator(
        constraints=_scope(), target_aspects=())
    a = _observe("PRIVATE_DOC_A")
    b = _observe("PRIVATE_DOC_B")
    stolen_key = next(iter(a.verified_evidence))
    different_source = next(iter(b.verified_sources))
    assert (stolen_key, different_source) not in a.evidence_source_pairs
    calls = []
    with pytest.raises(ValueError, match="coverage_verification_failed"):
        evaluator.assess_round(
            round_number=1, observation=a,
            witnesses=(EvidenceFacetWitness(0, stolen_key, different_source),),
            semantic_verifier=lambda *_: calls.append(1) or True,
            request_wide_attested=True,
        )
    assert calls == []
    with pytest.raises(ValueError, match="invalid_coverage_round"):
        evaluator.assess_round(round_number=1, observation=a,
                               witnesses=(), semantic_verifier=None,
                               request_wide_attested=True)


def test_no_request_wide_attestation_or_partial_page_fails_closed():
    a = _observe("PRIVATE_DOC_A")
    for obs, attested in ((a, False), (_observe("PRIVATE_DOC_B", complete=False), True)):
        evaluator = RequestWideCoverageEvaluator(
            constraints=_scope(), target_aspects=())
        calls = []
        result = evaluator.assess_round(
            round_number=1, observation=obs, witnesses=_witnesses(obs, 0),
            semantic_verifier=lambda *_: calls.append(1) or True,
            request_wide_attested=attested,
        )
        assert not result.coverage_sufficient
        assert result.result_incomplete
        assert not result.request_wide_attested
        assert calls == []
        with pytest.raises(ValueError, match="invalid_coverage_round"):
            evaluator.assess_round(round_number=2, observation=a, witnesses=(),
                                   semantic_verifier=None,
                                   request_wide_attested=True)


def test_verifier_exception_redacted_and_cannot_partially_commit():
    a = _observe("PRIVATE_DOC_A")
    evaluator = RequestWideCoverageEvaluator(
        constraints=_scope(), target_aspects=())
    with pytest.raises(ValueError, match="coverage_verification_failed") as exc:
        evaluator.assess_round(
            round_number=1, observation=a, witnesses=_witnesses(a, 0),
            semantic_verifier=lambda *_:
                (_ for _ in ()).throw(RuntimeError("PRIVATE_SECRET_TOKEN")),
            request_wide_attested=True,
        )
    assert "PRIVATE_SECRET_TOKEN" not in str(exc.value)
    assert evaluator.safe_audit()["round"] == 0


@pytest.mark.parametrize("bad", [
    ("aspect", ""), ("wrong", "X"), ("aspect", "PRIVATE\nSTRING"),
])
def test_invalid_scope_targets_rejected(bad):
    from agent.adaptive_retrieval.coverage_evaluator import CoverageTarget
    with pytest.raises(ValueError):
        CoverageTarget(*bad)


def test_reject_more_than_eight_total_targets_before_semantic_work():
    scope = _scope()
    with pytest.raises(ValueError, match="invalid_coverage_targets"):
        RequestWideCoverageEvaluator(
            constraints=scope,
            target_aspects=tuple(f"aspect{i}" for i in range(8)),
        )


def test_concurrent_same_round_witness_submission_cannot_double_append():
    evaluator = RequestWideCoverageEvaluator(
        constraints=_scope(), target_aspects=(),
        min_evidence_per_target=1, min_sources_per_target=1,
    )
    a = _observe("PRIVATE_DOC_A")
    def work(_):
        try:
            return evaluator.assess_round(
                round_number=1, observation=a, witnesses=_witnesses(a, 0),
                semantic_verifier=_accept, request_wide_attested=True,
            )
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(work, range(10)))
    assert sum(x is not None for x in results) == 1
    assert evaluator.safe_audit()["round"] == 1


def test_failed_later_verification_invalidates_previous_sufficient_public_audit():
    evaluator = RequestWideCoverageEvaluator(
        constraints=_scope(), target_aspects=(),
        min_evidence_per_target=1, min_sources_per_target=1,
    )
    a = _observe("PRIVATE_DOC_A")
    accepted = evaluator.assess_round(
        round_number=1, observation=a,
        witnesses=_witnesses(a, 0),
        semantic_verifier=_accept, request_wide_attested=True,
    )
    assert accepted.coverage_sufficient is True
    assert evaluator.safe_audit()["coverage_sufficient"] is True

    b = _observe("PRIVATE_DOC_B")
    valid_second = _witnesses(b, 0)[0]
    invalid_source = _witnesses(a, 0)[0].source_digest
    invalid_witness = EvidenceFacetWitness(
        0, valid_second.evidence_digest, invalid_source)
    with pytest.raises(ValueError, match="coverage_verification_failed"):
        evaluator.assess_round(
            round_number=2, observation=b, witnesses=(invalid_witness,),
            semantic_verifier=_accept, request_wide_attested=True,
        )
    public = evaluator.safe_audit()
    assert public["round"] == 1  # no second-round commit
    assert public["verified_sources"] == 1  # prior counts retained for diagnosis
    assert public["coverage_sufficient"] is False
    assert public["request_wide_attested"] is False
    assert public["result_incomplete"] is True
    assert public["failed_closed"] is True
    assert public["failure_reason"] == "SEMANTIC_OR_PROVENANCE_REJECTED"
    for secret in ("PRIVATE_DOC", "PRIVATE_ASPECT", invalid_source):
        assert secret not in json.dumps(public, ensure_ascii=False)


def test_absent_verifier_after_valid_round_is_terminal_not_stale_success():
    evaluator = RequestWideCoverageEvaluator(
        constraints=_scope(), target_aspects=(),
        min_evidence_per_target=1, min_sources_per_target=1,
    )
    a, b = _observe("PRIVATE_DOC_A"), _observe("PRIVATE_DOC_B")
    assert evaluator.assess_round(
        round_number=1, observation=a, witnesses=_witnesses(a, 0),
        semantic_verifier=_accept, request_wide_attested=True,
    ).coverage_sufficient
    with pytest.raises(ValueError, match="semantic_verifier_required"):
        evaluator.assess_round(
            round_number=2, observation=b, witnesses=_witnesses(b, 0),
            semantic_verifier=None, request_wide_attested=True,
        )
    public = evaluator.safe_audit()
    assert public["coverage_sufficient"] is False
    assert public["failed_closed"] is True
    assert public["failure_reason"] == "SEMANTIC_VERIFIER_MISSING"
