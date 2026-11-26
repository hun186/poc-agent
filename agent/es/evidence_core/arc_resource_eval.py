"""Offline paired measured resource comparison, independent of quality metrics.

Inputs are operator-observed measurements for two attempts at the same case
and measurement boundary, not ARC reservations or inferred token counts.
Missing observations remain null; failed attempts are not silently dropped.
No provider, timer, production decision, or source identity is involved.
"""
from __future__ import annotations

from .arc_semantic_eval import MAX_CASES, _ratio

METRICS = ("elapsed_ms", "es_calls", "llm_calls", "prompt_tokens", "completion_tokens")
_STATUSES = ("completed", "failed", "timed_out", "cancelled")
_LIMIT = 10**12


def _nearest_rank(values, percentile):
    if not values:
        return None
    return sorted(values)[(len(values) * percentile + 99) // 100 - 1]


def _summary(cases):
    output = {}
    for metric in METRICS:
        pairs = [(c["baseline"][metric], c["candidate"][metric]) for c in cases
                 if c["baseline"][metric] is not None and c["candidate"][metric] is not None]
        baseline = [a for a, _ in pairs]
        candidate = [b for _, b in pairs]
        delta = [b-a for a, b in pairs]
        n = len(pairs)
        output[metric] = {
            "paired_cases": n,
            "missing_baseline": sum(c["baseline"][metric] is None for c in cases),
            "missing_candidate": sum(c["candidate"][metric] is None for c in cases),
            "baseline_total": sum(baseline) if n else None,
            "candidate_total": sum(candidate) if n else None,
            "delta_total": sum(delta) if n else None,
            "relative_delta": _ratio(sum(delta), sum(baseline)),
            "baseline_p50": _nearest_rank(baseline, 50),
            "candidate_p50": _nearest_rank(candidate, 50),
            "baseline_p95": _nearest_rank(baseline, 95),
            "candidate_p95": _nearest_rank(candidate, 95),
            "paired_delta_p50": _nearest_rank(delta, 50),
            "paired_delta_p95": _nearest_rank(delta, 95),
            "candidate_higher_cases": sum(d > 0 for d in delta),
            "candidate_lower_cases": sum(d < 0 for d in delta),
        }
    return output


def evaluate_resource_cases(cases):
    """Compare all measured attempts and the jointly completed subset.

    Exactly baseline/candidate per case, each with status and every metric.
    Null means unmeasured, not zero. All counts are actual observed values,
    not reserved budgets. Completion status is operator-supplied. The
    evaluator cannot attest actual instrumentation or equal workload.
    """
    if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
        return None
    matrix = {s: dict.fromkeys(_STATUSES, 0) for s in _STATUSES}
    completed = []
    for case in cases:
        if type(case) is not dict or set(case) != {"baseline", "candidate"}:
            return None
        for arm in ("baseline", "candidate"):
            row = case[arm]
            if (type(row) is not dict or set(row) != {"status", *METRICS}
                    or type(row["status"]) is not str or row["status"] not in _STATUSES
                    or any(v is not None and (type(v) is not int or not 0 <= v <= _LIMIT)
                           for v in (row[k] for k in METRICS))):
                return None
        a, b = case["baseline"]["status"], case["candidate"]["status"]
        matrix[a][b] += 1
        if a == b == "completed":
            completed.append(case)
    return {
        "schema": "sraf_arc_resource_paired_eval_v1",
        "scope": "operator_measured_paired_attempts_not_reservations",
        "cases": len(cases),
        "status_transitions": matrix,
        "both_completed_cases": len(completed),
        "all_attempts": _summary(cases),
        "both_completed": _summary(completed),
    }
