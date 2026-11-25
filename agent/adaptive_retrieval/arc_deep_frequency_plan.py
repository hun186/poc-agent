"""Offline ARC A3b deep-report frequency query construction.

Not an ES admission, owner authorization, PIT operation or retrieval receipt.
A future transport must preserve the frozen plan's owner/deadline gates and
PIT identity lifecycle.
"""
from __future__ import annotations

from agent.es.arc_frequency_plan import build_frequency_plan
from .es_pit_adapter import _required_entity_filter
from .round_query_execution import FrozenSingleQueryPlan


def build_deep_frequency_plan(plan: FrozenSingleQueryPlan) -> dict | None:
    """Count-only plan from the active immutable retrieval scope; no IO.

    Use original canonical semantic groups, never planner-added terms or
    arbitrary DSL. Preserve original date and required entity predicates,
    not the relevance shoulds. The body is private and must not be logged.
    """
    if type(plan) is not FrozenSingleQueryPlan:
        return None
    coordinator = plan.coordinator
    constraints = plan.constraints
    progress = coordinator.safe_progress()
    if (coordinator._constraints is not constraints
            or plan.branch_code != "CANONICAL_MAIN"
            or progress["phase"] != "SEARCHING"
            or progress["round"] != plan.round_number
            or not set(constraints.allowed_indexes).issubset(plan.authorized_indexes)
            or (plan.round_number == 1 and plan.next_round_plan is not None)
            or (plan.round_number > 1 and (
                plan.next_round_plan is None
                or coordinator._approved_plan is not plan.next_round_plan))
            or constraints.fixed_fields
            or constraints.analysis_date.source != "none"
            or constraints.event_date.source == "none"):
        return None
    body = build_frequency_plan(
        [set(group) for group in coordinator._groups],
        date_from=constraints.event_date.start,
        date_to=constraints.event_date.end,
    )
    if body is None:
        return None
    if constraints.required_entities:
        body["query"]["bool"]["filter"].append({"bool": {
            "should": [_required_entity_filter(entity)
                       for entity in constraints.required_entities],
            "minimum_should_match": 1,
        }})
    return body
