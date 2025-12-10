#api/main.py
#cd D:\shared\TopicClassification\poc-agent&& uvicorn api.main:app --host 0.0.0.0 --port 9002
#cd /mntCZJ/TopicClassification/poc-agent&& uvicorn api.main:app --host 0.0.0.0 --port 9002
#http://192.168.0.228:9002/v1
#http://192.168.0.133:9002/v1
import os, json, time
import re
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException
from fastapi import Query
from fastapi.responses import PlainTextResponse, JSONResponse
from collections import defaultdict, deque
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from pydantic import BaseModel
from elasticsearch import Elasticsearch
from elasticsearch import NotFoundError
import traceback
import hashlib

# 你的代理人單例；內部已走 Ollama（LiteLLMModel -> MODEL_BASE_URL）
#from agent.agent import get_agent, SYSTEM
#from agent.agent import build_model  # 直接重用你已經有的 LiteLLMModel 建構器

#from agent.agent import ask_with_report
from agent.agent import answer_with_routing

from agent.direct_llm_json import OpenAIStyleOllama, task_tags, task_title, task_followups
from api.services.markdown_renderer import render_markdown
from api.core.url_utils import abs_url
from api.core.settings import json_llm,ES_INDEXES,ES
from api.services.sessions import ChatMessage
from api.services.sessions import pack_chat_history
from api.services.sessions import infer_session_key_from_payload
from api.services.sessions import choose_assistant_save
from api.services.sessions import get_sessions,get_last_structured,MAX_SESSIONS
'''
#SRA模型代理人API
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE")
print("PUBLIC_API_BASE",PUBLIC_API_BASE)

json_llm = OpenAIStyleOllama(
    base_url=os.getenv("MODEL_BASE_URL", "http://localhost:11434"),
    model=os.getenv("MODEL_ID", "gpt-oss:120b-32k"),
    temperature=float(os.getenv("MODEL_TEMPERATURE", "0")),
)
'''

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


def _strip_code_fences(s: str) -> str:
    # 若模型不小心包了 ```json ... ```，幫忙剝掉
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()








app = FastAPI(title="SRA-Structured Retrieval Agent (OpenAI-compatible)", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# ===== 通用多輪記憶（緊湊 JSON 狀態）=====
_memory: dict[str, dict] = {}   # 會話 -> 濃縮記憶(JSON)

def _render_memory_text(mem: dict | None) -> str:
    """把 JSON 記憶轉成可提示的短文字塊。"""
    if not mem:
        return ""
    parts = []
    if mem.get("topic"): parts.append(f"- 主題：{mem['topic']}")
    if mem.get("time_range"): parts.append(f"- 時間範圍：{mem['time_range']}")
    if mem.get("subtopics"): parts.append(f"- 子題：{', '.join([str(x) for x in mem['subtopics']][:6])}")
    if mem.get("entities"): parts.append(f"- 重要實體：{', '.join([str(x) for x in mem['entities']][:10])}")
    if mem.get("constraints"): parts.append(f"- 既定限制：{'; '.join([str(x) for x in mem['constraints']][:6])}")
    if mem.get("open_questions"): parts.append(f"- 未決問題：{'; '.join([str(x) for x in mem['open_questions']][:5])}")
    return "\n".join(parts).strip()

MEMORY_SYSTEM = "你是會話記憶壓縮器。請把對話濃縮成能幫助後續追問的一小段 JSON 狀態，保持簡潔、去重。"
def _update_memory(session_id: str, history_tail_text: str, last_out: dict | None):
    """用最近幾輪對話與上一輪輸出，產生/更新通用記憶(JSON)。"""
    prev = _memory.get(session_id) or {}
    last_answer = ""
    if isinstance(last_out, dict):
        last_answer = str(last_out.get("answer") or "")[:2000]
    user = (
        "請根據【既有記憶】與【最新對話片段】及【上一輪答案節選】，輸出緊湊 JSON：\n"
        '{ "topic": "", "time_range": "", "subtopics": [], "entities": [], "constraints": [], "open_questions": [] }\n\n'
        f"【既有記憶】\n{json.dumps(prev, ensure_ascii=False)}\n\n"
        f"【最新對話片段】\n{history_tail_text}\n\n"
        f"【上一輪答案節選】\n{last_answer}\n"
    )
    try:
        mem = json_llm.generate_json(
            MEMORY_SYSTEM,
            user,
            schema_hint='{"topic":"","time_range":"","subtopics":[],"entities":[],"constraints":[],"open_questions":[]}',
            num_ctx=32768
        )
        if isinstance(mem, dict):
            _memory[session_id] = mem
    except Exception:
        # 記憶更新失敗不影響主流程
        pass
    
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


@app.get("/healthz")
def healthz():
    return {"ok": True}

# --- OpenAI Chat Completions 相容端點（非串流版） ---
@app.get("/v1/models")
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

@app.post("/v1/chat/completions")
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
            mem_txt = _render_memory_text(_memory.get(session_key))

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

        mem_txt = _render_memory_text(_memory.get(session_key))
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
            _update_memory(session_key, tail_text, out if isinstance(out, dict) else None)
   



            # ★★★ 新增：若 session 數量超過上限，就淘汰最舊的一個，避免一直堆記憶體
            if len(sessions) > MAX_SESSIONS:
                victim_key = next(iter(sessions))  # dict 有插入順序，抓第一個當最舊
                print("[chat_completions] evict session:", repr(victim_key))

                sessions.pop(victim_key, None)
                _memory.pop(victim_key, None)
                last_structured.pop(victim_key, None)



        except Exception:
            pass


        
        return resp
    except Exception as e:
        # ★ 把真正錯誤印到 console，uvicorn 才看得到堆疊
        print("=== /v1/chat/completions 發生例外 ===")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

'''
ES_URL = os.getenv("ES_URL")
ES_USERNAME = os.getenv("ES_USERNAME")
ES_PASSWORD = os.getenv("ES_PASSWORD")
ES_INDEX_DEFAULT = os.getenv("ES_INDEX")
CA_CERT = "agent/certs/http_ca.crt"
ES_INDEX = ES_INDEX_DEFAULT  # 保留舊名稱，避免其他地方還有用到
ES_INDEX_RAW = os.getenv("ES_INDEX", "news_test,mil_reports-01")

# 允許用逗號分隔多個 index
ES_INDEXES = [idx.strip() for idx in ES_INDEX_RAW.split(",") if idx.strip()]

ES = Elasticsearch(
    ES_URL,ca_certs=CA_CERT,
    #headers={"Authorization": f"Bearer {ES_SERVICE_TOKEN}"},
    basic_auth=(ES_USERNAME, ES_PASSWORD),
    ssl_assert_hostname=False,   # ★ 不檢查 hostname
    #ssl_show_warn=False          # ★ 不一直跳警告（可選）
    )
print("Connecting to ES...")
print(ES.info())
'''



def _get_doc_source_or_404(doc_id: str) -> dict:
    """
    共用：依 doc_id（可能是 _id 或 uuid）從多個 index 中找到一筆文件的 _source。
    找不到就丟 404。
    """
    # 1) 逐一嘗試用 _id 直接抓（每個 index 都試）
    for idx in ES_INDEXES:
        try:
            got = ES.get(index=idx, id=doc_id, _source=True)
            src = got.get("_source", {}) or {}
            src["_id"] = got.get("_id")
            src["_index"] = got.get("_index")
            return src
        except NotFoundError:
            continue
        except Exception:
            # 其他錯誤先忽略，稍後用 search fallback
            continue

    # 2) 用 uuid.keyword 精確比對（跨索引 search）
    res = ES.search(
        index=ES_INDEXES,
        body={
            "size": 1,
            "_source": True,
            "query": {"term": {"uuid.keyword": doc_id}},
        },
    )
    hits = res.get("hits", {}).get("hits", []) or []
    if hits:
        hit = hits[0]
        src = hit.get("_source", {}) or {}
        src["_id"] = hit.get("_id")
        src["_index"] = hit.get("_index")
        return src

    # 3) 再試一次 uuid（非 keyword 的情況）
    res = ES.search(
        index=ES_INDEXES,
        body={
            "size": 1,
            "_source": True,
            "query": {"term": {"uuid": doc_id}},
        },
    )
    hits = res.get("hits", {}).get("hits", []) or []
    if hits:
        hit = hits[0]
        src = hit.get("_source", {}) or {}
        src["_id"] = hit.get("_id")
        src["_index"] = hit.get("_index")
        return src

    # 4) 最後保底：wildcard 模糊比對
    res = ES.search(
        index=ES_INDEXES,
        body={
            "size": 1,
            "_source": True,
            "query": {"wildcard": {"uuid": {"value": f"*{doc_id}*"}}},
        },
    )
    hits = res.get("hits", {}).get("hits", []) or []
    if hits:
        hit = hits[0]
        src = hit.get("_source", {}) or {}
        src["_id"] = hit.get("_id")
        src["_index"] = hit.get("_index")
        return src

    raise HTTPException(status_code=404, detail="document not found")

@app.get("/v1/docs/{doc_id}")
def get_doc(doc_id: str):
    return _get_doc_source_or_404(doc_id)
@app.get("/v1/docs/{doc_id}/fulltext")
def get_fulltext_on_demand(
    doc_id: str,
    format: str = Query(
        "json",
        description="回傳格式：json 或 txt，預設 json。",
    ),
    download: bool = Query(
        False,
        description="在 format=txt 時，為 true 則以附件下載形式回傳。",
    ),
):
    """
    按需下載全文：
    - 不經過 LLM / 文件跟進代理人。
    - 直接用既有 /v1/docs 的查詢邏輯找到文件，抽出全文欄位回傳。
    """
    src = _get_doc_source_or_404(doc_id)

    # 如果 _get_doc_source_or_404 回傳的是整個 ES hit，先把 _source 拉出來
    if isinstance(src, dict) and "_source" in src:
        src = src["_source"]

    # ==== 1) 全文 ====
    full_text = (
        src.get("full_text")
        or (src.get("rawInfo") or {}).get("content")
        or src.get("content")
        or ""
    )

    if not isinstance(full_text, str) or not full_text.strip():
        raise HTTPException(status_code=404, detail="文件存在，但沒有可用的全文內容。")

    # ==== 2) 標題 ====
    md = src.get("multidim_event_json") or {}
    comm = src.get("communication") or {}

    title = (
        md.get("article_title")
        or comm.get("subject")
        or src.get("title")
        or (src.get("rawInfo") or {}).get("title")
        or doc_id
    )

    # ==== 3) 日期：優先用 Event.time_iso，再用 Event_Timeline 的最大 date_iso ====
    def infer_article_date(src_doc: dict) -> str | None:
        mdj = src_doc.get("multidim_event_json") or {}

        evt = mdj.get("Event") or {}
        if isinstance(evt, dict):
            time_iso = evt.get("time_iso")
            if isinstance(time_iso, str) and time_iso.strip():
                return time_iso.strip()

        tl = mdj.get("Event_Timeline") or []
        dates: list[str] = []
        for item in tl:
            if not isinstance(item, dict):
                continue
            di = item.get("date_iso")
            if isinstance(di, str) and di.strip():
                dates.append(di.strip())
        if dates:
            return max(dates)
        return None

    date = (
        md.get("article_date_iso")
        or infer_article_date(src)
        or (src.get("rawInfo") or {}).get("date")
        or None
    )

    # ==== 4) 主旨（subject）====
    subject = (
        comm.get("subject")
        or md.get("article_title")
        or src.get("subject")
        or (src.get("rawInfo") or {}).get("subject")
        or None
    )

    total_length = len(full_text)

    # === JSON 模式：meta + full_text 一起回 ===
    fmt = (format or "").lower()
    if fmt == "json":
        return JSONResponse(
            {
                "uuid": src.get("uuid", doc_id),
                "title": title,
                "date": date,
                "subject": subject,
                "total_length": total_length,
                "full_text": full_text,
            }
        )

    # === TXT 模式：單純吐出全文（可選擇是否附件下載） ===
    if format.lower() == "txt":
        headers = {}
    
        if download:
            from urllib.parse import quote
    
            # ===== 1) 日期（放最前面）=====
            safe_date = (date or "unknown-date").replace(":", "-").replace("/", "-")
    
            # ===== 2) 標題（中間）=====
            raw_title = str(title).strip() or "no-title"
    
            # 給 filename= 用的 ASCII 版本（舊瀏覽器）
            ascii_title = re.sub(r'[\\/:*?"<>|]+', "_", raw_title)
            ascii_title = re.sub(r"[^\x00-\x7F]+", "_", ascii_title).strip("_")
            if not ascii_title:
                ascii_title = "no-title"
    
            # 給 filename*= 用的 UTF-8 版本（新瀏覽器顯示中文）
            utf8_title = quote(raw_title)
    
            # ===== 3) UUID（放最後）=====
            safe_uuid = src.get("uuid", doc_id)
    
            # ===== 4) 組合檔名 =====
            filename_ascii = f"{safe_date}_{ascii_title}_{safe_uuid}.txt"
            filename_utf8  = f"{safe_date}_{utf8_title}_{safe_uuid}.txt"
    
            headers["Content-Disposition"] = (
                f"attachment; "
                f'filename="{filename_ascii}"; '
                f"filename*=UTF-8''{filename_utf8}"
            )
    
        return PlainTextResponse(
            content=full_text,
            headers=headers,
            media_type="text/plain; charset=utf-8",
        )


    raise HTTPException(status_code=400, detail="format 只支援 json 或 txt。")
