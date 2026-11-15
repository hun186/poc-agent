"""Bounded postfilter Evidence budget and ES-hit-ordinal fair allocation.

The *candidate* budget is shared across hits. Reserving real candidate and
scan slots for later hits prevents a large early source from monopolizing the
request before canonical Event/Timeline and topic checks have run.

All inputs are already-returned ES hit dictionaries. No network, LLM or secrets.
"""
from __future__ import annotations

from typing import Any

from .json_utils import as_blocks, json_load_maybe

# These are hard opt-in upper ceilings, not user-supplied unbounded settings.
MAX_SCAN_CITATIONS = 2048
MAX_VALID_EVIDENCE = 1024
MAX_JSON_CHARS = 2097152
MAX_TEXT_CHARS = 1048576


def _source_demand(hit: Any) -> int:
    """Bounded estimate; unknown formats retain at least one fallback slot.

    Preserve the existing parser's real date/entity safeguards: no date/topic
    interpretation happens here. We only count potential source rows.
    """
    if not isinstance(hit, dict):
        return 1
    source = hit.get("_source")
    if not isinstance(source, dict):
        return 1
    raw = source.get("multidim_event_json")
    if isinstance(raw, str) and len(raw) > MAX_JSON_CHARS:
        return 1
    blocks = as_blocks(raw)
    structured = any(
        isinstance(block, dict) and (block.get("Event") or block.get("Event_Timeline"))
        for block in blocks
    )
    size = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        items = block.get("evidence_snippets")
        if isinstance(items, str):
            if len(items) > MAX_JSON_CHARS:
                continue
            items = json_load_maybe(items)
        if isinstance(items, list):
            size += len(items)
        elif isinstance(items, dict):
            size += 1
        if size >= MAX_SCAN_CITATIONS:
            break
    # The legacy unstructured _source path stays at <=20 citations/doc.
    if not structured:
        size = min(size, 20)
    # Preserve returned inner matches/fallback even without source snippets.
    return max(1, min(size, MAX_SCAN_CITATIONS))


def allocate_fair_source_quotas(
    es_hits: list[dict[str, Any]], capacity: int = MAX_SCAN_CITATIONS,
) -> list[int]:
    """Water-fill parser+source-scan quotas by ES hit ordinal, not UUID.

    Underfilled sources return their unused slots to others. With 500+12
    possible citations both can be read; with 2000+12, reserve 12 slots for
    the later document. O(number of hits + capacity), except for bounded
    existing _source block-count discovery.
    """
    if type(capacity) is not int or not 0 <= capacity <= MAX_SCAN_CITATIONS:
        return [0] * len(es_hits)
    demands = [_source_demand(hit) for hit in es_hits]
    slots = [0] * len(demands)
    active = [i for i, demand in enumerate(demands) if demand]
    remaining = capacity
    while remaining and active:
        increment = max(1, remaining // len(active))
        next_active = []
        for i in active:
            if remaining == 0:
                break
            take = min(remaining, increment, demands[i] - slots[i])
            slots[i] += take
            remaining -= take
            if slots[i] < demands[i]:
                next_active.append(i)
        active = next_active
    return slots


def source_text_quotas(
    citation_quotas: list[int], capacity: int = MAX_TEXT_CHARS,
) -> list[int]:
    """Reserve a bounded share of source text characters for every hit."""
    total = sum(citation_quotas)
    if total <= 0:
        return [0] * len(citation_quotas)
    return [capacity * quota // total for quota in citation_quotas]


def select_valid_fair_evidence(
    verified: list[Any], limit: int = MAX_VALID_EVIDENCE,
) -> list[Any]:
    """Select *already date/topic-verified* Evidence with source fairness.

    Strong Evidence always precedes weak. Distinct ES hit ordinals, not UUIDs,
    separate independent source documents, including identical UUIDs across
    indices. No reclassification, no date inference, no sorting by sensitive ID.
    Leave the original order unchanged when the budget is not exhausted.
    """
    if type(limit) is not int or not 0 <= limit <= MAX_VALID_EVIDENCE:
        return []
    if len(verified) <= limit:
        return verified
    result: list[Any] = []
    for weak in (False, True):
        groups: dict[int, list[Any]] = {}
        for index, item in enumerate(verified):
            if bool(getattr(item, "weak_evidence", False)) != weak:
                continue
            origin = getattr(item, "source_hit_ordinal", -1)
            # Unknown origin must never join all unrelated sources together.
            key = origin if type(origin) is int and origin >= 0 else -index - 1
            groups.setdefault(key, []).append(item)
        group_values = list(groups.values())
        depth = 0
        while len(result) < limit:
            added = False
            for rows in group_values:
                if depth >= len(rows):
                    continue
                result.append(rows[depth])
                added = True
                if len(result) == limit:
                    return result
            if not added:
                break
            depth += 1
    return result
