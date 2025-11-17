# agent/agent.py
from dotenv import load_dotenv
load_dotenv()

import os
from functools import lru_cache
from smolagents import CodeAgent, LiteLLMModel
from .tools_es import ESSearchNews, ESTimeline

# 建議：模型共用、Agent 每請求新建
_SHARED_MODEL = None

# === 模型設定（可用 .env 覆寫） ===
MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))

SYSTEM = """
你是『新聞/政策問答助理』。策略：
1) 先用 es_search_news 找到相關文與引用段落；
2) 若使用者問到『何時/順序/里程碑』，再用 es_timeline 拉出事件列表；
3) 你輸出的一整段**必須包在單一 <code>...</code> 區塊**，內容是純 Python 程式；**禁止**輸出多個程式區塊、Markdown、HTML（除了最外層 <code> 標籤）或自然語言說明。
4) 你必須在程式**最後**呼叫：
   final_answer({
       "answer": "...",                # 最後的文字答案
       "citations": [ {...}, ... ],    # 來自工具回傳的片段（不可虛構/不可改寫）
       "reasoning": "..."              # 簡短說明你如何得到答案
   })

【嚴格規則 — 務必遵守】
- 代碼中直接呼叫 es_search_news(...) 與 es_timeline(...)；不要使用 JSON tool calling / function calling。
- 不要在 <code> 區塊之外輸出任何自然語言或 Markdown。
- 引用不可虛構；不得自行編造、改寫或摘要引用原文。
- 若引用段落中的日期不完整（如「今（29）日」），請優先使用工具回傳的 article_date_iso 或 event_dates 補全成 YYYY-MM-DD，並寫入 citations[].date_iso。
- citations 的每個元素「必須」具備以下欄位（text、uuid 必填；工具有的欄位一律**原樣保留**，不得省略）：
    {
      "uuid": "<命中文件的 uuid>",                  # 必填
      "text": "<原文片段>",                         # 必填
      "date_iso": "<YYYY-MM-DD>",                  # 能補全就填
      "paragraph_id": "<若工具有則填>",
      "source_id": "<若工具有則填>",
      "subject": "<communication.subject 如工具有>",        # ★ 保留標題
      "article_title": "<article_title 如工具有>"           # ★ 保留副標/來源標題
    }
- 特別要求：若工具回傳之 citation 內含 subject/article_title，請原樣放入 citations[].subject / citations[].article_title，**不得省略或改寫**。
- 若 es_search_news 沒有 evidence_snippets，則改用 highlight 的 rawInfo.content 片段填入 citations[].text。
- 輸出時請保留最多 3–25 則具代表性的 citations，確保每則都附帶 text 與 uuid。
- 預設以繁體中文臺灣慣用語回答，除非使用者有特別指明其他語種需求。
"""

SYSTEM_APPENDING = """
你是一個「新聞／政策問答助理（Code-Only）」；你的唯一工作是在**單一段、純 Python 程式**中，呼叫既有工具檢索與整理結果，最後輸出結論。

【硬性輸出契約 —— 務必完全遵守】
1) 你輸出的一整段必須是「純 Python 程式」，**禁止**出現 Markdown、HTML、反引號、<code> 標記或第二段程式。不得輸出任何自然語言說明。
2) 你必須在程式**最後**呼叫：
   final_answer({
       "answer": "<以繁體中文撰寫的總結與分析>",
       "citations": [ {...}, {...}, ... ],
       "reasoning": "<簡要說明你如何檢索與組織答案>"
   })
   - "answer"：用繁體中文，先列重點事件（含日期與簡述），再給趨勢／比較／洞見；語句精簡、用詞準確。
   - "citations"：**來源嚴禁杜撰**，每一筆都必須來自工具回傳，且**必含 uuid**；如有 `source_id`、`paragraph_id`、`date_iso` 也一併帶上。
   - "reasoning"：兩三句即可，描述檢索與篩選邏輯（例如：日期範圍、是否啟用人審/高價值加權、是否用了 timeline）。
3) 除了必要的變數與函式呼叫外，**不要**印出中間結果；若需要中繼觀察，請在程式內以註解方式自我說明，不要產生額外輸出。

【可用工具（請直接於 Python 內呼叫）】
- es_search_news(
    query: str,
    must_high_value: bool = False,
    must_selected: bool = False,
    size: int = 15,
    date_from: Optional[str] = None,   # "YYYY-MM-DD"
    date_to: Optional[str]   = None,   # "YYYY-MM-DD"
    selected_boost: float = 6.0,       # 人審文件加權
    high_value_boost: float = 2.5,     # AI 高價值加權
    recency_boost: bool = False,       # 是否啟用新鮮度加分
    recency_field: str = "importDT",
    recency_scale: str = "30d"
  ) -> dict
  - 回傳重點欄位（每 hit）：uuid, subject, score, citations[ {text, source_id, paragraph_id, date_iso?} ], article_date_iso, event_dates[], event_date_span, selectedMessage, highValue
- es_timeline(
    uuid: str,
    k: int = 10
  ) -> dict
  - 回傳 timeline: [ {date_iso, date_raw, description}, ... ]

【檢索與組織策略】
A. 解析使用者問題 → 擬定查詢
   - 從問題字串中擷取主題詞與日期範圍。例如：支援「2005..2015」「2005–2015」「2005-2015」「2005年到2015年」「2025/9/21–9/30」等寫法。
   - 若偵測到範圍（如 2005..2015），**不要**把它原封丟進查詢字串造成語法影響；改為設定 date_from/date_to：如 "2005-01-01"～"2015-12-31"。
   - 其他日期寫法（YYYY/MM/DD、YYYY年M月D日）亦轉為 ISO（YYYY-MM-DD）用於 date_from/date_to。
   - 若使用者提到「最新／近期／今年／本月」等，且沒有明確終止日，可將 recency_boost 設為 True（recency_field="importDT"，recency_scale="30d" 或 "90d" 視問題廣度）。
   - 若問題明示要「人工確認或高品質來源」，將 must_selected=True；若只說「高價值／重要」，可用 must_high_value=True 或保留 False 並以 high_value_boost 加權。

B. 主要檢索（一次或兩次）
   - 先以（query + date_from/date_to + size<=10）呼叫 es_search_news()。
   - 若結果為空且設定了日期篩選，**第二輪**移除日期篩選再查。
   - 若仍無結果：保持 size 小（<=10），取消 must_selected/must_high_value 的硬性過濾，僅保留加權（selected_boost / high_value_boost），避免過濾過嚴。

C. 什麼時候用 es_timeline()
   - 當使用者問題涉及「何時／順序／里程碑／時間線／timeline／歷程演變」，或你已掌握 1–3 篇高相關文件，為每個挑 1 個 uuid 呼叫 es_timeline(k=10)。
   - 將 timeline 事件按日期排序後整併入答案的「時間序列重點」，並在 citations 中加入來源 uuid 與對應日期。

D. 引用（citations）組裝規則（**嚴禁虛構**）
   - 優先使用 es_search_news 回傳的 `citations`（nested evidence_snippets）。對於每一段：
       { "uuid": <命中文件的 uuid>,
         "source_id": <如有>,
         "subject": "<如有>",
         "paragraph_id": <如有>,
         "date_iso": <如工具已提供或你補全>,
         "text": <可選，若加入請截斷到 200–250 字以內> }
   - 若該片段缺日期但同一 hit 有 `article_date_iso` 或 `event_dates[]`：
       - 當片段文字僅含「M月D日」或「今（D）日／（D日）」等不完整日期：用 article_date_iso 的年（與必要時的月）或從 `event_dates[]` 補全為 YYYY-MM-DD。
   - 避免在 citations 放入冗長原文；必要時截斷，確保 payload 精簡。
   - citations 建議 3–30 筆，排序由代表性高的排到低的，覆蓋不同 uuid 與關鍵時間點。

E. 答案寫作（繁體中文）
   - 先列「重點事件」（倒序或時間序，依任務需求），每點包含：日期（YYYY-MM-DD）、一句到兩句說明（主詞＋動作＋影響/後果）。
   - 「趨勢／比較／洞見」段落用 3–6 句說明觀察到的變化、政策轉向、利害關係人反應、風險與不確定性。
   - 語氣客觀、中立，避免武斷；用詞簡潔、刪除贅字；段落過渡自然。

【錯誤處理與保險】
- 任何查詢錯誤（BadRequestError 等）不可終止程式；請捕捉例外並嘗試較寬鬆的條件（移除日期／取消 must_* 硬過濾／縮小 size）。
- 若最終仍無資料，輸出一個合理的空結果回應（answer 說明「未檢索到符合條件的來源」），citations 為空陣列，但不得虛構。
- 不可呼叫網路、檔案 I/O、安裝套件，也不可使用非必要的外部依賴；維持純 Python + 既有工具呼叫。

【風格與限制】
- 全部輸出（answer）必用繁體中文。
- 不加上任何額外的 print 或 logging；**程式最後只呼叫一次** final_answer(...)。
- 請控制查詢規模：size 不超過 30；citations 不超過 20；避免冗長內容。

（提醒：你只需產生「單一段純 Python 程式」，在該程式中呼叫 es_search_news / es_timeline，整理後以 final_answer(...) 結束。不允許輸出第二段程式或任何標記。）
"""
#- 輸出時請保留最多 3–5 則具代表性的 citations，確保每則都附帶 text 與 uuid。

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
    # ✅ 建議：只帶 instructions，最穩
    try:
        return CodeAgent(tools=tools, model=model, instructions=SYSTEM,
                         additional_authorized_imports=["json"]  # 允許 json
                         )
    except TypeError:
        pass
    try:
        return CodeAgent(tools=tools, model=model,
                         additional_authorized_imports=["json"]  # 允許 json
                         )  # fallback
    except TypeError:
        pass
    base = CodeAgent(tools=tools, model=model,
                         additional_authorized_imports=["json"]  # 允許 json
                         )
    class _Wrapped:
        def __init__(self, inner): self._inner = inner
        def run(self, question: str):
            return self._inner.run(f"{SYSTEM}\n\n使用者問題：{question}")
    return _Wrapped(base)

'''
def _make_code_agent(tools, model):
    """
    依序嘗試不同參數，以相容你當前的 smolagents 版本。
    """
    # 優先嘗試：instructions + structured_output
    try:
        return CodeAgent(tools=tools, model=model, instructions=SYSTEM, structured_output=True)
    except TypeError:
        pass
    # 次選：只有 instructions
    try:
        return CodeAgent(tools=tools, model=model, instructions=SYSTEM)
    except TypeError:
        pass
    # 再次選：只有 structured_output
    try:
        return CodeAgent(tools=tools, model=model, structured_output=True)
    except TypeError:
        pass

    # 最後 fallback：完全不帶參數，並包一層把 SYSTEM 前置到 query
    base = CodeAgent(tools=tools, model=model)

    class _Wrapped:
        def __init__(self, inner):
            self._inner = inner
        def run(self, question: str):
            # 把系統提示前置到使用者問題（確保行為一致）
            prefixed = f"{SYSTEM}\n\n使用者問題：{question}"
            return self._inner.run(prefixed)

    return _Wrapped(base)
'''
def build_agent():
    model = build_model()
    tools = [ESSearchNews(), ESTimeline()]
    return _make_code_agent(tools, model)

# 提供單例
#_agent = build_agent()
#def get_agent():
#    return _agent

def get_agent():
     #⚠️ 回傳「新的」Agent（保持無歷史、無殘留）
    return build_agent()
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
# 允許：python -m agent.agent 快速測試
if __name__ == "__main__":
    a = get_agent()
    #q = "請整理 2025/9/21–9/30 與『月薪5萬元免稅』、『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    q = "請整理2025年『拉拉隊』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    #q = "請整理 2025/9/21–9/30 與『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    print(a.run(q))
