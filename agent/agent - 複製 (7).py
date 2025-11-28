# agent/agent.py
from dotenv import load_dotenv
load_dotenv()

import os
import json

#from functools import lru_cache
from typing import Any, Dict, List
from smolagents import CodeAgent, LiteLLMModel, PythonInterpreterTool
#from .agent_utils import aggregate_month_quarter
from .tools_es import ESSearchNews, ESTimeline, ESFetchDocById


from agent.llm_utils.ollama_client import call_llm  # 你既有的封裝
from agent.config.index_loader import INDEX_CONFIG

from .style_agent import ask_with_style
from .report_agent import ask_with_report
#from agent.tools_es import _parse_index_hint

DEBUG_ROUTER = os.getenv("DEBUG_ROUTER", "1") == "1"

#print("finished load module")

# === 模型設定（可用 .env 覆寫） ===
#MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
#MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
#MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))

# === 動態組出 topic 列表 ===
AVAILABLE_TOPICS = INDEX_CONFIG["topic_index_map"].keys()
TOPIC_ENUM_TEXT = " | ".join(AVAILABLE_TOPICS) + " | none"

TOPIC_DESCRIPTIONS = {
    topic: info.get("description", "")
    for topic, info in INDEX_CONFIG["topic_index_map"].items()
}

topic_desc_lines = []
for topic, desc in TOPIC_DESCRIPTIONS.items():
    topic_desc_lines.append(f'- "{topic}": {desc}')
TOPIC_DESC_TEXT = "\n".join(topic_desc_lines)


# === Task Router System（safe string，避免 f-string {} 衝突）===
TASK_ROUTER_SYSTEM = (
    "你是一個「任務分類器」，負責判斷使用者目前的請求屬於哪一種模式，並回傳其語義上的主題分類（topic），後端會根據 topic 自行決定查哪些 Elasticsearch index。\n\n"
    "你只能回傳一個 JSON 物件，格式如下：\n\n"
    "{\n"
    '  "mode": "SRA_REPORT | SRA_STYLE | PURE_LLM",\n'
    '  "reason": "簡短說明為什麼這樣判斷",\n'
    f'  "topic": "{TOPIC_ENUM_TEXT}"\n'
    "}\n\n"
    "三種模式定義：\n\n"
    "1. SRA_REPORT\n"
    "   - 用途是「整理 / 分析 / 彙整 / 統計」某段期間的事件或趨勢。\n"
    "   - 需要查詢資料庫（例如新聞、軍情、政府文件）。\n"
    "   - 常見語氣：整理重點、歷史彙整、趨勢分析、比較前後、統計變化、政策效果、供應鏈分析等。\n\n"
    "2. SRA_STYLE\n"
    "   - 使用者提供「新的事件 / 情境」，要求以某種現有文件的風格寫新內容。\n"
    "   - 會用到資料庫內現有內容作為風格參考。\n\n"
    "3. PURE_LLM\n"
    "   - 模型自身即可回答，不需資料庫。\n"
    "   - 包含教學、翻譯、改寫、故事、一般聊天等。\n\n"
    "topic 定義（語義分類，由設定檔載入）：\n\n"
    f"{TOPIC_DESC_TEXT}\n\n"
    "請務必：\n"
    "- 只輸出 JSON，不要有任何其他文字。\n"
)

def _llm_route_task(user_msg: str) -> dict:
    text = (user_msg or "").strip()
    if not text:
        return {"mode": "PURE_LLM", "reason": "empty message", "topic": "none"}

    user_prompt = (
        "請依說明判斷下列使用者請求屬於哪一種模式，"
        "只輸出 JSON 物件，不要有其他文字。\n\n"
        f"【使用者請求】\n{text}"
    )

    try:
        raw = call_llm(
            user_prompt,
            system_prompt=TASK_ROUTER_SYSTEM,
            extra_params={"options": {}},
            timeout=60.0,
        )
        result = json.loads(raw)
    except Exception as e:
        print("[router] LLM route failed:", e)
        return {"mode": "PURE_LLM", "reason": "router error", "topic": "none"}

    mode = str(result.get("mode") or "").upper()
    if mode not in ("SRA_REPORT", "SRA_STYLE", "PURE_LLM"):
        mode = "PURE_LLM"

    ALL_TOPICS = set(INDEX_CONFIG["topic_index_map"].keys()) | {"none"}
    
    topic = result.get("topic", "none").strip().lower()
    if topic not in ALL_TOPICS:
        topic = "none"

    routed = {
        "mode": mode,
        "reason": result.get("reason") or "",
        "topic": topic,
    }
    print("[router] routed =", routed)
    return routed


def route_task_mode(
    user_msg: str,
    query_for_agent: str | None = None,
) -> dict:
    """
    對外提供的任務分流介面。

    - 優先使用 query_for_agent（通常包含壓縮記憶＋對話歷史＋目前問題）
    - 若沒有 query_for_agent，就退回只看當輪 user_msg
    """
    text = (query_for_agent or user_msg or "").strip()
    if not text:
        return {
            "mode": "PURE_LLM",
            "reason": "empty message",
            "es_index_key": None,
        }

    return _llm_route_task(text)







        


# 提供單例
#_agent = build_agent()
#def get_agent():
#    return _agent

'''
def get_agent():
     #⚠️ 回傳「新的」Agent（保持無歷史、無殘留）
    return build_agent()
'''

'''
def get_agent() -> ReportAgent:
    # 之後任何地方呼叫 get_agent()，拿到的都是這個兼容舊介面的 Agent
    return ReportAgent()
'''


def _build_router_input(
    current_user_msg: str,
    recent_user_msgs: list[str] | None = None,
    k: int = 2,  # 取「最近 k 個舊問題 + 目前問題」→ 總共最多 3 個
) -> str:
    """
    給任務分流器用的輸入字串：
    - 只包含 user 提過的問題，不包含任何 assistant 的回答
    - 預設取最近 k 個舊問題 + 目前問題
    - 格式：
        【過去問題1】
        ...
        
        【過去問題2】
        ...
        
        【目前問題】
        ...
    """
    current = (current_user_msg or "").strip()
    if not recent_user_msgs:
        return current

    # 過去問題只保留非空白的
    cleaned = [m.strip() for m in recent_user_msgs if m and m.strip()]
    if not cleaned:
        return current

    # 取最後 k 個
    tail = cleaned[-k:]

    parts: list[str] = []
    for i, m in enumerate(tail, 1):
        parts.append(f"【過去問題{i}】\n{m}")
    parts.append("【目前問題】\n" + current)
    return "\n\n".join(parts)

def answer_with_routing(
    user_msg: str,
    query_for_agent: str | None = None,
    recent_user_msgs: list[str] | None = None,
) -> Dict[str, Any]:
    """
    高層入口：
    - 用 LLM 做任務分流（SRA_REPORT / SRA_STYLE / PURE_LLM）
    - 視情況呼叫 ask_with_report / ask_with_style / 一般 call_llm
    - 回傳統一格式：{ answer, citations, reasoning, mode, route }

    recent_user_msgs:
      - 可選；如果有傳進來，會拿「最近 k 個」來幫助任務判斷
      - 只應該放 user 的提問內容，不要放 assistant 的回答
    """
    user_msg = (user_msg or "").strip()
    if not user_msg:
        return {
            "answer": "目前沒有收到任何問題內容，請再輸入一次。",
            "citations": [],
            "reasoning": "空輸入，直接回覆提示。",
            "mode": "PURE_LLM",
            "route": {"mode": "PURE_LLM", "reason": "empty", "es_index_key": None},
        }

    # === 1) 準備任務分流器輸入 ===
    router_input = _build_router_input(
        current_user_msg=user_msg,
        recent_user_msgs=recent_user_msgs,
        k=2,   # ★ 最近 2 輪 + 目前這一輪
    )

    # === 2) LLM 任務分類 ===
    route = route_task_mode(router_input)
    mode = route.get("mode", "PURE_LLM")
    topic = route.get("topic", "none")

    # === 3) 根據 topic 決定要查哪些 index（多 index 支援） ===
    topic_cfg = INDEX_CONFIG.get("topic_index_map", {}).get(topic)
    if topic_cfg:
        indexes = topic_cfg.get("indexes") or []
    else:
        # 撐底：用 default_index
        default_idx = INDEX_CONFIG.get("default_index")
        indexes = [default_idx] if default_idx else []

    if indexes:
        index_hint_prefix = f"[ES_INDEX_HINT={','.join(indexes)}]\n"
    else:
        index_hint_prefix = ""

    # === 4) 給 CodeAgent 的 query ===
    q_for_agent = (query_for_agent or user_msg).strip()
    q_for_agent = index_hint_prefix + q_for_agent

    try:
        # === SRA_REPORT：產生資料 payload → 報告 LLM 寫結論 ===
        if mode == "SRA_REPORT":
            out = ask_with_report(q_for_agent)

        # === SRA_STYLE：用既有語料模仿風格 ===
        elif mode == "SRA_STYLE":
            style_query = index_hint_prefix + user_msg
            out = ask_with_style(style_query)

        # === PURE_LLM：不查 ES，直接用模型知識回答 ===
        else:
            generic_answer = call_llm(
                user_msg,
                system_prompt=(
                    "你是一個一般用途的繁體中文助手。"
                    "請直接根據使用者問題回答或寫作，不需要查詢後端資料庫。"
                ),
                extra_params={"options": {}},
                timeout=180.0,
            )
            out = {
                "answer": generic_answer,
                "citations": [],
                "reasoning": "此回答由一般 LLM 直接生成，未查詢後端資料庫。",
            }

    except Exception as e:
        print("[agent] answer_with_routing error:", e)
        return {
            "answer": "後端分析過程發生錯誤，請稍後再試或聯絡系統管理員。",
            "citations": [],
            "reasoning": f"後端例外：{e}",
            "mode": mode,
            "route": route,
        }

    # === 補上 routing info（前端要看） ===
    out = out or {}
    out.setdefault("answer", "")
    out.setdefault("citations", [])
    out.setdefault("reasoning", "")
    out["mode"] = mode
    out["route"] = route

    return out



# 允許：python -m agent.agent 快速測試
if __name__ == "__main__":
    #a = get_agent()
    #q = "請整理 2025/9/21–9/30 與『月薪5萬元免稅』、『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    q = "請整理2025年『拉拉隊』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    #q = "請整理 2025/9/21–9/30 與『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    #print(a.run(q))
    print(ask_with_report(q))

