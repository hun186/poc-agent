"""Shared execution boundary for one non-meta Agent turn."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from fastapi import Request

from agent.agent import answer_with_routing
from api.services.memory import get_memory, render_memory_text
from api.services.sessions import (
    get_last_structured,
    get_sessions,
    infer_session_key_from_payload,
    save_structured_snapshot,
)
from telemetry import new_request_id, new_trace


@dataclass(frozen=True)
class AgentTurnResult:
    session_id: str
    turn_id: str
    request_id: str
    user_message: str
    output: dict
    trace: dict


def _resolve_session_id(payload: Any, request: Request | None, session_id: str | None) -> str:
    if session_id and session_id.strip():
        return session_id.strip()
    if request is None:
        return infer_session_key_from_payload(payload.messages or [])
    session_id = (
        request.headers.get("x-openwebui-chat-id")
        or request.headers.get("x-conversation-id")
        or request.headers.get("x-session-id")
        or ""
    ).strip()
    return session_id or infer_session_key_from_payload(payload.messages or [])


def _extract_turn_inputs(payload: Any, sessions: dict, session_id: str):
    user_msg = next(
        (message.content or "" for message in reversed(payload.messages) if message.role == "user"),
        "",
    )
    history = (
        list(sessions[session_id])
        if session_id in sessions and sessions[session_id]
        else list(payload.messages[:-1])
    )
    recent = [
        message.content.strip()
        for message in history
        if (message.role or "").lower() == "user" and (message.content or "").strip()
    ]
    return user_msg, history, recent


def _prepare_reuse(previous: dict) -> tuple[list[str], dict[int, str] | None]:
    candidates = list(previous.get("used_uuids") or [])
    for citation in previous.get("citations") or []:
        if isinstance(citation, dict):
            candidates.append(
                citation.get("uuid")
                or citation.get("source_id")
                or citation.get("doc_id")
                or citation.get("id")
            )
    reuse = list(dict.fromkeys(item for item in candidates if isinstance(item, str) and item))
    ref_map = {}
    for key, value in (previous.get("refno_uuid_map") or {}).items():
        try:
            ref_map[int(key)] = value
        except (TypeError, ValueError):
            continue
    return reuse, ref_map or None


def execute_agent_turn(
    *,
    payload: Any,
    request: Request | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    trace: dict | None = None,
) -> AgentTurnResult:
    """Execute an Agent turn and return its in-memory structured result.

    Persistence remains a compatibility side effect for the existing download
    endpoint, but callers can render ``output`` directly without reading it back.
    """
    sessions = get_sessions()
    last_structured = get_last_structured()
    request_id = str(request_id or new_request_id())
    session_id = _resolve_session_id(payload, request, session_id)
    trace = trace if trace is not None else new_trace(
        session_id=session_id,
        request_id=request_id,
    )

    user_msg, history_msgs, recent_user_msgs = _extract_turn_inputs(payload, sessions, session_id)
    history_items = [
        {"role": (message.role or ""), "content": (message.content or "")}
        for message in (history_msgs or [])
    ]
    memory_text = render_memory_text(get_memory().get(session_id))
    previous_output = last_structured.get(session_id) or {}
    reuse_uuids, refno_uuid_map = _prepare_reuse(previous_output)

    started = time.time()
    output = answer_with_routing(
        user_msg=user_msg,
        history_msgs=history_items,
        memory_text=memory_text,
        last_structured=previous_output,
        recent_user_msgs=recent_user_msgs or None,
        reuse_uuids=reuse_uuids,
        refno_uuid_map=refno_uuid_map,
        session_id=session_id,
        request_id=request_id,
        trace=trace,
    )
    trace.setdefault("timing", {})["routing_sec"] = time.time() - started
    if not isinstance(output, dict):
        raise TypeError("Agent turn must return a structured dictionary")

    output.setdefault("session_id", session_id)
    output.setdefault("turn_id", request_id)
    output.setdefault("request_id", request_id)
    if output.get("mode") in ("SRA_REPORT", "SRA_STYLE", "DOC_FOLLOWUP", "PURE_LLM"):
        save_structured_snapshot(session_id, request_id, output)

    return AgentTurnResult(
        session_id=session_id,
        turn_id=str(output["turn_id"]),
        request_id=request_id,
        user_message=user_msg,
        output=output,
        trace=trace,
    )
