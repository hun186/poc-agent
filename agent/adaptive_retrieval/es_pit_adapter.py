"""Explicit, single-round Elasticsearch PIT transport for future SRAF N-round Jobs.

This module is NOT wired into production API/ReportJobWorker. A trusted caller
must inject an authorized ES client, an immutable *trusted* QueryConstraints
object, and the caller's actual authorized index allowlist. No import-time IO.

Unlike legacy safe_search, this path forbids ignored missing indexes, missing
shards and unverified ES pages. Uses a PIT and stable _shard_doc tie breaker
for search_after; the existing canonical RoundESPageFence still decides
page-chain completeness, not semantic request-wide coverage or Word readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.es.query_body import build_main_query_body
from .contracts import QueryConstraints
from .coordinator import AdaptiveRequestCoordinator
from .es_page_fence import PageFenceError, RoundESPageFence
from .planner import BoundNextRoundPlan, _list_of_terms


class LiveRoundESFailure(ValueError):
    """Reason code only: never leak client errors, private URLs or ES hits."""


@dataclass(frozen=True)
class FencedESRound:
    """Private hit batch for a trusted request-wide evaluator, never for UI."""

    hits: list[dict[str, Any]]
    audit: dict[str, object]

    @property
    def request_wide_attested(self) -> bool:
        # One complete PIT page chain is NOT full query/semantic coverage.
        return False


def _response(value: Any) -> dict[str, Any]:
    body = value if type(value) is dict else getattr(value, "body", None)
    if type(body) is not dict:
        raise LiveRoundESFailure("untrusted_es_transport_response")
    return body


def _pit(value: Any) -> str:
    if type(value) is not str or not 1 <= len(value) <= 4096:
        raise LiveRoundESFailure("untrusted_es_pit_identity")
    return value


def _timeout(coordinator: AdaptiveRequestCoordinator, limit_seconds: int) -> int:
    remaining = coordinator._budget.snapshot()
    seconds = remaining.remaining_seconds - remaining.generation_reserve_seconds
    if seconds <= 0:
        raise LiveRoundESFailure("es_retrieval_budget_exhausted")
    return min(seconds, limit_seconds)


def _query(
    constraints: QueryConstraints,
    *,
    optional_terms: tuple[str, ...],
    page_size: int,
) -> dict[str, Any]:
    # Do not accept a plan's own DSL, indexes, dates, or scope fields.
    # The existing query builder creates nested Event/Timeline date candidate
    # clauses; canonical evidence verification must still enforce exact dates.
    query_terms = list(constraints.original_core_terms)
    all_terms = query_terms + list(optional_terms)
    if not query_terms and not constraints.question.strip():
        raise LiveRoundESFailure("missing_trusted_query_terms")
    body = build_main_query_body(
        query=constraints.question,
        must_high_value=False, must_selected=False, size=page_size,
        date_from=constraints.event_date.start,
        date_to=constraints.event_date.end,
        selected_boost=None, high_value_boost=None,
        recency_boost=False, recency_field=None, recency_scale=None,
        with_date=constraints.event_date.source != "none",
        effective_terms=all_terms, core_terms=query_terms,
        syn_terms=[], all_terms=all_terms,
        original_question=constraints.question,
    )
    if type(body) is not dict or type(body.get("query")) is not dict:
        raise LiveRoundESFailure("invalid_es_query_builder")
    # PIT _shard_doc breaks ties across documents with identical _score and
    # importDT, making the next page's cursor stable within one PIT.
    body["sort"] = [
        {"_score": {"order": "desc"}},
        {"importDT": {"order": "desc", "missing": "_last"}},
        {"_shard_doc": {"order": "asc"}},
    ]
    body["size"] = page_size
    return body


def search_fenced_es_round(
    *,
    coordinator: AdaptiveRequestCoordinator,
    constraints: QueryConstraints,
    authorized_indexes: tuple[str, ...],
    client: Any,
    plan: BoundNextRoundPlan | None = None,
    page_size: int = 50,
    max_pages: int = 20,
    request_timeout_seconds: int = 20,
) -> FencedESRound:
    """Run ONE full PIT page chain after worker-owned authorization and budget.

    Caller MUST separately attest original request/tenant RBAC and all intended
    query branches. Passing authorized_indexes is not itself an RBAC check.
    The only method here that accesses ES is this explicitly invoked function.
    It does not call complete_round, LLM or ReportJobWorker.

    PIT open consumes one admission; each search page uses a fresh PageTicket
    and ES budget admission. PIT close is mandatory cleanup even if a budget
    or ES error occurred. Errors cancel coordinator and never pass partial
    hits into the Evidence or Word pipeline.
    """
    if (type(coordinator) is not AdaptiveRequestCoordinator
            or type(constraints) is not QueryConstraints
            or coordinator._constraints is not constraints
            or type(authorized_indexes) is not tuple
            or not set(constraints.allowed_indexes).issubset(set(authorized_indexes))
            or any(type(index) is not str for index in authorized_indexes)
            or type(page_size) is not int or not 1 <= page_size <= 100
            or type(max_pages) is not int or not 1 <= max_pages <= 24
            or type(request_timeout_seconds) is not int
            or not 1 <= request_timeout_seconds <= 30
            or not all(callable(getattr(client, method, None))
                       for method in ("options", "open_point_in_time",
                                      "search", "close_point_in_time"))):
        raise LiveRoundESFailure("untrusted_es_adapter_context")

    # Fixed fields, mandatory entities and analysis-date semantics are not
    # supported by this first transport slice. Reject rather than silently
    # dropping a user-specified hard scope. Never turn a date into importDT.
    if (constraints.fixed_fields or constraints.required_entities
            or constraints.analysis_date.source != "none"):
        raise LiveRoundESFailure("unsupported_es_hard_scope")

    round_number = coordinator.safe_progress()["round"]
    if plan is None:
        if round_number != 1:
            raise LiveRoundESFailure("missing_next_round_strategy")
        optional_terms: tuple[str, ...] = ()
    else:
        if (type(plan) is not BoundNextRoundPlan
                or plan is not coordinator._approved_plan
                or plan.constraints is not constraints
                or plan.round_number != round_number
                or round_number < 2):
            raise LiveRoundESFailure("untrusted_next_round_strategy")
        try:
            optional_terms = _list_of_terms(
                list(plan.optional_terms), limit=8, max_chars=100)
            aspects = _list_of_terms(
                list(plan.target_aspects), limit=5, max_chars=120)
            if not optional_terms or not aspects:
                raise ValueError("missing_terms")
        except Exception:
            raise LiveRoundESFailure("untrusted_next_round_strategy") from None

    fence = RoundESPageFence(
        coordinator=coordinator, constraints=constraints,
        round_number=round_number, page_size=page_size, max_pages=max_pages,
    )
    # Validate the complete DSL before admitting any ES IO.
    try:
        base_query = _query(
            constraints, optional_terms=optional_terms,
            page_size=page_size,
        )
    except Exception:
        raise LiveRoundESFailure("invalid_es_query_builder") from None

    pit_id: str | None = None
    error: str | None = None
    result: FencedESRound | None = None
    try:
        # Account for PIT-open as an ES IO, not merely metadata. Each page
        # independently claims a second nonrefundable slot before search.
        if not coordinator.admit_es_call():
            raise LiveRoundESFailure("es_retrieval_budget_exhausted")
        pit_resp = _response(client.options(
            request_timeout=_timeout(coordinator, request_timeout_seconds),
            max_retries=0, retry_on_timeout=False, retry_on_status=(),
        ).open_point_in_time(
            index=",".join(constraints.allowed_indexes),
            keep_alive="1m", ignore_unavailable=False,
            # Requires Elasticsearch Python client/server supporting PIT
            # allow_partial_search_results=False (8.17+). Fail closed on
            # older versions; never create a PIT with missing shards.
            allow_partial_search_results=False,
        ))
        pit_id = _pit(pit_resp.get("id"))

        while True:
            ticket = fence.begin_page()
            body = dict(base_query)
            body["pit"] = {"id": pit_id, "keep_alive": "1m"}
            if ticket.search_after is not None:
                body["search_after"] = list(ticket.search_after)
            response = _response(client.options(
                request_timeout=_timeout(coordinator, request_timeout_seconds),
                max_retries=0, retry_on_timeout=False, retry_on_status=(),
            ).search(
                body=body, allow_partial_search_results=False,
            ))
            next_id = response.get("pit_id")
            if next_id is not None:
                pit_id = _pit(next_id)
            if fence.submit_page(ticket, response):
                result = FencedESRound(
                    hits=fence.take_complete_hits(), audit=fence.safe_audit())
                break
    except (PageFenceError, LiveRoundESFailure):
        error = "es_pit_page_chain_unverified"
    except Exception:
        error = "es_transport_unverified"
    finally:
        # The cleanup request never consumes a new search admission; PIT close
        # is required to avoid leaking ES server search contexts on failures.
        coordinator.cancel() if error is not None else None
        if pit_id is not None:
            try:
                closed = _response(client.options(
                    request_timeout=min(5, request_timeout_seconds),
                    max_retries=0, retry_on_timeout=False, retry_on_status=(),
                ).close_point_in_time(id=pit_id))
                if closed.get("succeeded") is not True:
                    raise LiveRoundESFailure("es_pit_cleanup_unverified")
            except Exception:
                # A failed PIT-close cannot authorize or complete anything;
                # report the cleanup failure instead of asserting full health.
                error = "es_pit_cleanup_unverified"
        if error is not None:
            coordinator.cancel()

    if error is not None or result is None:
        raise LiveRoundESFailure(error or "es_pit_page_chain_unverified")
    return result
