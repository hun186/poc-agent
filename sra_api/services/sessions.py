# api/services/sessions.py
import re
import os
import hashlib
from collections import defaultdict, deque, OrderedDict
from typing import Deque, Dict
from pydantic import BaseModel
from api.services.api_state_store import API_STORE

_persist_loaded = False

def _ensure_loaded_from_disk() -> None:
    global _persist_loaded
    if _persist_loaded:
        return
    _persist_loaded = True

    raw = API_STORE.load_raw_once() or {}
    raw_sessions = raw.get("sessions") or {}
    raw_last = raw.get("last_structured") or {}
    raw_hist = raw.get("structured_history") or {}

    # 1) 回填 sessions
    if isinstance(raw_sessions, dict):
        _sessions.clear()
        for sk, items in raw_sessions.items():
            if not isinstance(sk, str) or not isinstance(items, list):
                continue
            dq: Deque[ChatMessage] = deque(maxlen=SESSION_MAX_TURNS)
            for it in items[-SESSION_MAX_TURNS:]:
                if not isinstance(it, dict):
                    continue
                role = (it.get("role") or "").strip()
                content = it.get("content") or ""
                fmt = it.get("format") or "markdown"
                if role and isinstance(content, str):
                    dq.append(ChatMessage(role=role, content=content, format=fmt))
            if len(dq) > 0:
                _sessions[sk] = dq

    # 2) 回填 last_structured
    if isinstance(raw_last, dict):
        _last_structured.clear()
        for sk, out in raw_last.items():
            if isinstance(sk, str) and isinstance(out, dict):
                _last_structured[sk] = out

    # 3) 回填 structured_history（每輪快照）
    if isinstance(raw_hist, dict):
        _structured_history.clear()
        for sk, turns in raw_hist.items():
            if not isinstance(sk, str) or not isinstance(turns, dict):
                continue
            od: "OrderedDict[str, dict]" = OrderedDict()

            # turns: turn_id -> out
            for tid, out in turns.items():
                if not tid:
                    continue
                if isinstance(out, dict):
                    od[str(tid)] = out

            # 淘汰最舊，避免爆
            while len(od) > MAX_EXPORTS_PER_SESSION:
                od.popitem(last=False)

            if len(od) > 0:
                _structured_history[sk] = od
                
# ===== Session store（簡易記憶）=====
SESSION_MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "20"))

# ★ 最多保留多少個 session，超過就淘汰最舊的一個
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "100"))


class ChatMessage(BaseModel):
    role: str
    content: str
    format: str | None = "markdown"   # ← 新增


_sessions: dict[str, deque[ChatMessage]] = defaultdict(lambda: deque(maxlen=SESSION_MAX_TURNS))
_last_structured: dict[str, dict] = {}     # 會話 -> 上一輪 out（answer/citations/reasoning）
# 每個 session 存多輪 structured out（供每輪下載 Word）
MAX_EXPORTS_PER_SESSION = int(os.getenv("MAX_EXPORTS_PER_SESSION", "50"))

# session_id -> OrderedDict(turn_id -> out)
_structured_history: dict[str, "OrderedDict[str, dict]"] = defaultdict(OrderedDict)

# 多輪對話：抽前文答覆的「主文」，避免把 citations / details 整坨塞回模型
HISTORY_MAX_CHARS = int(os.getenv("HISTORY_MAX_CHARS", "12000"))

# 允許 "# 回答" 或純文字 "回答" 開頭；
# 主文擷取到「## 來源 / Citations」或「## 原始」或 <details> 或字串結尾 \Z 為止
ANSWER_BLOCK_RE = re.compile(
    r'(?su)^\s*(?:#\s*回答|回答)\s*\n'   # ^ 只錨定字串開頭，不要 multiline
    r'(?P<body>.*?)'
    r'(?=\n(?:'
        r'##\s*(?:來源|来源)\b'           # ## 來源
        r'|##\s*Citations\b'              # ## Citations
        r'|來源\s*/?\s*Citations'         # 來源 / Citations（保險，不一定有 ##）
        r'|##\s*(?:原始|原始\s*JSON)\b'   # ## 原始 / ## 原始 JSON
        r'|<details>'                     # <details>（推理/原始JSON 可能用 details）
        r'|\Z'                            # ✅ 僅匹配字串結尾（避免每行行尾）
    r'))'
)

# 與上面白名單一致；無需 $，所以不受 multiline 影響
_CUTOFF_RE = re.compile(
    r'\n(?:##\s*(?:來源|来源|Citations|原始|原始\s*JSON)\b|來源\s*/?\s*Citations|<details>)',
    re.I
)



def _normalize_newlines_for_save(s: str) -> str:
    # 把 \r\n → \n，並把「字面上的」\n 變成真正的換行
    return (s or "").replace("\r\n", "\n").replace("\\n", "\n").strip()

def _strip_assistant_content(s: str) -> str:
    # 先正規化換行，避免 CRLF 或字面 "\n" 影響邊界
    s = _normalize_newlines_for_save((s or "").strip())
    if not s:
        return s
    m = ANSWER_BLOCK_RE.search(s)
    if m:
        return m.group("body").strip()
    # Fallback：找白名單分隔符直接截
    return _CUTOFF_RE.split(s, 1)[0].strip()

def pack_chat_history(messages: list[ChatMessage], *, max_chars: int = HISTORY_MAX_CHARS) -> str:
    """
    將過往 system/user/assistant 簡化為：
      SYSTEM: ...
      USER: ...
      ASSISTANT: ...(只留主文)
    並限制長度（保留最近 max_chars 字元）。
    """
    lines: list[str] = []
    for m in messages:
        role = (m.role or "").lower()
        if role not in ("system", "user", "assistant"):
            continue
        content = (m.content or "").strip()
        if not content:
            continue
        if role == "assistant":
            #print("content before",content)
            content = _strip_assistant_content(content)
            #print("content after _strip_assistant_content",content)
            content = _normalize_newlines_for_save(content)
            #print("content after _normalize_newlines_for_save",content)
        lines.append(f"{role.upper()}:\n{content}\n")
    s = "".join(lines)
    if len(s) > max_chars:
        s = s[-max_chars:]   # 保留最近的上下文
    return s

def infer_session_key_from_payload(messages: list[ChatMessage]) -> str:
    """
    若前端沒帶 header，就用「第一個 user 訊息」的內容做 hash 當 session_key。
    同一個聊天室第一句不變 → session_key 穩定；不同聊天室 → 自然不同。
    """
    first_user = ""
    for m in messages:
        role = (m.role or "").lower()
        if role == "user":
            txt = (m.content or "").strip()
            if txt:
                first_user = txt
                break

    if not first_user:
        # 沒有 user 訊息，就退回用遞增編號（很少發生）
        return f"conv_{len(_sessions) + 1}"

    h = hashlib.sha256(first_user.encode("utf-8")).hexdigest()[:16]
    return f"conv_{h}"

def _best_assistant_text(session_id: str, maybe_text_from_client: str) -> str:
    """
    優先使用我們剛剛保存的完整渲染文本；若無則用前端回傳的。
    """
    if session_id and session_id in _sessions:
        # 在 deque 尾端尋找最近一則 assistant
        for m in reversed(_sessions[session_id]):
            if (getattr(m, "role", "") or "").lower() == "assistant":
                return str(m.content or "").strip() or maybe_text_from_client
    return maybe_text_from_client

def choose_assistant_save(out: dict | str, rendered_text: str) -> str:
    def _is_rich(txt: str) -> bool:
        txt = (txt or "").strip()
        return len(txt) >= 80 or txt.count("\n") >= 2

    if isinstance(out, dict):
        body = str(out.get("answer") or "")
        if _is_rich(body):
            return _normalize_newlines_for_save(body)
        pure = _strip_assistant_content(str(rendered_text))
        better = pure if len(pure) > len(body) else body
        return _normalize_newlines_for_save(better)
    return _normalize_newlines_for_save(_strip_assistant_content(str(rendered_text)))


def get_sessions():
    _ensure_loaded_from_disk()
    return _sessions

def get_last_structured():
    _ensure_loaded_from_disk()
    return _last_structured


def save_structured_snapshot(session_id: str, turn_id: str, out: dict) -> None:
    """
    存「某一輪」structured out（turn_id 建議用 request_id）。
    同時也會更新 last_structured（保持舊功能不變）。
    """
    if not session_id or not turn_id or not isinstance(out, dict):
        return

    # ✅ 只存你允許的模式（避免垃圾 out 塞爆 structured_history）
    mode = out.get("mode")
    if mode not in ("SRA_REPORT", "SRA_STYLE", "DOC_FOLLOWUP", "PURE_LLM"):
        return
    
    _ensure_loaded_from_disk()

    # out 自己帶上 turn_id（之後 render 按鈕好用）
    out.setdefault("session_id", session_id)
    out.setdefault("turn_id", str(turn_id))
    out.setdefault("request_id", str(turn_id))

    _last_structured[session_id] = out

    hist = _structured_history[session_id]
    hist[str(turn_id)] = out

    # 淘汰最舊
    while len(hist) > MAX_EXPORTS_PER_SESSION:
        hist.popitem(last=False)


def get_structured_snapshot(session_id: str, turn_id: str | None = None) -> dict | None:
    """
    取指定輪 out；turn_id=None 則回傳最新一輪（相容舊行為）。
    """
    _ensure_loaded_from_disk()

    if not session_id:
        return None

    if not turn_id:
        out = _last_structured.get(session_id)
        return out if isinstance(out, dict) else None

    out = _structured_history.get(session_id, {}).get(str(turn_id))
    return out if isinstance(out, dict) else None


def get_structured_history():
    """
    給 API_STORE 存檔用：取整包 structured_history。
    """
    _ensure_loaded_from_disk()
    return _structured_history
