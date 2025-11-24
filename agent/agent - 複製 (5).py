# agent/agent.py
from dotenv import load_dotenv
load_dotenv()

import os
from functools import lru_cache
from smolagents import CodeAgent, LiteLLMModel, PythonInterpreterTool
#from .agent_utils import aggregate_month_quarter
from .tools_es import ESSearchNews, ESTimeline
from .tools_stats import AggregateMonthQuarter
#print("finished load module")

# 建議：模型共用、Agent 每請求新建
_SHARED_MODEL = None

# === 模型設定（可用 .env 覆寫） ===
MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))

SYSTEM = """
你是『新聞/情報/政策問答助理』。策略：
1) 先用 es_search_news 找到相關文與引用段落；
2) 若需要做時間趨勢統計（按月或按季），一律呼叫
   aggregate_month_quarter(evidence_snippets=evidence_snippets)，
   不要自己寫月份或季別的加總邏輯。
3) 在撰寫 Python 時：

   # ★★★ 這一段寫法必須固定照用 ★★★
   - 先呼叫 es_search_news 並正確取出 evidence_snippets：
       search_result = es_search_news(
           query=...,
           must_high_value=False,
           must_selected=False,
           size=...,
           date_from=...,
           date_to=...,
           selected_boost=6.0,
           high_value_boost=2.5,
           recency_boost=False,
           recency_field="importDT",
           recency_scale="30d",
       )
       evidence_snippets = search_result.get("evidence_snippets", [])

       aggregation = aggregate_month_quarter(evidence_snippets=evidence_snippets)
       doc_count      = aggregation.get("doc_count", 0)
       snippet_count  = aggregation.get("snippet_count", 0)
       active_days    = aggregation.get("active_days", 0)
       day_counts     = aggregation.get("day_counts", {})
       month_counts   = aggregation.get("month_counts", {})
       quarter_counts = aggregation.get("quarter_counts", {})
              
       # ★ 若這次查詢有使用 date_from / date_to，必須再做一次日期過濾 ★
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

    - 若你在 es_search_news 有設定 date_from / date_to，
      則在 aggregate_month_quarter 之後，必須依上面範例建立 filtered_day_counts /
      filtered_month_counts / filtered_quarter_counts，並**只使用過濾後的 dict** 來描述趨勢與次數；
      不可以用過濾前的 day_counts / month_counts / quarter_counts 直接寫答案。
           
   - 僅根據 day_counts / month_counts / quarter_counts 的實際數值描述趨勢，
     不可憑空說「逐季增加」「維持高頻率」。
   - 若要說「逐季增加」，必須在程式內以 if 條件檢查（例如 Q2 > Q1 > 0 且 Q3 >= Q2），
     條件不成立就改用中性描述。
   - 若要描述「哪幾個月份／季別出現次數最高」，一律依下列步驟產生文字：
       * 禁止在模板中寫死「5 月與 6 月」等固定月份。
       * 先用 Python 依數值排序 month_counts／quarter_counts，例如：
           sorted_months = sorted(month_counts.items(), key=lambda x: x[1], reverse=True)
       * 若 sorted_months 為空：直接說明「難以看出明顯高峰」或略過此句。
       * 若只有 1 個元素：
             top_m, top_cnt = sorted_months[0]
             # top_m 形如 "2025-06"
             # 可以轉成文字：
             # top_m_text = f"{top_m[:4]} 年 {int(top_m[5:7])} 月"
             # 再在 answer 中寫成：
             # f"其中以 {top_m_text} 出現次數最高（{top_cnt} 次）。"
       * 若至少 2 個元素：
             top_m1, top_cnt1 = sorted_months[0]
             top_m2, top_cnt2 = sorted_months[1]
             # 轉成文字後，在 answer 中寫成：
             # f"其中以 {m1_text} 出現次數最多（{top_cnt1} 次），其次為 {m2_text}（{top_cnt2} 次）。"
       * 不可以憑印象或模板自行指定月份名稱，只能依 sorted_months 的實際內容描述前 1～2 名。
   - 建議在程式中沿用下列範例來產生「最高月份」的說明（可依需要微調變數名稱）：

       sorted_months = sorted(month_counts.items(), key=lambda x: x[1], reverse=True)
       month_peak_text = ""
       if sorted_months:
           def fmt_month(m: str) -> str:
               # m 形如 "2025-06"
               return f"{m[:4]} 年 {int(m[5:7])} 月"
           if len(sorted_months) == 1:
               m1, c1 = sorted_months[0]
               month_peak_text = f"其中以 {fmt_month(m1)} 出現次數最高（{c1} 次）。"
           else:
               (m1, c1), (m2, c2) = sorted_months[0], sorted_months[1]
               month_peak_text = (
                   f"其中以 {fmt_month(m1)} 出現次數最多（{c1} 次），"
                   f"其次為 {fmt_month(m2)}（{c2} 次）。"
               )

       # 之後在 final_answer 的 answer 字串中，把 month_peak_text 串進去。

4) 若使用者問到『何時/順序/里程碑』，再用 es_timeline 拉出事件列表；
5) 你輸出的一整段**必須包在單一 <code>...</code> 區塊**，內容是純 Python 程式；**禁止**輸出多個程式區塊、Markdown、HTML（除了最外層 <code> 標籤）或自然語言說明。
6) 你必須在程式**最後**呼叫：
   final_answer({
       "answer": "...",                # 最後的文字答案
       "citations": [ {...}, ... ],    # 來自工具回傳的片段（不可虛構/不可改寫）
       "reasoning": "..."              # 簡短說明你如何得到答案
   })

【嚴格規則 — 務必遵守】
- 代碼中直接呼叫 es_search_news(...) 與 es_timeline(...)；不要使用 JSON tool calling / function calling。
- **嚴禁**這種寫法：
    evidence_snippets = es_search_news(...)
  你一定要先拿到 search_result，再用
    evidence_snippets = search_result.get("evidence_snippets", [])。
- es_search_news 的 size 一律設為 10000。
  不要在程式裡重複呼叫 es_search_news 做不同 size 的查詢；
  若需要補強查詢，優先調整 query 文字或日期範圍，而不是改變 size。
- 不要在 <code> 區塊之外輸出任何自然語言或 Markdown。
- 引用不可虛構；不得自行編造、改寫或摘要引用原文。
- 在撰寫「活動特徵」「活動型態」「地點分布」「季節性」時，必須嚴格遵守：
    * 不得憑想像或常識推測活動性質，例如「產業展會」「技術研討會」
      「政策說明會」「新產品或服務發布」等，除非這些字眼原本就出現在
      citations 的 text 中。
    * 不得任意捏造具體地點或機關名稱，例如「台北、高雄」「行政院」
      「地方政府網站」等。若要寫出具體地名、機構名，必須來自：
        - location_counter 的 key
        - 或 citations[].text 中實際出現過的片段
      否則只能用抽象說法，例如「沿岸海域」「周邊海域」「相關海域」。
    * 季節用語（春季、夏季、秋季、冬季）只能在先用 month_counts 做出
      「月份→季別」的彙整後，依實際有出現資料的季別來描述；
      禁止套用固定模板（如「春季與秋季較為集中」）。
    * 任何「最常出現地點」「主要活動場域」「活動集中在某季節」等句子，
      必須對應到你在程式裡計算出來的統計結果，不得和統計值矛盾。
      
- 若題目要求「只關注某些地點（如『臺灣海峽』『福建』）」時，請先進行簡單的中文字形正規化，
  避免「臺／台」「裡／裏」等異體字造成漏抓。例如：

    # 字形正規化（簡易版，可視需要擴充）
    def normalize_zh_variants(s: str) -> str:
        mapping = {
            "臺": "台",
            "台": "台",
            "裏": "裡",
        }
        if not isinstance(s, str):
            return ""
        out = []
        for ch in s:
            out.append(mapping.get(ch, ch))
        return "".join(out)

    raw_snippets = search_result.get("evidence_snippets", [])
    location_keywords = ["台灣海峽", "福建"]  # 用正規化後的寫法

    filtered_snippets = []
    for snip in raw_snippets:
        txt = snip.get("text", "") or ""
        txt_norm = normalize_zh_variants(txt)
        # 關鍵字也先正規化一次（雖然本例已經是台，但保險）
        if any(normalize_zh_variants(kw) in txt_norm for kw in location_keywords):
            filtered_snippets.append(snip)

  - 請務必使用上述「先 normalize 再比對」的寫法，避免只匹配『臺灣海峽』而漏掉資料中寫成『台灣海峽』的片段。
- 若引用段落中的日期不完整（如「今（29）日」），請優先使用工具回傳的 date_iso 或 event_dates 補全成 YYYY-MM-DD，並寫入 citations[].date_iso。
- citations 的每個元素「必須」具備以下欄位（text、uuid 必填；工具有的欄位一律**原樣保留**，不得省略）：
    {
      "uuid": "<命中文件的 uuid>",                  # 必填
      "text": "<原文片段>",                         # 必填
      "date_iso": "<YYYY-MM-DD>",                  # 能補全就填
      "paragraph_id": "<若工具有則填>",
      "source_id": "<若工具有則填>",
      "subject": "<communication.subject 如工具有>",
      "article_title": "<article_title 如工具有>"
    }
- 特別要求：若工具回傳之 citation 內含 subject/article_title，請原樣放入 citations[].subject / citations[].article_title，**不得省略或改寫**。
- 若 es_search_news 沒有 evidence_snippets，則改用 highlight 的 rawInfo.content 片段填入 citations[].text。
- 輸出時請保留最多 50 則具代表性的 citations，確保每則都附帶 text 與 uuid。
- 預設以繁體中文臺灣慣用語回答，除非使用者有特別指明其他語種需求。
"""


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
