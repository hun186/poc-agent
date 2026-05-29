#agent/report_agent.py
from typing import Any, Dict, List, Optional
import json
import time
import os
from .data_agent import run_data_agent
#from .tools_es import ESSearchNews, ESTimeline, ESFetchDocById
#from .tools_stats import AggregateMonthQuarter
from agent.llm_utils.ollama_client import call_llm  # 你既有的封裝
from agent.utils.citations import build_citations_from_ev
from agent.utils.citations import compress_evidence
from agent.utils.citations import build_refno_uuid_map
from agent.utils.evidence_pack import pack_ev_for_llm
from agent.utils.evidence_pack import filter_ev_fields
from agent.utils.evidence_pack import guess_report_need_fields
from agent.utils.profiler import log_duration, log_total
from agent.utils.markdown_tables import sanitize_markdown_tables, replace_table_cell_br
from agent.refiners.query_refiner import refine_question_for_data_agent
#from agent.config.query_refiner_settings import load_report_refiner_config

REPORT_MODEL_ID = (
    os.getenv("REPORT_MODEL_ID")   # 有指定就用這個
    or os.getenv("MODEL_ID")       # 沒有就沿用主 MODEL_ID
    or "gpt-oss:120b-32k"          # 再不然給一個預設
)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        print(f"[report] invalid {name}={raw!r}; fallback to {default}")
        return default
    if value <= 0:
        print(f"[report] invalid {name}={raw!r}; fallback to {default}")
        return default
    return value


REPORT_LLM_TIMEOUT = _env_float(
    "REPORT_LLM_TIMEOUT",
    _env_float("REPORT_TIMEOUT", 300.0),
)

REPORT_SYSTEM_PROMPT = """
你是一個『資料驅動的分析助手』。

你會收到一個 JSON 物件 payload，格式大致如下（key 已簡化）：

{
  "q": "精煉後問句（用於檢索/統計與撰寫）",
  "q0": "使用者原始問句（僅供展示/稽核，可不使用）",
  "t": ["date_from 或 null", "date_to 或 null"],
  "agg": {
    "docs": 整體文件數,
    "snips": 整體片段數,
    "active_days": 有活動紀錄的天數,
    "month": [ ["YYYY-MM", count], ... ],
    "quarter": [ ["YYYY-Qx", count], ... ],
    "peak_days": [ ["YYYY-MM-DD", count], ... ],   # 活動最集中的幾天
    "first_last": ["第一天日期", "最後一天日期"]
  },
  "ev": [
    {
      "ref_no": 1,          # 必填：引用編號（1-based），只能用這個標註來源
      "note": "片段文字",    # 必填：事實只能來自 note
      "d": "YYYY-MM-DD",    # 選填：若有，代表片段日期
      "title": "原文標題",   # 選填：若有，代表片段標題
      "s": "subject",       # 選填：若有，代表主題/標籤
      "id": "uuid"          # 選填：若有，代表文件識別
    },
    ...
  ]
}

重要：ev 欄位可能缺少（例如沒有 d/title/s/id）。
你必須只根據「實際收到的欄位」分析與撰寫，不得假設缺欄位存在。
不得在內文提到未提供的欄位（缺 title 就不能寫「標題為…」；缺 d 就不能寫具體日期）。

請嚴格遵守：

1. 所有「具體事實（日期、事件順序、主題、地點、傷亡等）」只能來自：
   - agg 提供的統計數字（docs / snips / active_days / month / quarter / peak_days / first_last）
   - ev 裡的 note / title / d。
   不可以從常識或想像自行補充額外細節。

2. 不可以捏造不存在的數字（例如新增次數、比例、百分比、年份、城市名稱等）。
   資料沒有，就不要硬猜；若不確定，直接說「資料不足以判斷」。

3. 可以對趨勢做定性描述（例如「逐漸增加」「集中在第一季」「2017 年的關注度高於 2013 年」），
   但不得和 agg 的數字矛盾。

4. 引用具體事件時，請同時：
   - 簡要說明內容（用自己的話轉述 ev[i].note / title），以及
   - 用 ev[i].ref_no 來標註來源，例如：
     - 「根據 2013-03-19 一則標題為『……』的片段（來源1），……」
     - 「2017-03-24 的 OPCW 報告指出……（來源3）」
   其中「1」「2」「3」一律使用 ev 陣列中提供的 ref_no，不得自行重新編號或跳號。

5. 若同一段分析同時依據多個片段，可以寫成：
   - 「綜合來源1、來源2與來源5，可見……」
   或「（來源1、2、5）」等，仍然只能使用 ev.ref_no 提供的編號。

6. 如果資料明顯不足以完整回答問題（例如年份中間完全沒有資料），
   請直接說明「目前資料不足以完整覆蓋某些年份／時期」，並指出缺口在哪裡，
   但仍然要說明「在現有資料中可以看出的現象與趨勢」。

7. 報告結構建議包含（可依實際情況調整）：
   - 資料概況（簡要說明 docs/snips/active_days、時間範圍、月份與季度分布）
   - 重要事件時間線（依日期整理，逐項附上來源編號）
   - 趨勢分析（例如：國際關注度變化、安理會互動、化武使用與調查重點等）
   - 延伸的 SWOT 分析，在 SWOT 段落中，若有引用具體事實，依然要標註「來源X」。

8. 以條列 + 小段落方式寫出清楚、有邏輯的分析報告，使用繁體中文。
   報告可以適度使用小標題（例如「一、資料概況」「二、事件時間線」「三、趨勢分析」「四、SWOT 分析」）。

輸出時：
- 撰寫時以 q 為主；若 q0 有提供「額外但與任務相關的約束」（例如：受眾、分析框架、輸出順序），可採用。
- 不要再輸出 JSON，直接輸出可閱讀的中文說明即可。
- 內文中提到的所有「來源X」編號，必須都能在 ev.ref_no 中找到對應的數字，不得出現額外的編號。

【通用表格欄位排序規則（層次導向，強制）】
當你要輸出 Markdown 表格時，請先判斷資訊的「層次（由上而下）」並依層次排列欄位順序：

1) 第 1 欄：最上層分類（Group / 類別 / 維度 / 主軸）
   - 特徵：值最常重複、字最短、用來分群（例如：Strength/Weakness、國家、主題、區域、單位、類型）
2) 第 2 欄：次層項目（Sub-group / 子類 / 項目）
   - 特徵：在同一最上層分類下再細分（例如：具體面向、措施、事件子類、機構、方案）
3) 第 3 欄：主要內容（Description / 說明 / 事件概述 / 觀察）
   - 特徵：文字最長、可能需要 <br> 分行、承載細節
4) 最後一欄：來源 / 依據 / 備註（若有）
   - 特徵：通常是編號、短字串或引用集合

補充規則：
- 若資料只有 2 層：仍遵守「最上層在前、內容在後」。
- 若資料超過 2 層：最多只保留前 2 欄作為層次欄，其餘細節一律放到「主要內容」欄，以避免表格變得難讀。
- 任何表格列都必須完整輸出所有欄位，若某欄未知，請填「未知」；若確定沒有值，請填「—」，不得輸出空字串。
- 主要內容欄不得含實體換行；需要換行一律用 <br>。
- 為了利於後端 Word 排版合併，請讓「最常重複、最像章節標籤」的欄位放在第 1 欄。

在輸出表格前，請先用心中檢查：
- 第 1 欄是否為最上層分群欄（短、重複多）？
- 長段落是否集中在第 3 欄「主要內容」？
- 引用/來源是否集中在最後一欄？
若不符合，請調整欄位順序後再輸出。

【Markdown 表格絕對禁令】
1. 表格每一列「絕對禁止」出現物理換行符。所有段落切換、條列換行，一律使用 <br> 標籤。
2. 每一列必須以 | 開頭並以 | 結尾，且中間的 | 數量必須嚴格等於 (總欄位數 - 1)。
3. 日期或項目名稱（如 SWOT 的 Strength）：每一列都要「重複完整輸出」，禁止留空或使用「〃」。
   (原因：我們會在後端 Word 處理時自動合併重複項，但在 Markdown 中重複輸出能確保表格結構不縮水)。

【二維樞紐統計表輸出規則（強制）】
當任務要求「依兩個屬性做交叉統計」、「輸出二維樞紐表」、「輸出交叉表」、「橫軸/縱軸展開」時，才套用以下規則：

1. 必須輸出真正的二維表結構，不得將「(橫軸值, 縱軸值)」合併為單一 key。
   絕對禁止以下扁平化格式：
   - "(橫軸值,縱軸值)": 數值
   - "橫軸值|縱軸值": 數值
   - "橫軸值_縱軸值": 數值
   - 任何將兩軸值拼接為單一欄位名稱或 key 的形式

2. 二維表的基本原則為：
   - 橫軸 = 欄位（columns）
   - 縱軸 = 列（rows）
   - 每一列都必須完整包含所有橫軸欄位的值
   - 不可只輸出單向往下的 pair-to-value 清單

3. 若以 Markdown 表格輸出：
   - 第 1 欄必須是縱軸屬性
   - 後續各欄必須依序為各橫軸屬性值
   - 每一列都必須補齊全部橫軸欄位
   - 缺值請填 0、未知或 —（依任務語意選擇，但同一表內要一致）
   - 不得省略欄位，不得只列出有值的組合

4. 若以 JSON 結構表達二維表，只允許使用下列其中一種結構，不得自行改寫為其他格式：

【允許格式 A：columns + rows】
{
  "columns": ["橫軸值1", "橫軸值2", "..."],
  "rows": [
    {
      "row_key": "縱軸值1",
      "values": {
        "橫軸值1": 數值,
        "橫軸值2": 數值
      }
    }
  ]
}

【允許格式 B：matrix】
{
  "columns": ["橫軸值1", "橫軸值2", "..."],
  "rows": [
    ["縱軸值1", 數值1, 數值2],
    ["縱軸值2", 數值3, 數值4]
  ]
}

5. 若任務未明確指定排序方式：
   - 橫軸欄位可依字母、時間、數值大小或自然順序排列，但同一表內必須一致
   - 縱軸列也必須採一致排序，不得任意跳動

6. 若某些橫軸值與縱軸值的組合沒有資料：
   - 必須補齊該格
   - 若語意為計數，優先填 0
   - 若語意為未知或資料缺漏，填「未知」或「—」
   - 不得直接略過該格，導致表格退化成稀疏列表

7. 當你心中檢查輸出時，必須確認：
   - 是否已將橫軸與縱軸分離？
   - 是否每列都完整對應所有橫軸欄位？
   - 是否錯誤地把兩軸值拼成單一 key？
   若有上述情況，請先改正，再輸出。

【二維表錯誤示例（禁止輸出）】
{
  "(男,20-29)": 15,
  "(男,30-39)": 22,
  "(女,20-29)": 18
}

【二維表正確概念】
- 橫軸是欄位集合，不是 key 的一部分
- 縱軸是逐列展開，不是 key 的一部分
- 最終結果必須讓讀者一眼看出「列 × 欄」的交叉關係

8. 若任務是給人閱讀的報告型輸出，且適合表格呈現，優先使用 Markdown 表格呈現二維交叉表；
   除非任務明確要求 JSON，否則不要改用 JSON。

9. 只要輸出的是表格，就必須是「完整矩形結構」：
   - 表頭固定
   - 每列欄數一致
   - 不得有些列少欄位、有些列多欄位
   - 不得因缺值而省略儲存格
   
"""



def compress_stats(stats: dict, top_k_peak_days: int = 5) -> dict:
    day_counts = stats.get("day_counts") or {}
    # 轉成 list[ (date, count) ]
    day_items = sorted(day_counts.items())  # 依日期排序

    if day_items:
        first_day = day_items[0][0]
        last_day = day_items[-1][0]
    else:
        first_day = last_day = None

    # 取高峰日（依 count 由大到小取前 K 名）
    peak_days = sorted(day_items, key=lambda x: x[1], reverse=True)[:top_k_peak_days]

    # month & quarter 轉陣列形式
    month_counts = stats.get("month_counts") or {}
    quarter_counts = stats.get("quarter_counts") or {}

    month_arr = sorted(month_counts.items())        # e.g. [("2025-01", 34), ...]
    quarter_arr = sorted(quarter_counts.items())    # e.g. [("2025-Q1", 198), ...]

    return {
        "docs": stats.get("doc_count", 0),
        "snips": stats.get("snippet_count", 0),
        "active_days": stats.get("active_days", 0),
        "month": month_arr,
        "quarter": quarter_arr,
        "peak_days": peak_days,
        "first_last": [first_day, last_day],
    }




class ReportAgent:
    """
    run() 回傳 dict（含 citations），
    run_text() 回傳單純 answer。
    """
    def run(self, query: str) -> Dict[str, Any]:
        return ask_with_report(query)

    def run_text(self, query: str) -> str:
        result = ask_with_report(query)
        return result.get("answer", "").strip() or "[系統沒有產生任何文字答案]"
    
def ask_with_report(
    question: str,
    trace: Optional[Dict[str, Any]] = None,
    index_hint: str | None = None,
    
) -> Dict[str, Any]:
    if trace is None:
        trace = {}
    t_total_start = time.perf_counter()
    #print("question in ask_with_report",question)
    original_question = (question or "").strip()
    #print("original_question in ask_with_report",original_question)
    # ✅ 先精煉，再丟給 data_agent（只影響資料準備，不影響前端顯示的「使用者提問」）
    refined_question = refine_question_for_data_agent(
        original_question,
        mode="report",
        trace=trace,
        index_hint=index_hint, # ★ 新增
    )
    
    with log_duration("[report] run_data_agent", extra={"mode": "report"}):
        #payload = run_data_agent(refined_question, mode="report", trace=trace)
        payload = run_data_agent(
            refined_question,
            mode="report",
            trace=trace,
            question_raw=original_question,
            refined_question=refined_question,
            index_hint=index_hint,   # ✅ 補上
            route=trace.get("route")  # 或你當下的 route 變數
        )
        
    # ✅ 對外仍保留原問句（你原本就強調「使用者提問一定要存在」）
    payload["question"] = original_question or "[未提供使用者提問]"
    payload["question_raw"] = original_question or "[未提供使用者提問]"
    
    # ✅ 把精煉結果也留著（debug/稽核很有用）
    qm = payload.get("query_meta") or {}
    if isinstance(qm, dict):
        qm["refined_question"] = refined_question
        payload["query_meta"] = qm

    # 你可以用環境變數控管給 LLM 的最大片段數
    MAX_EV_FOR_LLM = int(os.getenv("REPORT_MAX_EVIDENCE_SNIPS", "120"))

    # 新增：前端回傳上限
    MAX_EV_FOR_FRONTEND_CFG = int(os.getenv("REPORT_MAX_EVIDENCE_SNIPS_FRONTEND", "150"))

    # 保底：前端至少 >= LLM（避免使用者覺得「前端比報告引用更少」）
    MAX_EV_FOR_FRONTEND = max(MAX_EV_FOR_FRONTEND_CFG, MAX_EV_FOR_LLM)
    
    # === 強/弱證據分流（強優先給報告 LLM）===
    ev_all = payload.get("evidence_snippets") or []
    ev_strong = [e for e in ev_all if not e.get("weak_evidence")]
    ev_weak   = [e for e in ev_all if e.get("weak_evidence")]
    
    # 強證據優先，不夠再補弱證據
    picked_for_llm = ev_strong[:MAX_EV_FOR_LLM]
    if len(picked_for_llm) < MAX_EV_FOR_LLM:
        need = MAX_EV_FOR_LLM - len(picked_for_llm)
        picked_for_llm += ev_weak[:need]
    
    # （可選）讓 payload 留個統計，方便 debug / 前端顯示
    payload["evidence_meta"] = {
        "total": len(ev_all),
        "strong": len(ev_strong),
        "weak": len(ev_weak),
        
        # LLM 相關
        "max_for_llm": MAX_EV_FOR_LLM,
        "picked_for_llm": len(picked_for_llm),
        
        # 前端相關（配置值 vs 實際生效值）
        "max_for_frontend_cfg": MAX_EV_FOR_FRONTEND_CFG,
        "max_for_frontend": MAX_EV_FOR_FRONTEND,
    
    }
    print("[report] evidence_meta =", payload["evidence_meta"])

    # === 精簡版（給報告 LLM 用） ===
    compressed_for_llm = {
        # 給報告 LLM：用精煉問句（避免字數/格式碎念干擾）
        "q": refined_question or payload.get("question"),
    
        # 若你希望報告內仍能提到「原問句」或做稽核：保留一份
        "q0": payload.get("question"),
        "t": [
            payload.get("time_range", {}).get("date_from"),
            payload.get("time_range", {}).get("date_to"),
        ],
        "agg": compress_stats(payload.get("stats") or {}),
        #"ev": compress_evidence(payload.get("evidence_snippets") or []),
        "ev": compress_evidence(picked_for_llm, max_samples=MAX_EV_FOR_LLM),
    }



    ev_compact = compressed_for_llm["ev"] or []
    payload["ev"] = ev_compact

    # === (止血) 單片 note 字元上限：避免 token 爆掉 ===
    NOTE_CHAR_LIMIT = int(os.getenv("REPORT_EV_NOTE_CHAR_LIMIT", "0"))  # 0=不限制
    TITLE_CHAR_LIMIT = int(os.getenv("REPORT_EV_TITLE_CHAR_LIMIT", "0"))  # 0=不限制（可選）

    truncated_notes = 0
    truncated_titles = 0
    note_truncated_chars_total = 0
    title_truncated_chars_total = 0

    if NOTE_CHAR_LIMIT > 0:
        for e in ev_compact:
            note = e.get("note")
            if isinstance(note, str) and len(note) > NOTE_CHAR_LIMIT:
                note_truncated_chars_total += (len(note) - NOTE_CHAR_LIMIT)
                e["note"] = note[:NOTE_CHAR_LIMIT] + "…"
                truncated_notes += 1

    # （可選）標題也可能很長，通常不太會，但加了更保險
    if TITLE_CHAR_LIMIT > 0:
        for e in ev_compact:
            title = e.get("title")
            if isinstance(title, str) and len(title) > TITLE_CHAR_LIMIT:
                title_truncated_chars_total += (len(title) - TITLE_CHAR_LIMIT)
                e["title"] = title[:TITLE_CHAR_LIMIT] + "…"
                truncated_titles += 1

    # === (可選) 整體 note 總字元預算：再加一道硬上限 ===
    NOTE_TOTAL_BUDGET = int(os.getenv("REPORT_EV_NOTE_TOTAL_BUDGET", "0"))  # 0=不限制
    if NOTE_TOTAL_BUDGET > 0:
        total = 0
        for e in ev_compact:
            note = e.get("note")
            if not isinstance(note, str):
                continue
            if total >= NOTE_TOTAL_BUDGET:
                # 超過預算後，直接把後面的 note 清空或改成極短提示（更省）
                e["note"] = "…"
                continue

            remain = NOTE_TOTAL_BUDGET - total
            if len(note) > remain:
                e["note"] = note[:remain] + "…"
                total = NOTE_TOTAL_BUDGET
            else:
                total += len(note)
                
    em = payload.get("evidence_meta")
    if isinstance(em, dict):
        em["note_char_limit"] = NOTE_CHAR_LIMIT
        em["title_char_limit"] = TITLE_CHAR_LIMIT
        em["truncated_notes"] = truncated_notes
        em["truncated_titles"] = truncated_titles
        em["note_truncated_chars_total"] = note_truncated_chars_total
        em["title_truncated_chars_total"] = title_truncated_chars_total
        em["note_total_budget"] = NOTE_TOTAL_BUDGET
        
    try:
        packed = pack_ev_for_llm(
            ev_compact,
            refined_question or payload.get("question") or "",
            mode=os.getenv("REPORT_EV_FIELD_SELECTOR_MODE", "rules"),
            call_llm_fn=call_llm,
            llm_model=os.getenv("REPORT_FIELD_SELECTOR_MODEL_ID") or REPORT_MODEL_ID,
            llm_timeout=float(os.getenv("REPORT_FIELD_SELECTOR_TIMEOUT", "60")),
            llm_max_fields=int(os.getenv("REPORT_FIELD_SELECTOR_MAX_FIELDS", "10")),
        )
    except Exception as ex:
        # 保底：任何錯誤都不要影響主流程
        packed = {
            "ev_slim": filter_ev_fields(ev_compact, guess_report_need_fields(refined_question or "")),
            "meta": {"mode": "rules", "llm_used": False, "llm_error": f"{type(ex).__name__}: {ex}", "allow_fields": [], "fields_count": 0}
        }
    compressed_for_llm["ev"] = packed["ev_slim"]
    
    em = payload.get("evidence_meta")
    if isinstance(em, dict):
        em["llm_ev_fields"] = packed["meta"].get("allow_fields")
        em["llm_ev_fields_count"] = packed["meta"].get("fields_count")
        em["llm_ev_field_selector"] = {
            "mode": packed["meta"].get("mode"),
            "llm_used": packed["meta"].get("llm_used"),
            "llm_error": packed["meta"].get("llm_error"),
        }
        em["llm_ev_returned"] = len(compressed_for_llm["ev"])
        
    # === related_articles：建議只列出 LLM 有用到的這些 doc ===
    ev_full = payload.get("evidence_snippets") or []
    
    # 取用於對齊的 doc_id（與 ev_compact 的 id 同概念）
    def _doc_id_from_full_snip(s: Dict[str, Any]) -> str:
        return str(s.get("uuid") or s.get("source_id") or "")
    
    used_ids = {str(e.get("id")) for e in ev_compact if e.get("id")}
    
    related_map: Dict[str, Dict[str, Any]] = {}
    for s in ev_full:
        doc_id = _doc_id_from_full_snip(s)
        if not doc_id:
            continue
        if used_ids and doc_id not in used_ids:
            continue
        if doc_id in related_map:
            continue
    
        related_map[doc_id] = {
            "uuid": s.get("uuid"),
            "source_id": s.get("source_id"),
            "article_title": s.get("article_title"),
            "article_date_iso": s.get("article_date_iso") or s.get("date_iso"),
            "subject": s.get("subject"),
        }
    
    payload["related_articles"] = list(related_map.values())

    # === 給 LLM 的 JSON ===
    user_prompt = json.dumps(
        compressed_for_llm,
        ensure_ascii=False,
        separators=(",", ":")
    )
    em = payload.get("evidence_meta")
    if isinstance(em, dict):
        em["llm_user_prompt_chars"] = len(user_prompt)  # ★ 可選但很實用
    #ev_for_llm = ev_compact
    ev_for_llm = compressed_for_llm["ev"]  # ★ 改成真的送進去那份
    
    print(f"MAX_EV_FOR_LLM:{MAX_EV_FOR_LLM}")
    print(f"MAX_EV_FOR_FRONTEND_CFG:{MAX_EV_FOR_FRONTEND_CFG}")
    print("=== DEBUG: EV (for LLM) ===")
    for e in ev_for_llm:
        print({
            "ref_no": e.get("ref_no"),
            "id": e.get("id"),
            "d": e.get("d"),
            "title": e.get("title"),
            "note_preview": (e.get("note") or "")[:100].replace("\n", " "),
            "keys": list(e.keys()),  # 這行對診斷欄位精簡很有用
        })
    t0 = time.perf_counter()
    with log_duration("[report] call_llm(report)",
        extra={"model_id": REPORT_MODEL_ID, "timeout_sec": REPORT_LLM_TIMEOUT},
    ):
        report_text = call_llm(
            user_prompt,
            system_prompt=REPORT_SYSTEM_PROMPT,
            extra_params={"options": {}},
            # 可用 REPORT_LLM_TIMEOUT（或舊名 REPORT_TIMEOUT）延長大型報告生成等待秒數
            timeout=REPORT_LLM_TIMEOUT,
            model=REPORT_MODEL_ID,
        )
    t1 = time.perf_counter()
    
    # ★ 修復 LLM 產出的所有 Markdown 表格（不限欄數）
    #print(f"DEBUG: report_text before Sanitized Markdown Row: {report_text}")
    if "<br>\n" in report_text or "<br />\n" in report_text or "<br/>\n" in report_text:
        print("FOUND br+newline inside output table!")
    if isinstance(report_text, str) and report_text.strip():
        report_text = sanitize_markdown_tables(report_text)
        # ★ OpenWebUI 容易對 <br> 的表格渲染出問題：把表格 cell 內的 <br> 改成分隔符
        report_text = replace_table_cell_br(report_text, sep="；")  # 你也可改成 " / "
    #print(f"DEBUG: report_text after Sanitized Markdown Row: {report_text}")
    # ★ 把這次報告 LLM 寫到 trace["llm"]["report"]
    llm_root = trace.setdefault("llm", {})
    report_logs: list[Dict[str, Any]] = llm_root.setdefault("report", [])
    #print("REPORT_SYSTEM_PROMPT",REPORT_SYSTEM_PROMPT)
    report_logs.append({
        "system": "REPORT_SYSTEM_PROMPT",
        "user": user_prompt,
        "answer_preview": (report_text[:200] if isinstance(report_text, str) else str(report_text)[:200]),
        "elapsed_sec": round(t1 - t0, 3),
        "model_id": REPORT_MODEL_ID,
    })
    
    # === evidence_snippets 仍可保留給其他用途（例如前端展開全文），但不再用來建 citations ===
    ev_for_frontend = payload.get("evidence_snippets") or []
    if len(ev_for_frontend) > MAX_EV_FOR_FRONTEND:
        ev_for_frontend = ev_for_frontend[:MAX_EV_FOR_FRONTEND]
        payload["evidence_snippets"] = ev_for_frontend

    # ✅ 寫入實際前端回傳數量
    em = payload.get("evidence_meta")
    if isinstance(em, dict):
        em["frontend_returned"] = len(ev_for_frontend)
    
    # ★ citations：直接用 ev_compact
    citations = build_citations_from_ev(ev_compact)

    reasoning = (
        "本回答根據 es_search_news 的查詢結果與 aggregate_month_quarter 所提供的統計，"
        "並綜整 evidence_snippets 及相關文章所做的資料驅動分析。"
    )

    # ★ used_uuids：也從 ev_compact 算，確保跟 LLM 實際用的一致
    used_uuids: List[str] = []
    for e in ev_compact:
        doc_id = e.get("id")
        if doc_id:
            doc_id = str(doc_id)
            if doc_id not in used_uuids:
                used_uuids.append(doc_id)
    refno_uuid_map = build_refno_uuid_map(ev_compact)
    #print("report_text",report_text)
    result: Dict[str, Any] = {
        "question": original_question or "[未提供使用者提問]",   # ✅ 給匯出用（最重要）
        "q": refined_question or (original_question or ""),      # ✅ 可選：給 debug 或一致性
        "q0": original_question or "",                           # ✅ 可選：保留原問句
        "answer": report_text,
        "citations": citations,
        "reasoning": reasoning,
        "used_uuids": used_uuids,
        "refno_uuid_map": refno_uuid_map,
    }

    # ★ 把資料整備代理人的 log 掛回給前端用
    data_agent = trace.get("data_agent")
    if data_agent:
        result["data_agent"] = data_agent

    # ★ 總耗時 log（報告管線整體）
    log_total(
        "[report] ask_with_report[TOTAL]",
        t_total_start,
        extra={
            "ev_count": len(ev_compact),
            "docs": compressed_for_llm.get("agg", {}).get("docs"),
        },
    )
    
    return result


