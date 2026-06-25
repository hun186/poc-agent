# agent/doc_followup/fetcher.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple

from ..tools_es import ESFetchDocById

_fetch_doc_tool = ESFetchDocById()


def fetch_docs_by_uuid(
    uuids: List[str],
    *,
    index_hint: str | None = None,
    index_candidates: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """
    根據 UUID 清單利用 ESFetchDocById 拉全文。

    會先嘗試：
    1) index_hint（若有）
    2) 再依序嘗試 index_candidates 裡的其他 index
    3) 最後再試一次 index_hint=None（走工具內建預設）

    回傳每篇的基本資訊（不再負責 index 編號）：
    {
        "uuid": "...",
        "title": "...",
        "date": "YYYY-MM-DD 或 None",
        "subject": "...",
        "full_text": "原文全文"
    }
    """
    index_candidates = index_candidates or []
    docs: List[Dict[str, Any]] = []
    used_indexes: Set[str] = set()

    def _try_fetch(u: str, idx_hint: str | None) -> Dict[str, Any] | None:
        try:
            print(f"[doc_followup] try fetch uuid={u!r}, index_hint={idx_hint!r}")
            return _fetch_doc_tool.forward(uuid=u, index_hint=idx_hint)
        except Exception as e:
            print(f"[doc_followup] fetch error for {u} (index_hint={idx_hint!r}): {e}")
            return None

    def _has_full_text(d: Dict[str, Any] | None) -> bool:
        if not d:
            return False
        ft = d.get("full_text") or ""
        return bool(str(ft).strip())

    for u in uuids:
        doc = None

        # 1) 先試 index_hint
        if index_hint:
            doc = _try_fetch(u, index_hint)

        # 2) 再試候選 index
        if not _has_full_text(doc):
            for idx in index_candidates:
                if not idx or idx == index_hint:
                    continue
                doc = _try_fetch(u, idx)
                if _has_full_text(doc):
                    print(f"[doc_followup] matched uuid={u!r} on index={idx!r}")
                    break

        # 3) 最後不帶 hint 再試一次
        if not _has_full_text(doc):
            doc = _try_fetch(u, None)

        if not _has_full_text(doc):
            print(f"[doc_followup] give up uuid={u!r}, no full_text from any index")
            continue
        
        #print("doc in fetch_docs_by_uuid:", doc)
        hit_index = doc.get("index") or doc.get("_index") or ""
        if isinstance(hit_index, str) and hit_index:
            used_indexes.add(hit_index)
        #print("hit_index in fetch_docs_by_uuid:", hit_index)
        src = doc.get("source") or {}
        full_text = doc.get("full_text") or ""

        # ===== 強化欄位抽取：multidim_event_json + communication =====
        md = (src.get("multidim_event_json") or {}) if isinstance(src, dict) else {}
        ev = (md.get("Event") or {}) if isinstance(md, dict) else {}
        print("md in fetch_docs_by_uuid:", md)
        timeline = md.get("Event_Timeline") or []
        if not isinstance(timeline, list):
            timeline = []

        title = (
            (src.get("communication", {}) or {}).get("subject") # 俄、中行使否決權  安理會...
            or md.get("article_title")                          # 事件短標：俄、中行使否決權
            or src.get("article_title")
            or src.get("title")
            or (src.get("rawInfo", {}) or {}).get("title")
        )
        
        # date：優先 ISO 日期，其次 rawInfo.date
        date = (
            src.get("article_date_iso")
            or src.get("date_iso")
            or ev.get("time_iso")
            or (timeline[0].get("date_iso") if timeline else None)
            or (src.get("rawInfo", {}) or {}).get("date")
        )

        # subject：給 citation 顯示用的主題字串
        subject = (
            src.get("subject")
            or (src.get("communication", {}) or {}).get("subject")
            or ev.get("object")
            or md.get("article_title")
        )

        # 最後防呆：如果還是沒有 title，就從全文第一行猜一個
        if not title:
            lines = [ln.strip() for ln in str(full_text).splitlines() if ln.strip()]
            title = (lines[0][:80] if lines else u)

        docs.append(
            {
                "uuid": u,
                "title": title,
                "date": date,
                "subject": subject,
                "full_text": full_text,
                "index": hit_index,  # 真正命中的 index（若工具有回）
            }
        )

    print("[doc_followup] final docs count =", len(docs))
    return docs, used_indexes
