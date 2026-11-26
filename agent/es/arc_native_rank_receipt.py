"""Private, single-search receipt for native DF ranking diagnostics.

Only the verified native transport creates this value. It is passed locally
to the first Evidence build, never to the model, public output or durable logs.
Matching groups/dates does not establish PIT snapshot identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .arc_frequency_plan import SCOPE


@dataclass(frozen=True, repr=False)
class NativeRankFrequency:
    groups: tuple[frozenset[str], ...] = field(repr=False)
    date_from: str = field(repr=False)
    date_to: str = field(repr=False)
    eligible_documents: int
    document_frequencies: tuple[int, ...]

    @classmethod
    def from_observation(cls, observation, *, groups, date_from, date_to):
        if (type(observation) is not dict
                or observation.get("scope") != SCOPE
                or observation.get("status") != "exact_es_query_counts"):
            return None
        return cls(tuple(frozenset(g) for g in groups), date_from, date_to,
                   observation["eligible_documents"],
                   tuple(row["document_frequency"] for row in observation["groups"]))

    def for_builder(self, groups, *, date_from, date_to, allowed_years):
        if (allowed_years is not None
                or self.date_from != date_from or self.date_to != date_to
                or self.groups != tuple(frozenset(g) for g in groups)):
            return None
        return {"schema": "sraf_arc_native_rank_frequency_v1", "scope": SCOPE,
                "status": "exact_es_query_counts",
                "eligible_documents": self.eligible_documents,
                "groups": [{"group_ordinal": i, "document_frequency": df}
                           for i, df in enumerate(self.document_frequencies, 1)]}


DEEP_SCOPE = "same_round_pit_root_documents_with_candidate_date_and_entity_filter"


@dataclass(frozen=True, repr=False)
class DeepNativeRankFrequency:
    """Separate same-round PIT diagnostic counts; never ordinary DF."""
    groups: tuple[frozenset[str], ...] = field(repr=False)
    date_from: str = field(repr=False)
    date_to: str = field(repr=False)
    eligible_documents: int
    document_frequencies: tuple[int, ...]

    @classmethod
    def from_record(cls, record, *, groups, date_from, date_to):
        if (type(record) is not dict
                or record.get("schema") != "sraf_arc_deep_frequency_shadow_v1"
                or record.get("scope") != DEEP_SCOPE
                or record.get("status") != "observed_counts"
                or type(groups) is not tuple or not 1 <= len(groups) <= 8):
            return None
        n, rows = record.get("eligible_documents"), record.get("groups")
        if (type(n) is not int or not 0 <= n <= 2**63 - 1
                or type(rows) is not list or len(rows) != len(groups)
                or any(type(g) is not frozenset or not g for g in groups)):
            return None
        frequencies = []
        for i, row in enumerate(rows, 1):
            if (type(row) is not dict or type(row.get("group_ordinal")) is not int
                    or row["group_ordinal"] != i
                    or type(row.get("document_frequency")) is not int
                    or not 0 <= row["document_frequency"] <= n):
                return None
            frequencies.append(row["document_frequency"])
        return cls(groups, date_from, date_to, n, tuple(frequencies))

    def for_builder(self, groups, *, date_from, date_to, allowed_years):
        if (allowed_years is not None or self.date_from != date_from
                or self.date_to != date_to
                or self.groups != tuple(frozenset(g) for g in groups)):
            return None
        return {"schema": "sraf_arc_deep_rank_frequency_v1", "scope": DEEP_SCOPE,
                "status": "exact_es_query_counts",
                "eligible_documents": self.eligible_documents,
                "groups": [{"group_ordinal": i, "document_frequency": df}
                           for i, df in enumerate(self.document_frequencies, 1)]}
