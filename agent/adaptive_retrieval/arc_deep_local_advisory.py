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
