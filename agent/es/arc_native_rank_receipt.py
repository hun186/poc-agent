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
