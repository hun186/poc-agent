"""Opt-in, deterministic, source-diverse Report Evidence selection (#397 P1-d).

Select only from already verified Evidence snippets; never widen date scope,
re-evaluate topic matching, rewrite Event/Timeline dates or fetch more documents.
Default report behavior is unchanged unless the caller explicitly opts in.
"""
from __future__ import annotations

from typing import Any

from shared.citations.citation_id import pick_doc_id


def select_source_diverse_evidence(
    snippets: list[dict[str, Any]], limit: int,
) -> list[dict[str, Any]]:
    """Strong-first, round-robin over source documents, stable within each source.

    Preserve the legacy strong-before-weak ordering. Within each strength class,
    take one snippet per distinct document before a second from any document.
    Unidentified snippets are separate groups rather than an invented shared
    source. This is a *count* bound, not a token budget or an assertion of date
    or topic coverage. The caller must supply already date-checked Evidence.
    """
    if limit <= 0 or not snippets:
        return []

    selected: list[dict[str, Any]] = []
    for weak in (False, True):
        groups: dict[tuple[str, str | int], list[dict[str, Any]]] = {}
        for index, snippet in enumerate(snippets):
            if bool(snippet.get("weak_evidence")) != weak:
                continue
            doc_id = pick_doc_id(snippet)
            key: tuple[str, str | int] = (
                ("doc", doc_id) if doc_id else ("missing", index)
            )
            groups.setdefault(key, []).append(snippet)
        if not groups:
            continue

        grouped = list(groups.values())
        depth = 0
        while len(selected) < limit:
            added = False
            for source_snippets in grouped:
                if depth >= len(source_snippets):
                    continue
                selected.append(source_snippets[depth])
                added = True
                if len(selected) == limit:
                    return selected
            if not added:
                break
            depth += 1

    return selected
