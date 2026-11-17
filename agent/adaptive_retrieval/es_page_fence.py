"""Offline ES pagination completeness fence for a future SRAF N-round adapter.

This is NOT an Elasticsearch client and never constructs DSL or calls network.
A trusted adapter must still independently enforce user RBAC, immutable index/
date/field scope, PIT consistency, query search_after, and transport timeouts.
This class only guarantees the *supplied* serial page chain is bounded, shard-
complete, unexpired at acceptance, and not partial or replayed. It does NOT
claim request-wide search or semantic coverage. It cannot resume after restart.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Lock
from typing import Any

from .contracts import QueryConstraints
from .coordinator import AdaptiveRequestCoordinator
from .evidence_ledger import MAX_HITS


class PageFenceError(ValueError):
    """Fixed reason only: never include private response details."""


@dataclass(frozen=True)
class PageTicket:
    """Private in-memory admission ticket; never log cursor or source data."""
    round_number: int
    page_number: int
    size: int
    search_after: tuple[object, ...] | None


def _cursor(hit: dict[str, Any]) -> tuple[object, ...]:
    raw = hit.get("sort")
    if type(raw) not in (list, tuple) or not 1 <= len(raw) <= 8:
        raise PageFenceError("missing_es_sort_cursor")
    parts = []
    for item in raw:
        if type(item) not in (type(None), str, int, float, bool):
            raise PageFenceError("invalid_es_sort_cursor")
        if type(item) is float and not math.isfinite(item):
            raise PageFenceError("invalid_es_sort_cursor")
        if type(item) is str and len(item) > 512:
            raise PageFenceError("invalid_es_sort_cursor")
        parts.append(item)
    return tuple(parts)


def _page_hits(raw: Any, size: int, allowed_indexes: tuple[str, ...]) -> list[dict]:
    if type(raw) is not dict or raw.get("timed_out") is not False:
        raise PageFenceError("es_timeout_or_bad_page")
    shards = raw.get("_shards")
    if type(shards) is not dict:
        raise PageFenceError("untrusted_es_shards")
    total = shards.get("total")
    successful = shards.get("successful")
    skipped = shards.get("skipped", 0)
    failed = shards.get("failed")
    if (any(type(v) is not int for v in (total, successful, skipped, failed))
            or total < 1 or successful < 0 or skipped < 0 or failed != 0
            # Elasticsearch includes skipped shards among successful shards.
            # Adding skipped to successful could mask unallocated shards.
            or successful != total or skipped > successful):
        raise PageFenceError("partial_es_shards")
    hits_section = raw.get("hits")
    if type(hits_section) is not dict or type(hits_section.get("hits")) is not list:
        raise PageFenceError("untrusted_es_hits")
    hits = hits_section["hits"]
    if len(hits) > size:
        raise PageFenceError("oversized_es_page")
    for hit in hits:
        if (type(hit) is not dict
                or type(hit.get("_index")) is not str
                or hit["_index"] not in allowed_indexes
                or type(hit.get("_id")) is not str
                or not 0 < len(hit["_id"]) <= 256
                or type(hit.get("_source")) is not dict):
            raise PageFenceError("untrusted_es_source")
    return hits


class RoundESPageFence:
    """One serial, same-plan ES page chain; strict no-network boundary.

    Full pages must be followed by another ES page (which may be empty).
    A short page terminates the chain. Caller must use the ticket's immutable
    search_after in its independently authorized ES query. This class cannot
    prove the server actually honored search_after or PIT.
    """

    def __init__(
        self, *, coordinator: AdaptiveRequestCoordinator,
        constraints: QueryConstraints, round_number: int,
        page_size: int = 50, max_pages: int = 24,
    ) -> None:
        if (type(coordinator) is not AdaptiveRequestCoordinator
                or type(constraints) is not QueryConstraints
                or coordinator._constraints is not constraints
                or type(round_number) is not int or not 1 <= round_number <= 8
                or type(page_size) is not int or not 1 <= page_size <= 100
                or type(max_pages) is not int or not 1 <= max_pages <= 24
                or page_size * max_pages > 2400):
            raise ValueError("invalid_es_page_fence_config")
        progress = coordinator.safe_progress()
        if progress["phase"] != "SEARCHING" or progress["round"] != round_number:
            raise ValueError("es_page_round_not_active")
        self._coordinator = coordinator
        self._constraints = constraints
        self._round = round_number
        self._size = page_size
        self._limit = max_pages
        self._lock = Lock()
        self._page_count = 0
        self._cursor: tuple[object, ...] | None = None
        self._pending: PageTicket | None = None
        self._hits: list[dict] = []
        self._seen: set[tuple[str, str]] = set()
        self._complete = False
        self._consumed = False
        self._failed: str | None = None

    def _ensure_active(self) -> None:
        progress = self._coordinator.safe_progress()
        if (progress["phase"] != "SEARCHING"
                or progress["round"] != self._round):
            raise PageFenceError("es_page_round_no_longer_active")

    def _abort(self, reason: str) -> None:
        self._pending = None
        self._failed = reason
        self._hits.clear()
        self._seen.clear()
        self._coordinator.cancel()

    def begin_page(self) -> PageTicket:
        """Reserve exactly one coordinator ES slot before an external request."""
        with self._lock:
            if self._failed or self._consumed or self._complete or self._pending:
                raise PageFenceError("es_page_not_admissible")
            self._ensure_active()
            if self._page_count >= self._limit:
                self._abort("es_page_limit_exhausted")
                raise PageFenceError("es_page_limit_exhausted")
            if not self._coordinator.admit_es_call():
                self._abort("es_page_budget_exhausted")
                raise PageFenceError("es_page_budget_exhausted")
            self._pending = PageTicket(
                round_number=self._round,
                page_number=self._page_count + 1,
                size=self._size,
                search_after=self._cursor,
            )
            return self._pending

    def submit_page(self, ticket: PageTicket, response: Any) -> bool:
        """Accept a checked page; True only if the supplied chain is complete.

        A failed page cancels future coordinator admission. Not a claim that
        the trusted adapter honored the PIT, scope, or search_after.
        """
        with self._lock:
            if self._pending is None or ticket is not self._pending:
                raise PageFenceError("stale_es_page_ticket")
            try:
                self._ensure_active()
                budget = self._coordinator._budget.snapshot()
                if budget.remaining_seconds <= budget.generation_reserve_seconds:
                    raise PageFenceError("es_page_after_retrieval_deadline")
                hits = _page_hits(response, self._size, self._constraints.allowed_indexes)
                if len(hits) + len(self._hits) > MAX_HITS:
                    raise PageFenceError("es_round_hit_limit_exhausted")
                new_ids = [(h["_index"], h["_id"]) for h in hits]
                if len(new_ids) != len(set(new_ids)) or any(
                        key in self._seen for key in new_ids):
                    raise PageFenceError("duplicate_es_pagination_source")
                next_cursor = _cursor(hits[-1]) if len(hits) == self._size else None
                if next_cursor is not None and next_cursor == self._cursor:
                    raise PageFenceError("unchanged_es_search_after")
            except PageFenceError as exc:
                self._abort(str(exc))
                raise
            except Exception:
                self._abort("invalid_es_page")
                raise PageFenceError("invalid_es_page") from None
            self._hits.extend(hits)
            self._seen.update(new_ids)
            self._page_count += 1
            self._cursor = next_cursor
            self._pending = None
            self._complete = len(hits) < self._size
            return self._complete

    def take_complete_hits(self) -> list[dict]:
        """One-time internal handoff. Does not attest query-wide coverage."""
        with self._lock:
            if self._pending or not self._complete or self._failed or self._consumed:
                raise PageFenceError("incomplete_es_page_chain")
            self._ensure_active()
            self._consumed = True
            return list(self._hits)

    def safe_audit(self) -> dict[str, object]:
        """Only fixed codes and counts; neither ES cursor nor raw articles."""
        with self._lock:
            return {
                "schema": "sraf_nround_es_page_fence_v1",
                "round": self._round,
                "pages_accepted": self._page_count,
                "sources_accepted": len(self._seen),
                "complete_page_chain": self._complete and not self._failed,
                "failed": self._failed or "NONE",
                "request_wide_attested": False,
                "live_es": "NOT_EXECUTED_BY_FENCE",
            }
