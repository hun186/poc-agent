"""Optional same-PIT count-only A3b observation after canonical pages.

Only the strict adapter calls this private helper, with the exact frozen
plan and owner binding. It cannot open a PIT or alter canonical Evidence.
"""
from __future__ import annotations

import logging
import json
import os
import re

from agent.es.arc_frequency_plan import parse_frequency_response
from .arc_deep_frequency_plan import build_deep_frequency_plan
from .es_pit_adapter import _pit, _response, _timeout
from .round_query_execution import FrozenSingleQueryPlan
from .worker_scope_binding import WorkerScopeBinding

_LOG = logging.getLogger("sraf.arc.deep_frequency")
_INDEX = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
MAX_COUNT = 2**63 - 1


def deep_frequency_enabled():
    return os.getenv("SRAF_ARC_DEEP_FREQUENCY") == "shadow"


def observe_same_pit_frequency(*, plan, binding, fence, client, pit_id,
                               canonical_body, request_timeout_seconds):
    """Return latest known PIT identity and a private count-only observation.

    The adapter retains cleanup ownership. Malformed replacement PIT IDs
    propagate as a hard cleanup uncertainty, rather than falsely certifying
    the previous identity as current. Other optional failures abstain.
    """
    from agent.external_capabilities import requirement_acceptance_active

    if (not deep_frequency_enabled()
            or type(plan) is not FrozenSingleQueryPlan
            or type(binding) is not WorkerScopeBinding
            or requirement_acceptance_active()):
        return pit_id, None
    record = {"schema": "sraf_arc_deep_frequency_shadow_v1",
              "scope": "same_round_pit_root_documents_with_candidate_date_and_entity_filter",
              "status": "unavailable"}
    try:
        indexes = plan.constraints.allowed_indexes
        if (len(indexes) != 1 or not _INDEX.fullmatch(indexes[0])
                or ".." in indexes[0]
                or indexes[0] != os.getenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX")):
            record["status"] = "unverified_mapping_scope"
            return pit_id, record
        body = build_deep_frequency_plan(plan)
        if (body is None
                or body["query"]["bool"]["filter"] !=
                   canonical_body["query"]["function_score"]["query"]["bool"]["filter"]):
            record["status"] = "unsupported_scope"
            return pit_id, record
        group_count = len(plan.coordinator._groups)
        if not binding.admit_optional_frequency(plan, fence):
            record["status"] = "not_admitted"
            return pit_id, record
        progress = plan.coordinator.safe_progress()
        if progress["phase"] != "SEARCHING" or progress["round"] != plan.round_number:
            record["status"] = "not_current"
            return pit_id, record
        body["pit"] = {"id": pit_id, "keep_alive": "1m"}
        response = _response(client.options(
            request_timeout=_timeout(plan.coordinator, min(3, request_timeout_seconds)),
            max_retries=0, retry_on_timeout=False, retry_on_status=(),
        ).search(body=body, allow_partial_search_results=False))
    except Exception:
        # The last known PIT still needs cleanup; transport errors do not
        # create evidence or trigger retries.
        return pit_id, record

    # MUST update identity before parsing count results, including partial
    # responses. Do not swallow malformed returned replacement IDs.
    if "pit_id" in response:
        pit_id = _pit(response["pit_id"])
    try:
        if ("_clusters" in response
                or response.get("is_partial", False) is not False
                or response.get("hits", {}).get("hits") != []):
            record["status"] = "incomplete"
            return pit_id, record
        observation = parse_frequency_response(response, group_count=group_count)
        if (observation["status"] != "exact_es_query_counts"
                or observation["eligible_documents"] > MAX_COUNT):
            record["status"] = "incomplete"
            return pit_id, record
        record.update(status="observed_counts",
                      eligible_documents=observation["eligible_documents"],
                      groups=observation["groups"])
    except Exception:
        record["status"] = "incomplete"
    return pit_id, record


def log_same_pit_frequency(record, *, plan, binding):
    """Publish counts only after cleanup and fresh owner/frequency permission."""
    if record is None:
        return
    if record["status"] == "observed_counts":
        if not binding.recheck_optional_frequency(plan):
            record = {"schema": record["schema"], "scope": record["scope"],
                      "status": "authorization_or_deadline_changed"}
    _LOG.warning("SRAF_ARC_DEEP_FREQUENCY=%s",
                 json.dumps(record, sort_keys=True, separators=(",", ":")))
