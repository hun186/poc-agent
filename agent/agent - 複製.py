# agent/agent.py
from dotenv import load_dotenv
load_dotenv()

import os
from smolagents import CodeAgent, LiteLLMModel
from .tools_es import ESSearchNews, ESTimeline

# === 模型設定（可用 .env 覆寫） ===
MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))

SYSTEM = (
  "你是『新聞/政策問答助理』。策略：\n"
  "1) 先用 es_search_news 找到相關文與引用段落；\n"
  "2) 若使用者問到『何時/順序/里程碑』，再用 es_timeline 拉出事件列表；\n"
  "3) 輸出請使用 JSON：{answer, citations[], reasoning}；"
  "   citations 帶 source_id（若有）或 uuid；不得虛構。\n"
)
SYSTEM = """
你是『新聞/政策問答助理』。策略：
1) 先用 es_search_news 找到相關文與引用段落；
2) 若使用者問到『何時/順序/里程碑』，再用 es_timeline 拉出事件列表；
3) 輸出請使用 JSON：{answer, citations[], reasoning}；
   citations 帶 uuid；不得虛構。

規則（務必遵守）：
- 只輸出一個 <code>...</code> 區塊，內容必須是可以直接執行的 Python 程式碼。
- 調用工具：在 Python 代碼裡直接呼叫 es_search_news(...) 與 es_timeline(...)。
- 不要使用 JSON tool calling / function calling，也不要輸出任何 tools 定義。
- 不要在 <code> 區塊之外輸出任何自然語言或 Markdown。
- 代碼最後必須呼叫：
    final_answer({
        "answer": "...",              # 最後的文字答案
        "citations": [ {...}, ... ],  # 來自工具回傳的片段/uuid
        "reasoning": "..."            # 簡短說明你如何得到答案
    })
- 嚴禁虛構引用；引用需來自工具回傳（包含 uuid）。
- 如引用段落中的日期不完整（如「今（29）日」），請優先使用工具回傳的 article_date_iso 或 event_dates 補全成 YYYY-MM-DD，再寫入 citations[].date_iso。

"""


def _normalize_model_id(mid: str) -> str:
    if "/" in mid:
        return mid
    return f"ollama_chat/{mid}"  # ← 走 /api/chat

def build_model():
    model_id = _normalize_model_id(MODEL_ID)
    return LiteLLMModel(
        model_id=model_id,
        api_base=MODEL_BASE_URL,
        temperature=MODEL_TEMPERATURE,
        # ↓ 若你這版 smolagents 支援，等同告訴底層「不要用工具呼叫」
        extra_generation_kwargs={"tool_choice": "none"}
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
        return CodeAgent(tools=tools, model=model, instructions=SYSTEM)
    except TypeError:
        pass
    try:
        return CodeAgent(tools=tools, model=model)  # fallback
    except TypeError:
        pass
    base = CodeAgent(tools=tools, model=model)
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
_agent = build_agent()
def get_agent():
    return _agent

# 允許：python -m agent.agent 快速測試
if __name__ == "__main__":
    a = get_agent()
    #q = "請整理 2025/9/21–9/30 與『月薪5萬元免稅』、『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    q = "請整理2025年『拉拉隊』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    #q = "請整理 2025/9/21–9/30 與『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    print(a.run(q))
