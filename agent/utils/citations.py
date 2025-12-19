#agent/utils/citations.py
from typing import Any, Dict, List
import re

def _normalize_snip_text(s: str) -> str:
    """
    簡單標準化文字：
    - 去頭尾空白
    - 把多個空白壓成一個
    目的是讓 ev.note 跟 evidence_snippets.text 比對成功。
    """
    if not isinstance(s, str):
        return ""
    s = s.strip()
    # 把連續空白壓成一個空白
    s = re.sub(r"\s+", " ", s)
    return s



def compress_evidence(snippets: list[dict], max_samples: int = 150) -> list[dict]:
    if not snippets:
        return []

    # 先依日期排序（確保時間上有鋪陳）
    snippets_sorted = sorted(
        snippets,
        key=lambda s: (s.get("date_iso") or "", s.get("uuid") or "")
    )
    '''
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
    '''
    seen = set()
    deduped = []
    for s in snippets_sorted:
        raw_txt = (s.get("text") or "").strip()
        if not raw_txt:
            continue

        uuid = str(s.get("uuid") or s.get("source_id") or "")
        txt_norm = _normalize_snip_text(raw_txt)
        if not uuid or not txt_norm:
            continue

        key = (uuid, txt_norm)          # ★ 避免不同文章因文字相同被誤去重
        if key in seen:
            continue
        seen.add(key)

        deduped.append(s)
    # 2) 若仍然太多，就等距取樣確保時間涵蓋
    if len(deduped) > max_samples:
        step = len(deduped) / max_samples
        picked: list[dict] = []
        i = 0.0
        while int(i) < len(deduped) and len(picked) < max_samples:
            picked.append(deduped[int(i)])
            i += step
    else:
        picked = deduped

    # 3) 映射成精簡欄位 + 指定 ref_no
    out: list[dict] = []
    for idx, s in enumerate(picked, start=1):
        # ★ 重要：把 ref_no 寫回原始 snippet，之後 build_citations 可以共用
        s["ref_no"] = idx

        out.append({
            "ref_no": idx,  # 給 LLM 用來寫「來源①、②…」
            "id": s.get("uuid"),
            "d": s.get("date_iso") or s.get("article_date_iso"),
            "title": s.get("article_title") or s.get("subject"),
            "s": s.get("subject"),
            "note": s.get("text"),
        })
    return out


def build_citations_from_ev(ev_compact: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    直接從 compressed_for_llm["ev"] 產生 citations。
    - 每一筆 ev 變成一筆 citation
    - ref_no 與 snippet_index 一律用 ev.ref_no
    - 前端可用 source_id / uuid 組 URL: /v1/docs/{source_id}
    """
    citations: List[Dict[str, Any]] = []

    for e in ev_compact:
        if not isinstance(e, dict):
            continue

        ref_no = e.get("ref_no")
        if not isinstance(ref_no, int):
            continue

        doc_id = e.get("id")
        if not doc_id:
            continue

        citations.append({
            "text": e.get("note"),
            "source_id": str(doc_id),
            "uuid": str(doc_id),
            "paragraph_id": None,   # 壓縮時沒保留就先 None
            "date_iso": e.get("d"),
            "subject": e.get("s"),
            "article_title": e.get("title"),
            "ref_no": ref_no,
            "snippet_index": ref_no,
        })

    # 按 ref_no 排好，保險
    citations.sort(key=lambda c: c.get("ref_no", 10**9))
    return citations



def _build_citations_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    - 先用 payload['ev'] 建立 (id, note) → ref_no 的對照表
    - 再走 payload['evidence_snippets']，盡量把正確的 ref_no 填回來
    - 每一個 evidence_snippet 變成一筆 citation
    - citations 會依 ref_no 排序，沒有 ref_no 的會排在後面
    - snippet_index 儘量與 ref_no 相同，方便前端對應
    """
    ev = payload.get("evidence_snippets") or []
    ev_compact = payload.get("ev") or []

    citations: List[Dict[str, Any]] = []

    # === 1) 建 ref_no 對照表： (id, note_normalized) -> ref_no ===
    ref_map: Dict[tuple, int] = {}
    '''
    print("=== DEBUG: RAW EVIDENCE_SNIPPETS ===")
    for s in ev:
        print({
            "uuid": s.get("uuid"),
            "source_id": s.get("source_id"),
            "date_iso": s.get("date_iso") or s.get("article_date_iso"),
            "text_preview": (s.get("text") or "")[:100].replace("\n", " ")
        })
    '''
    
    '''
    print("=== DEBUG: COMPACT EV (id + note) ===")
    for e in ev_compact:
        print({
            "ref_no": e.get("ref_no"),
            "id": e.get("id"),
            "d": e.get("d"),
            "note_preview": (e.get("note") or "")[:100].replace("\n", " ")
        })
    '''
    for e in ev_compact:
        if not isinstance(e, dict):
            continue
        ref_no = e.get("ref_no")
        if not isinstance(ref_no, int):
            continue
        ev_id = e.get("id")
        note = _normalize_snip_text(e.get("note") or "")
        if not ev_id or not note:
            continue
        key = (str(ev_id), note)
        # 後寫覆蓋沒關係，通常是一對一
        ref_map[key] = ref_no

    # === 2) 走 evidence_snippets，盡量掛上正確的 ref_no ===
    for idx, s in enumerate(ev, start=1):
        if not isinstance(s, dict):
            continue

        # 一律從 ref_map 對，不再信 snippet 自己的 ref_no
        ref_no = None

        sid = (
            s.get("uuid")
            or s.get("source_id")
            or s.get("doc_id")
            or s.get("id")
        )
        note = _normalize_snip_text(s.get("text") or "")
        if sid and note:
            key = (str(sid), note)
            ref_no = ref_map.get(key)

        citations.append({
            "text": s.get("text"),
            "source_id": s.get("source_id") or s.get("uuid"),
            "uuid": s.get("uuid"),
            "paragraph_id": s.get("paragraph_id"),
            "date_iso": s.get("article_date_iso") or s.get("date_iso"),
            "subject": s.get("subject"),
            "article_title": s.get("article_title"),

            # ref_no 對得到就用，對不到就先保留 None
            "ref_no": ref_no if isinstance(ref_no, int) else None,
            # snippet_index 直接用 idx，前端當 row id 比較穩
            "snippet_index": idx,
        })

    # === 3) 依 ref_no 排序：有 ref_no 的在前，沒有的排後面 ===
    citations.sort(
        key=lambda c: (
            c.get("ref_no") is None,       # True/False：沒 ref_no 的被排到後面
            c.get("ref_no") or 10**9       # 再依數字大小排序
        )
    )

    # === 4) 對於沒有 ref_no 的，補一個遞增的 snippet_index（避免是 None） ===
    running_idx = 1
    for c in citations:
        if not isinstance(c.get("snippet_index"), int):
            c["snippet_index"] = running_idx
        running_idx += 1
    '''
    print("=== DEBUG: CITATIONS AFTER BUILD ===")
    #print("check if citations is empty",citations)
    for c in citations:
        print({
            "ref_no": c.get("ref_no"),
            "snippet_index": c.get("snippet_index"),
            "uuid": c.get("uuid"),
            "date_iso": c.get("date_iso"),
            "subject": c.get("subject"),
            "title": c.get("article_title") or c.get("title"),
            "text_preview": (c.get("text") or "")[:100].replace("\n", " ")
        })
    '''
    return citations


def build_refno_uuid_map(ev: List[Dict[str, Any]]) -> Dict[int, str]:
    """
    依 ev 裡的 ref_no 建立：
        { ref_no(int) -> uuid(str) }
    若同一個 ref_no 缺 uuid 就略過；同一篇有多個片段共用同一 uuid 沒關係。
    """
    out: Dict[int, str] = {}
    for e in ev:
        ref_no = e.get("ref_no")
        uuid = e.get("id") or e.get("uuid")
        if not isinstance(ref_no, int):
            continue
        if not uuid:
            continue
        out[ref_no] = str(uuid)
    return out