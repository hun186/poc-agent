#agent/utils_citations.py
from typing import Any, Dict, List

def _build_citations_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    最簡單版：
    - 不再依 source_id 去重
    - 每一個 evidence_snippet 變成一筆 citation
    - citations 的順序 = evidence_snippets 的順序
    - 多加一個 snippet_index，方便前端對應 snippet #1、#2...
    """
    ev = payload.get("evidence_snippets") or []
    citations: List[Dict[str, Any]] = []

    for i, s in enumerate(ev, 1):  # i = 1, 2, 3 ...
        if not isinstance(s, dict):
            continue

        citations.append({
            "text": s.get("text"),
            "source_id": s.get("source_id") or s.get("uuid"),
            "uuid": s.get("uuid"),
            "paragraph_id": s.get("paragraph_id"),
            "date_iso": s.get("article_date_iso") or s.get("date_iso"),
            "subject": s.get("subject"),
            "article_title": s.get("article_title"),
            "snippet_index": i,  # ★ snippet #1 對應 1，給你前端用
        })

    return citations


def compress_evidence(snippets: list[dict], max_samples: int = 150) -> list[dict]:
    if not snippets:
        return []

    # 先依日期排序（確保時間上有鋪陳）
    snippets_sorted = sorted(
        snippets,
        key=lambda s: (s.get("date_iso") or "", s.get("uuid") or "")
    )

    # 1) 簡單去重：相同 text 只留一個
    seen_text = set()
    deduped = []
    for s in snippets_sorted:
        txt = (s.get("text") or "").strip()
        if not txt:
            continue
        if txt in seen_text:
            continue
        seen_text.add(txt)
        deduped.append(s)

    # 2) 若仍然太多，就等距取樣確保時間涵蓋
    if len(deduped) > max_samples:
        step = len(deduped) / max_samples
        picked = []
        i = 0.0
        while int(i) < len(deduped) and len(picked) < max_samples:
            picked.append(deduped[int(i)])
            i += step
    else:
        picked = deduped

    # 3) 映射成精簡欄位
    out = []
    for s in picked:
        out.append({
            "id": s.get("uuid"),
            "d": s.get("date_iso") or s.get("article_date_iso"),
            "title": s.get("article_title") or s.get("subject"),
            "s": s.get("subject"),
            "note": s.get("text"),
        })
    return out