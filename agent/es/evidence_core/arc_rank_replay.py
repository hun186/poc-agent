"""Private offline A4 replay over an operator-frozen, labeled strict prefix.

This uses the exact production shadow rank kernel, not a second implementation.
The input is already canonical Evidence as attested by the operator; this
module cannot certify provenance, snapshot identity, date checks, or labels.
No ES, LLM, production selection, or per-row output.
"""
from __future__ import annotations

from .arc_rank_shadow import _compare_rank, MAX_ROWS, MAX_ROW_CHARS, MAX_CHARS, TOP_K
from .arc_selection_eval import evaluate_selection_cases
from .arc_semantic_eval import MAX_CASES, MAX_TOTAL_ROWS
from .models import EvidenceSnippet
from ..arc_request_budget import ArcRequestBudget, bind_arc_budget

_MAX_TOTAL_CHARS = 1048576
_CASE_KEYS = {"groups", "frequency", "rows"}
_ROW_KEYS = {"text", "source", "group_hits", "weak", "direct_anchor", "gold"}


def replay_rank_cases(cases):
    if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
        return None
    total_rows = total_chars = 0
    paired = []
    scope_counts = {}
    for case in cases:
        if type(case) is not dict or set(case) != _CASE_KEYS:
            return None
        groups, frequency, rows = case["groups"], case["frequency"], case["rows"]
        if (type(groups) is not list or not 1 <= len(groups) <= 16
                or any(type(g) is not list or not 1 <= len(g) <= 64
                       or any(type(t) is not str or not 0 < len(t) <= 160 for t in g)
                       or len(set(g)) != len(g) for g in groups)
                or sum(map(len, groups)) > 64
                or type(frequency) is not dict
                or type(rows) is not list or not TOP_K < len(rows) <= MAX_ROWS):
            return None
        total_rows += len(rows)
        if total_rows > MAX_TOTAL_ROWS:
            return None
        evidence = []
        chars = 0
        for row in rows:
            if type(row) is not dict or set(row) != _ROW_KEYS:
                return None
            text, source, hits, weak = row["text"], row["source"], row["group_hits"], row["weak"]
            if (type(text) is not str or not 0 < len(text) <= MAX_ROW_CHARS or not text.strip()
                    or type(source) is not int or not 0 <= source < 2**31
                    or type(hits) is not int or not 1 <= hits <= len(groups)
                    or type(weak) is not bool or type(row["direct_anchor"]) is not bool
                    or type(row["gold"]) is not str
                    or row["gold"] not in ("relevant", "unrelated", "uncertain")):
                return None
            chars += len(text)
            if chars > MAX_CHARS or total_chars + chars > _MAX_TOTAL_CHARS:
                return None
            evidence.append(EvidenceSnippet(uuid="", text=text, date_iso="", article_date_iso="",
                            source_hit_ordinal=source, group_hits=hits, weak_evidence=weak,
                            match_policy="strict"))
        total_chars += chars
        order = []
        budget = ArcRequestBudget()
        try:
            with bind_arc_budget((budget, 1)):
                observation = _compare_rank(evidence, [set(g) for g in groups],
                                            frequency, _offline_order=order)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
            return None
        finally:
            budget.seal()
        if observation["status"] != "observed_rank" or len(order) != len(rows):
            return None
        scope = observation["scope"]
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
        candidate_ranks = {i: rank for rank, i in enumerate(order, 1)}
        paired.append([
            {"ordinal": i + 1, "source": row["source"], "gold": row["gold"],
             "direct_anchor": row["direct_anchor"], "strong": not row["weak"],
             "baseline_rank": i + 1, "candidate_rank": candidate_ranks[i]}
            for i, row in enumerate(rows)
        ])
    result = evaluate_selection_cases(paired)
    if result is None:
        return None
    return {"schema": "sraf_arc_rank_replay_v1",
            "scope": "operator_frozen_labeled_strict_prefix_not_corpus",
            "frequency_scope_cases": scope_counts, "comparison": result}
