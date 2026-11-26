"""ARC A3b optional ordinary-report native frequency observation.

Never authorize search, modify Evidence, or expose counts to the model. An
operator must explicitly approve one concrete index for corpus statistics and
attest its mapping/analyzer. A completed primary search is an additional
runtime fence, not a substitute for tenant authorization.
"""
from __future__ import annotations

import json
import logging
import os
import re

from elasticsearch import Elasticsearch

from .arc_frequency_plan import build_frequency_plan, parse_frequency_response
from .arc_request_budget import ArcUnits, current_arc_budget
from .arc_native_rank_receipt import NativeRankFrequency
from .ordinary_scope_receipt import current_ordinary_scope_capture

_LOG = logging.getLogger("sraf.arc.es_frequency")
_INDEX = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")


def native_frequency_enabled() -> bool:
    return os.getenv("SRAF_ARC_ES_FREQUENCY") == "shadow"


def _primary_scope_verified(index, body, response, plan) -> bool:
    # No alias, wildcard, remote cluster, empty hit or partial proof.
    if (type(index) is not str or not _INDEX.fullmatch(index)
            or ".." in index
            or index != os.getenv("SRAF_ARC_ES_FREQUENCY_VERIFIED_INDEX")):
        return False
    try:
        if (type(response) is not dict or response.get("timed_out") is not False
                or response.get("terminated_early", False) is not False
                or "_clusters" in response):
            return False
        shards = response["_shards"]
        total, successful, failed = (shards[k] for k in ("total", "successful", "failed"))
        if (any(type(v) is not int for v in (total, successful, failed))
                or total <= 0 or successful != total or failed != 0):
            return False
        hits = response["hits"]["hits"]
        if (type(hits) is not list or not hits
                or any(type(h) is not dict or h.get("_index") != index for h in hits)):
            return False
        # Reuse precisely the primary root filter list. Do not silently
        # drop a future owner/tenant or other required filter.
        query = body["query"]["function_score"]["query"]["bool"]
        # Conjunction order is immaterial; preserve multiplicity and every
        # nested predicate, rather than comparing sets or dropping filters.
        if type(query) is not dict or set(query) != {"filter", "should", "minimum_should_match"}:
            return False
        if type(query["minimum_should_match"]) is not int or query["minimum_should_match"] != 1:
            return False
        primary = query["filter"]
        expected = plan["query"]["bool"]["filter"]
        if type(primary) is not list or len(primary) != len(expected):
            return False
        def canonical(filters):
            return sorted(json.dumps(f, sort_keys=True, separators=(",", ":"), allow_nan=False)
                          for f in filters)
        return canonical(primary) == canonical(expected)
    except (KeyError, TypeError, ValueError):
        return False


def observe_native_frequency(
    client, *, index, ordinary_body, ordinary_response,
    groups, date_from, date_to, must_high_value, must_selected,
    receipt_sink: list[NativeRankFrequency] | None = None,
) -> None:
    """At most one extra SDK search; no retry; fail closed to a count-only log."""
    if not native_frequency_enabled():
        return
    status = "unavailable"
    observation = None
    try:
        from agent.external_capabilities import requirement_acceptance_active
        # Never interfere with E2E or the automatic deep-admission receipt.
        if (requirement_acceptance_active()
                or current_ordinary_scope_capture() is not None
                or type(client) is not Elasticsearch):
            status = "unsupported_scope"
            return
        scope = current_arc_budget()
        if scope is None:
            status = "missing_shared_budget"
            return
        plan = build_frequency_plan(
            groups, date_from=date_from, date_to=date_to,
            must_high_value=must_high_value, must_selected=must_selected,
        )
        if plan is None or not _primary_scope_verified(
            index, ordinary_body, ordinary_response, plan,
        ):
            status = "unsupported_scope"
            return
        budget, ordinal = scope
        if not budget.reserve(ordinal, ArcUnits(es_calls=1)):
            status = "shared_budget_exhausted"
            return
        response = client.options(
            request_timeout=3, max_retries=0, retry_on_timeout=False,
        ).search(
            index=index, body=plan, allow_partial_search_results=False,
            ignore_unavailable=False, allow_no_indices=False,
            expand_wildcards="none",
        )
        raw = response if type(response) is dict else response.body
        if type(raw) is dict and "_clusters" not in raw:
            observation = parse_frequency_response(raw, group_count=len(groups))
            status = observation["status"]
            if type(receipt_sink) is list and not receipt_sink:
                receipt = NativeRankFrequency.from_observation(
                    observation, groups=groups, date_from=date_from, date_to=date_to)
                if receipt is not None:
                    receipt_sink.append(receipt)
        else:
            status = "incomplete"
    except Exception:
        # No backend text, URL, query, index, document or term in the log.
        status = "unavailable"
        observation = None
    finally:
        record = {"schema": "sraf_arc_es_frequency_shadow_v1", "status": status}
        if observation is not None:
            record["observation"] = observation
        _LOG.warning("SRAF_ARC_ES_FREQUENCY=%s",
                     json.dumps(record, sort_keys=True, separators=(",", ":")))
