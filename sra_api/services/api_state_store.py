# api/services/api_state_store.py
from __future__ import annotations

import json
import os
import time
import tempfile
from typing import Any, Dict, Optional


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
    單一檔案保存：
      - sessions
      - last_structured
      - memory
    只負責讀寫 dict，不依賴 ChatMessage，避免循環 import。
    """

    def __init__(
        self,
        base_dir: str,
        filename: str,
        enabled: bool = True,
        save_min_interval_sec: float = 1.0,
        max_messages_per_session: int = 200,
        max_structured_turns_per_session: int = 50,  # ✅ 新增
    ) -> None:
        self.base_dir = base_dir
        self.filename = filename
        self.enabled = enabled
        self.save_min_interval_sec = save_min_interval_sec
        self.max_messages_per_session = max_messages_per_session
        self.max_structured_turns_per_session = max_structured_turns_per_session  # ✅ 新增

        self._loaded_once = False
        self._last_save_ts = 0.0
        self._cache: Dict[str, Any] = {}

    @property
    def path(self) -> str:
        return os.path.join(self.base_dir, self.filename)

    def load_raw_once(self) -> Dict[str, Any]:
        """
        只讀一次，結果快取在 self._cache。
        讓 sessions.py / memory.py 各自取需要的部分回填。
        """
        if not self.enabled:
            self._loaded_once = True
            self._cache = {}
            return self._cache

        if self._loaded_once:
            return self._cache

        self._loaded_once = True
        d = _read_json(self.path) or {}
        self._cache = d if isinstance(d, dict) else {}
        return self._cache
    '''
    def load_raw(self, force: bool = False) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        if force:
            return _read_json(self.path) or {}
        return self.load_raw_once()
    '''
    def read_raw(self) -> Dict[str, Any]:
        """
        每次都從磁碟讀最新 state.json（不走 _loaded_once 快取）。
        export 下載用這個最穩，避免多 worker 讀不到最新狀態。
        """
        if not self.enabled:
            return {}
        d = _read_json(self.path) or {}
        return d if isinstance(d, dict) else {}
    
    def save_all_throttled(
        self,
        *,
        sessions_ser: Dict[str, Any],
        last_structured: Dict[str, Any],
        memory_all: Dict[str, Any],
        structured_history: Dict[str, Any] | None = None,  # ★ 新增
        force: bool = False,
    ) -> None:
        if not self.enabled:
            return
    
        now = time.time()
        if not force and (now - self._last_save_ts) < self.save_min_interval_sec:
            return
        self._last_save_ts = now
    
        # 每個 session 最多保留 N 筆，避免檔案爆大
        trimmed_sessions: Dict[str, Any] = {}
        for sk, items in (sessions_ser or {}).items():
            if not isinstance(items, list):
                continue
            trimmed_sessions[sk] = items[-self.max_messages_per_session :]
    
        # ★ structured_history 也做「每個 session 最多保留 N 輪」裁切
        trimmed_hist: Dict[str, Any] = {}
        if isinstance(structured_history, dict):
            for sk, turns in structured_history.items():
                if not isinstance(turns, dict):
                    continue
                # turns: turn_id -> out
                keys = list(turns.keys())
                #keep_keys = keys[-self.max_messages_per_session :]
                keep_keys = keys[-self.max_structured_turns_per_session:]
                trimmed_hist[sk] = {k: turns[k] for k in keep_keys if k in turns}
    
        payload = {
            "version": 2,  # ★ 版本 +1
            "saved_at": _now_iso(),
            "sessions": trimmed_sessions,
            "last_structured": last_structured or {},
            "structured_history": trimmed_hist,  # ★ 新增
            "memory": memory_all or {},
        }
        _atomic_write_json(self.path, payload)
        
    def save_all_throttled_1224(
        self,
        *,
        sessions_ser: Dict[str, Any],
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

        # 每個 session 最多保留 N 筆，避免檔案爆大
        trimmed_sessions: Dict[str, Any] = {}
        for sk, items in (sessions_ser or {}).items():
            if not isinstance(items, list):
                continue
            trimmed_sessions[sk] = items[-self.max_messages_per_session :]

        payload = {
            "version": 1,
            "saved_at": _now_iso(),
            "sessions": trimmed_sessions,
            "last_structured": last_structured or {},
            "memory": memory_all or {},
        }
        _atomic_write_json(self.path, payload)


# ===== 全域單例（環境變數可控）=====
_API_STORE_ENABLED = os.getenv("API_STORE_ENABLED", "1") == "1"
_API_STORE_DIR = os.getenv("API_STORE_DIR", ".api_state")
_API_STORE_FILE = os.getenv("API_STORE_FILE", "state.json")
_API_STORE_MIN_INTERVAL = float(os.getenv("API_STORE_MIN_INTERVAL", "1.0"))
_API_STORE_MAX_MSGS = int(os.getenv("API_STORE_MAX_MSGS", "200"))
_API_STORE_MAX_STRUCTURED_TURNS = int(os.getenv("API_STORE_MAX_STRUCTURED_TURNS", "50"))  # ✅ 新增


API_STORE = APIStateStore(
    base_dir=_API_STORE_DIR,
    filename=_API_STORE_FILE,
    enabled=_API_STORE_ENABLED,
    save_min_interval_sec=_API_STORE_MIN_INTERVAL,
    max_messages_per_session=_API_STORE_MAX_MSGS,
    max_structured_turns_per_session=_API_STORE_MAX_STRUCTURED_TURNS,  # ✅ 新增
)
