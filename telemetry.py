# telemetry.py
import os
import json
import time
import uuid
import threading
from typing import Any, Dict, Optional

ENABLE_TELEMETRY = os.getenv("SRA_ENABLE_TELEMETRY", "1") == "1"

LOG_PATH = os.getenv("SRA_TELEMETRY_PATH", "logs/telemetry.jsonl")
TRACE_DIR = os.getenv("SRA_TRACE_DIR", "logs/traces")

_log_lock = threading.Lock()
_trace_lock = threading.Lock()
_log_dir_inited = False
_trace_dir_inited = False


def _ensure_log_dir():
    global _log_dir_inited
    if _log_dir_inited:
        return
    d = os.path.dirname(LOG_PATH)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    _log_dir_inited = True


def _ensure_trace_dir():
    global _trace_dir_inited
    if _trace_dir_inited:
        return
    if TRACE_DIR and not os.path.exists(TRACE_DIR):
        os.makedirs(TRACE_DIR, exist_ok=True)
    _trace_dir_inited = True


def new_request_id() -> str:
    return uuid.uuid4().hex


def log_event(
    event_type: str,
    *,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
):
    if not ENABLE_TELEMETRY:
        return

    _ensure_log_dir()
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "event_type": event_type,
        "session_id": session_id,
        "request_id": request_id,
        "data": data or {},
    }
    line = json.dumps(record, ensure_ascii=False)

    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def new_trace(session_id: str, request_id: str) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "request_id": request_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "user": {},
        "routing": {},
        "keywords": {},
        "es": {},
        "timing": {},
        "llm": {},
        "output": {},
    }


def save_trace(trace: Dict[str, Any]):
    if not ENABLE_TELEMETRY:
        return

    _ensure_trace_dir()
    req_id = trace.get("request_id") or new_request_id()
    path = os.path.join(TRACE_DIR, f"{req_id}.json")

    with _trace_lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)

    # 同步寫一筆 JSONL 方便後續批次分析
    log_event(
        "chat_trace",
        session_id=trace.get("session_id"),
        request_id=req_id,
        data=trace,
    )
