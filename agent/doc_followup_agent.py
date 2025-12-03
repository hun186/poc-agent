# agent/doc_followup_agent.py
from typing import Any, Dict, List, Optional, Set
import json
import os
import re

from .llm_utils.ollama_client import call_llm
from .tools_es import ESFetchDocById


DOC_FOLLOWUP_MAX_TOTAL_CHARS = int(os.getenv("DOC_FOLLOWUP_MAX_TOTAL_CHARS", "26000"))
DOC_FOLLOWUP_MAX_DOCS = int(os.getenv("DOC_FOLLOWUP_MAX_DOCS", "5"))

# 🔹 支援兩種常見樣式：
# - 40 位 hex（你現在 ES 那串長 hash）
# - 36 字元 UUID（帶 dash）
#UUID_HEX_40 = re.compile(r"\b[0-9a-f]{40}\b", re.IGNORECASE)
UUID_HEX_40 = re.compile(r"[0-9a-f]{40}", re.IGNORECASE)
UUID_HYPHEN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


# 緊接在 DOC_FOLLOWUP_MAX_TOTAL_CHARS 定義之後
_EX_N = DOC_FOLLOWUP_MAX_TOTAL_CHARS
_EX_1 = _EX_N
_EX_2_START = _EX_N + 1
_EX_2_END = _EX_N * 2
_EX_3_START = _EX_2_END + 1
_EX_3_END = _EX_N * 3

# === 單一工具實例 ===
_fetch_doc_tool = ESFetchDocById()


DOC_FOLLOWUP_PLANNER_SYSTEM = f"""
你是一個『文件後續處理規劃助手』（planner）。

任務：根據「使用者指令」與「文件列表（僅有基本資訊）」，
決定這一輪要處理哪幾篇文件、以及每一篇要讀取的字元範圍。

注意：
- 你只能看到 docs_meta（不含全文），其中包含 index / uuid / title / date / subject / total_length。
- 切片上限：本輪所有文件加總的字元數，不可以超過 MAX_CHARS = {DOC_FOLLOWUP_MAX_TOTAL_CHARS}。
- 若使用者沒有指定區間，就預設從該篇的開頭開始，最多讀取 MAX_CHARS 字元。
- 若使用者說「前 26k / 前 26000 個字」，要解讀為從開頭開始，長度不超過 MAX_CHARS。
- 若使用者說「A~B 個字 / A 至 B 個字」，採 1-based，start=A，end=B（含），但仍不得超過 MAX_CHARS。
- 可以理解以下自然語句並轉成範圍：
  - 「前 26k 個字」、「前 2 萬字」
  - 「27k~56k 個字」、「26001~52000 個字」
  - 「中間那一段」、「後半段」、「最後 1/3」等（用 total_length 推導出合適範圍）
- 若使用者說「第一篇、第二篇」等，要對應 index。
- 若使用者沒指定篇數，但有多篇文件，預設用第 1 篇。
- 若有多個文件需要比較（例如「比較第一篇和第二篇」），可以在計畫中同時列出多篇，但總字數仍不得超過 MAX_CHARS。

輸入 JSON：
{{
  "instruction": "使用者目前這一輪的指令",
  "docs_meta": [
    {{
      "index": 1,
      "uuid": "...",
      "title": "...",
      "date": "YYYY-MM-DD 或 null",
      "subject": "...",
      "total_length": 123456   // 原始全文字元長度
    }}
  ]
}}

輸出 JSON（只允許以下欄位，不能多也不能少）：
{{
  "plans": [
    {{
      "index": 1,            // 要處理的文件 index
      "start": 1,            // 1-based 起始字元位置
      "end": 26000           // 1-based 結束字元位置（含）
    }}
  ]
}}

規則：
1. 至少要有一個 plan；若根本無法判斷，就預設用 index=1, start=1, end=min(total_length, MAX_CHARS)。
2. start、end 必須在該篇文件的 1 ~ total_length 範圍內。
3. 對同一篇文件，不可產生多個重疊區間。
4. 所有 plans 的 (end - start + 1) 加總，不得超過 MAX_CHARS。
5. 嚴格遵守 JSON 格式，不可加註解或多餘欄位。
"""


DOC_FOLLOWUP_SYSTEM_PROMPT = f"""
你是一個『文件後續處理助手』。

所有可用資訊都來自 docs 陣列，不能查新的資料庫。

你可以做的任務包含但不限於：
- 把指定篇章翻譯成英文（例如：把第五篇翻成英文）
- 給我第一篇的全文（或某一段全文）
- 幫我逐篇摘要
- 比較第一篇與第二篇差異
- 基於這些文件做新的說明

輸入 JSON 格式：
{{
  "instruction": "使用者目前這一輪的指令",
  "docs": [
    {{
      "index": 1,
      "uuid": "...",
      "title": "...",
      "date": "...",
      "subject": "...",
      "full_text": "這次實際提供的文字片段（可能是全文的一部分）",
      "range": {{ "start": 1, "end": {_EX_1} }},
      "total_length": 123456
    }}
  ]
}}

規則：
1. 所有內容都只能來自 docs[i].full_text，不可新增外部事實。
2. 使用者說「第一篇、第二篇」要對應 index。
3. 若語言未指定，預設輸出繁體中文。
4. 若 docs 為空，必須回應「目前沒有可用的文件」。
5. 若某篇文件有 range 與 total_length，表示目前只讀取了全文的一部分：
   - 摘要與說明只能根據目前看到的片段，不要假裝看過全文。
   - 若使用者看起來想要「整篇處理」但目前只有片段，可以在回答最後友善提醒：
     建議他改用「分段提問」方式。
6. 若需要分段處理很長的文件時，回答中可以主動告訴使用者：
   - 可以分多次提問，例如：
     1. 給我第一篇資料的前 {_EX_1} 個字及摘要
     2. 給我第一篇資料的 {_EX_2_START}~{_EX_2_END} 個字及摘要
     3. 給我第一篇資料的 {_EX_3_START}~{_EX_3_END} 個字及摘要
""".strip()

def _extract_uuid_candidates(text: str, max_n: int = 3) -> list[str]:
    """
    從使用者指令裡抓「看起來像 uuid/hash」的字串。
    - 目前支援：
      - 40 位十六進位（ES hash 型態）
      - 標準 36 字元 UUID（含 dash）
    - 只回傳最多 max_n 個，避免誤抓太多。
    """
    if not text:
        return []

    out: list[str] = []

    # 先抓 40 位 hex
    for m in UUID_HEX_40.finditer(text):
        u = m.group(0)
        if u not in out:
            out.append(u)
            if len(out) >= max_n:
                return out

    # 再抓帶 dash 的 UUID
    for m in UUID_HYPHEN.finditer(text):
        u = m.group(0)
        if u not in out:
            out.append(u)
            if len(out) >= max_n:
                return out

    return out

def _plan_ranges_with_llm(instruction: str, docs: List[Dict[str, Any]]) -> List[Dict[str, int]]:
    """
    回傳格式：
    [
      {"index": 1, "start": 1, "end": 26000},
      {"index": 2, "start": 1, "end": 8000},
    ]

    若 LLM 解析失敗或格式有問題，回傳空 list，交給 regex fallback 處理。
    """
    if not docs:
        return []

    # 只給 meta，避免把全文塞進 planner prompt
    docs_meta = []
    for d in docs:
        text = d.get("full_text") or ""
        docs_meta.append({
            "index": d.get("index"),
            "uuid": d.get("uuid"),
            "title": d.get("title"),
            "date": d.get("date"),
            "subject": d.get("subject"),
            "total_length": len(text),
        })

    payload = {
        "instruction": instruction,
        "docs_meta": docs_meta,
    }

    user_prompt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    try:
        raw = call_llm(
            user_prompt,
            system_prompt=DOC_FOLLOWUP_PLANNER_SYSTEM,
            extra_params={"options": {}},
            timeout=60.0,
        )
        # 預期 raw 是 JSON 字串
        obj = json.loads(raw)
        plans = obj.get("plans") or []
        out: List[Dict[str, int]] = []
        used = 0

        for p in plans:
            try:
                idx = int(p["index"])
                start = int(p["start"])
                end = int(p["end"])
            except Exception:
                continue

            if start < 1 or end < start:
                continue

            # 這邊先不做 total_length 裁切，留給後面的 slice 層做
            length = end - start + 1
            if length <= 0:
                continue

            if used + length > DOC_FOLLOWUP_MAX_TOTAL_CHARS:
                # 超過總上限就縮短或丟棄
                remain = DOC_FOLLOWUP_MAX_TOTAL_CHARS - used
                if remain <= 0:
                    break
                end = start + remain - 1
                length = remain

            out.append({"index": idx, "start": start, "end": end})
            used += length

            if used >= DOC_FOLLOWUP_MAX_TOTAL_CHARS:
                break

        return out
    except Exception as e:
        print("[doc_followup] planner LLM failed:", e)
        return []
    
# 🔹 解析「第幾篇」
def _parse_target_index(instruction: str) -> int | None:
    """
    支援：第1篇、第 2 篇、第一篇、第二篇……
    找不到就回 None（之後可預設用第一篇）
    """
    text = instruction.strip()
    # 「第1篇 / 第 2 篇」
    m = re.search(r"第\s*(\d+)\s*篇", text)
    if m:
        return int(m.group(1))

    # 「第一篇 / 第二篇」簡單處理到十以內
    CN_NUM = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    m = re.search(r"第\s*([一二三四五六七八九十]+)\s*篇", text)
    if m:
        s = m.group(1)
        if s in CN_NUM:
            return CN_NUM[s]
    return None


# 🔹 解析「前 26k 個字」或「27k~56k 個字」
def _parse_char_range(instruction: str) -> tuple[int | None, int | None]:
    """
    回傳 (start, end)，皆為 0-based, end 為「不含」邊界。
    支援：
    - 前26k個字 / 前 26000 字
    - 27k~56k個字 / 27001~56000字 / 27k 至 56k 字
    若無明確範圍則回 (None, None)。
    """
    text = instruction.replace(" ", "")

    # 1) 前 N / 前 Nk
    m = re.search(r"前(\d+)(k|K)?(個?字)?", text)
    if m:
        n = int(m.group(1))
        if m.group(2):  # 有 k
            n *= 1000
        if n <= 0:
            return None, None
        return 0, n  # 0-based, end exclusive

    # 2) A~B / A 至 B（可帶 k）
    m = re.search(r"(\d+)(k|K)?[~～\-至](\d+)(k|K)?(個?字)?", text)
    if m:
        s = int(m.group(1))
        e = int(m.group(3))
        if m.group(2):
            s *= 1000
        if m.group(4):
            e *= 1000
        if s <= 0 or e <= 0:
            return None, None
        if e <= s:
            # 異常情況，改成從 s 起往後取一段
            return s - 1, s - 1 + DOC_FOLLOWUP_MAX_TOTAL_CHARS
        # 使用者用 1-based，轉成 0-based
        return s - 1, e
    return None, None



def fetch_docs_by_uuid(
    uuids: List[str],
    index_hint: str | None = None,
    index_candidates: Optional[List[str]] = None,   # ★ 新增
) -> List[Dict[str, Any]]:
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
        return bool(ft.strip())

    for u in uuids:
        doc = None

        # 1) 先試 router 給的 index_hint
        if index_hint:
            doc = _try_fetch(u, index_hint)

        # 2) 若沒成功，依序試其他候選 index
        if not _has_full_text(doc):
            for idx in index_candidates:
                if not idx or idx == index_hint:
                    continue
                doc = _try_fetch(u, idx)
                if _has_full_text(doc):
                    print(f"[doc_followup] matched uuid={u!r} on index={idx!r}")
                    break

        # 3) 再試一次完全不帶 index_hint（走工具預設）
        if not _has_full_text(doc):
            doc = _try_fetch(u, None)

        if not _has_full_text(doc):
            print(f"[doc_followup] give up uuid={u!r}, no full_text from any index")
            continue

        # ★ 從 tool 回來的結果抓實際 index
        hit_index = (
            doc.get("index")
            or doc.get("_index")
            or ""
        )
        if isinstance(hit_index, str) and hit_index:
            used_indexes.add(hit_index)
            
        src = doc.get("source") or {}
        full_text = doc.get("full_text") or ""

        # ===== 強化欄位抽取：multidim_event_json + communication =====
        md = src.get("multidim_event_json") or {}
        ev = md.get("Event") or {}
        timeline = md.get("Event_Timeline") or []

        # title：預設用完整新聞標題，其次事件標題
        title = (
            src.get("communication", {}).get("subject")   # 俄、中行使否決權  安理會...
            or md.get("article_title")                    # 事件短標：俄、中行使否決權
            or src.get("article_title")
            or src.get("title")
            or src.get("rawInfo", {}).get("title")
        )

        # date：優先 ISO 日期，其次 rawInfo.date
        date = (
            src.get("article_date_iso")
            or src.get("date_iso")
            or ev.get("time_iso")
            or (timeline[0].get("date_iso") if timeline else None)
            or src.get("rawInfo", {}).get("date")
        )

        # subject：給 citation 顯示用的主題字串
        subject = (
            src.get("subject")
            or src.get("communication", {}).get("subject")
            or ev.get("object")
            or md.get("article_title")
        )

        # ★ 最後防呆：如果還是沒有 title，就從全文第一行猜一個，最後才用 uuid
        if not title:
            lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
            if lines:
                title = lines[0][:80]
            else:
                title = u

        docs.append(
            {
                "uuid": u,
                "title": title,
                "date": date,
                "subject": subject,
                "full_text": full_text,
                "index": hit_index,   # ★ 順手放進 doc
            }
        )

    print("[doc_followup] final docs count =", len(docs))
    return docs, used_indexes

# 🔹 根據指令與全量 docs，切出實際要送進 LLM 的片段
def _slice_docs_for_instruction(instruction: str, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    - 優先使用 LLM 規劃的 plans（可理解「中間那段」、「後半段」這種自然語句）
    - 若 LLM 規劃失敗，再退回 regex 版 _parse_target_index/_parse_char_range
    - 每篇會多帶：
        - range: {"start": 起始字元(1-based), "end": 結束字元(1-based)}
        - total_length: 原全文總字數
    """
    if not docs:
        return []

    docs = docs[:DOC_FOLLOWUP_MAX_DOCS]

    # ===== 1) 先試 LLM planner =====
    plans = _plan_ranges_with_llm(instruction, docs)
    idx2doc = {d.get("index"): d for d in docs}
    sliced: List[Dict[str, Any]] = []
    remaining = DOC_FOLLOWUP_MAX_TOTAL_CHARS

    def _apply_slice_by_range(d: Dict[str, Any], start_1: int, end_1: int) -> Dict[str, Any] | None:
        nonlocal remaining
        text = d.get("full_text") or ""
        if not text:
            return None
        total_len = len(text)

        # 1-based → 0-based
        s = max(0, start_1 - 1)
        e = min(end_1, total_len)
        if e <= s:
            return None

        seg_len = e - s
        if seg_len <= 0 or remaining <= 0:
            return None

        if seg_len > remaining:
            e = s + remaining
            seg_len = remaining

        segment_text = text[s:e]
        remaining -= seg_len

        new_d = dict(d)
        new_d["full_text"] = segment_text
        new_d["range"] = {"start": s + 1, "end": e}
        new_d["total_length"] = total_len
        return new_d

    if plans:
        for p in plans:
            if remaining <= 0:
                break
            d = idx2doc.get(p["index"])
            if not d:
                continue
            sd = _apply_slice_by_range(d, p["start"], p["end"])
            if sd:
                sliced.append(sd)

    # 若 LLM 有切出東西，就直接用它的結果
    if sliced:
        return sliced

    # ===== 2) LLM 失敗 → fallback: regex 版 =====
    target_idx = _parse_target_index(instruction)
    start, end = _parse_char_range(instruction)
    remaining = DOC_FOLLOWUP_MAX_TOTAL_CHARS
    sliced = []

    def _apply_slice_regex(d: Dict[str, Any]) -> Dict[str, Any] | None:
        nonlocal remaining
        text = d.get("full_text") or ""
        if not text:
            return None
        total_len = len(text)

        if start is None and end is None:
            s = 0
            e = min(total_len, remaining)
        else:
            s = max(0, start or 0)
            if s >= total_len:
                return None
            e_raw = end if end is not None else total_len
            e = max(s + 1, min(e_raw, total_len))

        seg_len = e - s
        if seg_len <= 0 or remaining <= 0:
            return None

        if seg_len > remaining:
            e = s + remaining
            seg_len = remaining

        segment_text = text[s:e]
        remaining -= seg_len

        new_d = dict(d)
        new_d["full_text"] = segment_text
        new_d["range"] = {"start": s + 1, "end": e}
        new_d["total_length"] = total_len
        return new_d

    if target_idx is not None:
        for d in docs:
            if d.get("index") == target_idx:
                sd = _apply_slice_regex(d)
                if sd:
                    sliced.append(sd)
                break
    else:
        for d in docs:
            if remaining <= 0:
                break
            sd = _apply_slice_regex(d)
            if sd:
                sliced.append(sd)

    if not sliced:
        remaining = DOC_FOLLOWUP_MAX_TOTAL_CHARS
        d0 = docs[0]
        text = d0.get("full_text") or ""
        if text:
            use_len = min(len(text), remaining)
            sliced.append(
                {
                    **d0,
                    "full_text": text[:use_len],
                    "range": {"start": 1, "end": use_len},
                    "total_length": len(text),
                }
            )
    return sliced
def ask_with_doc_followup(
    instruction: str,
    uuids: Optional[List[str]] = None,
    index_hint: Optional[str] = None,
    refno_uuid_map: Optional[Dict[int, str]] = None,  # ★ 新增：ref_no -> uuid
    index_candidates: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    - 若 refno_uuid_map 有值：優先走「citation 模式」，index = ref_no。
      → 使用者說「第七篇」對應到 ref_no = 7 的那篇。
    - 若 refno_uuid_map 為 None：維持舊行為，用 uuids + 指令裡抓到的 uuid。
    """

    # === 1) 根據模式決定要抓哪幾個 uuid，並組好 docs（含 index） ===

    docs: List[Dict[str, Any]] = []
    mode = "uuid"  # or "refno"

    if refno_uuid_map:  # ---------- A. citation 模式 ----------
        mode = "refno"

        # 1-1) 判斷要用哪些 ref_no（有說「第 N 篇」就只取那一篇，否則全取）
        target_idx = _parse_target_index(instruction)  # "第七篇" → 7
        if target_idx is not None and target_idx in refno_uuid_map:
            ref_nos = [target_idx]
        else:
            ref_nos = sorted(refno_uuid_map.keys())

        # 1-2) 先整理成 (ref_no, uuid) pairing，並去掉重複 uuid 以減少 ES 查詢次數
        ref_pairs: List[tuple[int, str]] = []
        seen_uuid: set[str] = set()
        fetch_uuids: List[str] = []
        for ref_no in ref_nos:
            u = refno_uuid_map.get(ref_no)
            if not u:
                continue
            ref_pairs.append((ref_no, u))
            if u not in seen_uuid:
                seen_uuid.add(u)
                fetch_uuids.append(u)

        if not fetch_uuids:
            return {
                "answer": "refno_uuid_map 中沒有對應可用的 UUID，無法進行文件後續處理。",
                "citations": [],
                "reasoning": f"refno_uuid_map={refno_uuid_map!r}，但沒有任何有效的 uuid。",
                "used_uuids": [],
            }

        # 1-3) 拉全文，做成 uuid -> base_doc 對照
        base_docs_list, used_indexes = fetch_docs_by_uuid(
            fetch_uuids,
            index_hint=index_hint,
            index_candidates=index_candidates,
        )
        base_docs = {d["uuid"]: d for d in base_docs_list if d.get("uuid")}

        if not base_docs:
            return {
                "answer": "查無任何與指定 citation 對應的文件，請確認資料是否仍存在於索引中。",
                "citations": [],
                "reasoning": f"refno_uuid_map={refno_uuid_map!r}，但 ESFetchDocById 未回傳任何文件。",
                "used_uuids": [],
            }

        # 1-4) 按 ref_no 順序展開 docs，讓 index = ref_no
        for ref_no, u in ref_pairs:
            base = base_docs.get(u)
            if not base:
                continue
            d = dict(base)
            d["index"] = ref_no      # ★ 關鍵：index 就是「來源編號」
            docs.append(d)

    else:  # ---------- B. 舊有 uuid 模式 ----------
        # 1-1) 從指令裡抓看起來像 uuid/hash 的字串
        cand_uuids = _extract_uuid_candidates(instruction)  # 例如最多 3 個

        # 1-2) 合併呼叫端給的 uuids
        clean_uuids: List[str] = []
        for u in (uuids or []):
            if isinstance(u, str):
                s = u.strip()
                if s and s not in clean_uuids:
                    clean_uuids.append(s)

        # 1-3) 把指令裡抓到的 uuid 一併加進來（union）
        for u in cand_uuids:
            if u not in clean_uuids:
                clean_uuids.append(u)

        if not clean_uuids:
            return {
                "answer": "目前沒有可用的參考文件或指定的 UUID，因此無法進行這一輪的指令。",
                "citations": [],
                "reasoning": "呼叫端未提供 reuse_uuids，且在指令中也未偵測到可用的 UUID/hash。",
                "used_uuids": [],
            }

        # 1-4) 拉全文
        base_docs_list, used_indexes = fetch_docs_by_uuid(
            clean_uuids,
            index_hint=index_hint,
            index_candidates=index_candidates,
        )

        if not base_docs_list:
            return {
                "answer": "查無任何與指定 UUID 對應的文件，請確認字串是否正確，或是否存在於目前的索引中。",
                "citations": [],
                "reasoning": f"指定的 UUID 列表為 {clean_uuids!r}，但 ESFetchDocById 未回傳任何文件。",
                "used_uuids": [],
            }

        # 1-5) 這個模式下 index 就是「第幾篇文件」
        for idx, d in enumerate(base_docs_list, start=1):
            nd = dict(d)
            nd["index"] = idx
            docs.append(nd)

    # === 若兩種模式都沒產生 docs，就直接收掉 ===
    if not docs:
        return {
            "answer": "目前沒有可用的文件可供後續處理。",
            "citations": [],
            "reasoning": f"mode={mode!r}，但 docs 為空。",
            "used_uuids": [],
        }

    # === 2) 共用後半段流程：切片 → 丟給 LLM ===

    sliced_docs = _slice_docs_for_instruction(instruction, docs)

    payload = {
        "instruction": instruction,
        "docs": sliced_docs,
    }
    user_prompt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    answer = call_llm(
        user_prompt,
        system_prompt=DOC_FOLLOWUP_SYSTEM_PROMPT,
        extra_params={"options": {}},
        timeout=180.0,
    )

    used_uuids = sorted({d["uuid"] for d in docs if d.get("uuid")})
    used_indexes_list = sorted(used_indexes) if "used_indexes" in locals() else []

    if mode == "refno":
        reasoning = "依照前一輪報告中的 citation 編號（ref_no）對應到原始文件，進行本輪的後續處理。"
    else:
        reasoning = "僅依據呼叫端提供或在指令中偵測到的 UUID 所對應的文件全文（或片段）進行後續處理。"

    return {
        "answer": answer,
        "citations": [],
        "reasoning": reasoning,
        "used_uuids": used_uuids,
        "doc_count": len(docs),
        "used_indexes": used_indexes_list,
    }