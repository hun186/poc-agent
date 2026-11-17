"""Canonical private Evidence binding to semantic witnesses, synthetic only."""
from __future__ import annotations

import json

import pytest

from agent.adaptive_retrieval.contracts import DateWindow, QueryConstraints
from agent.adaptive_retrieval.coverage_evaluator import (
    EvidenceFacetWitness, RequestWideCoverageEvaluator,
)
from agent.adaptive_retrieval.evidence_ledger import (
    PrivateCanonicalEvidence, observe_canonical_round,
)
from agent.adaptive_retrieval.private_semantic_binding import (
    PrivateSemanticBindingError, prepare_private_semantic_grant,
)
from test_sraf_shared_evidence_budget import _hit, D0


def scope():
    return QueryConstraints(
        question="PRIVATE_甲軸乙軸丙軸之政策影響",
        event_date=DateWindow(D0, D0, "day", "explicit_user", D0),
        analysis_date=DateWindow(),
        allowed_indexes=("news_test",),
        required_entities=("甲軸",),
        original_core_terms=("甲軸", "乙軸", "丙軸"),
    )


def make_grant(*, hits=None, validator=None, max_semantic_checks=512):
    original = scope()
    evaluator = RequestWideCoverageEvaluator(
        constraints=original, target_aspects=("政策影響",),
        min_evidence_per_target=1, min_sources_per_target=1,
    )
    called = []

    def assessor(target, private):
        called.append((target.kind, private.text, private.date_iso))
        return (validator(target, private) if validator is not None else True)

    grant = prepare_private_semantic_grant(
        constraints=original, evaluator=evaluator,
        es_hits=([_hit(2, "PRIVATE_DOC_A", inner=False)]
                 if hits is None else hits),
        term_groups=[{"甲軸"}, {"乙軸"}, {"丙軸"}],
        effective_terms=["甲軸", "乙軸", "丙軸"],
        query_for_snippet="甲軸乙軸丙軸",
        complete=True, assessor=assessor,
        max_semantic_checks=max_semantic_checks,
    )
    return grant, evaluator, called


def test_verified_private_passages_bind_source_and_date_and_support_facets():
    grant, evaluator, called = make_grant()
    assert len(grant.observation.evidence_source_pairs) == 2
    assert len(grant.witnesses) == 4  # 2 verified passages x 2 targets
    assert len(called) == 4
    assert all("甲軸乙軸丙軸資訊" in text and when == D0
               for _, text, when in called)
    assert all(grant.semantic_verifier(
        evaluator.targets[witness.target_index], witness
    ) for witness in grant.witnesses)
    wrong = EvidenceFacetWitness(
        0, grant.witnesses[0].evidence_digest,
        "0" * 64,
    )
    assert not grant.semantic_verifier(evaluator.targets[0], wrong)
    from agent.adaptive_retrieval.coverage_evaluator import CoverageTarget
    assert not grant.semantic_verifier(CoverageTarget("entity", "甲軸"),
                                      grant.witnesses[0])

    # Synthetic caller attestation for a known complete fake document; this
    # does NOT claim real ES request-wide completeness.
    assessment = evaluator.assess_round(
        round_number=1, observation=grant.observation,
        witnesses=grant.witnesses,
        semantic_verifier=grant.semantic_verifier,
        request_wide_attested=True,
    )
    assert assessment.coverage_sufficient is True
    audit = json.dumps(grant.safe_audit(), ensure_ascii=False)
    for secret in ("PRIVATE_DOC_A", "news_test", "甲軸", D0,
                   next(iter(grant.observation.verified_evidence))):
        assert secret not in audit
    assert grant.safe_audit()["request_wide_attested"] is False
    assert "甲軸乙軸丙軸" not in repr(grant)


def test_wrong_event_date_never_offered_to_semantic_assessor():
    grant, evaluator, called = make_grant(
        hits=[_hit(2, "PRIVATE_DOC_A", other_date_every=2, inner=False)])
    assert len(grant.witnesses) == 2
    assert len(called) == 2
    assert all("第0筆" in text for _, text, _ in called)
    assert len(grant.observation.verified_evidence) == 1


def test_negative_assessor_never_turns_raw_hits_into_approved_witnesses():
    grant, evaluator, called = make_grant(validator=lambda *_: False)
    assert len(called) == 4
    assert grant.witnesses == ()
    record = evaluator.assess_round(
        round_number=1, observation=grant.observation,
        witnesses=grant.witnesses,
        semantic_verifier=grant.semantic_verifier,
        request_wide_attested=True,
    )
    assert record.coverage_sufficient is False
    assert len(record.missing_aspects) == 2


def test_no_verified_hits_still_requires_real_assessor_dependency():
    grant, evaluator, called = make_grant(hits=[])
    assert grant.witnesses == ()
    assert grant.observation.evidence_source_pairs == frozenset()
    assert called == []
    assert grant.safe_audit()["canonical_sources"] == 0


@pytest.mark.parametrize("bad", [
    "missing", "non_bool", "exception", "budget", "partial", "mismatched_scope",
])
def test_missing_or_invalid_semantic_dependency_fails_closed_without_raw_leak(bad):
    original = scope()
    evaluator = RequestWideCoverageEvaluator(
        constraints=original, target_aspects=("政策影響",))
    calls = []

    def assessor(*args):
        calls.append(1)
        if bad == "non_bool":
            return "PRIVATE_SECRET_NOT_A_BOOLEAN"
        if bad == "exception":
            raise RuntimeError("PRIVATE_SECRET_PROVIDER_RESPONSE")
        return True

    kwargs = dict(
        constraints=original, evaluator=evaluator,
        es_hits=[_hit(2, "PRIVATE_DOC_A", inner=False)],
        term_groups=[{"甲軸"}, {"乙軸"}, {"丙軸"}],
        effective_terms=["甲軸", "乙軸", "丙軸"],
        query_for_snippet="甲軸乙軸丙軸",
        complete=bad != "partial",
        assessor=None if bad == "missing" else assessor,
        max_semantic_checks=(1 if bad == "budget" else 512),
    )
    if bad == "mismatched_scope":
        kwargs["constraints"] = scope()
    with pytest.raises(PrivateSemanticBindingError) as ex:
        prepare_private_semantic_grant(**kwargs)
    assert "PRIVATE" not in str(ex.value)
    if bad in ("budget", "missing", "partial", "mismatched_scope"):
        assert calls == []


def test_private_capture_atomic_on_late_untrusted_source_row(monkeypatch):
    from agent.adaptive_retrieval import evidence_ledger as ledger
    sample = [_hit(2, "PRIVATE_DOC_A", inner=False)]
    from agent.es.evidence_core.builder import build_hits_and_evidence

    _, evidence, _ = build_hits_and_evidence(
        sample, date_from=D0, date_to=D0,
        term_groups=[{"甲軸"}, {"乙軸"}, {"丙軸"}],
        effective_terms=["甲軸", "乙軸", "丙軸"],
        query_for_snippet="甲軸乙軸丙軸",
        original_question=scope().question,
        include_source_hit_ordinal=True,
    )
    assert len(evidence) == 2
    bad = dict(evidence[0])
    bad["__sraf_source_hit_ordinal"] = 50000
    monkeypatch.setattr(
        ledger, "build_hits_and_evidence",
        lambda *args, **kwargs: ([], evidence + [bad], {}),
    )
    capture: dict[tuple[str, str], PrivateCanonicalEvidence] = {}
    with pytest.raises(ValueError, match="invalid_evidence_source_provenance"):
        observe_canonical_round(
            sample, date_from=D0, date_to=D0,
            term_groups=[{"甲軸"}, {"乙軸"}, {"丙軸"}],
            effective_terms=["甲軸", "乙軸", "丙軸"],
            query_for_snippet="甲軸乙軸丙軸",
            original_question=scope().question, complete=True,
            private_evidence=capture,
        )
    assert capture == {}  # no partial private text escape


def test_private_collector_must_start_empty_and_never_enter_public_observation():
    capture = {("not", "empty"): "PRIVATE_SECRET"}
    with pytest.raises(ValueError, match="invalid_private_evidence_collector"):
        observe_canonical_round(
            [], date_from=D0, date_to=D0,
            term_groups=[{"甲軸"}], effective_terms=["甲軸"],
            query_for_snippet="甲軸", original_question=scope().question,
            complete=True, private_evidence=capture,
        )
    assert capture == {("not", "empty"): "PRIVATE_SECRET"}
