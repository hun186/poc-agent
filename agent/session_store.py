# agent/session_store.py
from __future__ import annotations

import json
import os
import re
import time
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    # 2025-12-24T21:30:00+08:00 這種格式也可；此處用簡單 epoch 方便
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _safe_session_id(session_id: str) -> str:
    s = (session_id or "").strip()
    if not s:
        return "default"
    # 檔名安全：只留常見字元
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:120]  # 避免檔名過長


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)  # atomic on same filesystem
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


@dataclass
class SessionState:
    session_id: str
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    # turns: [{role:"user"|"assistant", content:"...", ts:"..."}]
    turns: List[Dict[str, Any]] = field(default_factory=list)

    # 可供下輪 DOC_FOLLOWUP / 路由使用的 context
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turns": self.turns,
            "context": self.context,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SessionState":
        s = SessionState(session_id=d.get("session_id") or "default")
        s.created_at = d.get("created_at") or _now_iso()
        s.updated_at = d.get("updated_at") or _now_iso()
        s.turns = d.get("turns") or []
        s.context = d.get("context") or {}
        return s


class FileSessionStore:
    """
    - 每個 session_id 對應一個 json 檔
    - 同時保留記憶體快取：效能更穩
    """

    def __init__(
        self,
        base_dir: str = ".agent_sessions",
        enabled: bool = True,
        max_turns: int = 60,          # 只保留最後 N 筆 turn（含 user/assistant）
        max_chars_per_turn: int = 8000,
        store_assistant: bool = True, # 是否也存 assistant 回覆（方便回溯）
    ) -> None:
        self.base_dir = base_dir
        self.enabled = enabled
        self.max_turns = max_turns
        self.max_chars_per_turn = max_chars_per_turn
        self.store_assistant = store_assistant
        self._cache: Dict[str, SessionState] = {}

    def _path(self, session_id: str) -> str:
        sid = _safe_session_id(session_id)
        return os.path.join(self.base_dir, f"{sid}.json")

    def get(self, session_id: str) -> SessionState:
        sid = _safe_session_id(session_id)
        if sid in self._cache:
            return self._cache[sid]

        path = self._path(sid)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                state = SessionState.from_dict(d if isinstance(d, dict) else {})
            except Exception:
                # 檔案壞掉就先重建，避免整個服務掛掉
                state = SessionState(session_id=sid)
        else:
            state = SessionState(session_id=sid)

        self._cache[sid] = state
        return state

    def save(self, state: SessionState) -> None:
        if not self.enabled:
            return
        state.updated_at = _now_iso()
        _atomic_write_json(self._path(state.session_id), state.to_dict())

    def _trim(self, text: str) -> str:
        t = (text or "").strip()
        if len(t) > self.max_chars_per_turn:
            return t[: self.max_chars_per_turn] + "\n…(截斷)"
        return t

    def append_turn(self, state: SessionState, role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        if role == "assistant" and not self.store_assistant:
            return

        item: Dict[str, Any] = {
            "role": role,
            "content": self._trim(content),
            "ts": _now_iso(),
        }
        if meta:
            item["meta"] = meta

        state.turns.append(item)

        # 只保留最後 max_turns 筆
        if self.max_turns > 0 and len(state.turns) > self.max_turns:
            state.turns = state.turns[-self.max_turns :]

    def recent_user_msgs(self, state: SessionState, k: int = 10) -> List[str]:
        msgs: List[str] = []
        for t in state.turns:
            if t.get("role") == "user":
                c = (t.get("content") or "").strip()
                if c:
                    msgs.append(c)
        return msgs[-k:] if k > 0 else msgs

    def update_context_from_out(self, state: SessionState, out: Dict[str, Any]) -> None:
        """
        把 report/style 輸出中可供下一輪使用的欄位存起來
        """
        if not out or not isinstance(out, dict):
            return

        # 讓重啟後仍可 DOC_FOLLOWUP：優先 refno_uuid_map，其次 used_uuids
        used_uuids = out.get("used_uuids")
        if isinstance(used_uuids, list) and used_uuids:
            state.context["reuse_uuids"] = used_uuids

        refno_uuid_map = out.get("refno_uuid_map")
        if isinstance(refno_uuid_map, dict) and refno_uuid_map:
            # JSON key 會變字串；先照存，讀取端再轉 int
            state.context["refno_uuid_map"] = refno_uuid_map

        # 也可以順便存 mode/topic 方便 debug
        if out.get("mode"):
            state.context["last_mode"] = out.get("mode")
        if isinstance(out.get("route"), dict) and out["route"].get("topic"):
            state.context["last_topic"] = out["route"].get("topic")
