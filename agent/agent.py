# agent/agent.py
from dotenv import load_dotenv
load_dotenv()

import os
import json
import time
from typing import Any, Dict, Optional, List
from telemetry import log_event  # 若之後想記 event 用得上，先匯進來
from agent.utils.profiler import log_duration, log_total
from agent.llm_utils.ollama_client import call_llm  # 你既有的封裝
from agent.config.index_loader import INDEX_CONFIG
from agent.agent_utils import _pack_chat_history_items,_build_query_for_agent_in_agent
from .style_agent import ask_with_style
from .report_agent import ask_with_report
from .doc_followup_agent import ask_with_doc_followup

from .session_store import FileSessionStore

SESSION_STORE_ENABLED = os.getenv("SESSION_STORE_ENABLED", "1") == "1"
SESSION_STORE_DIR = os.getenv("SESSION_STORE_DIR", ".agent_sessions")
SESSION_MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "60"))
SESSION_MAX_CHARS = int(os.getenv("SESSION_MAX_CHARS", "8000"))
SESSION_STORE_ASSISTANT = os.getenv("SESSION_STORE_ASSISTANT", "1") == "1"

SESSION_STORE = FileSessionStore(
    base_dir=SESSION_STORE_DIR,
    enabled=SESSION_STORE_ENABLED,
    max_turns=SESSION_MAX_TURNS,
    max_chars_per_turn=SESSION_MAX_CHARS,
    store_assistant=SESSION_STORE_ASSISTANT,
)

DEBUG_ROUTER = os.getenv("DEBUG_ROUTER", "1") == "1"


# ★ 新增：路由專用的模型 ID（可獨立於主 MODEL_ID）
ROUTER_MODEL_ID = (
    os.getenv("ROUTER_MODEL_ID")   # 若有指定就用這個
    or os.getenv("MODEL_ID")       # 沒指定就沿用主模型
    or "gpt-oss:120b-32k"          # 再不然就用一個預設
)

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


def _llm_route_task(
    user_msg: str,
    trace: Optional[Dict[str, Any]] = None,
) -> dict:
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
        with log_duration(
            "[router] LLM route",
            extra={"model_id": ROUTER_MODEL_ID},
        ):
            raw = call_llm(
                user_prompt,
                system_prompt=TASK_ROUTER_SYSTEM,
                extra_params={"options": {}},
                timeout=60.0,
                model=ROUTER_MODEL_ID,
            )
        t1 = time.perf_counter()
        result = json.loads(raw)
        
        # ★ 這裡把路由 LLM 的資訊寫進 trace["llm"]["router"]
        llm_root = trace.setdefault("llm", {})
        router_logs: list[Dict[str, Any]] = llm_root.setdefault("router", [])
        router_logs.append({
            "system": "TASK_ROUTER_SYSTEM",
            "user": user_prompt,
            "raw_response": raw,
            "parsed": result,
            "elapsed_sec": round(t1 - t0, 3),   # 保留給 trace 用
            "model_id": ROUTER_MODEL_ID,
        })
    except Exception as e:
        print("[router] LLM route failed:", e)
        # 失敗也寫一筆進 trace（方便 debug）
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
    trace: Optional[Dict[str, Any]] = None,
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
            "topic": "none",
        }

    return _llm_route_task(text, trace=trace)



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


def answer_with_routing(
    user_msg: str,
    query_for_agent: Optional[str] = None,          # 舊參數保留（相容）
    history_msgs: Optional[List[dict]] = None,      # ✅ 新增
    memory_text: Optional[str] = None,              # ✅ 新增
    last_structured: Optional[Dict[str, Any]] = None,  # ✅ 新增
    recent_user_msgs: list[str] | None = None,
    reuse_uuids: list[str] | None = None,
    refno_uuid_map: Optional[Dict[int, str]] = None,
    session_id: str | None = None,          # ★ 新增：可選，不一定會用到
    request_id: str | None = None,          # ★ 新增：可選，不一定會用到
    trace: Optional[Dict[str, Any]] = None, # ★ 新增：可選，用來累積遙測資訊
) -> Dict[str, Any]:
    """
    高層入口：
    - 用 LLM 做任務分流（SRA_REPORT / SRA_STYLE / PURE_LLM / DOC_FOLLOWUP）
    - 視情況呼叫 ask_with_report / ask_with_style / 一般 call_llm
    - 回傳統一格式：{ answer, citations, reasoning, mode, route }
    
    user_msg:使用者原始輸入
    
    query_for_agent = (
        (f"【對話記憶】\n{mem_txt}\n\n" if mem_txt else "") +
        f"【對話歷史】\n{history_text}\n\n"
        f"【目前問題】\n{user_msg}\n\n"
        "【要求】如果是有對話歷史的多輪對話，那麼延續上文已確立的主題/時間範圍/定義；避免過度衍伸。"
    )
    
    recent_user_msgs:
      - 可選；如果有傳進來，會拿「最近 k 個」來幫助任務判斷
      - 只應該放 user 的提問內容，不要放 assistant 的回答
      
    """
    # ★ 如果上游沒傳 trace 進來，就自己準備一個空的，避免 None
    trace = trace or {}
    # ✅ 若 API 端沒給 query_for_agent，就由 agent 自己組
    
    print("In answer_with_routing, input user_msg",user_msg)
    print("In answer_with_routing, input query_for_agent",query_for_agent)
    if not query_for_agent:
        query_for_agent = _build_query_for_agent_in_agent(
            user_msg=user_msg,
            history_msgs=history_msgs,
            memory_text=memory_text,
        )
        print("In answer_with_routing, after running _build_query_for_agent_in_agent",query_for_agent)
        
    # ✅ carry_over：給後續精煉 / 延續定義用（先放著，Level 2 會用）
    carry_over = {}
    prev = last_structured or {}
    if isinstance(prev, dict):
        qm = prev.get("query_meta") or {}
        if isinstance(qm, dict):
            # 例：上輪時間範圍（如果你有）
            tr = prev.get("time_range") or qm.get("time_range") or {}
            if isinstance(tr, dict):
                carry_over["time_range"] = tr
            # 也可以帶 core_terms / 定義等
            ct = prev.get("core_terms") or qm.get("core_terms")
            if isinstance(ct, list):
                carry_over["core_terms"] = ct

    trace.setdefault("context", {})
    trace["context"].update({
        "has_history": bool(history_msgs),
        "has_memory": bool((memory_text or "").strip()),
        "has_last_structured": bool(prev),
    })
    
    t_start = time.perf_counter()
    
    user_msg = (user_msg or "").strip()
    if not user_msg:
        out = {
            "answer": "目前沒有收到任何問題內容，請再輸入一次。",
            "citations": [],
            "reasoning": "空輸入，直接回覆提示。",
            "mode": "PURE_LLM",
            "route": {"mode": "PURE_LLM", "reason": "empty", "es_index_key": None},
        }
        # 簡單寫到 trace.routing，方便後面存檔
        trace.setdefault("routing", {}).update({
            "mode": "PURE_LLM",
            "reason": "empty",
            "topic": None,
            "indexes": [],
        })
        return out
    # === 0) session 持久化：從檔案補回多輪對話 / context ===
    state = None
    if session_id and SESSION_STORE_ENABLED:
        state = SESSION_STORE.get(session_id)

        # recent_user_msgs：只放 user 的提問（你的 docstring 也這樣要求）:contentReference[oaicite:4]{index=4}
        #if recent_user_msgs is None:
        #    recent_user_msgs = SESSION_STORE.recent_user_msgs(state, k=10)

        if not recent_user_msgs:
            recent_user_msgs = []
        
        file_recent = SESSION_STORE.recent_user_msgs(state, k=10)
        
        # 合併（檔案舊 → API 新），去重但保留順序
        merged: list[str] = []
        seen = set()
        for x in (file_recent + recent_user_msgs):
            if x and x not in seen:
                seen.add(x)
                merged.append(x)
        
        recent_user_msgs = merged[-10:]  # 最後只留 10 條

        # reuse_uuids / refno_uuid_map：讓重啟後仍可 DOC_FOLLOWUP
        if not reuse_uuids:
            ctx_uuids = state.context.get("reuse_uuids")
            if isinstance(ctx_uuids, list):
                reuse_uuids = ctx_uuids

        if not refno_uuid_map:
            ctx_map = state.context.get("refno_uuid_map")
            if isinstance(ctx_map, dict):
                refno_uuid_map = ctx_map  # 先照存，後面你本來就會轉 int key :contentReference[oaicite:5]{index=5}

        # 先把本輪 user 問題寫入 turn（即便後面路由/LLM 失敗也留得到）
        SESSION_STORE.append_turn(state, "user", user_msg, meta={"request_id": request_id})
        SESSION_STORE.save(state)
        
    # === 1) 準備任務分流器輸入 ===
    router_input = _build_router_input(
        current_user_msg=user_msg,
        recent_user_msgs=recent_user_msgs,
        k=2,   # ★ 最近 2 輪 + 目前這一輪
    )

    # === 2) LLM 任務分類 ===
    route = route_task_mode(router_input, trace=trace)
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
        index_hint = ",".join(indexes)
    else:
        index_hint = None
        
    # ★ 把「最終要用的索引資訊」補回 route，讓前端直接看到
    route["topic"] = topic
    route["indexes"] = indexes
    route["index_hint"] = index_hint
    
    # ★ 收集所有 index（給 DOC_FOLLOWUP 做 fallback）
    topic_map = INDEX_CONFIG.get("topic_index_map", {}) or {}
    all_indexes: list[str] = []
    for cfg in topic_map.values():
        for idx in cfg.get("indexes") or []:
            if idx and idx not in all_indexes:
                all_indexes.append(idx)

    # ★ 把 routing 的基本資訊寫進 trace
    trace.setdefault("routing", {}).update({
        "mode": mode,
        "topic": topic,
        "indexes": indexes,
        "index_hint": index_hint,
        "route_raw": route,
    })

    # 如果想多一筆 event log 也可以：
    try:
        log_event(
            "task_routing",
            session_id=session_id,
            request_id=request_id,
            data={
                "mode": mode,
                "topic": topic,
                "indexes": indexes,
            },
        )
    except Exception:
        # 就算遙測寫失敗也不要影響主流程
        pass

    # === 4) 給 CodeAgent 的 query ===
    q_for_agent = (query_for_agent or user_msg).strip()
    #q_for_agent = index_hint_prefix + q_for_agent
    # ★ 可選：把 query_for_agent 寫進 trace，方便 debug
    trace.setdefault("keywords", {}).update({
        "q_for_agent": q_for_agent,
    })
    try:
        # === DOC_FOLLOWUP：針對既有參考文件做後續處理，不再查新的 ES ===
        if mode == "DOC_FOLLOWUP":
            ref_map_int: Optional[Dict[int, str]] = None
            if refno_uuid_map:
                ref_map_int = {}
                for k, v in refno_uuid_map.items():
                    try:
                        kk = int(k)
                    except Exception:
                        continue
                    ref_map_int[kk] = v

            out = ask_with_doc_followup(
                instruction=user_msg,
                uuids=reuse_uuids or [],
                index_hint=index_hint,
                refno_uuid_map=ref_map_int,
                index_candidates=all_indexes,
                # ★ 這裡先不要傳 session_id / trace，避免子函式 signature 不合
            )

        # === SRA_REPORT：產生資料 payload → 報告 LLM 寫結論 ===
        elif mode == "SRA_REPORT":
            out = ask_with_report(
                q_for_agent,
                # 之後如果你有改 ask_with_report 支援 trace，再把 session_id / request_id / trace 傳進去
                index_hint=index_hint,   # ★ 新增：用參數下傳
                trace=trace
            )

        # === SRA_STYLE：用既有語料模仿風格 ===
        elif mode == "SRA_STYLE":
            #style_query = index_hint_prefix + user_msg
            out = ask_with_style(
                #style_query,
                user_msg,
                index_hint=index_hint,   # ★ 新增：用參數下傳
                trace=trace,
            )

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
        # 這邊也順便寫一下 trace
        trace.setdefault("routing", {}).update({
            "error": str(e),
        })
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

    # ✅ 統一保證每個模式都有「使用者提問」（Word / Markdown 都靠這個）
    out.setdefault("question", user_msg)

    # ✅ 可選：順手放 refined（若你後面有地方會用）
    #qm = out.setdefault("query_meta", {})
    #if isinstance(qm, dict):
    #    qm.setdefault("refined_question", (query_for_agent or user_msg).strip())
    # ✅ 統一保證每個模式都有「使用者提問」
    #out.setdefault("question", user_msg)
    
    qm = out.setdefault("query_meta", {})
    if isinstance(qm, dict):
        #qm.setdefault("question_raw", user_msg)  # 原始問句（展示/稽核）
        qm.setdefault("user_question", user_msg)  # 原始問句（展示/稽核）
        qm.setdefault("query_for_agent", (query_for_agent or user_msg).strip())  # 可能含上下文拼裝，僅供 debug
    
        # refined_question：交給下游（report_agent / refiner）來填
        # 如果下游有回傳 q（report_agent 有），就用它補上
        if not qm.get("refined_question"):
            refined = out.get("q")
            if not refined and isinstance(out.get("query_meta"), dict):
                refined = out["query_meta"].get("refined_question")
            if refined:
                qm["refined_question"] = refined
        
    # ★ 從 trace 裡把 data_agent 掛回結果（若還沒掛）
    data_agent = trace.get("data_agent")
    if data_agent and "data_agent" not in out:
        out["data_agent"] = data_agent
        
    # ★ 如果是 DOC_FOLLOWUP，且底層有回傳 used_indexes，就加到 route
    if mode == "DOC_FOLLOWUP":
        used_indexes = out.get("used_indexes") or []
        if used_indexes:
            out["route"]["actual_indexes"] = used_indexes
            
    # === 9) session 持久化：寫回 assistant + 更新 context ===
    if state is not None and SESSION_STORE_ENABLED:
        try:
            # 存 assistant 回覆（可用環境變數關掉）
            SESSION_STORE.append_turn(
                state,
                "assistant",
                (out.get("answer") or ""),
                meta={
                    "mode": out.get("mode"),
                    "topic": (out.get("route") or {}).get("topic"),
                    "request_id": request_id,
                },
            )

            # 把 used_uuids / refno_uuid_map 存入 context，確保重啟後 DOC_FOLLOWUP 仍可用
            SESSION_STORE.update_context_from_out(state, out)

            SESSION_STORE.save(state)
        except Exception as e:
            print("[agent] session_store writeback error:", e)
            
    log_total(
        "[answer_with_routing][TOTAL]",
        t_start,
        extra={"mode": mode, "topic": topic},
    )
    
    
    return out

# 允許：python -m agent.agent 快速測試
if __name__ == "__main__":
    q = "請整理2025年『拉拉隊』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    print(ask_with_report(q))

