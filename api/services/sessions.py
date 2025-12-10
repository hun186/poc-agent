# api/services/sessions.py
import re
import os
import hashlib
from collections import defaultdict, deque
from typing import Deque, Dict
from pydantic import BaseModel

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
    return _sessions

def get_last_structured():
    return _last_structured