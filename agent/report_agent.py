#agent/report_agent.py
from typing import Any, Dict, List, Optional, TypedDict
import json
from .data_agent import _run_data_agent
#from .tools_es import ESSearchNews, ESTimeline, ESFetchDocById
from .tools_es import ESFetchDocById
#from .tools_stats import AggregateMonthQuarter
from agent.llm_utils.ollama_client import call_llm  # 你既有的封裝
from agent.utils_citations import _build_citations_from_payload
from agent.utils_citations import compress_evidence

_es_fetch_doc_tool = ESFetchDocById()

class ReportPlan(TypedDict):
    need_full_docs: bool
    max_full_docs: int
    reason: str
    
REPORT_PLANNER_SYSTEM_PROMPT = """
你是一個「報告規劃助手」，負責判斷這次問題需不需要載入『參考資料原文全文』來協助撰寫報告。

你會收到一個 JSON 物件，格式大致如下（是精簡版的統計與片段）：

{
  "q": "使用者原始問題",
  "agg": {
    "docs": 整體文件數,
    "snips": 整體片段數,
    "active_days": 有活動紀錄的天數,
    "month": [ ["YYYY-MM", count], ... ],
    "quarter": [ ["YYYY-Qx", count], ... ],
    "peak_days": [ ["YYYY-MM-DD", count], ... ],
    "first_last": ["第一天日期", "最後一天日期"]
  },
  "ev": [
    {
      "id": "原始 uuid",
      "d": "YYYY-MM-DD",
      "title": "原文標題",
      "s": "subject（如 DF-15_225_20）",
      "note": "原始片段文字（節錄）"
    },
    ...
  ]
}

請只做下面這三件事：

1. 判斷這次任務是否「需要逐篇、逐段閱讀原文」：
   - 若問題只要求：整體趨勢、月份/季度分佈、是否增加或減少、列出幾個代表性事件、
     或是「逐條引述、加註來源」這種可以用片段（ev.note + 日期 + 標題）完成的需求，
     通常『不需要』全文，片段與統計就足夠。
   - 若問題明確要求：逐句檢視、全文比對、比對不同版本全文差異、
     或是要檢查片段以外的上下文細節，才傾向『需要』全文。
   - 若問題是在延續前一輪，並明講要「針對原文/全文」做分析 → 傾向『需要』全文。

2. 給出建議要抓幾篇全文（max_full_docs）：
   - 如果 ev 很多，但問題只需要一些代表案例，建議 3～5 篇即可。
   - 如果 ev 數量本來就很少（例如 <=5），可以設定成 ev 的數量。
   - max_full_docs 不能小於 0，也不要超過 10。

3. 用簡短文字說明原因（reason），方便後端 log/debug。

輸出格式（嚴格照此 JSON 結構，不要有多餘欄位）：

{
  "need_full_docs": true 或 false,
  "max_full_docs": 整數,
  "reason": "簡短說明"
}
"""


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
  ],
  "full_docs": [
    {
      "id": "原始 uuid",
      "d": "YYYY-MM-DD",
      "title": "原文標題",
      "s": "subject",
      "body": "完整內文"
    },
    ...
  ]
}

請嚴格遵守：

1. 所有「具體事實（日期、事件順序、主題）」只能來自：
   - agg 提供的統計數字（docs/snips/active_days/month/quarter/peak_days/first_last）
   - ev 裡的 note/title/d
   - full_docs 裡的 body/title/d
2. 不可以捏造不存在的數字（例如次數、比例、百分比）。資料沒有，就不要硬猜。
3. 可以對趨勢做定性描述（例如「逐漸增加」「集中在第一季」），
   但不得和 agg 的數字矛盾。
4. 引用具體事件時，請簡要說明來源片段，例如：
   「根據 2025-08-15 一則標題為『114/08/15 聯合情監偵綜整回報』的片段……」，
   內容可以用自己的話轉述。
5. 如果資料明顯不足以完整回答問題，請直接說明「目前資料不足以完整回答」，
   並仍然說明能看出的現象。
6. 以條列 + 小段落方式寫出清楚、有邏輯的分析報告，使用繁體中文。
7. 有 full_docs 時，可以用來：
   - 做較長段的引用、
   - 觀察用語差異、
   - 釐清片段沒看清楚的上下文。
   但避免將整篇原文長段落貼出，仍以摘要與重點為主，除非使用者指定想要整篇原文。
   - 注意：有時候 full_docs 只包含「部分原文」，例如：
  agg.docs 很多，但 full_docs 只有 1～3 篇，代表本次報告只對少數代表性原文做深入檢視。
  這種情況下，請在報告最後簡短提醒：
  「本次僅針對部分原文做深入分析，其餘資料仍以片段與統計為基礎；若需逐篇檢視，建議縮小時間範圍或分次查詢。」
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

def decide_report_full_docs(compressed_for_llm: dict) -> ReportPlan:
    """
    用 LLM 判斷本次報告是否需要載入原文全文，
    並建議最多要抓幾篇。
    """
    ev = compressed_for_llm.get("ev") or []
    agg = compressed_for_llm.get("agg") or {}
    q = (compressed_for_llm.get("q") or "").strip()
        
    # ev 太少或根本沒有，就算想看全文也沒東西可抓
    ev = compressed_for_llm.get("ev") or []
    if not ev:
        return {
            "need_full_docs": False,
            "max_full_docs": 0,
            "reason": "沒有 evidence 片段，無全文可抓。"
        }
    
    docs = agg.get("docs", 0) or 0
    snips = agg.get("snips", 0) or 0

    # ⭐ 1) 本地 heuristic：資料量不大、問題沒強調「逐句/逐段/全文」，就用片段即可
    #    → 這一條就直接 cover 你這個敘利亞 2013–2017 的案例
    strong_full_kw = ["逐句", "逐段", "逐篇", "全文比對", "完整原文", "看原文全文"]
    has_strong_full = any(kw in q for kw in strong_full_kw)

    if docs <= 10 and snips <= 30 and not has_strong_full:
        return {
            "need_full_docs": False,
            "max_full_docs": 0,
            "reason": f"docs={docs}, snips={snips}，資料量不大且問題未明講逐句/逐段/全文；片段已足夠支撐報告。"
        }

    # ⭐ 2) 如果題目有非常明講「原文/全文」再交給 LLM planner 判斷
    #    （下面開始才是你原本的 planner 流程）
    # 為了控制 token，可以先縮減 ev 的 note 長度（只給前幾則＆前幾字）
    
    # 為了控制 token，可以先縮減 ev 的 note 長度（只給前幾則＆前幾字）
    ev_preview = []
    for e in ev[:8]:  # 最多看前 8 則片段
        note = e.get("note") or ""
        if len(note) > 120:
            note = note[:120] + " ..."
        ev_preview.append({
            "id": e.get("id"),
            "d": e.get("d"),
            "title": e.get("title"),
            "s": e.get("s"),
            "note": note,
        })

    planner_input = {
        "q": compressed_for_llm.get("q"),
        "agg": compressed_for_llm.get("agg"),
        "ev": ev_preview,
    }

    user_prompt = json.dumps(
        planner_input,
        ensure_ascii=False,
        separators=(",", ":")
    )

    raw = call_llm(
        user_prompt,
        system_prompt=REPORT_PLANNER_SYSTEM_PROMPT,
        extra_params={},
        timeout=120.0,
    )

    # 嘗試解析 JSON（看你現有 call_llm 是不是就保證回 JSON，如果已經保證，可以省這段）
    try:
        parsed = json.loads(raw)
    except Exception:
        # 當作 planner 失敗 → 保守不抓全文
        return {
            "need_full_docs": False,
            "max_full_docs": 0,
            "reason": "planner 輸出非合法 JSON，略過全文。"
        }

    need_full = bool(parsed.get("need_full_docs"))
    max_docs = int(parsed.get("max_full_docs") or 0)
    if max_docs < 0:
        max_docs = 0
    if max_docs > 3:
        max_docs = 3

    reason = str(parsed.get("reason") or "").strip() or "無說明"

    return {
        "need_full_docs": need_full,
        "max_full_docs": max_docs,
        "reason": reason,
    }


def fetch_full_docs_for_report(
    snippets: List[dict],
    max_docs: int,
    index_hint: Optional[str] = None,
    text_field: Optional[str] = "rawInfo.content",
) -> List[dict]:
    """
    根據 evidence_snippets，實際去 ES 抓全文，回傳給 LLM 用的 full_docs 陣列。
    每筆格式大致為：
    {
        "id": uuid,
        "d": "YYYY-MM-DD",
        "title": "...",
        "s": "subject",
        "body": "完整內文"
    }
    """
    if max_docs <= 0:
        return []

    # ⭐ 再保險一次，這個函式永遠最多只會抓 3 篇
    HARD_FULL_DOC_LIMIT = 3
    if max_docs > HARD_FULL_DOC_LIMIT:
        max_docs = HARD_FULL_DOC_LIMIT
        
    full_docs: List[dict] = []
    seen: set[str] = set()

    for s in snippets:
        if len(full_docs) >= max_docs:
            break

        uuid = s.get("uuid") or s.get("id")
        if not uuid or uuid in seen:
            continue
        seen.add(uuid)

        try:
            out = _es_fetch_doc_tool.forward(
                uuid=uuid,
                index_hint=index_hint,
                text_field=text_field,
            )
        except Exception as e:
            print(f"[fetch_full_docs_for_report] error fetching {uuid}: {e}")
            continue

        full_text = (out or {}).get("full_text") or ""
        if not isinstance(full_text, str):
            full_text = str(full_text)

        full_text = full_text.strip()
        if not full_text:
            continue

        # ⭐ 內文太長時做截斷，避免把上下文塞爆
        MAX_BODY_CHARS = 4000  # 可依模型 context 再調整
        if len(full_text) > MAX_BODY_CHARS:
            full_text = full_text[:MAX_BODY_CHARS] + "\n...[內容過長已截斷，僅保留前段作為分析參考]"


        # 從 snippet 裡帶一些 metadata（日期/標題/subject）
        full_docs.append({
            "id": uuid,
            "d": s.get("article_date_iso") or s.get("date_iso") or s.get("d"),
            "title": s.get("article_title") or s.get("title"),
            "s": s.get("subject") or s.get("s"),
            "body": full_text,
        })

    return full_docs



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
    need_full_docs_hint: bool | None = None,
    max_full_docs_hint: int | None = None,
) -> Dict[str, Any]:
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

    # === 決策：這次需不需要拉全文？ ===
    # 先決定要不要用 planner；若上游有硬指定 hint，就以 hint 為主
    plan: ReportPlan
    if need_full_docs_hint is not None:
        plan = {
            "need_full_docs": bool(need_full_docs_hint),
            "max_full_docs": int(max_full_docs_hint or 0),
            "reason": "上游 hint 指定，不經過 planner。",
        }
    else:
        plan = decide_report_full_docs(compressed_for_llm)

    # 這裡先簡單印 log（你也可以換成 log4 / print）
    print("[report_agent] plan_full_docs =", plan)
    # === 若需要全文，這裡實際去 ES 抓 ===
    full_docs: List[dict] = []
    if plan.get("need_full_docs") and plan.get("max_full_docs", 0) > 0:
        ev_full = payload.get("evidence_snippets") or []
        # 如果 data_agent 有記錄 index_hint，可以從 payload 拿；沒有就傳 None
        index_hint = payload.get("index_hint")  # 若沒有此欄位就會是 None
        full_docs = fetch_full_docs_for_report(
            snippets=ev_full,
            max_docs=plan.get("max_full_docs", 0),
            index_hint=index_hint,
            text_field="rawInfo.content",  # 依你的索引實際欄位調整
        )

        if full_docs:
            compressed_for_llm["full_docs"] = full_docs
        else:
            print("[report_agent] plan 要全文，但實際沒抓到任何 full_docs。")
    else:
        # 不需要全文的情況，可以印個 log 方便 debug
        print("[report_agent] skip fetching full docs.")
        
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

    return {
        "answer": report_text,
        "citations": citations,
        "reasoning": reasoning,
        # 如果你想 debug 也可以順便把 compressed_for_llm 回傳：
        # "debug_payload_for_llm": compressed_for_llm,
    }
