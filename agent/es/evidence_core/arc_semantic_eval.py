"""A9 offline paired-label evaluation for A8 semantic-review counterfactuals.

Operator-supplied, privately labeled cases only. No model calls, Evidence
text, retrieval changes, or production removal decision. The live A8
count-only observations cannot be reconstructed as per-row predictions.
"""
from __future__ import annotations

from collections import Counter

MAX_CASES = 32
MAX_CASE_ROWS = 256
MAX_TOTAL_ROWS = 4096
_LABELS = frozenset({"relevant", "uncertain", "unrelated"})


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def evaluate_semantic_cases(cases):
    """Compare keep-all with hypothetical drop-model-unrelated on paired rows.

    Each case is a list of local ordinal rows: source, gold, predicted,
    direct_anchor, strong. Source ordinal is local to that case, not an
    application UUID. Prediction/gold uncertainty is explicit; missing
    predictions invalidate the fixture rather than count as negative.
    No identifiers, text or per-row verdicts are returned.
    """
    if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
        return None
    if any(type(case) is not list or not 1 <= len(case) <= MAX_CASE_ROWS for case in cases):
        return None
    if sum(map(len, cases)) > MAX_TOTAL_ROWS:
        return None
    matrix = {g: dict.fromkeys(sorted(_LABELS), 0) for g in sorted(_LABELS)}
    counts = Counter()
    for case in cases:
        seen = set()
        relevant_sources = set()
        retained_relevant_sources = set()
        all_sources = set()
        retained_sources = set()
        for row in case:
            if type(row) is not dict or set(row) != {
                    "ordinal", "source", "gold", "predicted", "direct_anchor", "strong"}:
                return None
            ordinal, source = row["ordinal"], row["source"]
            gold, predicted = row["gold"], row["predicted"]
            if (type(ordinal) is not int or not 1 <= ordinal <= MAX_CASE_ROWS
                    or ordinal in seen or type(source) is not int or not 0 <= source < 2**31
                    or type(gold) is not str or gold not in _LABELS
                    or type(predicted) is not str or predicted not in _LABELS
                    or type(row["direct_anchor"]) is not bool or type(row["strong"]) is not bool):
                return None
            seen.add(ordinal)
            all_sources.add(source)
            matrix[gold][predicted] += 1
            counts["rows"] += 1
            keep = predicted != "unrelated"
            if keep:
                counts["retained"] += 1
                retained_sources.add(source)
            if gold == "relevant":
                relevant_sources.add(source)
                if keep:
                    retained_relevant_sources.add(source)
                if row["direct_anchor"]:
                    counts["gold_relevant_anchor"] += 1
                    counts["lost_relevant_anchor"] += int(not keep)
                if row["strong"]:
                    counts["gold_relevant_strong"] += 1
                    counts["lost_relevant_strong"] += int(not keep)
        # Source coverage is summed per case, never merged across queries.
        counts["all_sources"] += len(all_sources)
        counts["retained_sources"] += len(retained_sources)
        counts["relevant_sources"] += len(relevant_sources)
        counts["lost_relevant_sources"] += len(relevant_sources - retained_relevant_sources)
        counts["cases_with_relevant_source_loss"] += int(bool(relevant_sources - retained_relevant_sources))
    relevant = sum(matrix["relevant"].values())
    unrelated = sum(matrix["unrelated"].values())
    uncertain = sum(matrix["uncertain"].values())
    lost = matrix["relevant"]["unrelated"]
    removed_unrelated = matrix["unrelated"]["unrelated"]
    removed_uncertain = matrix["uncertain"]["unrelated"]
    retained_relevant = relevant - lost
    retained_labeled = relevant + unrelated - lost - removed_unrelated
    return {
        "schema": "sraf_arc_semantic_paired_eval_v1",
        "scope": "operator_labeled_paired_candidate_rows_not_corpus",
        "cases": len(cases),
        "rows": counts["rows"],
        "gold_counts": {"relevant": relevant, "unrelated": unrelated, "uncertain": uncertain},
        "confusion": matrix,
        "baseline": {"retained": counts["rows"],
                     "known_label_precision": _ratio(relevant, relevant + unrelated)},
        "counterfactual": {
            "retained": counts["retained"],
            "removed": counts["rows"] - counts["retained"],
            "known_label_precision": _ratio(retained_relevant, retained_labeled),
            "relevant_retention": _ratio(retained_relevant, relevant),
            "false_removal_rate": _ratio(lost, relevant),
            "unrelated_removal_rate": _ratio(removed_unrelated, unrelated),
            "uncertain_gold_removed": removed_uncertain,
            "uncertain_gold_removal_rate": _ratio(removed_uncertain, uncertain),
            "anchor_relevant_false_removal": _ratio(counts["lost_relevant_anchor"], counts["gold_relevant_anchor"]),
            "strong_relevant_false_removal": _ratio(counts["lost_relevant_strong"], counts["gold_relevant_strong"]),
            "source_retention": _ratio(counts["retained_sources"], counts["all_sources"]),
            "relevant_source_loss": _ratio(counts["lost_relevant_sources"], counts["relevant_sources"]),
            "cases_with_relevant_source_loss": counts["cases_with_relevant_source_loss"],
        },
        "model_uncertain": sum(matrix[g]["uncertain"] for g in _LABELS),
    }
