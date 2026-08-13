from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from agent.llm_utils.ollama_client import call_llm
from agent.utils.profiler import log_duration
from config.index_loader import INDEX_CONFIG

ROUTER_MODEL_ID = (
    os.getenv("ROUTER_MODEL_ID")
    or os.getenv("MODEL_ID")
    or "gpt-oss:120b-32k"
)

AVAILABLE_TOPICS = INDEX_CONFIG["topic_index_map"].keys()
TOPIC_ENUM_TEXT = " | ".join(AVAILABLE_TOPICS) + " | none"
TOPIC_DESCRIPTIONS = {
    topic: info.get("description", "")
    for topic, info in INDEX_CONFIG["topic_index_map"].items()
}
TOPIC_DESC_TEXT = "\n".join(
    f'- "{topic}": {desc}'
    for topic, desc in TOPIC_DESCRIPTIONS.items()
)

TOPIC_INDEX_MAP: dict = INDEX_CONFIG["topic_index_map"]
ES_INDEX_DEFAULT: str = INDEX_CONFIG.get("default_index", "news_test")

ROUTER_CURRENT_MAX_CHARS = max(
    512, int(os.getenv("ROUTER_CURRENT_MAX_CHARS", "6000"))
)
ROUTER_HISTORY_MAX_CHARS = max(
    256, int(os.getenv("ROUTER_HISTORY_MAX_CHARS", "1500"))
)


def _compact_router_text(text: str, max_chars: int) -> str:
    """Bound classifier input while retaining instructions at both ends."""
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned

    marker = "\n\n【中間大量任務資料已省略，完整內容仍會交給執行模型】\n\n"
    available = max_chars - len(marker)
    head_chars = int(available * 0.75)
    tail_chars = available - head_chars
    return f"{cleaned[:head_chars]}{marker}{cleaned[-tail_chars:]}"


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

    return ",".join(idxs)


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


def llm_route_task(user_msg: str, trace: Optional[Dict[str, Any]] = None) -> dict:
    if trace is None:
        trace = {}

    text = (user_msg or "").strip()
    if not text:
        return {"mode": "PURE_LLM", "reason": "empty message", "topic": "none"}

    user_prompt = (
        "請依說明判斷下列使用者請求屬於哪一種模式，"
        "只輸出 JSON 物件，不要有其他文字。\n\n"
        f"【使用者請求】\n{text}"
    )

    try:
        t0 = time.perf_counter()
        with log_duration("[router] LLM route", extra={"model_id": ROUTER_MODEL_ID}):
            raw = call_llm(
                user_prompt,
                system_prompt=TASK_ROUTER_SYSTEM,
                extra_params={"options": {}},
                timeout=120.0,
                model=ROUTER_MODEL_ID,
            )
        t1 = time.perf_counter()
        result = json.loads(raw)

        llm_root = trace.setdefault("llm", {})
        router_logs: list[Dict[str, Any]] = llm_root.setdefault("router", [])
        router_logs.append({
            "system": "TASK_ROUTER_SYSTEM",
            "user": user_prompt,
            "raw_response": raw,
            "parsed": result,
            "elapsed_sec": round(t1 - t0, 3),
            "model_id": ROUTER_MODEL_ID,
        })
    except Exception as e:
        print("[router] LLM route failed:", e)
        llm_root = trace.setdefault("llm", {})
        router_logs: list[Dict[str, Any]] = llm_root.setdefault("router", [])
        router_logs.append({
            "system": "TASK_ROUTER_SYSTEM",
            "user": user_prompt,
            "error": str(e),
            "model_id": ROUTER_MODEL_ID,
        })
        return {"mode": "PURE_LLM", "reason": "router error", "topic": "none"}

    mode = str(result.get("mode") or "").upper()
    if mode not in ("SRA_REPORT", "SRA_STYLE", "DOC_FOLLOWUP", "PURE_LLM"):
        mode = "PURE_LLM"

    all_topics = set(INDEX_CONFIG["topic_index_map"].keys()) | {"none"}
    topic = result.get("topic", "none").strip().lower()
    if topic not in all_topics:
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
    trace: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    對外提供的任務分流介面。

    - 優先使用 query_for_agent（通常包含壓縮記憶＋對話歷史＋目前問題）
    - 若沒有 query_for_agent，就退回只看當輪 user_msg
    """
    text = (query_for_agent or user_msg or "").strip()
    if not text:
        return {"mode": "PURE_LLM", "reason": "empty message", "topic": "none"}

    return llm_route_task(text, trace=trace)


def build_router_input(
    current_user_msg: str,
    recent_user_msgs: list[str] | None = None,
    k: int = 2,
) -> str:
    """
    給任務分流器用的輸入字串：
    - 一律以「目前問題」為主，過去問題只是輔助理解上下文
    - 路由只需要任務意圖與主題；大型資料本文會截成頭尾樣本，完整內容仍由執行模型處理
    """
    current = _compact_router_text(current_user_msg, ROUTER_CURRENT_MAX_CHARS)
    if not recent_user_msgs:
        return f"【目前問題】\n{current}"

    cleaned = [
        _compact_router_text(m, ROUTER_HISTORY_MAX_CHARS)
        for m in recent_user_msgs
        if m and m.strip()
    ]
    if not cleaned:
        return f"【目前問題】\n{current}"

    parts: list[str] = ["【目前問題（務必以此為準）】\n" + current]
    for i, message in enumerate(cleaned[-k:], 1):
        parts.append(f"【過去問題{i}（用來判斷主題與語境，若未提到新主題則視為延續）】\n{message}")

    return "\n\n".join(parts)
