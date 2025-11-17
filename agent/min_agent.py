# agent/min_agent.py
from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()

import os, json, traceback, time, uuid, typing as T
from dataclasses import dataclass
from pydantic import BaseModel, Field, ValidationError
import requests
import logging  # NEW

# ---------- 日誌設定（可用環境變數調等級） ----------
LOG_LEVEL = os.getenv("AGENT_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("min_agent")

def _short(s: str, n: int = 500) -> str:
    s = s or ""
    return s[:n] + ("…(trunc)" if len(s) > n else "")

def _now_ms() -> int:
    return int(time.time() * 1000)

# 建議：模型共用、Agent 每請求新建
_SHARED_MODEL = None

# === 模型設定（可用 .env 覆寫） ===
MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))

from agent.tools_es import ESSearchNews, ESTimeline

OPENAI_BASE = os.environ.get("MODEL_BASE_URL", "http://localhost:11434")
MODEL_ID = os.environ.get("MODEL_ID", "gpt-oss:120b-32k")
API_KEY = os.environ.get("OPENAI_API_KEY", "no-key-needed-for-local")

# ---------- Chat Completions 包裝（加上耗時與失敗細節） ----------
def chat_api(messages: list[dict], response_format_json: bool = True) -> dict:
    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "temperature": 0,
    }
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    t0 = _now_ms()
    try:
        r = requests.post(f"{OPENAI_BASE}/v1/chat/completions", headers=headers, json=payload, timeout=120)
        dt = _now_ms() - t0
        log.debug(f"[chat_api] status={r.status_code} dt_ms={dt} url={OPENAI_BASE}/v1/chat/completions")
        # 若 4xx/5xx，先記錄 body 再 raise，以免只看到 500
        if r.status_code >= 400:
            log.error(f"[chat_api] HTTP {r.status_code} body={_short(r.text)}")
        r.raise_for_status()
        j = r.json()
        # 簡短列印模型回覆摘要
        try:
            content = j["choices"][0]["message"]["content"]
            log.debug(f"[chat_api] model_content={_short(content)}")
        except Exception:
            pass
        return j
    except Exception as e:
        log.exception("[chat_api] request failed")
        raise

# ===== 工具參數模型（略） =====
class SearchNewsArgs(BaseModel):
    query: str
    must_high_value: bool | None = False
    must_selected: bool | None = False
    size: int | None = 10
    date_from: str | None = None
    date_to: str | None = None
    selected_boost: float | None = 6.0
    high_value_boost: float | None = 2.5
    recency_boost: bool | None = False
    recency_field: str | None = "importDT"
    recency_scale: str | None = "30d"

class TimelineArgs(BaseModel):
    uuid: str
    k: int | None = 10

@dataclass
class ToolSpec:
    name: str
    desc: str
    args_model: type[BaseModel]
    run: T.Callable[[BaseModel], dict]

TOOLS: dict[str, ToolSpec] = {
    "es_search_news": ToolSpec(
        name="es_search_news",
        desc="新聞檢索：支援關鍵字 / 日期過濾 / 內文證據段落回傳。",
        args_model=SearchNewsArgs,
        run=lambda a: ESSearchNews().forward(**a.dict())
    ),
    "es_timeline": ToolSpec(
        name="es_timeline",
        desc="讀取指定 uuid 的時間線（date_iso, description）。",
        args_model=TimelineArgs,
        run=lambda a: ESTimeline().forward(**a.dict())
    ),
}

SYSTEM = """你是「新聞/政策問答助理」。你只能回傳 JSON，不得輸出文字敘述。
輸出有兩種形態：
1) 工具呼叫：
   {"call": {"tool": "<tool_name>", "args": { ... }}}
   - tool ∈ {""" + ",".join(TOOLS.keys()) + """}
   - args 必須符合該工具參數結構
2) 最終答案：
   {"final": {"answer":"<繁體中文總結>", "citations":[...], "reasoning":"<簡述>"}}

規則：
- 工具回傳值會再以 role=tool 回餵給你，你可多輪呼叫 1~3 次。
- 請務必用繁體中文撰寫 final.answer。
- 僅輸出 JSON（單一物件），不得夾雜其他字元。
- 參數名稱必須精準符合工具定義：日期請使用 "date_from" 與 "date_to"（不得使用 start_date / end_date）。
- 若無法判斷日期，先使用 { "call": { "tool": "es_search_news", "args": { "query": "<使用者原句>", "size": 10 } } }。
"""

def parse_json(s: str) -> dict:
    s = (s or "").strip()
    try:
        return json.loads(s)
    except Exception:
        # 去除 ```json 包裹
        if s.startswith("```"):
            try:
                s2 = s[s.find("{"): s.rfind("}") + 1]
                return json.loads(s2)
            except Exception:
                pass
        raise

# ---------- 主流程：加入 debug trace ----------
def run_agent(user_query: str, max_calls: int = 3, debug: bool = False) -> dict:
    trace: list[dict] = []
    def tr(event: str, **kw):
        item = {"t": _now_ms(), "event": event, **kw}
        trace.append(item)
        if LOG_LEVEL in ("DEBUG", "TRACE"):
            # 即時也打到 console
            log.debug(f"[trace] {event} | { {k: ( _short(v) if isinstance(v,str) else v) for k,v in kw.items()} }")

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_query}]
    tr("start", user_query=user_query)

    for step in range(max_calls + 1):
        t0 = _now_ms()
        try:
            resp = chat_api(messages, response_format_json=True)
        except Exception as e:
            tr("chat_error", step=step, error=str(e), tb=traceback.format_exc())
            break
        dt = _now_ms() - t0

        content = ""
        try:
            content = resp["choices"][0]["message"]["content"]
        except Exception as e:
            tr("malformed_response", step=step, raw=_short(json.dumps(resp, ensure_ascii=False)))
            break

        tr("llm_reply", step=step, dt_ms=dt, content=_short(content))

        # 解析 JSON
        try:
            obj = parse_json(content)
        except Exception as e:
            tr("json_parse_fail", step=step, content_preview=_short(content), err=str(e))
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "請只輸出有效 JSON。"})
            continue

        # 分流：tool call / final
        if "call" in obj:
            call = obj["call"]
            tool_name = call.get("tool")
            args = call.get("args", {})
        
            # ★ 鍵名正規化（避免 LLM 回 start_date/end_date）
            if tool_name == "es_search_news":
                if "start_date" in args and "date_from" not in args:
                    args["date_from"] = args.pop("start_date")
                if "end_date" in args and "date_to" not in args:
                    args["date_to"] = args.pop("end_date")
                # 也順手容錯常見替代鍵
                for a, b in (("from", "date_from"), ("to", "date_to")):
                    if a in args and b not in args:
                        args[b] = args.pop(a)

            spec = TOOLS[tool_name]
            try:
                parsed = spec.args_model(**args)
            except ValidationError as ve:
                tr("arg_validation_error", tool=tool_name, error=str(ve))
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"參數驗證失敗：{ve}. 請修正後再輸出 JSON。"})
                continue

            # 執行工具並量測耗時 / 結果摘要
            t1 = _now_ms()
            try:
                result = spec.run(parsed)  # dict
                dt_tool = _now_ms() - t1
                # 摘要（避免整包貼 log）
                summary = {}
                if tool_name == "es_search_news":
                    hits = (result or {}).get("hits", [])
                    summary = {"hits": len(hits)}
                elif tool_name == "es_timeline":
                    tl = (result or {}).get("timeline", [])
                    summary = {"timeline": len(tl)}
                tr("tool_done", tool=tool_name, dt_ms=dt_tool, summary=summary)
            except Exception as e:
                tr("tool_exception", tool=tool_name, error=str(e), tb=traceback.format_exc())
                result = {"error": str(e)}
            # 回餵工具結果
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "tool", "name": tool_name, "content": json.dumps(result, ensure_ascii=False)})
            continue

        if "final" in obj:
            tr("final_ready")
            final = obj["final"]
            if debug:
                final["_debug"] = trace  # 把完整 trace 夾帶回傳（見下方 API 包裝）
            return final

        tr("format_error", step=step, obj_type=list(obj.keys()))
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": "格式錯誤。請只輸出 {\"call\":...} 或 {\"final\":...} 的 JSON。"})

    # 超出 max_calls 或出錯
    tr("give_up")
    out = {"answer": "未能完成檢索流程。請更明確描述問題或放寬條件。", "citations": [], "reasoning": "超過最大工具呼叫次數或上游失敗。"}
    if debug:
        out["_debug"] = trace
    return out
