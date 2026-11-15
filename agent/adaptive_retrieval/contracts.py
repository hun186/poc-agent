"""Immutable, server-owned scope for a later adaptive retrieval planner.

Only trusted request processing may construct these objects. They prevent a
planner response from mutating constraints, but they DO NOT independently prove
that the first-round LLM parsed the user's question correctly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re


_INDEX = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_FIELD = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_ALLOWED_SOURCES = {"none", "explicit_user", "trusted_context"}
_PRECISIONS = {"none", "year", "month", "day", "second"}


def _bounded_text(value: str, *, limit: int = 160) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError("invalid_adaptive_text")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("invalid_adaptive_text")
    return value.strip()


def _terms(values: tuple[str, ...], *, limit: int = 8) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > limit:
        raise ValueError("invalid_adaptive_terms")
    checked = tuple(_bounded_text(v, limit=100) for v in values)
    if len({v.casefold() for v in checked}) != len(checked):
        raise ValueError("duplicate_adaptive_terms")
    return checked


@dataclass(frozen=True)
class DateWindow:
    """One user-derived temporal facet. No ES/LLM code may mutate it."""

    start: str | None = None
    end: str | None = None
    precision: str = "none"
    source: str = "none"
    source_text: str | None = None

    def __post_init__(self) -> None:
        if self.source not in _ALLOWED_SOURCES or self.precision not in _PRECISIONS:
            raise ValueError("invalid_date_constraint")
        if self.source == "none":
            if any(x is not None for x in (self.start, self.end, self.source_text)) or self.precision != "none":
                raise ValueError("unexpected_date_constraint")
            return
        if not isinstance(self.start, str) or not isinstance(self.end, str):
            raise ValueError("invalid_date_constraint")
        try:
            first = date.fromisoformat(self.start)
            last = date.fromisoformat(self.end)
        except ValueError as exc:
            raise ValueError("invalid_date_constraint") from exc
        if self.start != first.isoformat() or self.end != last.isoformat() or first > last:
            raise ValueError("invalid_date_constraint")
        if self.precision == "none" or not isinstance(self.source_text, str):
            raise ValueError("unproven_date_constraint")
        _bounded_text(self.source_text, limit=160)


@dataclass(frozen=True)
class QueryConstraints:
    """Immutable scope from the trusted first-round interpretation.

    A higher-level verifier must establish dates, index/field authorizations
    and entity/keyword policy BEFORE producing this value. The planner cannot
    create or approve any change to these server-owned constraints.
    """

    question: str
    event_date: DateWindow
    analysis_date: DateWindow
    allowed_indexes: tuple[str, ...]
    fixed_fields: tuple[tuple[str, str], ...] = ()
    required_entities: tuple[str, ...] = ()
    original_core_terms: tuple[str, ...] = ()
    keyword_policy: str = "flexible"

    def __post_init__(self) -> None:
        _bounded_text(self.question, limit=4096)
        if type(self.event_date) is not DateWindow or type(self.analysis_date) is not DateWindow:
            raise ValueError("invalid_date_constraint")
        if type(self.allowed_indexes) is not tuple or not 1 <= len(self.allowed_indexes) <= 8:
            raise ValueError("invalid_allowed_indexes")
        if any(type(x) is not str or not _INDEX.fullmatch(x) for x in self.allowed_indexes):
            raise ValueError("invalid_allowed_indexes")
        if len(set(self.allowed_indexes)) != len(self.allowed_indexes):
            raise ValueError("invalid_allowed_indexes")
        if type(self.fixed_fields) is not tuple or len(self.fixed_fields) > 16:
            raise ValueError("invalid_fixed_fields")
        for pair in self.fixed_fields:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("invalid_fixed_fields")
            name, value = pair
            if type(name) is not str or not _FIELD.fullmatch(name):
                raise ValueError("invalid_fixed_fields")
            _bounded_text(value, limit=256)
        _terms(self.required_entities)
        _terms(self.original_core_terms)
        if self.keyword_policy not in ("flexible", "user_locked"):
            raise ValueError("invalid_keyword_policy")


@dataclass(frozen=True)
class RoundEvidenceSummary:
    """Request-wide assessment, NOT a single builder-slice diagnostic."""

    number: int
    search_terms: tuple[str, ...]
    verified_evidence: int
    newly_verified_evidence: int
    known_sources: int
    missing_aspects: tuple[str, ...]
    coverage_sufficient: bool
    result_incomplete: bool
    request_wide: bool = False

    def __post_init__(self) -> None:
        if type(self.number) is not int or not 1 <= self.number <= 100:
            raise ValueError("invalid_round_number")
        _terms(self.search_terms)
        if any(type(x) is not int or not 0 <= x <= 1_000_000 for x in
               (self.verified_evidence, self.newly_verified_evidence, self.known_sources)):
            raise ValueError("invalid_evidence_counts")
        if (self.newly_verified_evidence > self.verified_evidence
                or self.known_sources > self.verified_evidence):
            raise ValueError("inconsistent_evidence_counts")
        if type(self.missing_aspects) is not tuple or len(self.missing_aspects) > 8:
            raise ValueError("invalid_missing_aspects")
        for aspect in self.missing_aspects:
            _bounded_text(aspect, limit=120)
        if any(type(v) is not bool for v in
               (self.coverage_sufficient, self.result_incomplete, self.request_wide)):
            raise ValueError("invalid_round_assessment")


@dataclass(frozen=True)
class BudgetSnapshot:
    """Read-only admission hint; not a claim of hard SDK cancellation."""

    remaining_es_calls: int
    remaining_planner_calls: int
    remaining_seconds: int
    generation_reserve_seconds: int

    def __post_init__(self) -> None:
        if any(type(v) is not int or not 0 <= v <= 86400 for v in (
            self.remaining_es_calls, self.remaining_planner_calls,
            self.remaining_seconds, self.generation_reserve_seconds,
        )):
            raise ValueError("invalid_adaptive_budget")
