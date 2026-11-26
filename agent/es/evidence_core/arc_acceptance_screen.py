"""Offline paired ARC rollout screening, not production authorization.

Every case carries the paired selection rows and paired *observed* resources
for that same case. The operator must independently establish snapshot,
workload, measurement boundary and human-label quality. This module
evaluates explicit operator policy only; it cannot change flags, query,
Evidence, model configuration or deployment.
"""
from __future__ import annotations

from collections import Counter

from .arc_selection_eval import evaluate_selection_cases
from .arc_resource_eval import METRICS, evaluate_resource_cases
from .arc_semantic_eval import MAX_CASES

_DELTA_KEYS = {
    "elapsed_ms": "max_elapsed_increase_ms",
    "es_calls": "max_es_call_increase",
    "llm_calls": "max_llm_call_increase",
    "prompt_tokens": "max_prompt_token_increase",
    "completion_tokens": "max_completion_token_increase",
}
_POLICY_KEYS = {
    "minimum_cases", "min_full_precision_delta_bps",
    "min_top20_precision_delta_bps", "min_net_relevant_gain",
    *_DELTA_KEYS.values(),
}


def _valid_policy(policy):
    return (type(policy) is dict and set(policy) == _POLICY_KEYS
            and type(policy["minimum_cases"]) is int
            and 1 <= policy["minimum_cases"] <= MAX_CASES
            and all(type(policy[k]) is int and -10000 <= policy[k] <= 10000
                    for k in ("min_full_precision_delta_bps", "min_top20_precision_delta_bps"))
            and type(policy["min_net_relevant_gain"]) is int
            and 0 <= policy["min_net_relevant_gain"] <= 4096
            and all(type(policy[k]) is int and 0 <= policy[k] <= 10**12
                    for k in _DELTA_KEYS.values()))


def _precision_meets(comp, minimum_bps):
    # Compare exact integer fractions, avoiding rounding a marginal failure
    # into a pass. Undefined known-label precision is not evidence of safety.
    a = comp["baseline"]["known_label_precision"]
    b = comp["candidate"]["known_label_precision"]
    if not a["denominator"] or not b["denominator"]:
        return None
    return ((b["numerator"] * a["denominator"] -
             a["numerator"] * b["denominator"]) * 10000
            >= minimum_bps * a["denominator"] * b["denominator"])


def screen_selection_acceptance(fixture):
    """Evaluate a deliberately conservative offline acceptance screen.

    Full-selection relevant/uncertain removals and any protected anchor,
    strong or relevant-source loss in full/top20 are hard blockers. Top20
    relevant counts must not regress per case. Precision tolerance and
    resource increases are explicit operator choices, evaluated per case.
    No average or added rows can hide a case failure. No pass grants
    production authority or certifies corpus recall.
    """
    if (type(fixture) is not dict or set(fixture) != {"policy", "cases"}
            or not _valid_policy(fixture["policy"])
            or type(fixture["cases"]) is not list
            or not 1 <= len(fixture["cases"]) <= MAX_CASES):
        return None
    policy, cases = fixture["policy"], fixture["cases"]
    if any(type(case) is not dict or set(case) != {"selection", "resources"}
           for case in cases):
        return None
    selections = [case["selection"] for case in cases]
    resources = [case["resources"] for case in cases]
    quality = evaluate_selection_cases(selections)
    resource = evaluate_resource_cases(resources)
    if quality is None or resource is None:
        return None

    blockers, incomplete = Counter(), Counter()
    if len(cases) < policy["minimum_cases"]:
        incomplete["minimum_case_count_not_met"] += 1
    if quality["full_selection"]["net_relevant_change"] < policy["min_net_relevant_gain"]:
        blockers["aggregate_relevant_gain_below_policy"] += 1
    if quality["full_selection"]["baseline"]["gold_counts"]["relevant"] == 0:
        incomplete["no_baseline_relevant_evidence"] += 1
    for case in cases:
        comparison = evaluate_selection_cases([case["selection"]])
        full, top = comparison["full_selection"], comparison["top_20"]
        if full["removed"]["relevant"]:
            blockers["full_relevant_removed"] += 1
        if full["removed"]["uncertain"]:
            blockers["full_uncertain_removed"] += 1
        if top["net_relevant_change"] < 0:
            blockers["top20_relevant_count_regressed"] += 1
        for label, comp, threshold in (
                ("full", full, policy["min_full_precision_delta_bps"]),
                ("top20", top, policy["min_top20_precision_delta_bps"])):
            for kind in ("anchor", "strong", "source"):
                if comp["baseline_relevant_" + kind + "_loss"]["numerator"]:
                    blockers[label + "_relevant_" + kind + "_loss"] += 1
            if comp["added"]["uncertain"] or comp["removed"]["uncertain"]:
                incomplete[label + "_uncertain_selection_changed"] += 1
            meets = _precision_meets(comp, threshold)
            if meets is None:
                incomplete[label + "_known_label_precision_undefined"] += 1
            elif not meets:
                blockers[label + "_precision_delta_below_policy"] += 1

        baseline, candidate = case["resources"]["baseline"], case["resources"]["candidate"]
        if baseline["status"] != "completed" or candidate["status"] != "completed":
            blockers["attempt_not_jointly_completed"] += 1
        for metric in METRICS:
            a, b = baseline[metric], candidate[metric]
            if a is None or b is None:
                incomplete[metric + "_not_measured"] += 1
            elif b - a > policy[_DELTA_KEYS[metric]]:
                blockers[metric + "_increase_above_policy"] += 1

    status = ("BLOCKED" if blockers else "INCOMPLETE" if incomplete
              else "MEETS_OFFLINE_THRESHOLDS")
    return {
        "schema": "sraf_arc_offline_acceptance_screen_v1",
        "scope": "operator_labeled_paired_selection_and_measured_resources",
        "status": status,
        "production_authorized": False,
        "cases": len(cases),
        "blockers": dict(sorted(blockers.items())),
        "incomplete": dict(sorted(incomplete.items())),
        "quality": quality, "resources": resource,
    }
