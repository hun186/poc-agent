#agent/report_agent.py
from typing import Any, Dict, List
import json
from .data_agent import _run_data_agent
#from .tools_es import ESSearchNews, ESTimeline, ESFetchDocById
#from .tools_stats import AggregateMonthQuarter
from agent.llm_utils.ollama_client import call_llm  # 你既有的封裝
from agent.utils_citations import _build_citations_from_payload
from agent.utils_citations import compress_evidence

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
      "d": "YYYY-MM-DD",
      "title": "原文標題",
      "s": "subject（如 DF-15_225_20）",
      "note": "原始片段文字"
    },
    ...
  ]
}

請嚴格遵守：

1. 所有「具體事實（日期、事件順序、主題）」只能來自：
   - agg 提供的統計數字（docs/snips/active_days/month/quarter/peak_days/first_last）
   - ev 裡的 note/title/d。
2. 不可以捏造不存在的數字（例如次數、比例、百分比）。資料沒有，就不要硬猜。
3. 可以對趨勢做定性描述（例如「逐漸增加」「集中在第一季」），
   但不得和 agg 的數字矛盾。
4. 引用具體事件時，請簡要說明來源片段，例如：
   「根據 2025-08-15 一則標題為『114/08/15 聯合情監偵綜整回報』的片段……」，
   內容可以用自己的話轉述。
5. 如果資料明顯不足以完整回答問題，請直接說明「目前資料不足以完整回答」，
   並仍然說明能看出的現象。
6. 以條列 + 小段落方式寫出清楚、有邏輯的分析報告，使用繁體中文。

輸出時：
- 不要再輸出 JSON，直接輸出可閱讀的中文說明即可。
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
    

def ask_with_report(question: str) -> Dict[str, Any]:
    # 第 1 階段：取得 payload（純資料）
    payload = _run_data_agent(question, mode="report")

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

    # === 仍然在原始 payload 上補充 related_articles（給前端 / citation 用） ===
    ev_full = payload.get("evidence_snippets") or []
    related_map: Dict[str, Dict[str, Any]] = {}

    for s in ev_full:
        uuid_ = s.get("uuid")
        if not uuid_:
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

    # === 第 2 階段：用「精簡版」 payload 餵報告 LLM ===
    #   不再用原本的 payload_for_llm / evidence_snippets
    user_prompt = json.dumps(
        compressed_for_llm,
        ensure_ascii=False,
        separators=(",", ":")   # 再瘦一點 JSON
    )

    report_text = call_llm(
        user_prompt,
        system_prompt=REPORT_SYSTEM_PROMPT,
        extra_params={
            "options": {
                #"num_ctx": 1024*32,             # 看你的模型上限調
                #"num_predict": 1024*12,         # 限制生成長度，避免寫太長拖很久
            }
        },
        timeout=180.0,
    )

    # === 控制前端要用的 evidence_snippets 數量 ===
    ev_for_frontend = payload.get("evidence_snippets") or []
    if len(ev_for_frontend) > 100:
        ev_for_frontend = ev_for_frontend[:100]
        payload["evidence_snippets"] = ev_for_frontend

    # citations 還是從「原始 payload」來
    citations = _build_citations_from_payload(payload)

    reasoning = (
        "本回答根據 es_search_news 的查詢結果與 aggregate_month_quarter 所提供的統計，"
        "並綜整 evidence_snippets 及相關文章所做的資料驅動分析。"
    )

    # ★ 新增：整理本輪實際有用到的 uuid（順序照 evidence_snippets）
    used_uuids: List[str] = []
    for s in payload.get("evidence_snippets") or []:
        u = s.get("uuid")
        if u and u not in used_uuids:
            used_uuids.append(u)

    return {
        "answer": report_text,
        "citations": citations,
        "reasoning": reasoning,
        "used_uuids": used_uuids,          # ★ 給前端帶去下一輪當 reuse_uuids
        # "debug_payload_for_llm": compressed_for_llm,
    }

