# api/routers/chat.py
#import os
import json
import time
from fastapi import APIRouter, Request, HTTPException
import traceback

from agent.agent import answer_with_routing
from api.services.markdown_renderer import render_markdown
from api.services.sessions import (
    ChatMessage,
    get_sessions,
    get_last_structured,
)
from api.services.memory import render_memory_text, get_memory
from telemetry import log_event, new_request_id, new_trace, save_trace
#from api.services.api_state_store import APIStateStore
from api.services.sessions import save_structured_snapshot

from api.services.api_state_store import API_STORE
from api.services.sessions import get_structured_history


router = APIRouter()

'''
API_STORE_ENABLED = os.getenv("API_STORE_ENABLED", "1") == "1"
API_STORE_DIR = os.getenv("API_STORE_DIR", ".api_state")
API_STORE_FILE = os.getenv("API_STORE_FILE", "state.json")
API_STORE_MIN_INTERVAL = float(os.getenv("API_STORE_MIN_INTERVAL", "1.0"))
API_STORE_MAX_MSGS = int(os.getenv("API_STORE_MAX_MSGS", "200"))

API_STORE = APIStateStore(
    base_dir=API_STORE_DIR,
    enabled=API_STORE_ENABLED,
    filename=API_STORE_FILE,
    save_min_interval_sec=API_STORE_MIN_INTERVAL,
    max_messages_per_session=API_STORE_MAX_MSGS,
)
'''
from sra_api.routers.chat_support import (
    ChatPayload,
    build_citations,
    detect_meta_kind,
    extract_user_and_history,
    handle_meta_task,
    prepare_reuse_info,
    resolve_session_key,
    save_session_and_memory,
)

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
    
    #mem_all = get_memory()
    #API_STORE.load_once(sessions=sessions, last_structured=last_structured, memory_all=mem_all)
    
    request_id = new_request_id()
    t_start = time.time()

    try:
        # 0) 決定 session_key
        session_key = resolve_session_key(payload, request)

        # 建立 trace 雛形
        trace = new_trace(session_id=session_key, request_id=request_id)

        # 1) 抽出本輪 user 提問 + 歷史
        user_msg, query, history_msgs, recent_user_msgs = extract_user_and_history(
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
        kind = detect_meta_kind(query)
        if kind:
            resp = handle_meta_task(
                kind=kind,
                session_key=session_key,
                payload=payload,
                sessions=sessions,
                trace=trace,
            )
            trace["timing"]["total_sec"] = time.time() - t_start
            save_trace(trace)
            return resp

        # 3) 一般任務 → 準備 query_for_agent
        #query_for_agent = _build_query_for_agent(
        #    session_key=session_key,
        #    history_msgs=history_msgs,
        #    user_msg=user_msg,
        #)
        # 3) 不再拼裝，改傳原料
        mem_all = get_memory()
        mem_txt = render_memory_text(mem_all.get(session_key))
        
        history_items = [
            {"role": (m.role or ""), "content": (m.content or "")}
            for m in (history_msgs or [])
        ]
        
        prev_out = (last_structured.get(session_key) or {}) if session_key in last_structured else {}

        # 4) 準備 reuse_uuids / refno_uuid_map
        reuse_uuids, refno_uuid_map = prepare_reuse_info(session_key, last_structured)

        # 5) 呼叫總路由（answer_with_routing）
        try:
            t_route_start = time.time()
            '''
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
            '''
            out = answer_with_routing(
                user_msg=user_msg,
                history_msgs=history_items,
                memory_text=mem_txt,
                last_structured=prev_out,
                recent_user_msgs=recent_user_msgs,
                reuse_uuids=reuse_uuids,
                refno_uuid_map=refno_uuid_map,
                session_id=session_key,
                request_id=request_id,
                trace=trace,
            )
            t_route_end = time.time()
            trace.setdefault("timing", {})["routing_sec"] = t_route_end - t_route_start

        except Exception as e:
            print("answer_with_routing 發生錯誤：", e)
            raise HTTPException(status_code=500, detail="後端分析發生錯誤，請稍後再試")
        # ✅ 5.3) 本輪 out 存快照（turn_id=request_id）
        if isinstance(out, dict):
            try:
                # 讓後面 Markdown 下載連結用得到
                out.setdefault("session_id", session_key)
                out.setdefault("turn_id", str(request_id))
                out.setdefault("request_id", str(request_id))
        
                mode = out.get("mode")
                if mode in ("SRA_REPORT", "SRA_STYLE", "DOC_FOLLOWUP", "PURE_LLM"):
                    save_structured_snapshot(session_key, request_id, out)
            except Exception:
                pass
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
        citations = build_citations(out, request)

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
        #save_structured_snapshot(session_key, request_id, out)
        save_session_and_memory(
            sessions=sessions,
            last_structured=last_structured,
            session_key=session_key,
            user_msg=user_msg,
            out=out,
            request=request,
        )
        #'''
        # 9.5) API 狀態落地（節流寫入）
        # 序列化 sessions（deque[ChatMessage] -> list[dict]）
        sessions_ser: dict[str, list[dict]] = {}
        for sk, dq in sessions.items():
            items: list[dict] = []
            for m in list(dq):
                items.append({
                    "role": m.role,
                    "content": m.content,
                    "format": getattr(m, "format", None) or "markdown",
                })
            sessions_ser[sk] = items
        
        API_STORE.save_all_throttled(
            sessions_ser=sessions_ser,
            last_structured=last_structured,
            memory_all=get_memory(),
            structured_history=get_structured_history(),  # ✅ 關鍵：把快照存進去
        )
        #'''
        # 10) 總耗時 + 寫 trace
        trace.setdefault("timing", {})["total_sec"] = time.time() - t_start
        save_trace(trace)

        return resp

    except Exception as e:
        print("=== /v1/chat/completions 發生例外 ===")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
