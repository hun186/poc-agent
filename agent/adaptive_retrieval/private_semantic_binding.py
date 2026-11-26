"""Trusted in-memory binding of canonical Evidence text to semantic witnesses.

Isolated, no production Job, no IO on import. The canonical parser is run
once while building the PRIVATE text lookup, and only date/topic/source
validated rows can be offered to a separately injected trusted assessor.
The assessor may be a real provider in a future Worker, but this module
does not call any provider, ES, SQL or filesystem itself.

An approved witness is only a *semantic callback result*, not proof of the
callback's truthfulness, request-wide ES completeness or report readiness.
Do not log raw evidence, target labels, source hashes or model prompts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .contracts import QueryConstraints
from .coverage_evaluator import (
    CoverageTarget, EvidenceFacetWitness, RequestWideCoverageEvaluator,
)
from .evidence_ledger import (
    CanonicalReportEvidence, PrivateCanonicalEvidence, RoundObservation, observe_canonical_round,
)


class PrivateSemanticBindingError(ValueError):
    """Fixed reason only; never leak the private Evidence or callback failure."""


@dataclass(frozen=True)
class CanonicalSemanticGrant:
    """Temporary trusted handoff; witnesses are private and never serialized."""

    observation: RoundObservation = field(repr=False)
    witnesses: tuple[EvidenceFacetWitness, ...] = field(repr=False)
    targets: tuple[CoverageTarget, ...] = field(repr=False)
    _approved: frozenset[tuple[int, str, str]] = field(repr=False)
    _report_rows: tuple[CanonicalReportEvidence, ...] = field(default=(), repr=False)

    def semantic_verifier(
        self, target: CoverageTarget, witness: EvidenceFacetWitness,
    ) -> bool:
        if (type(witness) is not EvidenceFacetWitness
                or type(target) is not CoverageTarget
                or witness.target_index >= len(self.targets)
                or target is not self.targets[witness.target_index]):
            return False
        return (witness.target_index, witness.evidence_digest,
                witness.source_digest) in self._approved

    def safe_audit(self) -> dict[str, int | bool | str]:
        return {
            "schema": "sraf_nround_private_semantic_binding_v1",
            "canonical_evidence": len(self.observation.verified_evidence),
            "canonical_sources": len(self.observation.verified_sources),
            "tested_facets": len(self.targets),
            "approved_witnesses": len(self.witnesses),
            "request_wide_attested": False,
            "external_semantic_verifier": "TRUSTED_CALLER_INJECTED",
            "live_job": "NOT_INTEGRATED",
        }


def prepare_private_semantic_grant(
    *,
    constraints: QueryConstraints,
    evaluator: RequestWideCoverageEvaluator,
    es_hits: list[dict],
    term_groups: list[set[str]],
    effective_terms: list[str],
    query_for_snippet: str,
    complete: bool,
    assessor: Callable[[CoverageTarget, PrivateCanonicalEvidence], bool] | None,
    max_semantic_checks: int = 512,
    deep_rank_frequency=None,
) -> CanonicalSemanticGrant:
    """Produce witnesses bound to canonical source+text, not arbitrary ES hits.

    Caller MUST attest the full trusted query plan independently, and must
    inject an assessor that actually checks target support against each
    private canonical passage. This helper does NOT make that determination
    or grant request-wide completeness automatically.

    Refuse to call the assessor for incomplete rounds or if there would be
    more than max_semantic_checks calls (including rejected proposals).
    """
    if (type(constraints) is not QueryConstraints
            or type(evaluator) is not RequestWideCoverageEvaluator
            or evaluator._constraints is not constraints
            or not callable(assessor)
            or type(complete) is not bool or not complete
            or type(max_semantic_checks) is not int
            or not 1 <= max_semantic_checks <= 2048):
        raise PrivateSemanticBindingError("untrusted_semantic_binding_context")
    # This temporary lookup never leaves the trusted function or persists.
    captured: dict[tuple[str, str], PrivateCanonicalEvidence] = {}
    report_rows: dict[tuple[str, str], CanonicalReportEvidence] = {}
    try:
        obs = observe_canonical_round(
            es_hits,
            date_from=constraints.event_date.start,
            date_to=constraints.event_date.end,
            term_groups=term_groups,
            effective_terms=effective_terms,
            query_for_snippet=query_for_snippet,
            original_question=constraints.question,
            complete=True,
            private_evidence=captured, private_report_rows=report_rows,
            **({"deep_rank_frequency": deep_rank_frequency} if deep_rank_frequency is not None else {}),
        )
        if set(captured) != obs.evidence_source_pairs:
            raise ValueError("incomplete_capture")
        targets = evaluator.targets
        if len(captured) * len(targets) > max_semantic_checks:
            raise ValueError("semantic_checks_over_budget")
        accepted: set[tuple[int, str, str]] = set()
        for (ev, src), private in sorted(captured.items()):
            for index, target in enumerate(targets):
                approved = assessor(target, private)
                if type(approved) is not bool:
                    raise ValueError("untrusted_semantic_verdict")
                if approved:
                    accepted.add((index, ev, src))
        # A report may consume only a passage actually approved for at least
        # one target. Do not reconstruct it later from raw ES hits.
        selected = tuple(report_rows[pair] for pair in
                         sorted({(ev, src) for _, ev, src in accepted}))
    except Exception:
        raise PrivateSemanticBindingError("private_semantic_verification_failed") from None
    finally:
        # The grant exposes only identities; private text is no longer needed
        # by this bridge once the injected checker has completed.
        captured.clear()
        report_rows.clear()
    witnesses = tuple(
        EvidenceFacetWitness(index, ev, src)
        for index, ev, src in sorted(accepted)
    )
    return CanonicalSemanticGrant(
        observation=obs, witnesses=witnesses, targets=targets,
        _approved=frozenset(accepted), _report_rows=selected,
    )
