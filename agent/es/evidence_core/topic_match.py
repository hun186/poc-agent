#agent/es/evidence_core/topic_match.py
from __future__ import annotations

from typing import List, Optional, Set, Tuple

from .text_norm import normalize_for_match


def match_topic(
    ev_text: str,
    subject: Optional[str],
    title: Optional[str],
    term_groups: List[Set[str]],
    *,
    min_groups_required: Optional[int] = None,
) -> Tuple[bool, Set[str], str, int]:
    """
    語意群組版主題詞過濾：

    - term_groups: list[set[str]]，每一組是一個語意軸（例如「敘利亞」群、「化學武器」群）
    - 若 term_groups 為空 → 不過濾（避免誤殺其他任務）

    判斷邏輯（嚴格）：
    - 1 軸：命中 1 軸即可
    - 2 軸：兩軸都要命中
    - 3 軸：三軸都要命中
    - 4 軸以上：至少命中 3 軸
    
    寬鬆：
    命中　min_groups_required 數量即可
    
    回傳：ok, hit_terms, scope(text/meta/mixed), group_hits
    """
    if not term_groups:
        return True, set(), "no_filter", 0

    text_norm = normalize_for_match(ev_text or "")
    subj_norm = normalize_for_match(subject or "")
    title_norm = normalize_for_match(title or "")

    hit_terms: Set[str] = set()
    group_hits = 0
    hit_in_text = False
    hit_in_meta = False

    for g in term_groups:
        if not g:
            continue

        g_hit: Set[str] = set()
        for t in g:
            if not t:
                continue
            t_norm = normalize_for_match(t)
            if not t_norm:
                continue

            in_text = t_norm in text_norm
            in_meta = (t_norm in subj_norm) or (t_norm in title_norm)

            if in_text or in_meta:
                g_hit.add(t)
                hit_in_text = hit_in_text or in_text
                hit_in_meta = hit_in_meta or in_meta

        if g_hit:
            group_hits += 1
            hit_terms |= g_hit

    if group_hits == 0:
        return False, set(), "none", 0

    if hit_in_text and hit_in_meta:
        scope = "mixed"
    elif hit_in_text:
        scope = "text"
    elif hit_in_meta:
        scope = "meta"
    else:
        scope = "none"

    if min_groups_required is not None:
        return (group_hits >= min_groups_required), hit_terms, scope, group_hits

    n = len(term_groups)
    if n <= 1:
        return True, hit_terms, scope, group_hits
    if n == 2:
        return (group_hits == 2), hit_terms, scope, group_hits
    if n == 3:
        return (group_hits == 3), hit_terms, scope, group_hits

    return (group_hits >= 3), hit_terms, scope, group_hits
