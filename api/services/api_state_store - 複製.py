# api/services/api_state_store.py
from __future__ import annotations

import json
import os
import time
import tempfile
from typing import Any, Dict, Optional, Tuple, List

from api.services.sessions import ChatMessage


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


class APIStateStore:
    """
    儲存三份資料：
    - sessions：{session_key: [{role, content}, ...]}
    - last_structured：{session_key: {...structured out...}}
    - memory：{session_key: ...}  (依你的 api/services/memory.py 結構照存)
    """

    def __init__(
        self,
        base_dir: str = ".api_state",
        enabled: bool = True,
        filename: str = "state.json",
        save_min_interval_sec: float = 1.0,   # 節流：避免每次請求都狂寫硬碟
        max_messages_per_session: int = 200,  # 保底，避免單一 session 檔案爆大
    ) -> None:
        self.base_dir = base_dir
        self.enabled = enabled
        self.filename = filename
        self.save_min_interval_sec = save_min_interval_sec
        self.max_messages_per_session = max_messages_per_session

        self._loaded_once = False
        self._last_save_ts = 0.0

    @property
    def path(self) -> str:
        return os.path.join(self.base_dir, self.filename)

    def load_once(
        self,
        sessions: Dict[str, List[ChatMessage]],
        last_structured: Dict[str, Any],
        memory_all: Dict[str, Any],
    ) -> Tuple[int, int, int]:
        """
        只載入一次（避免每次 request 重複載）。
        回傳：載入的 sessions / last_structured / memory 的 key 數量
        """
        if not self.enabled or self._loaded_once:
            return (0, 0, 0)

        d = _read_json(self.path)
        self._loaded_once = True
        if not d:
            return (0, 0, 0)

        raw_sessions = d.get("sessions") or {}
        raw_last = d.get("last_structured") or {}
        raw_mem = d.get("memory") or {}

        # 1) sessions：轉回 ChatMessage
        if isinstance(raw_sessions, dict):
            for sk, items in raw_sessions.items():
                if not isinstance(sk, str) or not isinstance(items, list):
                    continue
                msgs: List[ChatMessage] = []
                for it in items[-self.max_messages_per_session :]:
                    if not isinstance(it, dict):
                        continue
                    role = (it.get("role") or "").strip()
                    content = it.get("content") or ""
                    if role and isinstance(content, str):
                        msgs.append(ChatMessage(role=role, content=content))
                if msgs:
                    sessions[sk] = msgs

        # 2) last_structured：照存
        if isinstance(raw_last, dict):
            for sk, out in raw_last.items():
                if isinstance(sk, str) and isinstance(out, dict):
                    last_structured[sk] = out

        # 3) memory：照存（依你 memory.py 的 dict 結構）
        if isinstance(raw_mem, dict):
            for sk, v in raw_mem.items():
                if isinstance(sk, str):
                    memory_all[sk] = v

        return (len(raw_sessions), len(raw_last), len(raw_mem))

    def save_throttled(
        self,
        sessions: Dict[str, List[ChatMessage]],
        last_structured: Dict[str, Any],
        memory_all: Dict[str, Any],
        force: bool = False,
    ) -> None:
        if not self.enabled:
            return

        now = time.time()
        if not force and (now - self._last_save_ts) < self.save_min_interval_sec:
            return
        self._last_save_ts = now

        # sessions 轉成 dict/list
        ser_sessions: Dict[str, Any] = {}
        for sk, msgs in sessions.items():
            if not isinstance(sk, str) or not isinstance(msgs, list):
                continue
            tail = msgs[-self.max_messages_per_session :]
            ser_sessions[sk] = [{"role": m.role, "content": m.content} for m in tail if getattr(m, "role", None)]

        payload = {
            "version": 1,
            "saved_at": _now_iso(),
            "sessions": ser_sessions,
            "last_structured": last_structured,
            "memory": memory_all,
        }
        _atomic_write_json(self.path, payload)
