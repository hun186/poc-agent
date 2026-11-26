"""Private offline A5 replay of the actual strict-prefix counterfactual.

The operator supplies already date/topic-validated rows from one frozen
primary result. No ES, LLM, evidence mutation, or production selection.
The input cannot attest real snapshot identity or source/date eligibility.
"""
from __future__ import annotations

from .arc_tighten_shadow import (
    _compare_tightening, CandidatePressure, MIN_CANDIDATE_TOTAL, MIN_STRICT,
    MAX_ROWS, MAX_CHARS, MAX_ROW_CHARS,
)
from .arc_selection_eval import evaluate_selection_cases
from .arc_semantic_eval import MAX_CASES, MAX_TOTAL_ROWS
from .models import EvidenceSnippet
from .question_anchor import derive_explicit_question_anchor
from .cross_language_alias import alias_matches
from ..arc_request_budget import ArcRequestBudget, bind_arc_budget

_CASE_KEYS = {"groups", "question", "pressure", "local_frequency", "native_frequency", "rows"}
_ROW_KEYS = {"text", "source", "group_hits", "weak", "gold"}
_MAX_TOTAL_CHARS = 1048576


def replay_tightening_cases(cases):
    """Aggregate each applicable strategy separately, without missing-as-zero."""
    if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
        return None
    total_rows = total_chars = 0
    paired = {}
    floor_counts = {}
    for case in cases:
        if type(case) is not dict or set(case) != _CASE_KEYS:
            return None
        groups, question, pressure, rows = (
            case["groups"], case["question"], case["pressure"], case["rows"])
        local, native = case["local_frequency"], case["native_frequency"]
        if (type(groups) is not list or not 4 <= len(groups) <= 16
                or any(type(g) is not list or not 1 <= len(g) <= 32
                       or any(type(t) is not str or not 0 < len(t) <= 160 or not t.strip() for t in g)
                       or len(set(g)) != len(g) for g in groups)
                or sum(map(len, groups)) > 64
                or type(question) is not str or not 0 < len(question) <= 8192
                or type(pressure) is not dict or set(pressure) != {"relation", "total", "returned"}
                or pressure["relation"] not in ("eq", "gte")
                or type(pressure["total"]) is not int
                or type(pressure["returned"]) is not int
                or not MIN_CANDIDATE_TOTAL <= pressure["total"] <= 2**63 - 1
                or not 1 <= pressure["returned"] <= pressure["total"]
                or (local is not None and type(local) is not dict)
                or (native is not None and type(native) is not dict)
                or type(rows) is not list or not MIN_STRICT <= len(rows) <= MAX_ROWS):
            return None
        groups = [set(g) for g in groups]
        anchor = derive_explicit_question_anchor(question, groups)
        if anchor is None:
            return None
        total_rows += len(rows)
        if total_rows > MAX_TOTAL_ROWS:
            return None
        evidence, anchors = [], []
        chars = 0
        for row in rows:
            if type(row) is not dict or set(row) != _ROW_KEYS:
                return None
            text, source, hits, weak = row["text"], row["source"], row["group_hits"], row["weak"]
            if (type(text) is not str or not 0 < len(text) <= MAX_ROW_CHARS or not text.strip()
                    or type(source) is not int or not 0 <= source < pressure["returned"]
                    or source >= 2**31
                    or type(hits) is not int or not 3 <= hits <= len(groups)
                    or type(weak) is not bool or type(row["gold"]) is not str
                    or row["gold"] not in ("relevant", "uncertain", "unrelated")):
                return None
            chars += len(text)
            if chars > MAX_CHARS or total_chars + chars > _MAX_TOTAL_CHARS:
                return None
            evidence.append(EvidenceSnippet(uuid="", text=text, date_iso="", article_date_iso="",
                            source_hit_ordinal=source, group_hits=hits, weak_evidence=weak,
                            match_policy="strict"))
            anchors.append(alias_matches(anchor.literal, text))
        total_chars += chars
        positions = {}
        budget = ArcRequestBudget()
        try:
            with bind_arc_budget((budget, 1)):
                observation = _compare_tightening(
                    evidence, groups, original_question=question,
                    pressure=CandidatePressure(**pressure), local_frequency=local,
                    native_frequency=native, _offline_selections=positions)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
            return None
        finally:
            budget.seal()
        if observation["status"] != "observed_tightening" or not positions:
            return None
        for strategy in observation["strategies"]:
            name = strategy["strategy"]
            selected = positions[name]
            ranks = {i: rank for rank, i in enumerate(selected, 1)}
            paired.setdefault(name, []).append([
                {"ordinal": i+1, "source": row["source"], "gold": row["gold"],
                 "direct_anchor": anchors[i], "strong": not row["weak"],
                 "baseline_rank": i+1, "candidate_rank": ranks.get(i)}
                for i, row in enumerate(rows)
            ])
            floor_counts[name] = floor_counts.get(name, 0) + int(strategy["sample_floor_met"])
    results = {}
    for name, fixtures in paired.items():
        metrics = evaluate_selection_cases(fixtures)
        if metrics is None:
            return None
        results[name] = {"applicable_cases": len(fixtures),
                         "sample_floor_met_cases": floor_counts[name],
                         "comparison": metrics}
    return {"schema": "sraf_arc_tightening_replay_v1",
            "scope": "operator_frozen_labeled_strict_prefix_not_corpus",
            "cases": len(cases), "strategies": results}
