"""Conservative question-driven GLM text-field query additions.

Source-of-truth design checked against GLM
czjLLM/config_es/schemas/InfoExtraction-MultiDim-mapping.yaml
(blob 35f88c72652e9ae5f7da77eab748075ee4f9fb45).

Only fields declared TEXT in that blueprint are included. Runtime ES mapping
may differ and MUST be checked before enabling 'on' in production. Optional
nested paths use ignore_unmapped, and missing fields merely match nothing.
This module never adds hard filters, Evidence citations, or ES calls.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

MD = "multidim_event_json"
MAX_ORIGINAL_CHARS = 4096
MAX_QUERY_CHARS = 2048
MAX_EXTRA_FIELDS = 5

# Domains are a deliberately small, fixed intent lexicon; LLM rewrites,
# document content and ES metadata are never authoritative intent signals.
_INTENT_MARKERS = {
    "policy": ("政策", "法規", "法案", "立法", "措施", "規定", "條例", "制裁",
               "補助", "policy", "regulation", "legislation"),
    "person": ("人物", "發言", "表態", "立場", "發表", "誰", "總統",
               "首相", "person", "stance", "statement"),
    "causal": ("原因", "影響", "衝擊", "後果", "導致", "因果",
               "原因分析", "consequence", "impact", "caused"),
}
# Only validated text fields. NOT Event.action, Person.stance, facet,
# core_entities, locations, Event.subject or Involved_Parties.party_role,
# which the GLM mapping declares keyword (not Chinese tokenized).
_FIELDS = {
    "policy": (
        ("outer", "Event_Summary", 1.2),
        ("Event", "consequence", 1.15),
        ("Impact", "impact_description", 1.15),
    ),
    "person": (
        ("Person", "action", 1.2),
        ("Person", "relation", 1.1),
    ),
    "causal": (
        ("Event", "relation", 1.2),
        ("Event", "consequence", 1.2),
        ("Impact", "impact_description", 1.25),
        ("outer", "Event_Summary", 1.1),
    ),
}


def select_text_fields(question: str | None) -> tuple[tuple[str, str, float], ...]:
    """Return a bounded mapping-aware text-only field plan."""
    if not isinstance(question, str) or not 0 < len(question) <= MAX_ORIGINAL_CHARS:
        return ()
    clean = unicodedata.normalize("NFKC", question).casefold()
    # Avoid promoting a field plan from search rewrite / quoted long snippets.
    plans: dict[tuple[str, str], float] = {}
    for domain, markers in _INTENT_MARKERS.items():
        if any(token in clean for token in markers):
            for scope, field, boost in _FIELDS[domain]:
                key = (scope, field)
                plans[key] = max(plans.get(key, 0.0), boost)
    return tuple((scope, field, boost) for (scope, field), boost in
                 list(plans.items())[:MAX_EXTRA_FIELDS])


def build_intent_shoulds(
    *, search_query: str, original_question: str | None,
) -> list[dict[str, Any]]:
    """Nested query paths are isolated, no flattened cross-Event matches."""
    if (not isinstance(search_query, str) or not search_query.strip()
            or len(search_query) > MAX_QUERY_CHARS):
        return []
    clauses: list[dict[str, Any]] = []
    for scope, field, boost in select_text_fields(original_question):
        full_field = f"{MD}.{field}" if scope == "outer" else f"{MD}.{scope}.{field}"
        match = {"match": {full_field: {"query": search_query, "boost": boost}}}
        if scope != "outer":
            match = {"nested": {
                "path": f"{MD}.{scope}", "query": match, "ignore_unmapped": True,
                "score_mode": "max",
            }}
        clauses.append({"nested": {
            "path": MD, "query": match, "ignore_unmapped": True,
            "score_mode": "max",
        }})
    return clauses
