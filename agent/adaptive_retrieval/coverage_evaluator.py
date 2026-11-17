"""Isolated, provenance-bound request-wide N-round coverage accounting.

Only canonical topic/date-verified Evidence from observe_canonical_round can
supply identity pairs. An independent TRUSTED semantic verifier must bind a
target (entity / analysis aspect) to each specific Evidence+source identity.
This module cannot itself decide whether raw prose supports an aspect, parse
dates or attest that an ES request fetched all planned branches.

No ES, LLM, SQL, API, network, filesystem, checkpoint or DOCX operations.
Never publish targets or internal SHA digests through safe_audit(). Not wired
into the live SRAF API or ReportJobWorker.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Callable

from .contracts import QueryConstraints, _bounded_text
from .evidence_ledger import RoundObservation, MAX_EVIDENCE, MAX_ROUNDS


@dataclass(frozen=True)
class CoverageTarget:
    """Server-owned entity or question aspect; labels are PRIVATE."""
    kind: str
    label: str

    def __post_init__(self) -> None:
        if self.kind not in ("entity", "aspect"):
            raise ValueError("invalid_coverage_target")
        _bounded_text(self.label, limit=120)


@dataclass(frozen=True)
class EvidenceFacetWitness:
    """Trusted assessor proposal bound to one canonical Evidence/source pair."""
    target_index: int
    evidence_digest: str
    source_digest: str

    def __post_init__(self) -> None:
        if (type(self.target_index) is not int
                or not 0 <= self.target_index < 8
                or any(type(value) is not str or len(value) != 64
                       or any(c not in "0123456789abcdef" for c in value)
                       for value in (self.evidence_digest, self.source_digest))):
            raise ValueError("invalid_coverage_witness")


@dataclass(frozen=True)
class CoverageAssessment:
    """Private assessment for a FUTURE trusted coordinator/worker bridge."""
    round_number: int
    missing_aspects: tuple[str, ...]
    coverage_sufficient: bool
    request_wide_attested: bool
    result_incomplete: bool
    verified_evidence: int
    verified_sources: int
    required_targets: int

    def safe_audit(self) -> dict[str, int | bool | str]:
        """Expose counts only; no target text, evidence keys or source IDs."""
        return {
            "schema": "sraf_nround_coverage_provenance_v1",
            "round": self.round_number,
            "required_targets": self.required_targets,
            "missing_targets": len(self.missing_aspects),
            "coverage_sufficient": self.coverage_sufficient,
            "request_wide_attested": self.request_wide_attested,
            "result_incomplete": self.result_incomplete,
            "verified_evidence": self.verified_evidence,
            "verified_sources": self.verified_sources,
            "semantic_verifier": "EXTERNAL_TRUSTED_CALLBACK",
            "live_job": "NOT_INTEGRATED",
        }


class RequestWideCoverageEvaluator:
    """Bounded cross-round de-duplication for trusted semantic Evidence witnesses.

    The caller must verify:
    1) QueryConstraints really represent authorized original user constraints.
    2) The complete observation corresponds to ALL intended ES queries/pages.
    3) semantic_verifier independently checks the private text's *meaning*
       for the supplied (target, evidence digest, source digest). This module
       checks canonical identity membership but has no text/meaning access.
    Any unavailable attestation fails closed, never infers sufficient coverage
    from hit counts, model guesses, duplicate passages or single sources.
    """

    def __init__(
        self, *,
        constraints: QueryConstraints,
        target_aspects: tuple[str, ...],
        min_evidence_per_target: int = 2,
        min_sources_per_target: int = 2,
    ) -> None:
        if (type(constraints) is not QueryConstraints
                or type(target_aspects) is not tuple
                or len(target_aspects) > 8
                or type(min_evidence_per_target) is not int
                or type(min_sources_per_target) is not int
                or not 1 <= min_evidence_per_target <= 20
                or not 1 <= min_sources_per_target <= 10):
            raise ValueError("invalid_coverage_policy")
        targets = (
            tuple(CoverageTarget("entity", text)
                  for text in constraints.required_entities)
            + tuple(CoverageTarget("aspect", text) for text in target_aspects)
        )
        if not targets or len(targets) > 8:
            raise ValueError("invalid_coverage_targets")
        folded = [(t.kind, t.label.casefold()) for t in targets]
        if len(folded) != len(set(folded)):
            raise ValueError("duplicate_coverage_target")
        self._constraints = constraints
        self._targets = targets
        self._min_evidence = min_evidence_per_target
        self._min_sources = min_sources_per_target
        self._support: dict[int, set[tuple[str, str]]] = {
            index: set() for index in range(len(targets))
        }
        self._rounds = 0
        self._failed = False
        self._lock = Lock()
        self._last: CoverageAssessment | None = None

    @property
    def targets(self) -> tuple[CoverageTarget, ...]:
        """PRIVATE worker-only target names; not a public audit."""
        return self._targets

    def assess_round(
        self, *,
        round_number: int,
        observation: RoundObservation,
        witnesses: tuple[EvidenceFacetWitness, ...],
        semantic_verifier: Callable[[CoverageTarget, EvidenceFacetWitness], bool] | None,
        request_wide_attested: bool,
    ) -> CoverageAssessment:
        """Append one complete round; never mutate on rejected semantic claims."""
        with self._lock:
            if (self._failed or type(round_number) is not int
                    or round_number != self._rounds + 1
                    or round_number > MAX_ROUNDS
                    or type(observation) is not RoundObservation
                    or type(witnesses) is not tuple
                    or len(witnesses) > MAX_EVIDENCE
                    or type(request_wide_attested) is not bool):
                raise ValueError("invalid_coverage_round")
            if not observation.complete or not request_wide_attested:
                self._failed = True
                result = CoverageAssessment(
                    round_number, tuple(t.label for t in self._targets),
                    False, False, True, 0, 0, len(self._targets),
                )
                self._last = result
                return result
            if witnesses and not callable(semantic_verifier):
                raise ValueError("semantic_verifier_required")
            proposed: dict[int, set[tuple[str, str]]] = {
                i: set(pairs) for i, pairs in self._support.items()
            }
            seen: set[EvidenceFacetWitness] = set()
            try:
                for witness in witnesses:
                    if (type(witness) is not EvidenceFacetWitness
                            or witness.target_index >= len(self._targets)
                            or (witness.evidence_digest, witness.source_digest)
                            not in observation.evidence_source_pairs):
                        raise ValueError("unverified_coverage_provenance")
                    if witness in seen:
                        continue
                    seen.add(witness)
                    valid = semantic_verifier(
                        self._targets[witness.target_index], witness)
                    if valid is not True and valid is not False:
                        raise ValueError("unverified_coverage_semantics")
                    if valid:
                        proposed[witness.target_index].add(
                            (witness.evidence_digest, witness.source_digest))
            except Exception:
                self._failed = True
                raise ValueError("coverage_verification_failed") from None
            missing: list[str] = []
            for index, target in enumerate(self._targets):
                pairs = proposed[index]
                if (len({e for e, _ in pairs}) < self._min_evidence
                        or len({src for _, src in pairs}) < self._min_sources):
                    missing.append(target.label)
            all_evidence = {
                evid for pairs in proposed.values() for evid, _ in pairs
            }
            all_sources = {
                source for pairs in proposed.values() for _, source in pairs
            }
            assessment = CoverageAssessment(
                round_number, tuple(missing), not missing, True, False,
                len(all_evidence), len(all_sources), len(self._targets),
            )
            self._support = proposed
            self._last = assessment
            self._rounds += 1
            return assessment

    def safe_audit(self) -> dict[str, int | bool | str]:
        with self._lock:
            if self._last is None:
                return {
                    "schema": "sraf_nround_coverage_provenance_v1",
                    "round": 0,
                    "required_targets": len(self._targets),
                    "missing_targets": len(self._targets),
                    "coverage_sufficient": False,
                    "request_wide_attested": False,
                    "result_incomplete": True,
                    "verified_evidence": 0,
                    "verified_sources": 0,
                    "semantic_verifier": "EXTERNAL_TRUSTED_CALLBACK",
                    "live_job": "NOT_INTEGRATED",
                }
            return self._last.safe_audit()
