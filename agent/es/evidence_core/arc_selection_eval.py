"""A9 paired selection/ranking evaluation over a fixed labeled universe.

An operator supplies the union of both arms (and optionally other labeled
candidates from the same snapshot). This module cannot attest completeness,
snapshot identity, label quality, or eligibility of real ES documents.
No production filter, model, raw evidence or network access.
"""
from __future__ import annotations

from collections import Counter

from .arc_semantic_eval import MAX_CASES, MAX_CASE_ROWS, MAX_TOTAL_ROWS, _ratio

_LABELS = frozenset({"relevant", "uncertain", "unrelated"})
_KEYS = frozenset({"ordinal", "source", "gold", "direct_anchor", "strong",
                   "baseline_rank", "candidate_rank"})


def _measure(cases, limit):
    totals = Counter()
    arm_counts = {"baseline": Counter(), "candidate": Counter()}
    for case in cases:
        gold_relevant_sources = {r["source"] for r in case if r["gold"] == "relevant"}
        totals["relevant_sources"] += len(gold_relevant_sources)
        totals["gold_relevant"] += sum(r["gold"] == "relevant" for r in case)
        selected = {}
        relevant_sources = {}
        for arm, counts in arm_counts.items():
            rows = [r for r in case if r[arm + "_rank"] is not None
                    and (limit is None or r[arm + "_rank"] <= limit)]
            selected[arm] = {r["ordinal"] for r in rows}
            relevant_sources[arm] = {r["source"] for r in rows if r["gold"] == "relevant"}
            counts["sources"] += len({r["source"] for r in rows})
            counts["relevant_sources"] += len(relevant_sources[arm])
            for row in rows:
                counts[row["gold"]] += 1
                if row["gold"] == "relevant":
                    counts["relevant_anchor"] += int(row["direct_anchor"])
                    counts["relevant_strong"] += int(row["strong"])
        lost = selected["baseline"] - selected["candidate"]
        added = selected["candidate"] - selected["baseline"]
        relevant_lost = False
        for row in case:
            if row["ordinal"] in lost:
                totals["removed_" + row["gold"]] += 1
                if row["gold"] == "relevant":
                    relevant_lost = True
                    totals["removed_relevant_anchor"] += int(row["direct_anchor"])
                    totals["removed_relevant_strong"] += int(row["strong"])
            if row["ordinal"] in added:
                totals["added_" + row["gold"]] += 1
        totals["cases_with_relevant_loss"] += int(relevant_lost)
        source_loss = relevant_sources["baseline"] - relevant_sources["candidate"]
        totals["lost_relevant_sources"] += len(source_loss)
        totals["gained_relevant_sources"] += len(relevant_sources["candidate"] - relevant_sources["baseline"])
        totals["cases_with_relevant_source_loss"] += int(bool(source_loss))

    def arm_summary(c):
        return {
            "selected": sum(c[label] for label in _LABELS),
            "gold_counts": {label: c[label] for label in sorted(_LABELS)},
            "known_label_precision": _ratio(c["relevant"], c["relevant"] + c["unrelated"]),
            "labeled_universe_relevant_coverage": _ratio(c["relevant"], totals["gold_relevant"]),
            "sources": c["sources"],
            "relevant_sources": c["relevant_sources"],
            "labeled_universe_relevant_source_coverage": _ratio(c["relevant_sources"], totals["relevant_sources"]),
        }

    base = arm_counts["baseline"]
    candidate = arm_counts["candidate"]
    return {
        "baseline": arm_summary(base),
        "candidate": arm_summary(candidate),
        "removed": {label: totals["removed_" + label] for label in sorted(_LABELS)},
        "added": {label: totals["added_" + label] for label in sorted(_LABELS)},
        "net_relevant_change": candidate["relevant"] - base["relevant"],
        "baseline_relevant_loss": _ratio(totals["removed_relevant"], base["relevant"]),
        "baseline_relevant_anchor_loss": _ratio(totals["removed_relevant_anchor"], base["relevant_anchor"]),
        "baseline_relevant_strong_loss": _ratio(totals["removed_relevant_strong"], base["relevant_strong"]),
        "baseline_relevant_source_loss": _ratio(totals["lost_relevant_sources"], base["relevant_sources"]),
        "gained_relevant_sources": totals["gained_relevant_sources"],
        "cases_with_relevant_loss": totals["cases_with_relevant_loss"],
        "cases_with_relevant_source_loss": totals["cases_with_relevant_source_loss"],
    }


def evaluate_selection_cases(cases):
    """Validate full local ranks and calculate full-arm and top-20 comparisons.

    None rank = not selected. Both arms may select zero rows. Every selected
    rank must be unique and contiguous in its own case/arm. Each ordinal
    denotes one paired passage; no content or IDs may appear in input/output.
    Missing or uncertain labels cannot silently become unrelated.
    """
    if (type(cases) is not list or not 1 <= len(cases) <= MAX_CASES
            or any(type(case) is not list or not 1 <= len(case) <= MAX_CASE_ROWS
                   for case in cases)
            or sum(map(len, cases)) > MAX_TOTAL_ROWS):
        return None
    for case in cases:
        seen = set()
        ranks = {"baseline_rank": set(), "candidate_rank": set()}
        for row in case:
            if type(row) is not dict or set(row) != _KEYS:
                return None
            ordinal, source, gold = row["ordinal"], row["source"], row["gold"]
            if (type(ordinal) is not int or not 1 <= ordinal <= MAX_CASE_ROWS
                    or ordinal in seen or type(source) is not int or not 0 <= source < 2**31
                    or type(gold) is not str or gold not in _LABELS
                    or type(row["direct_anchor"]) is not bool or type(row["strong"]) is not bool):
                return None
            seen.add(ordinal)
            for key, values in ranks.items():
                rank = row[key]
                if rank is None:
                    continue
                if type(rank) is not int or not 1 <= rank <= len(case) or rank in values:
                    return None
                values.add(rank)
        if any(values != set(range(1, len(values) + 1)) for values in ranks.values()):
            return None
    return {
        "schema": "sraf_arc_selection_paired_eval_v1",
        "scope": "operator_labeled_fixed_universe_not_corpus",
        "cases": len(cases),
        "rows": sum(map(len, cases)),
        "full_selection": _measure(cases, None),
        "top_20": _measure(cases, 20),
    }
