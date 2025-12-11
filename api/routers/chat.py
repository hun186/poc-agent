# api/routers/chat.py
import json
import time
from typing import Any, List
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
    try:
        # 0) 決定 session_key：優先用 header，否則用「第一個 user 訊息 hash」
        raw_header_session = (
            request.headers.get("x-openwebui-chat-id")
            or request.headers.get("x-conversation-id")  # 舊相容
            or request.headers.get("x-session-id")
            or ""
        )
        #print("request.headers",request.headers)
        #print("Conversation-ID",request.headers.get("x-openwebui-chat-id"))
        raw_header_session = (raw_header_session or "").strip()
        
        if raw_header_session:
            session_key = raw_header_session
        else:
            session_key = infer_session_key_from_payload(payload.messages or [])
        
        print("[chat_completions] chosen session_key =", repr(session_key))
        # 1) 前置 system + 取最後一則 user（保持原本邏輯）
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

        # 2) 呼叫代理
        #agent = get_agent()          # ← 每請求新建乾淨 Agent
        #out = agent.run(query)
        
        # 2-1) ★路由：若偵測到 WebUI 的分析任務 → 直接用 LLM 回 JSON；否則才走 CodeAgent
        # >>> 新增：若是 WebUI 的 JSON 分析任務，直接用 json_llm 產生，繞開 CodeAgent <<<
        kind = _detect_meta_kind(query)
        if kind:
            if session_key in sessions and len(sessions[session_key]) > 0:
                base_history_msgs = list(sessions[session_key])
            else:
                base_history_msgs = list(payload.messages)
            
            history_text = pack_chat_history(base_history_msgs)
            #mem_txt = _render_memory_text(_memory.get(session_key))
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

            # 直接把「raw JSON」塞進 content（你的 WebUI 期望如此）
            text = json.dumps(result, ensure_ascii=False)

            return {
                "id": f"chatcmpl-{int(time.time()*1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": payload.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text,
                        "context": {"mode": "META_TASK", "kind": kind}
                    },
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }
        # 2-2) 否則 → 多輪：把歷史一併送進 Agent
        # 構造可讀歷史：優先使用我們保存於 session 的乾淨主文
        if session_key in sessions and len(sessions[session_key]) > 0:
            history_msgs = list(sessions[session_key])
        else:
            history_msgs = list(payload.messages[:-1])

        
        # ★ 給任務分流器用的「最近幾個 user 問題」（不含本輪）
        recent_user_msgs: list[str] = []
        for m in history_msgs:
            role = (m.role or "").lower()
            if role == "user" and (m.content or "").strip():
                recent_user_msgs.append(m.content.strip())
                
        #print("history_msgs (effective)", history_msgs)
        history_text = pack_chat_history(history_msgs)
        #print("history_text from pack_chat_history",history_text)
        # 附上上一輪摘要（自動）：主要機構清單（就算正文被截也有這份保底）
        #if session_id and session_id in _last_orgs and _last_orgs[session_id]:
        #    summary_tail = "【上一輪摘要（自動）】\n- 主要機構：" + "、".join(_last_orgs[session_id][:15]) + "\n"
        #    history_text = (history_text + "\n" + summary_tail).strip()

        #mem_txt = render_memory_text(memory.get(session_key))
        mem_all = get_memory()
        mem_txt = render_memory_text(mem_all.get(session_key))
        query_for_agent = (
            (f"【對話記憶】\n{mem_txt}\n\n" if mem_txt else "") +
            f"【對話歷史】\n{history_text}\n\n"
            f"【目前問題】\n{user_msg}\n\n"
            "【要求】如果是有對話歷史的多輪對話，那麼延續上文已確立的主題/時間範圍/定義；避免過度衍伸。"
        )

        # 2) 準備 reuse_uuids + refno_uuid_map
        reuse_uuids: list[str] = []
        refno_uuid_map: dict[int, str] | None = None

        # 2-1) 第一優先：這個 session 自己上一輪的 structured out
        if session_key in last_structured:
            prev_out = last_structured.get(session_key) or {}

            # a) 撿可重用的 uuid（給 DOC_FOLLOWUP / ESFetchDocById）
            reuse_uuids = _collect_reuse_from(prev_out)

            # b) 撿上一輪報告產生的 refno_uuid_map（來源編號 → uuid）
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

        # 2) 呼叫總路由（answer_with_routing：內部自己決定是 SRA_REPORT / SRA_STYLE / DOC_FOLLOWUP / PURE_LLM）
        try:
            out = answer_with_routing(
                user_msg=user_msg,
                query_for_agent=query_for_agent,
                recent_user_msgs=recent_user_msgs,
                reuse_uuids=reuse_uuids,
                refno_uuid_map=refno_uuid_map,  # ★ 新增這一行
            )

        except Exception as e:
            print("answer_with_routing 發生錯誤：", e)
            raise HTTPException(status_code=500, detail="後端分析發生錯誤，請稍後再試")
       
        # 3) 產主文：保留你的 format / render_markdown 行為
        fmt = (payload.format or "markdown").lower()
        if fmt == "json":
            text = json.dumps(out, ensure_ascii=False)
        else:
            #print("in render_markdown, out",out)
            text = render_markdown(out, request)

        # 4) 產 citations（加上「可點的」絕對連結）
        citations = []
        if isinstance(out, dict):
            for c in (out.get("citations") or []):
                uuid_ = c.get("uuid")
                source_id = c.get("source_id")
                # ★ 連結優先用 uuid，fallback 才用 source_id
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

        # 5) 回 OpenAI 兼容格式（多帶一個非標準的 context，客戶端不需要也會略過）
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
                        "mode": out.get("mode"),
                        "route": out.get("route"),
                    }
                },
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }

        
        # 6) 保存本輪到會話歷史 & 更新通用記憶
        try:
            sessions[session_key].append(ChatMessage(role="user", content=user_msg))
            rendered_full = render_markdown(out, request) if isinstance(out, dict) else str(out)
            assistant_save = choose_assistant_save(out, rendered_full)
            sessions[session_key].append(ChatMessage(role="assistant", content=assistant_save))

            if isinstance(out, dict):
                mode = out.get("mode")
                if mode in ("SRA_REPORT", "SRA_STYLE", "DOC_FOLLOWUP"):
                   last_structured[session_key] = out
                else:
                   # PURE_LLM 或其他模式就不要沿用 used_uuids，避免污染
                   last_structured.pop(session_key, None)

                print(
                    "[chat_completions] saved last_structured for",
                   repr(session_key),
                    "used_uuids =", out.get("used_uuids")
                )

            tail_msgs = list(sessions[session_key])[-6:]
            tail_text = pack_chat_history(tail_msgs, max_chars=4000)
            update_memory(session_key, tail_text, out if isinstance(out, dict) else None)
   



            # ★★★ 新增：若 session 數量超過上限，就淘汰最舊的一個，避免一直堆記憶體
            if len(sessions) > MAX_SESSIONS:
                victim_key = next(iter(sessions))  # dict 有插入順序，抓第一個當最舊
                print("[chat_completions] evict session:", repr(victim_key))

                sessions.pop(victim_key, None)
                #memory.pop(victim_key, None)
                mem_all = get_memory()
                mem_all.pop(victim_key, None)
                last_structured.pop(victim_key, None)

        except Exception:
            pass
        
        return resp
    except Exception as e:
        # ★ 把真正錯誤印到 console，uvicorn 才看得到堆疊
        print("=== /v1/chat/completions 發生例外 ===")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))