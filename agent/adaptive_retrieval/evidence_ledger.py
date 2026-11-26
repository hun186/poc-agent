"""Request-local evidence ledger for FUTURE bounded multi-round retrieval.

This is an in-memory contract only. No ES/LLM/SQL/API calls are made. A trusted
adapter must provide the exact ES hit batch and the query/date constraints.
The canonical builder is the only source of eligibility; raw hit counts,
summaries, arbitrary LLM claims and fallback rows never authorize evidence.

The ledger cannot attest live ES completeness, authorizations, or human
precision. The outer coordinator must independently attest full scope/pages
and recheck the real search transport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
from typing import Any

from shared.citations.citation_id import pick_doc_id
from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.json_utils import as_blocks
from agent.es.event_time import event_ids_in_block, parse_structured_time
from .contracts import RoundEvidenceSummary, _terms

MAX_HITS = 1000
MAX_EVIDENCE = 4096
MAX_ROUNDS = 8
MAX_TOTAL_KEYS = 16384
_ALLOWED_POLICY = frozenset(("strict", "relaxed", "adaptive_two_axis"))
_ALLOWED_SCOPE = frozenset(("text", "meta", "mixed"))


def _digest(parts: tuple[Any, ...]) -> str:
    return sha256(json.dumps(
        parts, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _es_source_keys(raw_hits: list[dict]) -> tuple[str, ...]:
    if type(raw_hits) is not list or len(raw_hits) > MAX_HITS:
        raise ValueError("invalid_round_source_batch")
    identities: list[str] = []
    for hit in raw_hits:
        if type(hit) is not dict:
            raise ValueError("invalid_round_source_batch")
        index, docid = hit.get("_index"), hit.get("_id")
        if (type(index) is not str or not 0 < len(index) <= 256
                or type(docid) is not str or not 0 < len(docid) <= 256):
            raise ValueError("missing_es_source_identity")
        identities.append(_digest((index, docid)))
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate_es_source_identity")
    return tuple(identities)


@dataclass(frozen=True)
class PrivateCanonicalEvidence:
    """Private, validated in-memory Evidence data. Never serialize to audit."""

    text: str = field(repr=False)
    date_iso: str = field(repr=False)
    matched_event_times: tuple[tuple[str, str, str, str, str], ...] = field(repr=False)
    event_ids: tuple[str, ...] = field(repr=False)

    def safe_audit(self) -> dict[str, int | bool]:
        return {
            "has_text": bool(self.text),
            "has_exact_day": bool(self.date_iso),
            "matched_event_times": len(self.matched_event_times),
            "event_ids": len(self.event_ids),
        }


@dataclass(frozen=True)
class CanonicalReportEvidence:
    """Private citation projection of the exact canonically assessed passage."""

    pair: tuple[str, str] = field(repr=False)
    passage: PrivateCanonicalEvidence = field(repr=False)
    doc_id: str = field(repr=False)
    title: str = field(repr=False)
    subject: str = field(repr=False)
    structured: bool
    weak: bool
    scope: str
    group_hits: int

    def report_snippet(self) -> dict[str, Any]:
        # Publication dates are intentionally NOT used as event dates.
        times = [dict(zip(
            ("source", "time_precision", "time_iso", "date_start", "date_end"), point
        )) for point in self.passage.matched_event_times]
        return {
            "uuid": self.doc_id, "text": self.passage.text,
            "date_iso": self.passage.date_iso,
            "article_title": self.title, "subject": self.subject,
            "structured_time_context": self.structured,
            "matched_event_time_candidates": times,
            "event_time_candidates": times,
            "weak_evidence": self.weak, "match_scope": self.scope,
            "group_hits": self.group_hits,
        }


@dataclass(frozen=True)
class RoundObservation:
    """Private digests are never emitted in public report audit counters."""

    candidate_sources: frozenset[str]
    verified_evidence: frozenset[str]
    verified_sources: frozenset[str]
    parser_output_rows: int
    validated_rows: int
    fallback_rows: int
    complete: bool
    # Canonical source and Evidence identity pairs for future trusted
    # aspect verification. No raw passages or identifying _id values.
    evidence_source_pairs: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        if (type(self.candidate_sources) is not frozenset
                or type(self.verified_evidence) is not frozenset
                or type(self.verified_sources) is not frozenset
                or any(type(x) is not str or len(x) != 64 for group in (
                    self.candidate_sources, self.verified_evidence,
                    self.verified_sources,
                ) for x in group)
                or not self.verified_sources.issubset(self.candidate_sources)
                or len(self.candidate_sources) > MAX_HITS
                or len(self.verified_evidence) > MAX_EVIDENCE
                or type(self.parser_output_rows) is not int
                or not 0 <= self.parser_output_rows <= MAX_EVIDENCE
                or type(self.validated_rows) is not int
                or not 0 <= self.validated_rows <= self.parser_output_rows
                or len(self.verified_evidence) > self.validated_rows
                or type(self.fallback_rows) is not int
                or self.fallback_rows != self.parser_output_rows -
                    self.validated_rows
                or type(self.complete) is not bool
                or type(self.evidence_source_pairs) is not frozenset
                or len(self.evidence_source_pairs) > MAX_EVIDENCE
                or any(type(pair) is not tuple or len(pair) != 2
                       or type(pair[0]) is not str or type(pair[1]) is not str
                       or len(pair[0]) != 64 or len(pair[1]) != 64
                       or pair[0] not in self.verified_evidence
                       or pair[1] not in self.verified_sources
                       for pair in self.evidence_source_pairs)
                or {pair[0] for pair in self.evidence_source_pairs} != (
                    self.verified_evidence if self.evidence_source_pairs
                    else frozenset())):
            raise ValueError("invalid_round_observation")


def observe_canonical_round(
    es_hits: list[dict], *, date_from: str | None, date_to: str | None,
    term_groups: list[set[str]], effective_terms: list[str],
    query_for_snippet: str, original_question: str,
    complete: bool,
    private_evidence: dict[tuple[str, str], PrivateCanonicalEvidence] | None = None,
    private_report_rows: dict[tuple[str, str], CanonicalReportEvidence] | None = None,
    deep_rank_frequency=None,
) -> RoundObservation:
    """Validate a *single* page/round with the current canonical parser.

    Caller must attest that this is all pages/queries planned in this round.
    This function cannot prove a live ES request occurred, nor can it infer
    absence of uninspected/omitted pages from the hit list alone.
    """
    # A private collector is an explicit worker-only opt-in. Never mutate
    # caller state until the ENTIRE canonical round has passed validation.
    if private_evidence is not None and (
            type(private_evidence) is not dict or private_evidence):
        raise ValueError("invalid_private_evidence_collector")
    if private_report_rows is not None and (
            type(private_report_rows) is not dict or private_report_rows):
        raise ValueError("invalid_private_report_collector")
    source_keys = _es_source_keys(es_hits)
    if (type(complete) is not bool or type(term_groups) is not list
            or not 1 <= len(term_groups) <= 32
            or any(type(g) is not set or not g or len(g) > 32
                   for g in term_groups)
            or type(effective_terms) is not list
            or len(effective_terms) > 256
            or type(original_question) is not str
            or not 0 < len(original_question) <= 4096
            or type(query_for_snippet) is not str
            or len(query_for_snippet) > 2048):
        raise ValueError("invalid_canonical_round_parameters")

    # Builder uses the actual existing per-Event/Timeline date and topic
    # checks. No source text is logged by this function or its callers.
    _, evidence, _ = build_hits_and_evidence(
        es_hits, date_from=date_from, date_to=date_to, allowed_years=None,
        term_groups=term_groups, effective_terms=effective_terms,
        query_for_snippet=query_for_snippet,
        original_question=original_question,
        include_source_hit_ordinal=True,
        **({"deep_rank_frequency": deep_rank_frequency} if deep_rank_frequency is not None else {}),
    )
    if len(evidence) > MAX_EVIDENCE:
        raise ValueError("round_evidence_over_cap")
    evidence_keys: set[str] = set()
    verified_sources: set[str] = set()
    evidence_sources: set[tuple[str, str]] = set()
    staged_private: dict[tuple[str, str], PrivateCanonicalEvidence] = {}
    staged_report: dict[tuple[str, str], CanonicalReportEvidence] = {}
    fallback_rows = 0
    validated_rows = 0
    for row in evidence:
        ordinal = row.get("__sraf_source_hit_ordinal")
        if type(ordinal) is not int or not 0 <= ordinal < len(source_keys):
            raise ValueError("invalid_evidence_source_provenance")
        scope, policy, groups = (
            row.get("match_scope"), row.get("match_policy"),
            row.get("group_hits"),
        )
        # Legacy builder may mark a no-term fallback policy="strict"
        # even though match_scope="none". Both fallback cases excluded.
        if (scope not in _ALLOWED_SCOPE or policy not in _ALLOWED_POLICY
                or type(groups) is not int or groups <= 0):
            fallback_rows += 1
            continue
        contents = row.get("text")
        when = row.get("date_iso")
        if (type(contents) is not str or not 0 < len(contents) <= 16384
                or type(when) is not str):
            raise ValueError("invalid_verified_evidence")
        # The canonical parser intentionally leaves date_iso empty when a
        # structured Event has only YEAR/MONTH precision or multiple matched
        # dates. Do not invent a day or reject otherwise valid Evidence.
        if when:
            try:
                if len(when) != 10 or when != date.fromisoformat(when).isoformat():
                    raise ValueError("invalid_date")
            except ValueError as exc:
                raise ValueError("invalid_verified_evidence_date") from exc
        matched = row.get("matched_event_time_candidates", [])
        if type(matched) is not list or len(matched) > 64:
            raise ValueError("invalid_matched_time_candidates")
        time_parts: list[tuple[str, str, str, str, str]] = []
        for item in matched:
            if type(item) is not dict:
                raise ValueError("invalid_matched_time_candidates")
            source = item.get("source")
            if source not in ("Event", "Event_Timeline"):
                raise ValueError("invalid_matched_time_candidates")
            point = parse_structured_time(
                item.get("time_iso"), item.get("time_precision"), source,
            )
            if (point is None or point.time_iso != item.get("time_iso")
                    or point.precision != item.get("time_precision")
                    or point.start != item.get("date_start")
                    or point.end != item.get("date_end")
                    or not point.overlaps(date_from, date_to)):
                raise ValueError("invalid_matched_time_candidates")
            time_parts.append((
                point.source, point.precision, point.time_iso,
                point.start, point.end,
            ))
        if not when and not time_parts and (date_from or date_to):
            # Legacy unstructured Evidence without a known date can pass
            # the old topic-only builder even with a caller date window.
            # Do not abort other valid rows, but NEVER count this one as
            # date+topic verified in a new request-wide ledger.
            fallback_rows += 1
            continue
        # In an unbounded query, a legacy undated Evidence may still be
        # topic-valid; it never acquires an invented date.
        temporal_key = tuple(sorted(time_parts)) if time_parts else (
            ("exact_day", when) if when else ("unbounded_undated",),
        )
        ids = row.get("event_ids", [])
        if (type(ids) is not list or len(ids) > 32
                or any(type(v) is not str or not 0 < len(v) <= 256 for v in ids)):
            raise ValueError("invalid_verified_event_ids")
        block = row.get("__sraf_block_index")
        if block is not None and (type(block) is not int or block < 0
                                  or block > 100_000):
            raise ValueError("invalid_verified_block")
        if block is None and ids:
            # The canonical parser accepts some multi-block inner hits
            # without a parent _nested offset only when all Event IDs
            # identify one unique block. Reconstruct that SAME safe owner
            # from the original _source, so the same passage arriving via
            # an explicit-offset inner hit or _source gets ONE identity.
            raw_source = es_hits[ordinal].get("_source")
            blocks = as_blocks(
                raw_source.get("multidim_event_json")
                if type(raw_source) is dict else None
            )
            if len(blocks) == 1:
                block = 0
            elif len(blocks) > 1:
                declarations = [event_ids_in_block(b) for b in blocks]
                owners: set[int] = set()
                for eid in ids:
                    occurrences = [
                        i for i, declared in enumerate(declarations)
                        if eid in declared
                    ]
                    if len(occurrences) != 1:
                        owners.clear()
                        break
                    owners.add(occurrences[0])
                if len(owners) == 1:
                    block = next(iter(owners))
        def prop(name):
            value = row.get(name)
            if value is None:
                return ""
            if type(value) is not str or len(value) > 256:
                raise ValueError("invalid_verified_identity")
            return value
        validated_rows += 1
        key = _digest((source_keys[ordinal], block, temporal_key,
                       tuple(sorted(ids)), prop("source_id"),
                       prop("paragraph_id"), contents))
        evidence_keys.add(key)
        verified_sources.add(source_keys[ordinal])
        pair = (key, source_keys[ordinal])
        evidence_sources.add(pair)
        if private_evidence is not None or private_report_rows is not None:
            item = PrivateCanonicalEvidence(
                text=contents, date_iso=when,
                matched_event_times=tuple(time_parts),
                event_ids=tuple(ids),
            )
            previous = staged_private.get(pair)
            if previous is not None and previous != item:
                raise ValueError("inconsistent_verified_private_evidence")
            staged_private[pair] = item
            if private_report_rows is not None:
                doc_id = pick_doc_id(row)
                # Unciteable passages may still be useful for retrieval
                # diagnostics; they cannot enter the later report prompt.
                doc_id = doc_id if isinstance(doc_id, str) and len(doc_id) <= 256 else ""
                def optional_text(name):
                    value = row.get(name)
                    return value if type(value) is str and len(value) <= 4096 else ""
                projected = CanonicalReportEvidence(
                    pair=pair, passage=item, doc_id=doc_id,
                    title=optional_text("article_title"), subject=optional_text("subject"),
                    structured=bool(row.get("structured_time_context") or time_parts),
                    weak=bool(row.get("weak_evidence")), scope=scope, group_hits=groups,
                )
                prior = staged_report.get(pair)
                if prior is not None and prior.doc_id != projected.doc_id:
                    raise ValueError("inconsistent_report_source")
                staged_report.setdefault(pair, projected)
    # If one identical passage appears twice in the same parser slice,
    # parser output count can exceed unique verified evidence identities.
    observation = RoundObservation(
        candidate_sources=frozenset(source_keys),
        verified_evidence=frozenset(evidence_keys),
        verified_sources=frozenset(verified_sources),
        parser_output_rows=len(evidence),
        validated_rows=validated_rows,
        fallback_rows=fallback_rows,
        complete=complete,
        evidence_source_pairs=frozenset(evidence_sources),
    )
    if private_evidence is not None:
        if set(staged_private) != observation.evidence_source_pairs:
            raise ValueError("private_evidence_provenance_incomplete")
        private_evidence.update(staged_private)
    if private_report_rows is not None:
        if set(staged_report) != observation.evidence_source_pairs:
            raise ValueError("private_report_provenance_incomplete")
        private_report_rows.update(staged_report)
    return observation


class RequestWideEvidenceLedger:
    """One request, no global state, no IO. Stores digests, not raw snippets."""

    def __init__(self, *, max_rounds: int = MAX_ROUNDS) -> None:
        if type(max_rounds) is not int or not 1 <= max_rounds <= MAX_ROUNDS:
            raise ValueError("invalid_request_round_cap")
        self._max_rounds = max_rounds
        self._seen: set[str] = set()
        self._known_sources: set[str] = set()
        self._history: list[RoundEvidenceSummary] = []
        self._audits: list[dict[str, int | bool]] = []

    def append(
        self, observation: RoundObservation, *, search_terms: tuple[str, ...],
        missing_aspects: tuple[str, ...], coverage_sufficient: bool,
        request_wide_attested: bool,
    ) -> RoundEvidenceSummary:
        """Only a trusted request coordinator may attest full-page assessment.

        A caller cannot infer coverage_sufficient from candidate hit counts.
        Incomplete/unattested rounds always stop subsequent planning.
        """
        if (type(observation) is not RoundObservation
                or len(self._history) >= self._max_rounds
                or (self._history and (
                    self._history[-1].result_incomplete or
                    not self._history[-1].request_wide or
                    self._history[-1].coverage_sufficient))):
            raise ValueError("round_not_admissible")
        _terms(search_terms)
        if type(missing_aspects) is not tuple or len(missing_aspects) > 8:
            raise ValueError("invalid_round_aspects")
        for aspect in missing_aspects:
            from .contracts import _bounded_text
            _bounded_text(aspect, limit=120)
        if (type(coverage_sufficient) is not bool
                or type(request_wide_attested) is not bool
                or (coverage_sufficient and (
                    not observation.complete or not request_wide_attested))):
            raise ValueError("unattested_coverage_sufficiency")
        gained = observation.verified_evidence - self._seen
        gained_sources = observation.verified_sources - self._known_sources
        if len(self._seen | observation.verified_evidence) > MAX_TOTAL_KEYS:
            raise ValueError("cumulative_evidence_over_cap")
        next_seen = self._seen | observation.verified_evidence
        next_sources = self._known_sources | observation.verified_sources
        record = RoundEvidenceSummary(
            number=len(self._history) + 1, search_terms=search_terms,
            verified_evidence=len(next_seen), newly_verified_evidence=len(gained),
            known_sources=len(next_sources), missing_aspects=missing_aspects,
            coverage_sufficient=coverage_sufficient,
            result_incomplete=not observation.complete,
            request_wide=request_wide_attested,
        )
        self._seen, self._known_sources = next_seen, next_sources
        self._history.append(record)
        self._audits.append({
            "round": record.number, "candidate_sources": len(observation.candidate_sources),
            "parser_output": observation.parser_output_rows,
            "validated_rows": observation.validated_rows,
            "fallback": observation.fallback_rows,
            "verified_in_round": len(observation.verified_evidence),
            "new_verified": len(gained), "new_sources": len(gained_sources),
            "cumulative_verified": len(self._seen),
            "cumulative_sources": len(self._known_sources),
            "complete": observation.complete, "request_wide_attested": request_wide_attested,
        })
        return record

    @property
    def history(self) -> tuple[RoundEvidenceSummary, ...]:
        return tuple(self._history)

    def safe_audit(self) -> tuple[dict[str, int | bool], ...]:
        """Fixed schema counts only; never return source digests or terms."""
        return tuple(dict(a) for a in self._audits)
