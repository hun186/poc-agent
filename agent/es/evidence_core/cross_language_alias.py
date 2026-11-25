"""ARC A2 offline alias admission helpers; not wired into live retrieval.

Statistical frequency is not semantic equivalence. Callers must establish
equivalence before passing proposed aliases; this module only guards shape,
ambiguity, and boundedness. It never removes or merges original groups.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .text_norm import normalize_for_match

MAX_GROUPS = 16
MAX_PROPOSALS = 64
MAX_PER_GROUP = 8
MAX_TERM_CHARS = 160


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def alias_matches(alias: str, text: str) -> bool:
    """Latin-containing aliases require token boundaries, retaining spaces.

    This deliberately does not change the existing Chinese/core matcher.
    ASCII word boundaries allow English names adjacent to Chinese characters.
    """
    if not isinstance(alias, str) or not isinstance(text, str):
        return False
    alias = _fold(alias).strip()
    if not alias or len(alias) > MAX_TERM_CHARS:
        return False
    if re.search(r"[a-z]", alias):
        phrase = r"\s+".join(re.escape(part) for part in alias.split())
        return bool(re.search(r"(?<![a-z0-9_])" + phrase + r"(?![a-z0-9_])", _fold(text)))
    needle = normalize_for_match(alias)
    return bool(needle and needle in normalize_for_match(text))


def admit_aliases(
    original: list[set[str]], proposed: list[list[str]],
) -> list[set[str]]:
    """Admit bounded optional aliases without cross-group normalized collisions.

    Unsupported inputs fail closed to unchanged copies of the original groups.
    Original aliases are never evicted to fit optional expansion budgets.
    """
    out = [set(group) for group in original]
    if not 1 <= len(original) <= MAX_GROUPS or len(proposed) != len(original):
        return out
    if any(not isinstance(group, list) for group in proposed):
        return out
    if sum(map(len, proposed)) > MAX_PROPOSALS:
        return out
    owners: dict[str, set[int]] = defaultdict(set)
    for idx, group in enumerate(original):
        for term in group:
            if not isinstance(term, str) or not 0 < len(term) <= MAX_TERM_CHARS:
                return out
            key = normalize_for_match(term)
            if key:
                owners[key].add(idx)
    candidates: list[list[tuple[str, str]]] = []
    for idx, group in enumerate(proposed):
        accepted = []
        for term in group:
            if not isinstance(term, str) or not 0 < len(term) <= MAX_TERM_CHARS:
                continue
            term = term.strip()
            key = normalize_for_match(term)
            if not key or not any(ch.isalpha() for ch in key):
                continue
            owners[key].add(idx)
            accepted.append((key, term))
        candidates.append(accepted)
    for idx, group in enumerate(candidates):
        existing = {normalize_for_match(term) for term in out[idx]}
        added = 0
        for key, term in group:
            if added >= MAX_PER_GROUP:
                break
            if key in existing or owners[key] != {idx}:
                continue
            out[idx].add(term)
            existing.add(key)
            added += 1
    return out
