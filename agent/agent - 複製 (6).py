# agent/agent.py
from dotenv import load_dotenv
load_dotenv()

import os
import json
from functools import lru_cache
from typing import Any, Dict, List
from smolagents import CodeAgent, LiteLLMModel, PythonInterpreterTool
#from .agent_utils import aggregate_month_quarter
from .tools_es import ESSearchNews, ESTimeline
from .tools_stats import AggregateMonthQuarter
from agent.llm_utils.ollama_client import call_llm  # 你既有的封裝

#print("finished load module")

# 建議：模型共用、Agent 每請求新建
_SHARED_MODEL = None

# === 模型設定（可用 .env 覆寫） ===
MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))

SYSTEM = """
你是一個『新聞/情報/政策的資料準備代理人』。

你的任務只有一件事：
- 產生一段 Python 程式碼，呼叫工具把資料查回來、做完統計，組成 payload（JSON 結構），然後交給後續的「報告撰寫 LLM」使用。
- 你自己不要撰寫長篇報告或結論，只負責準備乾淨的資料。

【基本流程】

1. 取得使用者問題字串，存在變數 question，例如：

   question = "請整理 2025 年『拉拉隊』相關的重點事件，並做趨勢分析。"

2. 在程式一開始，先依 question 萃取 3–8 個關鍵字（主題、地點），時間資訊用於其他檢索引數，不要放到core_terms：

   core_terms = [
       # 例如: "敘利亞", "化學武器"
   ]
   core_query = " ".join(core_terms)

   若你無法明確列出 terms，就至少把 question 中的「請整理」「綜整成」「趨勢分析」
   「SWOT 分析」「目標長度為」「完整報告」等片語去掉，只留下主題與時間。

   如果使用者有提供資料時間起迄點，在呼叫工具時，一併填入引數date_from及date_to；如果沒有，則填入None。
   
   然後用 core_query 當成 es_search_news 的 query 參數，而不是原始 question：

   search_result = es_search_news(
       query=question,
       must_high_value=False,
       must_selected=False,
       size=10000,
       date_from=...,   # 若使用者有指定日期，再改成 "YYYY-MM-DD"
       date_to=...,     # 同上
       selected_boost=6.0,
       high_value_boost=2.5,
       recency_boost=False,
       recency_field="importDT",
       recency_scale="30d",
   )

   # 從結果中取出 evidence_snippets：
   evidence_snippets = search_result.get("evidence_snippets", [])

3. 若需要做時間統計，請一律呼叫 aggregate_month_quarter：

   aggregation = aggregate_month_quarter(evidence_snippets=evidence_snippets)
   doc_count      = aggregation.get("doc_count", 0)
   snippet_count  = aggregation.get("snippet_count", 0)
   active_days    = aggregation.get("active_days", 0)
   day_counts     = aggregation.get("day_counts", {})
   month_counts   = aggregation.get("month_counts", {})
   quarter_counts = aggregation.get("quarter_counts", {})

4. 如果 es_search_news 有傳入 date_from / date_to，請再針對 day_counts / month_counts / quarter_counts 做一次日期過濾，只保留落在範圍內的 key，類似：

   start_date = date_from  # 例如 "2025-05-01"；若沒有就設為 None
   end_date   = date_to    # 例如 "2025-05-31"；若沒有就設為 None

   if start_date or end_date:
       # 過濾 day_counts
       filtered_day_counts = {}
       for d, cnt in day_counts.items():
           if start_date and d < start_date:
               continue
           if end_date and d > end_date:
               continue
           filtered_day_counts[d] = cnt
       day_counts = filtered_day_counts

       # 過濾 month_counts（只保留完全落在範圍內的月份）
       filtered_month_counts = {}
       for m, cnt in month_counts.items():  # m 形式如 "2025-05"
           m_year = m[0:4]
           m_month = m[5:7]
           m_first = f"{m_year}-{m_month}-01"
           m_last  = f"{m_year}-{m_month}-31"   # 簡化處理即可
           if start_date and m_last < start_date:
               continue
           if end_date and m_first > end_date:
               continue
           filtered_month_counts[m] = cnt
       month_counts = filtered_month_counts

       # 過濾 quarter_counts（例如 "2025-Q2"）
       filtered_quarter_counts = {}
       for q, cnt in quarter_counts.items():
           q_year = q[0:4]
           q_id = q[-1]   # '1'..'4'
           if q_id == "1":
               q_first, q_last = f"{q_year}-01-01", f"{q_year}-03-31"
           elif q_id == "2":
               q_first, q_last = f"{q_year}-04-01", f"{q_year}-06-30"
           elif q_id == "3":
               q_first, q_last = f"{q_year}-07-01", f"{q_year}-09-30"
           else:
               q_first, q_last = f"{q_year}-10-01", f"{q_year}-12-31"

           if start_date and q_last < start_date:
               continue
           if end_date and q_first > end_date:
               continue
           filtered_quarter_counts[q] = cnt
       quarter_counts = filtered_quarter_counts

5. 把要給報告 LLM 用的內容組成 payload，至少包含：

   payload = {
       "question": question,
       "time_range": {
           "date_from": date_from,
           "date_to": date_to,
       },
       "stats": {
           "doc_count": doc_count,
           "snippet_count": snippet_count,
           "active_days": active_days,
           "day_counts": day_counts,
           "month_counts": month_counts,
           "quarter_counts": quarter_counts,
       },
       "evidence_snippets": evidence_snippets,
       "raw_search_result": search_result,
   }

6. 程式最後 **只做一件事**：呼叫 final_answer，回傳 payload，絕對不要在這裡寫完整報告文字。

   final_answer({
       "payload": payload
   })

【嚴格規則】

- 程式必須包在單一 <code>...</code> 區塊中，內容是純 Python 程式。
- 禁止在 <code> 區塊之外輸出任何 Markdown 或自然語言。
- 呼叫工具時：
    * 一律先拿到 search_result，再用 search_result.get("evidence_snippets", [])；
      禁止寫成 evidence_snippets = es_search_news(...)
    * es_search_news 的 size 一律設為 10000。
- 不要在這一層寫「趨勢描述」「評估效果」「政策建議」等文字，
  那些全部交給後續報告 LLM 根據 payload 來處理。
- 回答語系一律使用繁體中文臺灣用語，但因為你不寫報告，只要確保程式內字串（如 question）是繁體即可。
"""

REPORT_SYSTEM_PROMPT = """
你是一個『資料驅動的分析助手』。

你會收到一個 JSON 物件 payload（由上一層代理人產生），格式大致如下：

{
  "question": "...使用者原始問題...",
  "time_range": {
    "date_from": "YYYY-MM-DD 或 null",
    "date_to": "YYYY-MM-DD 或 null"
  },
  "stats": {
    "doc_count": ...,
    "snippet_count": ...,
    "active_days": ...,
    "day_counts": {...},
    "month_counts": {...},
    "quarter_counts": {...}
  },
  "evidence_snippets": [
    {
      "uuid": "...",
      "text": "...",
      "date_iso": "YYYY-MM-DD",
      "article_date_iso": "YYYY-MM-DD",
      "subject": "...",
      "article_title": "...",
      "source_id": "...",
      "paragraph_id": "..."
    },
    ...
  ],
  "raw_search_result": {...}
}

請嚴格遵守：

1. 所有「具體事實（日期、事件順序、主題）」只能來自 stats 或 evidence_snippets。
2. 不可以捏造不存在的數字（例如病例數、百分比、金額）。資料沒有，就不要硬猜。
3. 可以對趨勢做合理的定性描述（例如「逐漸增加」「集中在 2024–2025 年間」），
   但不得和 stats 的數字矛盾。
4. 引用具體事件時，請簡要說明來源片段（例如「根據 2024-03-15 的一則報導……」），
   內容可以用自己的話轉述。
5. 如果資料明顯不足以回答問題，請直接說明「目前資料不足以完整回答」，並仍然給出你能看出的現象。
6. 以條列 + 小段落方式寫出清楚、有邏輯的分析報告，使用繁體中文。

輸出時：
- 不要再輸出 JSON，直接輸出可閱讀的中文說明即可。
"""


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

        
def _normalize_model_id(mid: str) -> str:
    if "/" in mid:
        return mid
    return f"ollama_chat/{mid}"  # ← 走 /api/chat
'''
@lru_cache(maxsize=8)  # 依參數組合做快取，避免單例污染
def build_model(
    *,
    base_url: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
    model_id: str | None = None,
    temperature: float = 0.0,
    extra_kwargs: dict | None = None,
    extra_generation_kwargs: dict | None = None,
):
    """
    向後相容的建模器：
    - 接受 base_url/api_base 與 model/model_id 兩種命名
    - 把 extra_kwargs / extra_generation_kwargs 合併後往下傳
    - 以 (model_id, api_base, temperature, frozenset(extra.items())) 作為快取 key
    """
    # 參數整併（兼容兩組命名）
    print("start to run build_model")
    api_base = api_base or base_url or os.getenv("MODEL_BASE_URL", "http://localhost:11434")
    model_id = model_id or model or os.getenv("MODEL_ID", "gpt-oss:120b-32k")
    temperature = float(temperature or os.getenv("MODEL_TEMPERATURE", "0"))
    print("got parameters")
    # 合併兩種 extra
    extra = {}
    if isinstance(extra_generation_kwargs, dict):
        extra.update(extra_generation_kwargs)
    if isinstance(extra_kwargs, dict):
        extra.update(extra_kwargs)

    # 預設禁止工具（需要時再在外層開）
    extra.setdefault("tool_choice", "none")
    print("start to build llm in build_model")
    # >>> 這裡請確定 LiteLLMModel 的參數名稱正確 <<<
    # 如果你的 LiteLLMModel 其實要用 base_url/model，而不是 api_base/model_id，就把下面兩個參數名對應改成它支援的。
    llm = LiteLLMModel(
        model_id=model_id,          # 若你的實作是 `model=...`，就改成 model=model_id
        api_base=api_base,          # 若你的實作是 `base_url=...`，就改成 base_url=api_base
        temperature=temperature,
        extra_generation_kwargs=extra  # 若你的實作用 `model_kwargs` 或 `extra_kwargs`，就改成那個
    )
    return llm
'''

def build_model():
    global _SHARED_MODEL
    if _SHARED_MODEL is not None:
        return _SHARED_MODEL
    model_id = _normalize_model_id(MODEL_ID)
    _SHARED_MODEL = LiteLLMModel(
        model_id=model_id,
        api_base=MODEL_BASE_URL,
        temperature=MODEL_TEMPERATURE,
        # 只保留這個即可，避免誤截斷
        extra_generation_kwargs={"tool_choice": "none"}
    )
    return _SHARED_MODEL

def build_model_old():
    model_id = _normalize_model_id(MODEL_ID)
    return LiteLLMModel(
        model_id=model_id,
        api_base=MODEL_BASE_URL,
        temperature=MODEL_TEMPERATURE,
        # ↓ 若你這版 smolagents 支援，等同告訴底層「不要用工具呼叫」
        extra_generation_kwargs={
            "tool_choice": "none"
        }
    )
'''
def build_model():
    model_id = _normalize_model_id(MODEL_ID)
    return LiteLLMModel(
        model_id=model_id,
        api_base=MODEL_BASE_URL,
        temperature=MODEL_TEMPERATURE
    )
'''
def _make_code_agent(tools, model):
    """
    嘗試不同 smolagents 版本常見的參數組合：
    - 新版：model=..., instructions=...
    - 舊版：llm=..., system_prompt=...
    如果前面都失敗，再退而求其次用「不帶 SYSTEM」版本。
    """
    common_kwargs = {
        "tools": tools,
        "additional_authorized_imports": ["json"],
    }

    print("[agent] building CodeAgent: try model + instructions")
    try:
        agent = CodeAgent(
            model=model,
            instructions=SYSTEM,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with model+instructions")
        return agent
    except TypeError as e:
        print("[agent] model+instructions failed:", e)

    print("[agent] try llm + system_prompt")
    try:
        agent = CodeAgent(
            llm=model,
            system_prompt=SYSTEM,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with llm+system_prompt")
        return agent
    except TypeError as e:
        print("[agent] llm+system_prompt failed:", e)

    print("[agent] try model only")
    try:
        agent = CodeAgent(
            model=model,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with model only")
        return agent
    except TypeError as e:
        print("[agent] model only failed:", e)

    print("[agent] try llm only")
    try:
        agent = CodeAgent(
            llm=model,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with llm only")
        return agent
    except TypeError as e:
        print("[agent] llm only failed:", e)
        raise RuntimeError(
            f"無法用目前 smolagents 版本建立 CodeAgent，"
            f"請確認 __init__ 參數。原始錯誤：{e}"
        )

def build_agent():
    model = build_model()
    #print("start to build_agent")
    tools = [ESSearchNews(), ESTimeline(), AggregateMonthQuarter(),
             PythonInterpreterTool(),
             ]
    #print("returning in build_agent")
    return _make_code_agent(tools, model)

# 提供單例
#_agent = build_agent()
#def get_agent():
#    return _agent

'''
def get_agent():
     #⚠️ 回傳「新的」Agent（保持無歷史、無殘留）
    return build_agent()
'''

def get_agent() -> ReportAgent:
    # 之後任何地方呼叫 get_agent()，拿到的都是這個兼容舊介面的 Agent
    return ReportAgent()

'''
def get_agent(disable_tools: bool=False, exclude_tools: tuple[str, ...]=()):
    base_url = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
    model_id = os.getenv("MODEL_ID", "gpt-oss:120b-32k")
    temp = float(os.getenv("MODEL_TEMPERATURE", "0"))

    # 關工具：傳 tool_choice=none；要開再把 tools 傳進 CodeAgent（而不是傳 tools 給底層 LLM）
    extra = {"tool_choice": "none"} if disable_tools else {}
    print("start to build llm")
    try:
        llm = build_model(
            base_url=base_url,
            model=model_id,
            temperature=temp,
            extra_kwargs=extra,
        )
    except Exception as ex:
        print(ex)
    print("finished building llm")
    # 別再用 list(MODEL_ID) 當工具清單了…
    tools = []
    if not disable_tools:
        try:
            from agent.tools import DEFAULT_TOOLS
            tools = [t for t in DEFAULT_TOOLS if not exclude_tools or t.name not in set(exclude_tools)]
        except Exception:
            tools = []

    return CodeAgent(llm=llm, tools=tools, system=SYSTEM)
'''

def _run_data_agent(question: str) -> Dict[str, Any]:
    """
    只負責呼叫 CodeAgent（依 SYSTEM 規則），取得 payload。
    不要用 get_agent() 以免和 ReportAgent 互相遞迴。
    """
    code_agent = build_agent()  # 這個會建立 CodeAgent + 工具（ESSearchNews 等）
    result = code_agent.run(question)

    # 預期 final_answer({"payload": payload}) → result 是 dict 且有 "payload"
    if isinstance(result, dict) and "payload" in result:
        return result["payload"]

    # 若之後 CodeAgent 直接回 payload（沒有包一層），也一起容錯
    if isinstance(result, dict):
        return result

    raise ValueError("資料代理人回傳格式非 dict，請檢查 CodeAgent 的 final_answer 使用方式。")

def ask_with_report(question: str) -> Dict[str, Any]:
    """
    兩階段：
    1) 用 CodeAgent 依 question 查 ES 並做統計，拿到 payload
    2) 把 payload 丟給報告 LLM，產生最後的文字報告
    3) 回傳 dict，給 FastAPI 的 render_markdown 使用
    """
    # 第 1 階段：取得 payload（純資料）
    payload = _run_data_agent(question)

    # === NEW 1：從 evidence_snippets 推回「相關原始文章」清單 ===
    ev = payload.get("evidence_snippets") or []
    related_map: Dict[str, Dict[str, Any]] = {}

    for s in ev:
        uuid_ = s.get("uuid")
        if not uuid_:
            continue
        if uuid_ in related_map:
            # 已經收過同一篇文章，就不用重複塞
            continue

        related_map[uuid_] = {
            "uuid": uuid_,
            "article_title": s.get("article_title"),
            # 優先用 article_date_iso，沒有再退回 date_iso
            "article_date_iso": s.get("article_date_iso") or s.get("date_iso"),
            "subject": s.get("subject"),
            "source_id": s.get("source_id"),
        }

    payload["related_articles"] = list(related_map.values())

    # === NEW 2：準備給報告 LLM 的精簡版 payload（移除 raw_search_result） ===
    payload_for_llm = dict(payload)  # 淺拷貝一份，避免影響原始 payload
    payload_for_llm.pop("raw_search_result", None)

    # 第 2 階段：用報告 LLM 產出文字報告
    user_prompt = json.dumps(payload_for_llm, ensure_ascii=False)
    report_text = call_llm(
        user_prompt,
        system_prompt=REPORT_SYSTEM_PROMPT
    )

    # ★ 控制 evidence_snippets 數量，避免 payload 過大（保留給前端當 citation）
    #ev = payload.get("evidence_snippets") or []
    #if len(ev) > 50:
    #    ev = ev[:50]
    #    payload["evidence_snippets"] = ev

    # 從 payload 裡取 citation，對應到你的 render_markdown(out, request)
    citations = payload.get("evidence_snippets") or []

    reasoning = "本回答根據 Elasticsearch 查詢結果與統計資料（doc_count、month_counts 等）撰寫，未對原始數據以外的數字進行推測。"

    # ★ 從 payload 中組 citations，沿用舊代理人的結構
    citations = _build_citations_from_payload(payload)

    # ★ reasoning 可以先簡單一點，用 deterministic 字串就好，
    #   之後如果要讓 LLM 幫忙寫，也可以在 REPORT_SYSTEM_PROMPT 裡加要求回 JSON。
    reasoning = (
        "本回答根據 es_search_news 的查詢結果與 aggregate_month_quarter 所提供的統計，"
        "並綜整 evidence_snippets 及相關文章所做的資料驅動分析。"
    )

    return {
        "answer": report_text,
        "citations": citations,
        "reasoning": reasoning,
    }

def _build_citations_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    ev = payload.get("evidence_snippets") or []
    citations: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for s in ev:
        if not isinstance(s, dict):
            continue
        doc_id = s.get("source_id") or s.get("uuid")
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)

        citations.append({
            "text": s.get("text"),
            "source_id": doc_id,
            "uuid": s.get("uuid"),
            "paragraph_id": s.get("paragraph_id"),
            "date_iso": s.get("article_date_iso") or s.get("date_iso"),
            "subject": s.get("subject"),
            "article_title": s.get("article_title"),
        })
    return citations  
# 允許：python -m agent.agent 快速測試
if __name__ == "__main__":
    a = get_agent()
    #q = "請整理 2025/9/21–9/30 與『月薪5萬元免稅』、『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    q = "請整理2025年『拉拉隊』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    #q = "請整理 2025/9/21–9/30 與『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    #print(a.run(q))
    print(ask_with_report(q))

