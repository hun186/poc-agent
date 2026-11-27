"""A8c final-Evidence binding; local-only unless explicitly authorized.

A receipt attests a bounded real primary response and the exact retained
date-refill slice. It is NOT ES TLS identity, owner authorization, or egress
permission. Never persist or expose the receipt or batch.
"""
from __future__ import annotations

from agent.arc_mode import arc_shadow_enabled

from dataclasses import dataclass, field, replace
from datetime import date
import json
import logging
import math
import os
import re
import time

from .arc_request_budget import ArcUnits, current_arc_budget
from .evidence_core.arc_tighten_shadow import CandidatePressure
from .evidence_core.arc_semantic_review import (
    MAX_PREFIX, MAX_ROW_CHARS, SemanticReviewBatch, build_semantic_review_batch,
)
from .evidence_core.models import EvidenceSnippet
from .ordinary_scope_receipt import current_ordinary_scope_capture

_LOG = logging.getLogger("sraf.arc.review_scope")
_INDEX = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
MAX_HITS = 128
_ORIGIN = "__sraf_source_hit_ordinal"


def review_scope_enabled(index):
    return (arc_shadow_enabled("SRAF_ARC_REVIEW_SCOPE")
            and type(index) is str and _INDEX.fullmatch(index) is not None
            and ".." not in index
            and index == os.getenv("SRAF_ARC_REVIEW_VERIFIED_INDEX"))


@dataclass(frozen=True, repr=False)
class PrimaryReviewReceipt:
    index: str
    body: dict = field(repr=False)
    response: dict = field(repr=False)
    hits: tuple = field(repr=False)
    ids: tuple[str, ...] = field(repr=False)


def capture_primary_review(*, index, body, response, real_client, sink):
    """Called only by safe_search's non-retry primary success boundary."""
    from agent.external_capabilities import requirement_acceptance_active

    if (type(sink) is not list or sink or real_client is not True
            or not review_scope_enabled(index)
            or requirement_acceptance_active()
            or current_ordinary_scope_capture() is not None
            or current_arc_budget() is None):
        return
    try:
        pressure = CandidatePressure.from_primary(response)
        # Narrow pilot: prove the entire bounded candidate page, not merely
        # a lower-bound result window or a truncated multi-page query.
        if (pressure.relation != "eq" or pressure.total != pressure.returned
                or not 1 <= pressure.returned <= MAX_HITS):
            return
        hits = tuple(response["hits"]["hits"])
        ids = []
        for h in hits:
            if (type(h) is not dict or h.get("_index") != index
                    or type(h.get("_id")) is not str or not 0 < len(h["_id"]) <= 512):
                return
            ids.append(h["_id"])
        if len(set(ids)) != len(ids):
            return
        sink.append(PrimaryReviewReceipt(index, body, response, hits, tuple(ids)))
    except Exception:
        # Optional diagnostic cannot break normal search. No raw exception.
        return


@dataclass(frozen=True, repr=False)
class FinalReviewInput:
    primary: PrimaryReviewReceipt
    original_question: str = field(repr=False)
    groups: tuple[frozenset[str], ...] = field(repr=False)
    date_from: str = field(repr=False)
    date_to: str = field(repr=False)


def _date_pair(first, last):
    try:
        return (type(first) is str and type(last) is str
                and date.fromisoformat(first).isoformat() == first
                and date.fromisoformat(last).isoformat() == last
                and first <= last)
    except ValueError:
        return False


def make_final_review_input(receipt, *, question, groups, date_from, date_to, manual):
    if (type(receipt) is not PrimaryReviewReceipt or manual is not False
            or not _date_pair(date_from, date_to)
            or type(question) is not str or not 0 < len(question) <= 6000
            or type(groups) is not list or not 1 <= len(groups) <= 16
            or any(type(g) is not set or not g for g in groups)
            or sum(map(len, groups)) > 64
            or any(type(t) is not str or not 0 < len(t) <= 160 for g in groups for t in g)):
        return None
    return FinalReviewInput(receipt, question, tuple(frozenset(g) for g in groups),
                            date_from, date_to)


@dataclass(frozen=True, repr=False)
class _PreparedFinalReview:
    batch: SemanticReviewBatch = field(repr=False)
    source_ids: tuple[str, ...] = field(repr=False)
    ambiguous: bool


def _prepare_final_review(scope, *, body, first_response, raw, selected,
                          selected_evidence, meta):
    """Build a private bounded batch ONLY from the exact final retained prefix.

    No unselected rows, raw source, other page, or UUID-based joins. Caller
    supplies the canonical date-refill selection, not model arguments.
    """
    if type(scope) is not FinalReviewInput:
        return None
    receipt = scope.primary
    if (type(receipt) is not PrimaryReviewReceipt
            or not review_scope_enabled(receipt.index)
            or body is not receipt.body or first_response is not receipt.response
            or type(meta) is not dict or type(meta.get("pages_fetched")) is not int
            or meta["pages_fetched"] != 1
            or meta.get("incomplete_due_to_scan_limit") is not False
            or meta.get("incomplete_due_to_page_admission", False) is not False
            or type(raw) is not list or len(raw) != len(receipt.hits)
            or not 1 <= len(raw) <= MAX_HITS
            or type(selected) is not list or not 1 <= len(selected) <= len(raw)
            or type(selected_evidence) is not list or not selected_evidence):
        return None
    if any(h is not expected or h.get("_index") != receipt.index or h.get("_id") != id_
           for h, expected, id_ in zip(raw, receipt.hits, receipt.ids)):
        return None
    origins = set()
    for row in selected:
        i = row.get(_ORIGIN)
        if type(i) is not int or not 0 <= i < len(raw) or i in origins:
            return None
        origins.add(i)
    budget_scope = current_arc_budget()
    if budget_scope is None:
        return None
    budget, ordinal = budget_scope
    if not budget.reserve(ordinal, ArcUnits(slices=1, hits=MAX_HITS, rows=MAX_PREFIX,
                                            chars=MAX_PREFIX * MAX_ROW_CHARS)):
        return None
    # Preserve the first final prefix order. Only linked structured-date
    # strict rows are projected; legacy fallback cannot establish this pilot.
    prefix = selected_evidence[:MAX_PREFIX]
    rows = []
    source_ids = set()
    for row in prefix:
        i = row.get(_ORIGIN)
        if type(i) is not int or i not in origins:
            return None
        text = row.get("text")
        if (row.get("match_policy") != "strict"
                or row.get("structured_time_context") is not True
                or not row.get("matched_event_time_candidates")
                or type(text) is not str or not 0 < len(text) <= MAX_ROW_CHARS
                or row.get("match_scope") not in ("text", "mixed", "meta")
                or type(row.get("weak_evidence", False)) is not bool):
            continue
        # Canonical builder has already validated linked Event/Timeline
        # overlap. This narrow projection supplies only fields used by A8.
        source_ids.add(receipt.ids[i])
        rows.append(EvidenceSnippet(uuid="", text=text, date_iso="", article_date_iso="",
                                    source_hit_ordinal=i, match_policy="strict",
                                    match_scope=row["match_scope"],
                                    weak_evidence=row.get("weak_evidence", False)))
    batch = build_semantic_review_batch(scope.original_question,
                                        [set(g) for g in scope.groups], rows)
    if batch is None:
        return None
    batch = replace(batch, prefix_count=len(prefix),
                    prefix_limited=len(selected_evidence) > len(prefix),
                    skipped_rows=batch.skipped_rows + len(prefix) - len(rows))
    # Policy covers a conservative superset of sources eligible for the
    # sampler, not merely selected document UUIDs or guessed source IDs.
    return _PreparedFinalReview(batch, tuple(sorted(source_ids)),
                               any(e.weak_evidence or e.match_scope in ("meta", "mixed")
                                   for e in rows))


def prepare_final_review(scope, **kwargs):
    """Compatibility local batch contract; no authorization or transport."""
    prepared = _prepare_final_review(scope, **kwargs)
    return prepared.batch if prepared is not None else None


def _observe_authorized_review(scope, prepared, *, final_count, check_review_egress,
                               review_deadline_monotonic):
    """Explicit trusted Python-only pilot, not a production grant.

    The caller's policy must bind the authenticated owner, original question,
    groups, date scope, actual source IDs and endpoint/model/CA. The deadline
    is the caller's monotonic cutoff AFTER reserving report generation time.
    """
    from agent.external_capabilities import requirement_acceptance_active
    from .arc_semantic_review_transport import _approved_endpoint, observe_semantic_review

    if (not callable(check_review_egress)
            or type(review_deadline_monotonic) not in (int, float)
            or not math.isfinite(review_deadline_monotonic)
            or final_count < 40 or prepared.batch.count < 4
            or not prepared.ambiguous):
        return
    index = scope.primary.index
    budget_scope = current_arc_budget()
    if budget_scope is None:
        return

    def still_current(approved):
        return (review_scope_enabled(index)
                and not requirement_acceptance_active()
                and current_ordinary_scope_capture() is None
                and current_arc_budget() == budget_scope
                and review_deadline_monotonic - time.monotonic() >= 25
                and _approved_endpoint(index) == approved)

    def authorize(approved):
        if not still_current(approved):
            return False
        permitted = check_review_egress(
            question=scope.original_question, groups=scope.groups,
            date_from=scope.date_from, date_to=scope.date_to,
            index=index, source_ids=prepared.source_ids,
            endpoint=approved.url, model=approved.model, verify=approved.verify,
        )
        return permitted is True and still_current(approved)

    approved = _approved_endpoint(index)
    if approved is not None and still_current(approved):
        # Transport owns the nonrefundable LLM reservation and performs
        # pre/post checks. No retry, no alternate provider, no row verdicts.
        observe_semantic_review(prepared.batch, index=index, authorize=authorize)


def observe_final_review_scope(scope, *, check_review_egress=None,
                               review_deadline_monotonic=None, **kwargs):
    """Local by default; only an explicit trusted policy can request A8."""
    record = {"schema": "sraf_arc_final_review_scope_v1", "status": "unavailable"}
    try:
        prepared = _prepare_final_review(scope, **kwargs)
        if prepared is not None:
            batch = prepared.batch
            record.update(status="bound_local_batch", batch_count=batch.count,
                          prefix_count=batch.prefix_count, prefix_limited=batch.prefix_limited,
                          skipped_rows=batch.skipped_rows)
            if check_review_egress is not None:
                _observe_authorized_review(
                    scope, prepared, final_count=len(kwargs["selected_evidence"]),
                    check_review_egress=check_review_egress,
                    review_deadline_monotonic=review_deadline_monotonic,
                )
    except Exception:
        pass
    _LOG.warning("SRAF_ARC_REVIEW_SCOPE=%s",
                 json.dumps(record, sort_keys=True, separators=(",", ":")))
