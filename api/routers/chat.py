# api/routers/chat.py
import json
import time
from typing import List, Tuple
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import traceback

from agent.agent import answer_with_routing
from agent.direct_llm_json import task_tags, task_title, task_followups
from api.core.settings import json_llm
from api.core.url_utils import abs_url
from api.services.markdown_renderer import render_markdown
from api.services.sessions import (
    ChatMessage,
    pack_chat_history,
    infer_session_key_from_payload,
    choose_assistant_save,
    get_sessions,
    get_last_structured,
    MAX_SESSIONS,
)
from api.services.memory import render_memory_text, update_memory, get_memory
from telemetry import log_event, new_request_id, new_trace, save_trace
import time

router = APIRouter()

class ChatPayload(BaseModel):
    model: str = "SRA-Structured Retrieval Agent"
    messages: list[ChatMessage]
    stream: bool | None = None
    format: str | None = "markdown"   # ← 新增
    
def _detect_meta_kind(text: str) -> str | None:
    t = (text or "").lower()
    if "generate 1-3 broad tags" in t or "### task" in t and "tags" in t:
        return "tags"
    if "generate a concise, 3-5 word title" in t or ("title" in t and "emoji" in t and "json" in t):
        return "title"
    if "suggest 3-5 relevant follow-up" in t or ("follow-up" in t and "json" in t):
        return "followups"
    return None

def _collect_reuse_from(out: dict) -> list[str]:
    """
    從一個 structured out 裡撿出可 reuse 的 uuids：
    - 先看 used_uuids
    - 再從 citations 裡補 uuid/source_id/doc_id
    - 去重、過濾空字串
    """
    if not isinstance(out, dict):
        return []

    candidates: list[str] = []

    # 1) used_uuids
    uids = out.get("used_uuids") or []
    if isinstance(uids, list):
        candidates.extend([u for u in uids if isinstance(u, str)])

    # 2) citations 裡補 uuid/source_id/doc_id
    for c in out.get("citations") or []:
        if not isinstance(c, dict):
            continue
        u = (
            c.get("uuid")
            or c.get("source_id")
            or c.get("doc_id")
            or c.get("id")
        )
        if isinstance(u, str):
            candidates.append(u)

    # 3) 去重
    seen: set[str] = set()
    reuse: list[str] = []
    for u in candidates:
        if u and u not in seen:
            seen.add(u)
            reuse.append(u)

    return reuse

def _resolve_session_key(payload: ChatPayload, request: Request, sessions) -> str:
    raw_header_session = (
        request.headers.get("x-openwebui-chat-id")
        or request.headers.get("x-conversation-id")
        or request.headers.get("x-session-id")
        or ""
    )
    raw_header_session = (raw_header_session or "").strip()

    if raw_header_session:
        session_key = raw_header_session
    else:
        session_key = infer_session_key_from_payload(payload.messages or [])

    print("[chat_completions] chosen session_key =", repr(session_key))
    return session_key


def _extract_user_and_history(
    payload: ChatPayload,
    sessions,
    session_key: str,
) -> Tuple[str, str, List[ChatMessage], List[str]]:
    """
    回傳：
    - user_msg: 本輪 user 問題
    - query: system + user 組合後的 query
    - history_msgs: 真正當作歷史的訊息（給 pack_chat_history 用）
    - recent_user_msgs: 給任務分流器用的「最近幾輪 user 問題」
    """
    # system + 最後一則 user
    sys_prefix = ""
    for m in payload.messages:
        if m.role == "system" and m.content:
            sys_prefix += m.content.strip() + "\n\n"

    user_msg = ""
    for m in reversed(payload.messages):
        if m.role == "user":
            user_msg = m.content or ""
            break

    query = (sys_prefix + user_msg).strip() if sys_prefix else user_msg.strip()

    # 歷史訊息：優先用我們儲存的 sessions
    if session_key in sessions and len(sessions[session_key]) > 0:
        history_msgs = list(sessions[session_key])
    else:
        history_msgs = list(payload.messages[:-1])

    recent_user_msgs: List[str] = []
    for m in history_msgs:
        role = (m.role or "").lower()
        if role == "user" and (m.content or "").strip():
            recent_user_msgs.append(m.content.strip())

    return user_msg, query, history_msgs, recent_user_msgs


def _build_query_for_agent(
    session_key: str,
    history_msgs: List[ChatMessage],
    user_msg: str,
) -> str:
    history_text = pack_chat_history(history_msgs)
    mem_all = get_memory()
    mem_txt = render_memory_text(mem_all.get(session_key))

    query_for_agent = (
        (f"【對話記憶】\n{mem_txt}\n\n" if mem_txt else "") +
        f"【對話歷史】\n{history_text}\n\n"
        f"【目前問題】\n{user_msg}\n\n"
        "【要求】如果是有對話歷史的多輪對話，那麼延續上文已確立的主題/時間範圍/定義；避免過度衍伸。"
    )
    return query_for_agent


def _prepare_reuse_info(
    session_key: str,
    last_structured: dict,
) -> Tuple[List[str], dict | None]:
    reuse_uuids: List[str] = []
    refno_uuid_map: dict[int, str] | None = None

    if session_key in last_structured:
        prev_out = last_structured.get(session_key) or {}

        reuse_uuids = _collect_reuse_from(prev_out)

        raw_map = prev_out.get("refno_uuid_map") or {}
        if isinstance(raw_map, dict):
            tmp: dict[int, str] = {}
            for k, v in raw_map.items():
                try:
                    kk = int(k)
                except Exception:
                    continue
                if isinstance(v, str):
                    tmp[kk] = v
            if tmp:
                refno_uuid_map = tmp
    else:
        reuse_uuids = []

    print("[chat_completions] reuse_uuids =", reuse_uuids)
    print("[chat_completions] refno_uuid_map =", refno_uuid_map)

    return reuse_uuids, refno_uuid_map


def _build_citations(out: dict, request: Request) -> list:
    citations = []
    if not isinstance(out, dict):
        return citations

    for c in (out.get("citations") or []):
        uuid_ = c.get("uuid")
        source_id = c.get("source_id")
        doc_id = uuid_ or source_id or c.get("doc_id") or c.get("id")
        href = abs_url(request, f"/v1/docs/{doc_id}") if doc_id else None

        citations.append({
            "text": c.get("text"),
            "uuid": uuid_,
            "source_id": source_id,
            "paragraph_id": c.get("paragraph_id"),
            "href": href,
            "title": (
                c.get("subject")
                or c.get("article_title")
                or c.get("title")
                or (source_id or uuid_ or str(doc_id))
            ),
        })
    return citations


def _save_session_and_memory(
    sessions,
    last_structured,
    session_key: str,
    user_msg: str,
    out,
    request: Request,
):
    try:
        sessions[session_key].append(ChatMessage(role="user", content=user_msg))
        #rendered_full = render_markdown(out, request) if isinstance(out, dict) else str(out)
        rendered_full = render_markdown(out, request, session_key) if isinstance(out, dict) else str(out)
        assistant_save = choose_assistant_save(out, rendered_full)
        sessions[session_key].append(ChatMessage(role="assistant", content=assistant_save))

        if isinstance(out, dict):
            mode = out.get("mode")
            if mode in ("SRA_REPORT", "SRA_STYLE", "DOC_FOLLOWUP", "PURE_LLM"):
                last_structured[session_key] = out
            else:
                last_structured.pop(session_key, None)

            print(
                "[chat_completions] saved last_structured for",
                repr(session_key),
                "used_uuids =", out.get("used_uuids"),
            )

        tail_msgs = list(sessions[session_key])[-6:]
        tail_text = pack_chat_history(tail_msgs, max_chars=4000)
        update_memory(session_key, tail_text, out if isinstance(out, dict) else None)

        if len(sessions) > MAX_SESSIONS:
            victim_key = next(iter(sessions))
            print("[chat_completions] evict session:", repr(victim_key))

            sessions.pop(victim_key, None)
            mem_all = get_memory()
            mem_all.pop(victim_key, None)
            last_structured.pop(victim_key, None)
    except Exception:
        pass
    
def _handle_meta_task(
    kind: str,
    session_key: str,
    payload: ChatPayload,
    sessions,
    request: Request,
    trace: dict,
) -> dict:
    if session_key in sessions and len(sessions[session_key]) > 0:
        base_history_msgs = list(sessions[session_key])
    else:
        base_history_msgs = list(payload.messages)

    history_text = pack_chat_history(base_history_msgs)
    mem_all = get_memory()
    mem_txt = render_memory_text(mem_all.get(session_key))

    if mem_txt:
        history_text += f"\nMEMORY:\n{mem_txt}\n"

    if kind == "tags":
        result = task_tags(json_llm, history_text)
    elif kind == "title":
        result = task_title(json_llm, history_text)
    else:
        result = task_followups(json_llm, history_text)

    text = json.dumps(result, ensure_ascii=False)

    # trace output
    trace["routing"] = {"mode": "META_TASK", "meta_kind": kind}
    trace["output"] = {
        "answer_preview": text[:200],
        "answer_length": len(text),
    }

    resp = {
        "id": f"chatcmpl-{int(time.time()*1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": text,
                "context": {"mode": "META_TASK", "kind": kind},
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    return resp

@router.get("/healthz")
def healthz():
    return {"ok": True}

# --- OpenAI Chat Completions 相容端點（非串流版） ---
@router.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "SRA-Structured Retrieval Agent",
                "object": "model",
                "owned_by": "owner"
            }
        ]
    }

@router.post("/v1/chat/completions")
def chat_completions(payload: ChatPayload, request: Request):
    sessions = get_sessions()
    last_structured = get_last_structured()

    request_id = new_request_id()
    t_start = time.time()

    try:
        # 0) 決定 session_key
        session_key = _resolve_session_key(payload, request, sessions)

        # 建立 trace 雛形
        trace = new_trace(session_id=session_key, request_id=request_id)

        # 1) 抽出本輪 user 提問 + 歷史
        user_msg, query, history_msgs, recent_user_msgs = _extract_user_and_history(
            payload, sessions, session_key
        )
        if not recent_user_msgs:
            recent_user_msgs = None

        trace["user"] = {
            "latest_question": user_msg,
            "recent_history": [m.content for m in history_msgs if m.role == "user"][-5:],
        }

        # 簡單記一下 request 資訊
        try:
            client_ip = request.client.host if request.client else None
        except Exception:
            client_ip = None

        log_event(
            "chat_request",
            session_id=session_key,
            request_id=request_id,
            data={
                "client_ip": client_ip,
                "num_messages": len(payload.messages or []),
            },
        )

        # 2) 先檢查是不是 WebUI 的 META 任務
        kind = _detect_meta_kind(query)
        if kind:
            resp = _handle_meta_task(
                kind=kind,
                session_key=session_key,
                payload=payload,
                sessions=sessions,
                request=request,
                trace=trace,
            )
            trace["timing"]["total_sec"] = time.time() - t_start
            save_trace(trace)
            return resp

        # 3) 一般任務 → 準備 query_for_agent
        query_for_agent = _build_query_for_agent(
            session_key=session_key,
            history_msgs=history_msgs,
            user_msg=user_msg,
        )

        # 4) 準備 reuse_uuids / refno_uuid_map
        reuse_uuids, refno_uuid_map = _prepare_reuse_info(session_key, last_structured)

        # 5) 呼叫總路由（answer_with_routing）
        try:
            t_route_start = time.time()
            out = answer_with_routing(
                user_msg=user_msg,
                query_for_agent=query_for_agent,
                recent_user_msgs=recent_user_msgs,
                reuse_uuids=reuse_uuids,
                refno_uuid_map=refno_uuid_map,
                session_id=session_key,
                request_id=request_id,
                trace=trace,  # 給報告代理 / ES 工具填 core_terms, ES 狀況
            )
            t_route_end = time.time()
            trace.setdefault("timing", {})["routing_sec"] = t_route_end - t_route_start

        except Exception as e:
            print("answer_with_routing 發生錯誤：", e)
            raise HTTPException(status_code=500, detail="後端分析發生錯誤，請稍後再試")

        # 6) 產主文
        fmt = (payload.format or "markdown").lower()
        if fmt == "json":
            text = json.dumps(out, ensure_ascii=False)
        else:
            text = render_markdown(out, request, session_key)

        trace["output"] = {
            "answer_preview": text[:200],
            "answer_length": len(text),
        }

        # 7) citations
        citations = _build_citations(out, request)

        # 8) OpenAI 兼容格式
        resp = {
            "id": f"chatcmpl-{int(time.time()*1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                    "context": {
                        "citations": citations,
                        "mode": out.get("mode") if isinstance(out, dict) else None,
                        "route": out.get("route") if isinstance(out, dict) else None,
                    },
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

        # 9) 儲存 session / memory
        _save_session_and_memory(
            sessions=sessions,
            last_structured=last_structured,
            session_key=session_key,
            user_msg=user_msg,
            out=out,
            request=request,
        )

        # 10) 總耗時 + 寫 trace
        trace.setdefault("timing", {})["total_sec"] = time.time() - t_start
        save_trace(trace)

        return resp

    except Exception as e:
        print("=== /v1/chat/completions 發生例外 ===")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
