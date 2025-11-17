#cd D:\shared\TopicClassification\poc-agent&& uvicorn api.main:app --host 0.0.0.0 --port 8000
import os, json, time
import re
import html
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query
from fastapi import Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from elasticsearch import Elasticsearch
from elasticsearch import NotFoundError

# 你的代理人單例；內部已走 Ollama（LiteLLMModel -> MODEL_BASE_URL）
from agent.agent import get_agent, SYSTEM
from agent.agent import build_model  # 直接重用你已經有的 LiteLLMModel 建構器

from agent.direct_llm_json import OpenAIStyleOllama, task_tags, task_title, task_followups

PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE")

json_llm = OpenAIStyleOllama(
    base_url=os.getenv("MODEL_BASE_URL", "http://localhost:11434"),
    model=os.getenv("MODEL_ID", "gpt-oss:120b-32k"),
    temperature=float(os.getenv("MODEL_TEMPERATURE", "0")),
)

def _abs_url(request: Request, path: str) -> str:
    print("PUBLIC_API_BASE",PUBLIC_API_BASE)
    base = (PUBLIC_API_BASE or str(request.base_url)).rstrip("/")
    print("base",base)
    print(f"{base}{path}")
    return f"{base}{path}"

# --- Heuristics：辨識 WebUI 的「分析任務」：只要純 JSON / 有 <chat_history> / 有 ### Task 標頭等 ---
META_TASK_TRIGGERS = [
    r"^###\s*Task:",  # 常見格式： '### Task: ...'
    #r"JSON\s+format:\s*\{",  # 指定 JSON 輸出格式
    #r"Your entire response must .* JSON object",  # 強調只能回傳 JSON
    r"<chat_history>",  # 帶封裝的歷史
    r"Generate\s+1-3\s+broad\s+tags",  # tags 任務
    r"Generate a concise,\s*3-5 word title",  # title 任務
    r"Suggest\s+3-5\s+relevant follow-up questions",  # follow-ups 任務
]

BYPASS_AGENT_FOR_META=1

def _detect_meta_kind(text: str) -> str | None:
    t = (text or "").lower()
    if "generate 1-3 broad tags" in t or "### task" in t and "tags" in t:
        return "tags"
    if "generate a concise, 3-5 word title" in t or ("title" in t and "emoji" in t and "json" in t):
        return "title"
    if "suggest 3-5 relevant follow-up" in t or ("follow-up" in t and "json" in t):
        return "followups"
    return None

'''
def _is_webui_meta_task(s: str) -> bool:
    if not s: 
        return False
    for pat in META_TASK_TRIGGERS:
        if re.search(pat, s, flags=re.IGNORECASE | re.DOTALL):
            return True
    return False
'''

def _strip_code_fences(s: str) -> str:
    # 若模型不小心包了 ```json ... ```，幫忙剝掉
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

app = FastAPI(title="TableRAG Agent (OpenAI-compatible)", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

#agent = get_agent()

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatPayload(BaseModel):
    model: str = "SRA-Structured Retrieval Agent"
    messages: list[ChatMessage]
    stream: bool | None = None
    format: str | None = "markdown"   # ← 新增
def render_markdown(out: Any, request: Request) -> str:
    """
    把代理人輸出（dict 或 str）轉成排版好的 Markdown：
    - 回答主文（支援把 <em>/<i>/<strong>/<b>/<br>/<p> 轉成 Markdown）
    - 引用來源（含段落、縮短引文、可點連結）
    - 可展開的「推理步驟」與「原始 JSON」
    """
    ALLOW_DETAILS = os.getenv("MD_ALLOW_DETAILS", "1") == "1"  # ← 新增：是否輸出 <details>（預設關閉）
    # 1) 把常見 HTML 轉成 Markdown（保守白名單）
    def _html_to_markdown_light(s: str) -> str:
        if not isinstance(s, str):
            return ""
        s = html.unescape(s)  # &lt;em&gt; → <em>

        # 換行/段落
        s = re.sub(r'(?i)<br\s*/?>', '\n', s)
        s = re.sub(r'(?i)</p\s*>', '\n\n', s)
        s = re.sub(r'(?i)<p[^>]*>', '', s)

        # 強調/粗體
        s = re.sub(r'(?i)<(em|i)(\s+[^>]*)?>', '*', s)
        s = re.sub(r'(?i)</(em|i)\s*>', '*', s)
        s = re.sub(r'(?i)<(strong|b)(\s+[^>]*)?>', '**', s)
        s = re.sub(r'(?i)</(strong|b)\s*>', '**', s)

        # 清單（簡化處理）
        s = re.sub(r'(?i)</li\s*>', '\n', s)
        s = re.sub(r'(?i)<li[^>]*>', '- ', s)
        s = re.sub(r'(?i)</?(ul|ol|div|span)[^>]*>', '', s)

        # 其餘標籤直接移除
        s = re.sub(r'<[^>]+>', '', s)
        return s

    # 2) 統一換行：把字面 "\\n" 變真正換行；也處理 \r\n
    def _normalize_newlines(s: str) -> str:
        if not isinstance(s, str):
            return ""
        return s.replace("\r\n", "\n").replace("\\n", "\n")

    # 3) 綜合正規化
    def _normalize_text(s: str) -> str:
        return _normalize_newlines(_html_to_markdown_light(s)).strip()

    # 字串就直接回傳（也正規化一次）
    if not isinstance(out, dict):
        return _normalize_text(str(out))

    # 取欄位 & 正規化
    answer = _normalize_text(out.get("answer") or "")
    reasoning = _normalize_text(out.get("reasoning") or "")
    citations = out.get("citations") or []

    # 把 citation 的 text 也處理（避免 <em> 顯示失敗）
    for c in citations:
        if isinstance(c.get("text"), str):
            c["text"] = _normalize_text(c["text"])

    md = []

    # 主文
    if answer:
        md.append("# 回答\n")
        md.append(answer)

    # 引用來源
    if citations:
        md.append("\n\n## 來源 / Citations\n")
        seen = set()
        for i, c in enumerate(citations, 1):
            sid = c.get("source_id") or c.get("uuid") or c.get("doc_id") or c.get("id")
            if sid in seen:
                continue
            seen.add(sid)

            pid = c.get("paragraph_id")
            txt = (c.get("text") or "").replace("\n", " ").strip()
            if len(txt) > 160:
                txt = txt[:160] + "…"

            link = ""
            if isinstance(sid, str):
                url = _abs_url(request, f"/v1/docs/{sid}")
                link = f" · <{url}>"

            pid_str = f"（段落 {pid}）" if pid else ""
            date_piece = f" · 🗓 {c.get('date_iso')}" if c.get("date_iso") else ""
            md.append(f"{i}. **{sid}**{pid_str}{link}{date_piece}\n\n   > {txt}")

    # 推理（可收合 / fallback）
    if reasoning:
        if ALLOW_DETAILS:
            # 讓前端能渲染 <details>（需前端允許原生 HTML）
            md.append("\n\n<details><summary>展開推理 / 步驟</summary>\n\n")
            md.append("```text\n" + reasoning + "\n```")
            md.append("\n</details>")
        else:
            # Fallback：純 Markdown 章節
            md.append("\n\n## 推理 / 步驟\n")
            md.append("```text\n" + reasoning + "\n```")

    # 原始 JSON（可收合 / fallback 同理）
    raw_json = "```json\n" + json.dumps(out, ensure_ascii=False, indent=2) + "\n```"
    if ALLOW_DETAILS:
        md.append("\n\n<details><summary>原始 JSON</summary>\n\n")
        md.append(raw_json)
        md.append("\n</details>\n")
    else:
        md.append("\n\n## 原始 JSON\n\n")
        md.append(raw_json)
        md.append("\n")

    return "\n\n".join(md)

def render_markdown_OLD(out: Any, request: Request) -> str:
    """
    把代理人輸出（dict 或 str）轉成排版好的 Markdown，包含：
    - 回答主文
    - 引用來源（含段落、縮短引文、可點連結到 /v1/docs/{uuid}）
    - 可展開的「推理步驟」與「原始 JSON」
    """
    # 字串就直接回傳
    if not isinstance(out, dict):
        return str(out)

    answer = (out.get("answer") or "").strip()
    citations = out.get("citations") or []
    reasoning = (out.get("reasoning") or "").strip()

    md = []

    # 主文
    if answer:
        md.append("# 回答\n")
        md.append(answer)

    # 引用來源
    if citations:
        md.append("\n\n## 來源 / Citations\n")
        seen = set()
        for i, c in enumerate(citations, 1):
            sid = c.get("source_id") or c.get("uuid") or c.get("doc_id") or c.get("id")
            if sid in seen:
                continue
            seen.add(sid)

            pid = c.get("paragraph_id")
            txt = (c.get("text") or "").replace("\n", " ").strip()
            if len(txt) > 160:
                txt = txt[:160] + "…"

            # 生成可點的反查連結（顯示完整 URL，最不會被前端清洗）
            link = ""
            if isinstance(sid, str):
                url = _abs_url(request, f"/v1/docs/{sid}")
                link = f" · <{url}>"

            pid_str = f"（段落 {pid}）" if pid else ""          
            date_piece = f" · 🗓 {c.get('date_iso')}" if c.get("date_iso") else ""
            md.append(f"{i}. **{sid}**{pid_str} · <{url}>{date_piece}\n\n   > {txt}")

    # 推理（可收合）
    if reasoning:
        md.append("\n\n<details><summary>展開推理 / 步驟</summary>\n\n")
        md.append("```text\n" + reasoning + "\n```")
        md.append("\n</details>")

    # 原始 JSON（可收合，方便反查/除錯）
    md.append("\n\n<details><summary>原始 JSON</summary>\n\n")
    md.append("```json\n" + json.dumps(out, ensure_ascii=False, indent=2) + "\n```")
    md.append("\n</details>\n")
    
    return "\n\n".join(md)

RAW_JSON_SYSTEM = (
    "You are a formatter. "
    "Return ONLY the raw JSON object requested by the user. "
    "No backticks, no code fences, no commentary."
)

'''
def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _direct_llm_json(query: str) -> str:
    from agent.agent import build_model  # 避免循環 import
    model = build_model()
    prompt = f"{RAW_JSON_SYSTEM}\n\n{query}"
    last_err = None

    # 逐步嘗試不同 API（不同版本 smolagents / litellm 可能差異）
    for call in ("__call__", "generate", "chat"):
        try:
            if call == "__call__":
                text = model(prompt)  # 有些版本 __call__ 直接回字串
            elif call == "generate":
                text = model.generate(prompt)  # 有些版本是 .generate(...)
            else:
                # 最保險：聊天訊息風格
                text = model.chat([{"role":"user","content":prompt}])
            return _strip_code_fences(str(text))
        except Exception as e:
            print(f"[direct_llm_json:{call}] error:", repr(e))
            last_err = e

    # 全部失敗 → 丟出 400（避免吃掉細節）
    raise HTTPException(status_code=400, detail=f"direct LLM failed: {last_err}")
'''
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
    try:
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
        agent = get_agent()          # ← 每請求新建乾淨 Agent
        #out = agent.run(query)
        
        # 2-1) ★路由：若偵測到 WebUI 的分析任務 → 直接用 LLM 回 JSON；否則才走 CodeAgent
        # >>> 新增：若是 WebUI 的 JSON 分析任務，直接用 json_llm 產生，繞開 CodeAgent <<<
        kind = _detect_meta_kind(query)
        if kind:
            # 用整段 chat history（轉成純文字）給 LLM 參考
            history_text = ""
            for m in payload.messages:
                role = m.role.upper()
                history_text += f"{role}:\n{m.content}\n\n"

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
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }
        # 2-2) 否則 → 原本走代理（會回 dict：answer/citations/reasoning）
        try:
            out = agent.run(query)
        except Exception:
            # 建立一個新 agent 再跑一次，避免是上一輪殘留造成的
            agent = get_agent()
            out = agent.run(query)
        

        # 3) 產主文：保留你的 format / render_markdown 行為
        fmt = (payload.format or "markdown").lower()
        if fmt == "json":
            text = json.dumps(out, ensure_ascii=False)
        else:
            text = render_markdown(out, request)   # ← 把 request 傳進去

        # 4) 產 citations（加上「可點的」絕對連結）
        citations = []
        if isinstance(out, dict):
            for c in (out.get("citations") or []):
                doc_id = c.get("source_id") or c.get("uuid")
                href = _abs_url(request, f"/v1/docs/{doc_id}") if doc_id else None
                print("href",href)
                citations.append({
                    "text": c.get("text"),
                    "source_id": doc_id,
                    "paragraph_id": c.get("paragraph_id"),
                    "href": href,  # ← 前端可直接用這個做「反查」
                })

        # 5) 回 OpenAI 兼容格式（多帶一個非標準的 context，客戶端不需要也會略過）
        return {
            "id": f"chatcmpl-{int(time.time()*1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,               # 主文（維持你原本格式）
                    "context": {"citations": citations}  # 反查資訊（新加）
                },
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
'''
@app.post("/v1/chat/completions")
def chat_completions(payload: ChatPayload):
    try:
        # 取最後一則使用者訊息；如果有 system，就把它前置到 query（保持你原本 SYSTEM 邏輯）
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

        out = agent.run(query)

        #if isinstance(out, dict):
        #    text = out.get("answer") or json.dumps(out, ensure_ascii=False)
        #else:
        #    text = str(out)
        
        #text = render_markdown(out)
        
        fmt = (payload.format or "markdown").lower()
        if fmt == "json":
            # 直接把 out 序列化回去
            text = json.dumps(out, ensure_ascii=False)
        else:
            text = render_markdown(out)

        return {
            "id": f"chatcmpl-{int(time.time()*1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
'''

@app.post("/v1/chat/completions_stream")
def chat_completions_stream(payload: ChatPayload):
    def gen():
        # 解析 user 訊息同上……
        msgs = payload.messages
        user_msg = next((m.content for m in reversed(msgs) if m.role == "user"), "")
        out = agent.run(user_msg)
        text = out.get("answer") if isinstance(out, dict) else str(out)
        # 模擬切塊
        for chunk in [text[i:i+100] for i in range(0, len(text), 100)]:
            data = {
                "id": f"chatcmpl-{int(time.time()*1000)}",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        # 結尾
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

'''
@app.get("/v1/chat/completions")
def chat_completions_get(q: str = Query(..., description="Your question")):
    out = agent.run(q)
    text = out.get("answer") if isinstance(out, dict) else str(out)
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "SRA-Structured Retrieval Agent",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }
'''

ES_URL = os.getenv("ES_URL", "http://localhost:9200")
#ES_URL = "http://192.168.0.228:9200"
ES_INDEX = os.getenv("ES_INDEX", "news_test")
ES = Elasticsearch(ES_URL)

@app.get("/v1/docs/{doc_id}")
def get_doc(doc_id: str):
    # 1) 先嘗試用 _id 直接抓（最快、最穩）
    print(f"running get_doc for {doc_id}")
    try:
        got = ES.get(index=ES_INDEX, id=doc_id, _source=True)
        src = got.get("_source", {})
        # 順手把 _id 帶回去（有助前端辨識）
        src["_id"] = got.get("_id")
        return src
    except NotFoundError:
        pass
    except Exception:
        # 有些舊版 client 不會丟 NotFoundError，就直接忽略進 fallback
        pass

    # 2) 用 uuid.keyword 精確比對（若 mapping 有 keyword 子欄位）
    res = ES.search(
        index=ES_INDEX,
        body={
            "size": 1,
            "_source": True,
            "query": {"term": {"uuid.keyword": doc_id}}
        },
    )
    hits = res.get("hits", {}).get("hits", []) or []
    if hits:
        hit = hits[0]
        src = hit.get("_source", {})
        src["_id"] = hit.get("_id")
        return src

    # 3) 若沒 keyword 子欄位，試試直接 term 在 uuid（若它本身就是 keyword）
    res = ES.search(
        index=ES_INDEX,
        body={
            "size": 1,
            "_source": True,
            "query": {"term": {"uuid": doc_id}}
        },
    )
    hits = res.get("hits", {}).get("hits", []) or []
    if hits:
        hit = hits[0]
        src = hit.get("_source", {})
        src["_id"] = hit.get("_id")
        return src

    # 4) 最後保底：模糊比對（避免因為大小寫/格式微差抓不到）
    res = ES.search(
        index=ES_INDEX,
        body={
            "size": 1,
            "_source": True,
            "query": {"wildcard": {"uuid": {"value": f"*{doc_id}*"}}}
        },
    )
    hits = res.get("hits", {}).get("hits", []) or []
    if hits:
        hit = hits[0]
        src = hit.get("_source", {})
        src["_id"] = hit.get("_id")
        return src

    # 全部找不到
    raise HTTPException(status_code=404, detail="document not found")