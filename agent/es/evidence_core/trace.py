"""Opt-in bounded, content-free diagnostics for Evidence retrieval (#397 P1-a).

This emits *only* generated trace IDs, numeric per-hit/citation ordinals,
bounded counts and fixed reason-code enums. Do not add document identifiers,
query terms, text, dates, event IDs or host paths to this trace.
"""
from __future__ import annotations

from collections import Counter
import json
import logging
import os
import secrets
from typing import Any

_LOG = logging.getLogger("sraf.evidence_trace")
_MAX_HIT_RECORDS = 64
_MAX_CITATION_RECORDS = 256

# Fixed internal-only stage count identifiers for #404/#405 opt-in rescue.
# Never accept caller-provided strings or event/document values as keys.
_STAGE_COUNTS = frozenset({
    "source_refill.strict_candidates", "source_refill.weak_candidates",
    "source_refill.strict_selected", "source_refill.weak_selected",
    "source_refill.unselected_by_target", "bounded_rescue.selected",
})

# Keep all public trace fields fixed, not influenced by Elasticsearch values.
_REASONS = frozenset({
    "accepted", "date_unmatched", "date_unknown", "date_before",
    "date_after", "year_unmatched", "no_uuid", "empty_text",
    "topic_rejected", "fallback_selected",
})


class EvidenceTrace:
    """Per builder invocation; not a cross-page or cross-request global record."""

    def __init__(self) -> None:
        self.trace_id = secrets.token_hex(8)
        self.counts: Counter[str] = Counter()
        self.documents: list[dict[str, Any]] = []
        self.citations: list[dict[str, Any]] = []
        self.documents_overflow = 0
        self.citations_overflow = 0

    @classmethod
    def from_env(cls) -> "EvidenceTrace | None":
        # Other values, including accidental non-boolean settings, remain OFF.
        return cls() if os.environ.get("SRAF_EVIDENCE_TRACE") == "1" else None

    def parsed_hit(
        self, *, ordinal: int, source_count: int, inner_count: int,
        parsed_count: int, selected_count: int, mode: str,
        source_uninspected_after_cap: int = 0,
    ) -> None:
        # Never capture _index/_id/uuid/title/source text or event IDs.
        if mode not in {"inner", "source", "fallback", "none"}:
            mode = "none"
        self.counts["parser.hits"] += 1
        self.counts["parser.source_candidates"] += source_count
        self.counts["parser.inner_returned"] += inner_count
        self.counts["parser.citations_parsed"] += parsed_count
        self.counts["parser.citations_selected"] += selected_count
        self.counts["parser.citations_capped"] += max(0, parsed_count - selected_count)
        # Source-loop cap stops *before* skipped items are validated; these
        # are possible candidates, NOT proven valid Evidence citations.
        self.counts["parser.source_uninspected_after_cap"] += max(0, source_uninspected_after_cap)
        if len(self.documents) < _MAX_HIT_RECORDS:
            self.documents.append({
                "hit_ordinal": ordinal, "mode": mode,
                "source_candidates": source_count,
                "inner_returned": inner_count,
                "parsed": parsed_count, "selected": selected_count,
                "source_uninspected_after_cap": max(0, source_uninspected_after_cap),
            })
        else:
            self.documents_overflow += 1

    def citation(self, *, stage: str, hit_ordinal: int,
                 citation_ordinal: int, reason: str) -> None:
        if stage not in {"strict", "relaxed", "fallback_no_terms",
                         "fallback_any_term"}:
            return
        reason = reason if reason in _REASONS else "topic_rejected"
        self.counts[f"{stage}.{reason}"] += 1
        if len(self.citations) < _MAX_CITATION_RECORDS:
            self.citations.append({
                "stage": stage, "hit_ordinal": hit_ordinal,
                "citation_ordinal": citation_ordinal, "reason": reason,
            })
        else:
            self.citations_overflow += 1

    def stage_count(self, key: str, count: int) -> None:
        """Count only a fixed, bounded internal rescue stage; never free text."""
        if key in _STAGE_COUNTS and type(count) is int and 0 <= count <= 1_000_000:
            self.counts[key] += count

    def emit(self, *, output_hits: int, output_evidence: int,
             strict_count: int, relaxed_used: bool) -> None:
        payload = {
            "schema": "sraf_evidence_retrieval_trace_v1",
            "scope": "single_builder_evaluation_not_final_report",
            "trace_id": self.trace_id,
            "limits": {
                "document_records": _MAX_HIT_RECORDS,
                "citation_records": _MAX_CITATION_RECORDS,
            },
            "counters": dict(sorted(self.counts.items())),
            "strict_accepted": strict_count,
            "relaxed_used": bool(relaxed_used),
            "output_hits": output_hits,
            "output_evidence": output_evidence,
            "document_records_overflow": self.documents_overflow,
            "citation_records_overflow": self.citations_overflow,
            "documents": self.documents,
            "citations": self.citations,
        }
        _LOG.warning("SRAF_EVIDENCE_TRACE=%s", json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
        ))
