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
from .doc_followup_agent import ask_with_doc_followup
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

TOPIC_INDEX_MAP: dict = INDEX_CONFIG["topic_index_map"]
ES_INDEX_DEFAULT: str = INDEX_CONFIG.get("default_index", "news_test")

def topic_to_index_hint(topic: str | None) -> str | None:
    """
    把 LLM 判斷出的 topic（例如 "mil_intel"）轉成 index_hint 給 ES 使用。

    - 若 topic 未設定或找不到對應，就回傳 None（讓後續走 default）
    - 若該 topic 綁多個 index，就用逗號串起來："a,b,c"
    """
    if not topic:
        return None

    cfg = TOPIC_INDEX_MAP.get(topic)
    if not cfg:
        return None

    idxs = cfg.get("indexes") or []
    if not idxs:
        return None

    # 多個 index 就 "a,b,c"；_resolve_es_index 已經支援這種格式
    return ",".join(idxs)

# === Task Router System（safe string，避免 f-string {} 衝突）===
TASK_ROUTER_SYSTEM = (
    "你是一個「任務分類器」，負責判斷使用者目前的請求屬於哪一種模式，並回傳其語義上的主題分類（topic），後端會根據 topic 自行決定查哪些 Elasticsearch index。\n\n"
    "你只能回傳一個 JSON 物件，格式如下：\n\n"
    "{\n"
    '  "mode": "SRA_REPORT | SRA_STYLE | DOC_FOLLOWUP | PURE_LLM",\n'
    '  "reason": "簡短說明為什麼這樣判斷",\n'
    f'  "topic": "{TOPIC_ENUM_TEXT}"\n'
    "}\n\n"
    "四種模式定義（請特別注意 SRA_REPORT 與 DOC_FOLLOWUP 的差異）：\n\n"
    "1. SRA_REPORT\n"
    "   - 重點是「整理 / 分析 / 彙整 / 統計」一段期間或一個主題的事件。通常會：\n"
    "       * 問『某個主題在某段時間的趨勢如何』、\n"
    "       * 『幫我整理 2013–2017 的重點事件並分析』、\n"
    "       * 『比較政策 A、B 的差異』等。\n"
    "   - 會需要重新用關鍵字查詢資料庫，彙整多篇文件再寫報告。\n"
    "   - 如果問題本身包含『整理、趨勢、分析、統計、比較』等語氣，優先選 SRA_REPORT。\n\n"
    "2. SRA_STYLE\n"
    "   - 使用者提供「新的事件 / 內容」，要求用某種既有文件的風格改寫。\n"
    "   - 會用資料庫內的文件當作風格參考（例如聯合國新聞、公文範例），但事實來自使用者提供的新內容。\n\n"
    "3. DOC_FOLLOWUP\n"
    "   - 重點是「對已經存在於本次對話上下文中的特定文件，做後續操作」，而不是重新搜尋新資料。\n"
    "   - 常見語氣（舉例）：\n"
    "       * 『把剛剛的第五篇參考文件全文貼出來』\n"
    "       * 『針對上一輪那幾篇新聞，各寫一段摘要』\n"
    "       * 『給我第一篇的參考全文』\n"
    "       * 『請把 2017-02-28 那篇〈俄、中行使否決權〉全文貼出來』\n"
    "       * 『把上面引用到的那篇聯合國報告翻成英文』\n"
    "   - 這類請求只是在『取出 / 翻譯 / 摘要 / 重寫』一兩篇（或少數幾篇）**已知的文件**，\n"
    "     並沒有要整理整個主題的趨勢或統計，因此應選 DOC_FOLLOWUP，而不是 SRA_REPORT。\n"
    "   - 一個簡單判斷：\n"
    "       * 如果使用者只是要某一篇或少數幾篇「已知文章」的全文、翻譯或摘要 ⇒ DOC_FOLLOWUP。\n"
    "       * 如果使用者要的是某個主題在一段時間內的整體情況 ⇒ SRA_REPORT。\n\n"
    "4. PURE_LLM\n"
    "   - 模型自身即可回答，不需資料庫或既有文件。\n"
    "   - 包含一般聊天、翻譯、改寫、教學、故事等。\n\n"
    "topic 定義（語義分類，由設定檔載入）：\n\n"
    f"{TOPIC_DESC_TEXT}\n\n"
    "請務必：\n"
    "- 只輸出 JSON，不要有任何其他文字。\n"
    "- 可以利用「過去問題」來判斷主題與語境，但在具體操作指令上仍以【目前問題】為準。\n"
    "- 如果【目前問題】看起來只是針對「同一個主題」改變統計方式、時間區間、篩選條件或呈現格式（例如：改成依月份統計、改成用地點分組、改成畫圖、改成樞紐分析），而沒有明確提到新的主題，請沿用過去問題的主題與 topic。\n"
    "- 只有當【目前問題】明確聚焦在「不同的主體、系統、國家、領域」時，才判定為新的 topic；否則視為延續同一主題的多輪對話。\n"
)


TASK_ROUTER_SYSTEM_1128 = (
    "你是一個「任務分類器」，負責判斷使用者目前的請求屬於哪一種模式，並回傳其語義上的主題分類（topic），後端會根據 topic 自行決定查哪些 Elasticsearch index。\n\n"
    "你只能回傳一個 JSON 物件，格式如下：\n\n"
    "{\n"
    '  "mode": "SRA_REPORT | SRA_STYLE | DOC_FOLLOWUP | PURE_LLM",\n'
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
    "3. DOC_FOLLOWUP\n"
    "   - 用途是針對「前幾輪已經引用過的參考文件」做後續處理。\n"
    "   - 不會對事件本身再做新的關鍵字檢索，只用既有參考文件的全文來完成任務。\n"
    "   - 常見語氣：\n"
    "       - 把剛剛的第五篇參考全文翻成英文\n"
    "       - 針對每一篇參考文件各寫一段摘要\n"
    "       - 把第一篇參考全文列出來\n"
    "       - 用上一輪的那些參考文件，再寫一版不同角度的說明\n\n"
    "4. PURE_LLM\n"
    "   - 模型自身即可回答，不需資料庫。\n"
    "   - 包含教學、翻譯、改寫、故事、一般聊天等。\n\n"
    "topic 定義（語義分類，由設定檔載入）：\n\n"
    f"{TOPIC_DESC_TEXT}\n\n"
    "請務必：\n"
    "- 只輸出 JSON，不要有任何其他文字。\n"
    "- 當【目前問題】與過去問題的要求衝突時，一律以【目前問題】為準，過去問題僅供理解上下文。\n"
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
    # ★ 這裡把 DOC_FOLLOWUP 加進合法清單
    if mode not in ("SRA_REPORT", "SRA_STYLE", "DOC_FOLLOWUP", "PURE_LLM"):
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



def _build_router_input(
    current_user_msg: str,
    recent_user_msgs: list[str] | None = None,
    k: int = 2,
) -> str:
    """
    給任務分流器用的輸入字串：
    - 一律以「目前問題」為主，過去問題只是輔助理解上下文
    """
    current = (current_user_msg or "").strip()
    if not recent_user_msgs:
        return f"【目前問題】\n{current}"

    cleaned = [m.strip() for m in recent_user_msgs if m and m.strip()]
    if not cleaned:
        return f"【目前問題】\n{current}"

    tail = cleaned[-k:]

    parts: list[str] = []
    # ✅ 先放目前問題，請 LLM 以此為主
    parts.append("【目前問題（務必以此為準）】\n" + current)

    # 再補過去問題，明講「僅供參考」
    for i, m in enumerate(tail, 1):
        parts.append(f"【過去問題{i}（用來判斷主題與語境，若未提到新主題則視為延續）】\n{m}")

    return "\n\n".join(parts)

def _build_router_input_1127(
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
    reuse_uuids: list[str] | None = None,   # ★ 新增
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
    
    # === 2.5) 處理 uuid context ===
    reuse_uuids = reuse_uuids or []
    if reuse_uuids:
        print("[answer_with_routing] DOC_FOLLOWUP reuse_uuids =", reuse_uuids)
        
    # === 3) 根據 topic 決定要查哪些 index（多 index 支援） ===
    topic_cfg = INDEX_CONFIG.get("topic_index_map", {}).get(topic)
    if topic_cfg:
        indexes = topic_cfg.get("indexes") or []
    else:
        # 撐底：用 default_index
        default_idx = INDEX_CONFIG.get("default_index")
        indexes = [default_idx] if default_idx else []

    if indexes:
        # 給 CodeAgent / SRA_REPORT 用的提示前綴
        index_hint_str = ",".join(indexes)
        index_hint_prefix = f"[ES_INDEX_HINT={index_hint_str}]\n"
        # 給 ESFetchDocById / DOC_FOLLOWUP 用的 index_hint
        index_hint = index_hint_str
    else:
        index_hint_prefix = ""
        index_hint = None

    # === 4) 給 CodeAgent 的 query ===
    q_for_agent = (query_for_agent or user_msg).strip()
    q_for_agent = index_hint_prefix + q_for_agent

    try:
        # === DOC_FOLLOWUP：針對既有參考文件做後續處理，不再查新的 ES ===
        if mode == "DOC_FOLLOWUP":
            if not reuse_uuids:
                # 有判斷成 DOC_FOLLOWUP，但手上沒有 uuid，可退回 PURE_LLM 或直接提示
                generic_answer = (
                    "目前沒有可用的參考文件列表，因此無法針對「剛剛的第幾篇」等指令操作。"
                    "如需後續處理，請先重新發起一次查詢取得參考文件。"
                )
                out = {
                    "answer": generic_answer,
                    "citations": [],
                    "reasoning": "router 判斷為 DOC_FOLLOWUP，但呼叫端未提供 reuse_uuids。",
                }
            else:
                out = ask_with_doc_followup(
                    instruction=user_msg,
                    uuids=reuse_uuids,
                    index_hint=index_hint,   # ★ 把剛算好的 index_hint 帶進去
                )
                
        # === SRA_REPORT：產生資料 payload → 報告 LLM 寫結論 ===
        elif mode == "SRA_REPORT":
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

