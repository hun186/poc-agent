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
from agent.utils.profiler import log_duration, log_total
from agent.utils.markdown_tables import sanitize_markdown_tables

REPORT_MODEL_ID = (
    os.getenv("REPORT_MODEL_ID")   # 有指定就用這個
    or os.getenv("MODEL_ID")       # 沒有就沿用主 MODEL_ID
    or "gpt-oss:120b-32k"          # 再不然給一個預設
)

REPORT_SYSTEM_PROMPT = """
你是一個『資料驅動的分析助手』。

你會收到一個 JSON 物件 payload，格式大致如下（key 已簡化）：

{
  "q": "使用者原始問題",
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
      "id": "原始 uuid",
      "ref_no": 1,                      # ★ 這是此片段的固定編號（1-based）
      "d": "YYYY-MM-DD",
      "title": "原文標題",
      "s": "subject（如 DF-15_225_20）",
      "note": "原始片段文字"
    },
    ...
  ]
}

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
) -> Dict[str, Any]:
    if trace is None:
        trace = {}
    t_total_start = time.perf_counter()
    #payload = run_data_agent(question, mode="report")
    #payload = run_data_agent(question, mode="report", trace=trace)
    # ★ data_agent 區段時間
    with log_duration("[report] run_data_agent", extra={"mode": "report"}):
        payload = run_data_agent(question, mode="report", trace=trace)

    # ★ 先確保 payload["question"] 永遠有值
    payload_question = (payload.get("question") or question or "").strip()
    payload["question"] = payload_question or "[未提供使用者提問]"

    # === 精簡版（給報告 LLM 用） ===
    compressed_for_llm = {
        "q": payload.get("question"),
        "t": [
            payload.get("time_range", {}).get("date_from"),
            payload.get("time_range", {}).get("date_to"),
        ],
        "agg": compress_stats(payload.get("stats") or {}),
        "ev": compress_evidence(payload.get("evidence_snippets") or []),
    }

    ev_compact = compressed_for_llm["ev"] or []
    payload["ev"] = ev_compact

    # === related_articles：建議只列出 LLM 有用到的這些 doc ===
    ev_full = payload.get("evidence_snippets") or []
    used_ids = {str(e.get("id")) for e in ev_compact if e.get("id")}

    related_map: Dict[str, Dict[str, Any]] = {}
    for s in ev_full:
        uuid_ = s.get("uuid")
        if not uuid_:
            continue

        # ★ 只保留有出現在 ev_compact 的那些文章
        if used_ids and str(uuid_) not in used_ids:
            continue

        if uuid_ in related_map:
            continue

        related_map[uuid_] = {
            "uuid": uuid_,
            "article_title": s.get("article_title"),
            "article_date_iso": s.get("article_date_iso") or s.get("date_iso"),
            "subject": s.get("subject"),
            "source_id": s.get("source_id"),
        }

    payload["related_articles"] = list(related_map.values())

    # === 給 LLM 的 JSON ===
    user_prompt = json.dumps(
        compressed_for_llm,
        ensure_ascii=False,
        separators=(",", ":")
    )
    
    ev_for_llm = ev_compact
    print("=== DEBUG: EV (for LLM) ===")
    for e in ev_for_llm:
        print({
            "ref_no": e.get("ref_no"),
            "id": e.get("id"),
            "d": e.get("d"),
            "title": e.get("title"),
            "note_preview": (e.get("note") or "")[:100].replace("\n", " ")
        })
    t0 = time.perf_counter()
    with log_duration("[report] call_llm(report)",
        extra={"model_id": REPORT_MODEL_ID},
    ):
        report_text = call_llm(
            user_prompt,
            system_prompt=REPORT_SYSTEM_PROMPT,
            extra_params={"options": {}},
            timeout=180.0,
            model=REPORT_MODEL_ID,
        )
    t1 = time.perf_counter()
    
    # ★ 修復 LLM 產出的所有 Markdown 表格（不限欄數）
    print(f"DEBUG: report_text before Sanitized Markdown Row: {report_text}")
    if isinstance(report_text, str) and report_text.strip():
        report_text = sanitize_markdown_tables(report_text)
    print(f"DEBUG: report_text after Sanitized Markdown Row: {report_text}")
    # ★ 把這次報告 LLM 寫到 trace["llm"]["report"]
    llm_root = trace.setdefault("llm", {})
    report_logs: list[Dict[str, Any]] = llm_root.setdefault("report", [])
    report_logs.append({
        "system": "REPORT_SYSTEM_PROMPT",
        "user": user_prompt,
        "answer_preview": (report_text[:200] if isinstance(report_text, str) else str(report_text)[:200]),
        "elapsed_sec": round(t1 - t0, 3),
        "model_id": REPORT_MODEL_ID,
    })
    
    # === evidence_snippets 仍可保留給其他用途（例如前端展開全文），但不再用來建 citations ===
    ev_for_frontend = payload.get("evidence_snippets") or []
    if len(ev_for_frontend) > 150:
        ev_for_frontend = ev_for_frontend[:150]
        payload["evidence_snippets"] = ev_for_frontend

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
    print("report_text",report_text)
    result: Dict[str, Any] = {
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


