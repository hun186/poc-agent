"""Bounded local A3/A4 summaries for an already-approved A7 pilot prompt.

Never interpret parser sample frequencies as corpus DF, source truth or
semantic relevance. No scans, provider calls, ranking or query mutation here.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.arc_mode import arc_shadow_enabled


@dataclass(frozen=True)
class LocalGroupAdvisory:
    eligible_hits: int
    group_count: int
    common_groups: int
    uncommon_groups: int
    unobserved_groups: int
    sample_limited: bool
    # Optional existing A4 comparison: prefix, replacements, rarity-only
    # replacements, baseline/shadow distinct hit counts and strong counts.
    rank: tuple[int, ...] = ()
    rank_prefix_limited: bool = False

    def payload(self):
        if not arc_shadow_enabled("SRAF_ARC_GROUP_FREQUENCY"):
            return {}
        if (any(type(n) is not int for n in (self.eligible_hits,
                self.group_count, self.common_groups, self.uncommon_groups,
                self.unobserved_groups))
                or not 16 <= self.eligible_hits <= 128
                or not 1 <= self.group_count <= 16
                or any(not 0 <= n <= self.group_count for n in (
                    self.common_groups, self.uncommon_groups, self.unobserved_groups))
                or self.common_groups + self.uncommon_groups + self.unobserved_groups > self.group_count
                or type(self.sample_limited) is not bool):
            return {}
        result = {"local_group_discrimination": {
            "scope": "ordered_date_valid_parser_sample_not_corpus_df",
            "eligible_hits": self.eligible_hits,
            "group_count": self.group_count,
            "common_groups_at_least_80pct": self.common_groups,
            "uncommon_groups_positive_at_most_20pct": self.uncommon_groups,
            "unobserved_groups_not_rarity": self.unobserved_groups,
            "sample_limited": self.sample_limited}}
        if (arc_shadow_enabled("SRAF_ARC_RANK")
                and type(self.rank) is tuple and len(self.rank) == 7
                and all(type(n) is int for n in self.rank)
                and type(self.rank_prefix_limited) is bool):
            prefix, replaced, rarity, original, shadow, strong, shadow_strong = self.rank
            if (21 <= prefix <= 128 and 0 <= replaced <= min(20, prefix - 20)
                    and 0 <= rarity <= min(20, prefix - 20)
                    and 1 <= original <= 20 and 1 <= shadow <= 20
                    and 0 <= strong <= 20 and 0 <= shadow_strong <= 20):
                result["local_rank_comparison"] = {
                    "scope": "strict_prefix_shadow_not_quality_verdict",
                    "top_k": 20, "prefix_count": prefix,
                    "prefix_limited": self.rank_prefix_limited,
                    "top_k_replaced": replaced,
                    "rarity_only_top_k_replaced": rarity,
                    "baseline_source_hits": original, "shadow_source_hits": shadow,
                    "baseline_strong": strong, "shadow_strong": shadow_strong}
        return result


def summarize_local_advisory(diagnostics):
    """Project the existing same-builder local sample; never use native DF."""
    if type(diagnostics) is not dict:
        return None
    freq = diagnostics.get("frequency")
    if (type(freq) is not dict
            or freq.get("schema") != "sraf_arc_group_frequency_v1"
            or freq.get("scope") != "ordered_parser_slice_date_valid_sample_text_only"
            or freq.get("status") != "observed_sample"
            or type(freq.get("sample_limited")) is not bool):
        return None
    n, rows = freq.get("eligible_hits"), freq.get("groups")
    if (type(n) is not int or not 16 <= n <= 128
            or type(rows) is not list or not 1 <= len(rows) <= 16):
        return None
    values = []
    for i, row in enumerate(rows, 1):
        if (type(row) is not dict or type(row.get("group_ordinal")) is not int
                or row["group_ordinal"] != i
                or type(row.get("sample_hit_frequency")) is not int
                or not 0 <= row["sample_hit_frequency"] <= n):
            return None
        values.append(row["sample_hit_frequency"])
    rank, limited = (), False
    observed = diagnostics.get("rank")
    if (type(observed) is dict
            and observed.get("schema") == "sraf_arc_rank_shadow_v1"
            and observed.get("scope") == "same_parser_slice_ordered_sample_strict_prefix"
            and observed.get("status") == "observed_rank"
            and observed.get("top_k") == 20
            and type(observed.get("prefix_limited")) is bool
            and observed.get("frequency_sample_limited") is freq["sample_limited"]):
        rank = tuple(observed.get(k) for k in (
            "prefix_count", "top_k_replaced", "rarity_only_top_k_replaced",
            "original_source_hits", "shadow_source_hits", "original_strong", "shadow_strong"))
        limited = observed["prefix_limited"]
    return LocalGroupAdvisory(
        n, len(values), sum(v * 5 >= n * 4 for v in values),
        sum(0 < v * 5 <= n for v in values), values.count(0),
        freq["sample_limited"], rank, limited)


@dataclass(frozen=True)
class LocalPressureAdvisory:
    # Not a selection or a permission: only fixed aggregate counterfactuals.
    low: tuple[int, ...] = ()
    high: tuple[int, ...] = ()
    retained: tuple[tuple[str, int, int], ...] = ()

    def payload(self, *, candidate_sources, canonical_count):
        result = {}
        if (arc_shadow_enabled("SRAF_ARC_RELAX") and type(self.low) is tuple
                and len(self.low) == 7 and all(type(n) is int and 0 <= n <= 4096 for n in self.low)):
            parsed, eligible, date_rejected, other, topic, strict, cap = self.low
            if (candidate_sources > 0 and 0 < canonical_count < 3
                    and 0 < strict < 3 and parsed == eligible + date_rejected + other
                    and eligible == strict + topic and topic > 0
                    and 0 < cap <= min(2, 3 - strict)):
                result["local_relaxation_counterfactual"] = {
                    "scope": "bounded_date_valid_parser_sample_not_admitted_evidence",
                    "strict_rows": strict, "topic_rejected_rows": topic,
                    "hypothetical_add_cap": cap,
                    "focus": "review_topic_aliases_without_relaxing_verification"}
        if (arc_shadow_enabled("SRAF_ARC_TIGHTEN") and type(self.high) is tuple
                and len(self.high) == 1 and type(self.high[0]) is int
                and 40 <= self.high[0] <= 128 and canonical_count >= 40
                and type(self.retained) is tuple and 1 <= len(self.retained) <= 2):
            prefix = self.high[0]
            options = []
            seen = set()
            for row in self.retained:
                if (type(row) is not tuple or len(row) != 3 or type(row[0]) is not str
                        or row[0] not in ("all_text_axes", "anchor_plus_local_discriminative_axis")
                        or row[0] in seen or type(row[1]) is not int or type(row[2]) is not int
                        or not 20 <= row[1] < prefix or not 8 <= row[2] <= row[1]):
                    return result
                seen.add(row[0])
                options.append({"strategy": row[0], "retained_rows": row[1],
                                "retained_source_hits": row[2]})
            result["local_tightening_counterfactual"] = {
                "scope": "strict_parser_prefix_not_quality_verdict",
                "strict_prefix_rows": prefix, "options": options,
                "focus": "prioritize_missing_facets_without_removing_verified_evidence"}
        return result


def summarize_pressure_advisory(diagnostics):
    """Reuse completed same-builder observations; reject limited samples."""
    if type(diagnostics) is not dict:
        return None
    low, high, retained = (), (), ()
    raw = diagnostics.get("low")
    if (type(raw) is dict and raw.get("schema") == "sraf_arc_relax_shadow_v1"
            and raw.get("scope") == "first_primary_strict_parser_slice"
            and raw.get("status") == "observed_relaxation"
            and raw.get("sample_limited") is False):
        low = tuple(raw.get(k) for k in ("parsed_citations", "canonical_eligible",
                    "date_rejected", "other_rejected", "topic_rejected", "strict_count",
                    "hypothetical_add_cap"))
    raw = diagnostics.get("high")
    if (type(raw) is dict and raw.get("schema") == "sraf_arc_tighten_shadow_v1"
            and raw.get("scope") == "strict_parser_prefix_only"
            and raw.get("status") == "observed_tightening"
            and raw.get("prefix_limited") is False
            and type(raw.get("prefix_count")) is int
            and raw["prefix_count"] == raw.get("strict_count")
            and type(raw.get("strategies")) is list and 1 <= len(raw["strategies"]) <= 3):
        prefix = raw["prefix_count"]
        options = []
        seen = set()
        for row in raw["strategies"]:
            if (type(row) is not dict or type(row.get("strategy")) is not str
                    or row["strategy"] not in ("all_text_axes", "anchor_plus_local_discriminative_axis",
                                               "anchor_plus_native_discriminative_axis")
                    or row["strategy"] in seen):
                return LocalPressureAdvisory(low=low) if low else None
            seen.add(row["strategy"])
            rows, sources = row.get("retained_prefix_rows"), row.get("retained_source_hits")
            if (type(rows) is not int or type(sources) is not int
                    or not 0 <= sources <= rows <= prefix
                    or type(row.get("sample_floor_met")) is not bool):
                return LocalPressureAdvisory(low=low) if low else None
            if (row["strategy"] != "anchor_plus_native_discriminative_axis"
                    and row["sample_floor_met"] is True
                    and 20 <= rows < prefix and sources >= 8):
                options.append((row["strategy"], rows, sources))
        if options:
            high, retained = (prefix,), tuple(options)
    return LocalPressureAdvisory(low, high, retained) if low or high else None
