#api/main.py
#cd D:\shared\TopicClassification\poc-agent&& uvicorn api.main:app --host 0.0.0.0 --port 8000
import os, json, time
import re
import html
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException
from collections import defaultdict, deque
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query
from fastapi import Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from elasticsearch import Elasticsearch
from elasticsearch import NotFoundError
import traceback

# 你的代理人單例；內部已走 Ollama（LiteLLMModel -> MODEL_BASE_URL）
from agent.agent import get_agent, SYSTEM
from agent.agent import build_model  # 直接重用你已經有的 LiteLLMModel 建構器

from agent.direct_llm_json import OpenAIStyleOllama, task_tags, task_title, task_followups

PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE")
print("PUBLIC_API_BASE",PUBLIC_API_BASE)

json_llm = OpenAIStyleOllama(
    base_url=os.getenv("MODEL_BASE_URL", "http://localhost:11434"),
    model=os.getenv("MODEL_ID", "gpt-oss:120b-32k"),
    temperature=float(os.getenv("MODEL_TEMPERATURE", "0")),
)

def _abs_url(request: Request, path: str) -> str:
    #print("PUBLIC_API_BASE",PUBLIC_API_BASE)
    base = (PUBLIC_API_BASE or str(request.base_url)).rstrip("/")
    #print("base",base)
    #print(f"href {base}{path}")
    return f"{base}{path}"


class ChatMessage(BaseModel):
    role: str
    content: str
    format: str | None = "markdown"   # ← 新增

class ChatPayload(BaseModel):
    model: str = "SRA-Structured Retrieval Agent"
    messages: list[ChatMessage]
    stream: bool | None = None
    format: str | None = "markdown"   # ← 新增

# ===== Session store（簡易記憶）=====
SESSION_MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "20"))
_sessions: dict[str, deque[ChatMessage]] = defaultdict(lambda: deque(maxlen=SESSION_MAX_TURNS))
_last_structured: dict[str, dict] = {}     # 會話 -> 上一輪 out（answer/citations/reasoning）
#_last_orgs: dict[str, list[str]] = {}      # 會話 -> 上一輪提到的機構/組織清單
    
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

def _normalize_newlines_for_save(s: str) -> str:
    # 把 \r\n → \n，並把「字面上的」\n 變成真正的換行
    return (s or "").replace("\r\n", "\n").replace("\\n", "\n").strip()


# 多輪對話：抽前文答覆的「主文」，避免把 citations / details 整坨塞回模型
HISTORY_MAX_CHARS = int(os.getenv("HISTORY_MAX_CHARS", "12000"))

# 允許 "# 回答" 或純文字 "回答" 開頭；
# 主文擷取到「## 來源 / Citations」或「## 原始」或 <details> 或字串結尾 \Z 為止
ANSWER_BLOCK_RE = re.compile(
    r'(?su)^\s*(?:#\s*回答|回答)\s*\n'   # ^ 只錨定字串開頭，不要 multiline
    r'(?P<body>.*?)'
    r'(?=\n(?:'
        r'##\s*(?:來源|来源)\b'           # ## 來源
        r'|##\s*Citations\b'              # ## Citations
        r'|來源\s*/?\s*Citations'         # 來源 / Citations（保險，不一定有 ##）
        r'|##\s*(?:原始|原始\s*JSON)\b'   # ## 原始 / ## 原始 JSON
        r'|<details>'                     # <details>（推理/原始JSON 可能用 details）
        r'|\Z'                            # ✅ 僅匹配字串結尾（避免每行行尾）
    r'))'
)

# 與上面白名單一致；無需 $，所以不受 multiline 影響
_CUTOFF_RE = re.compile(
    r'\n(?:##\s*(?:來源|来源|Citations|原始|原始\s*JSON)\b|來源\s*/?\s*Citations|<details>)',
    re.I
)

def _strip_assistant_content(s: str) -> str:
    # 先正規化換行，避免 CRLF 或字面 "\n" 影響邊界
    s = _normalize_newlines_for_save((s or "").strip())
    if not s:
        return s
    m = ANSWER_BLOCK_RE.search(s)
    if m:
        return m.group("body").strip()
    # Fallback：找白名單分隔符直接截
    return _CUTOFF_RE.split(s, 1)[0].strip()

def pack_chat_history(messages: list[ChatMessage], *, max_chars: int = HISTORY_MAX_CHARS) -> str:
    """
    將過往 system/user/assistant 簡化為：
      SYSTEM: ...
      USER: ...
      ASSISTANT: ...(只留主文)
    並限制長度（保留最近 max_chars 字元）。
    """
    lines: list[str] = []
    for m in messages:
        role = (m.role or "").lower()
        if role not in ("system", "user", "assistant"):
            continue
        content = (m.content or "").strip()
        if not content:
            continue
        if role == "assistant":
            print("content before",content)
            content = _strip_assistant_content(content)
            print("content after _strip_assistant_content",content)
            content = _normalize_newlines_for_save(content)
            print("content after _normalize_newlines_for_save",content)
        lines.append(f"{role.upper()}:\n{content}\n")
    s = "".join(lines)
    if len(s) > max_chars:
        s = s[-max_chars:]   # 保留最近的上下文
    return s

def _best_assistant_text(session_id: str, maybe_text_from_client: str) -> str:
    """
    優先使用我們剛剛保存的完整渲染文本；若無則用前端回傳的。
    """
    if session_id and session_id in _sessions:
        # 在 deque 尾端尋找最近一則 assistant
        for m in reversed(_sessions[session_id]):
            if (getattr(m, "role", "") or "").lower() == "assistant":
                return str(m.content or "").strip() or maybe_text_from_client
    return maybe_text_from_client

def _choose_assistant_save(out: Any, rendered_text: str) -> str:
    """
    優先使用 out['answer']；若太短或行數太少，回退渲染後 Markdown 的『純主文』。
    返回前一律做換行正規化，避免把 '\\n' 存進 session。
    """
    def _is_rich(txt: str) -> bool:
        txt = (txt or "").strip()
        return len(txt) >= 80 or txt.count("\n") >= 2  # 足夠長或至少兩行

    if isinstance(out, dict):
        body = str(out.get("answer") or "")
        if _is_rich(body):
            return _normalize_newlines_for_save(body)
        pure = _strip_assistant_content(str(rendered_text))
        # 二選一取較長者，並正規化
        better = pure if len(pure) > len(body) else body
        return _normalize_newlines_for_save(better)

    # out 不是 dict：直接抽純主文並正規化
    return _normalize_newlines_for_save(_strip_assistant_content(str(rendered_text)))

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
    
#agent = get_agent()

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
            #sid = c.get("source_id") or c.get("uuid") or c.get("doc_id") or c.get("id")
            #if sid in seen:
            #    continue
            #seen.add(sid)

            doc_id = c.get("source_id") or c.get("uuid") or c.get("doc_id") or c.get("id")
            if doc_id in seen:
                continue
            seen.add(doc_id)
    
            # ★ 新增：顯示名稱優先 subject，其次 article_title/title，最後才用 UUID
            display = c.get("subject") or c.get("article_title") or c.get("title") or str(doc_id)
            
            pid = c.get("paragraph_id")
            txt = (c.get("text") or "").replace("\n", " ").strip()
            if len(txt) > 300:
                txt = txt[:300] + "…"

            link = ""
            #if isinstance(sid, str):
            #    url = _abs_url(request, f"/v1/docs/{sid}")
            #    link = f" · <{url}>"

            if isinstance(doc_id, str):
                url = _abs_url(request, f"/v1/docs/{doc_id}")
                link = f" · <{url}>"
                
            pid_str = f"（段落 {pid}）" if pid else ""
            date_piece = f" · 🗓 {c.get('date_iso')}" if c.get("date_iso") else ""
            #md.append(f"{i}. **{sid}**{pid_str}{link}{date_piece}\n\n   > {txt}")
            # ★ 用 display（subject）取代原先的 sid（UUID）
            md.append(f"{i}. **{display}**{pid_str}{link}{date_piece}\n\n   > {txt}")

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

RAW_JSON_SYSTEM = (
    "You are a formatter. "
    "Return ONLY the raw JSON object requested by the user. "
    "No backticks, no code fences, no commentary."
)

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
        # 0) 會話 ID（可用前端 header 傳入）
        session_id = request.headers.get("x-conversation-id") or request.headers.get("x-session-id") or ""

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
            # 用整段 chat history（統一經 pack_chat_history），優先使用我們的 session
            if session_id and session_id in _sessions and len(_sessions[session_id]) > 0:
                base_history_msgs = list(_sessions[session_id])
            else:
                base_history_msgs = list(payload.messages)
            
            history_text = pack_chat_history(base_history_msgs)
            mem_txt = _render_memory_text(_memory.get(session_id))
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
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }
        # 2-2) 否則 → 多輪：把歷史一併送進 Agent
        # 構造可讀歷史：優先使用我們保存於 session 的乾淨主文
        if session_id and session_id in _sessions and len(_sessions[session_id]) > 0:
            history_msgs = list(_sessions[session_id])
        else:
            # 沒有 session 時才退回用前端帶回的歷史（去掉當輪 user）
            history_msgs = list(payload.messages[:-1])
        
        print("history_msgs (effective)", history_msgs)
        history_text = pack_chat_history(history_msgs)
        print("history_text from pack_chat_history",history_text)
        # 附上上一輪摘要（自動）：主要機構清單（就算正文被截也有這份保底）
        #if session_id and session_id in _last_orgs and _last_orgs[session_id]:
        #    summary_tail = "【上一輪摘要（自動）】\n- 主要機構：" + "、".join(_last_orgs[session_id][:15]) + "\n"
        #    history_text = (history_text + "\n" + summary_tail).strip()

        mem_txt = _render_memory_text(_memory.get(session_id))
        query_for_agent = (
            (f"【對話記憶】\n{mem_txt}\n\n" if mem_txt else "") +
            f"【對話歷史】\n{history_text}\n\n"
            f"【目前問題】\n{user_msg}\n\n"
            "【要求】如果是有對話歷史的多輪對話，那麼延續上文已確立的主題/時間範圍/定義；避免過度衍伸。"
        )
        
        try:
            out = agent.run(query_for_agent)
        except Exception:
            agent = get_agent()
            out = agent.run(query_for_agent)
        

        # 3) 產主文：保留你的 format / render_markdown 行為
        fmt = (payload.format or "markdown").lower()
        if fmt == "json":
            text = json.dumps(out, ensure_ascii=False)
        else:
            text = render_markdown(out, request)

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
                    "title": c.get("subject") or c.get("article_title") or c.get("title") or str(doc_id)  # ★ 可選
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
                    "context": {"citations": citations}
                },
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
        
        # 6) 保存本輪到會話歷史 & 更新通用記憶
        try:
            if session_id:
                _sessions[session_id].append(ChatMessage(role="user", content=user_msg))
                # 無論回前端是 json 或 markdown，都另外渲染一份完整 markdown 給保存邏輯用
                rendered_full = render_markdown(out, request) if isinstance(out, dict) else str(out)
                assistant_save = _choose_assistant_save(out, rendered_full)
                _sessions[session_id].append(ChatMessage(role="assistant", content=assistant_save))
                if isinstance(out, dict):
                    _last_structured[session_id] = out
                tail_msgs = list(_sessions[session_id])[-6:]
                tail_text = pack_chat_history(tail_msgs, max_chars=4000)
                _update_memory(session_id, tail_text, out if isinstance(out, dict) else None)
        except Exception:
            pass
        
        return resp
    except Exception as e:
        # ★ 把真正錯誤印到 console，uvicorn 才看得到堆疊
        print("=== /v1/chat/completions 發生例外 ===")
        traceback.print_exc()
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
def chat_completions_stream(payload: ChatPayload, request: Request):
    def gen():
        session_id = request.headers.get("x-conversation-id") or request.headers.get("x-session-id") or ""

        # 合併歷史（若前端只送當輪，就用我們存的）
        merged_msgs = list(payload.messages)
        if session_id and session_id in _sessions and len(merged_msgs) <= 2:
            merged_msgs = list(_sessions[session_id])

        # 當輪 user
        user_msg = next((m.content for m in reversed(merged_msgs) if m.role == "user"), "")

        # 歷史（不含當輪 user）
        try:
            last_user_index = max(i for i, m in enumerate(merged_msgs) if m.role == "user")
            history_msgs = merged_msgs[:last_user_index]
        except ValueError:
            history_msgs = merged_msgs

        history_text = pack_chat_history(history_msgs)
        mem_txt = _render_memory_text(_memory.get(session_id))

        prompt = (
            (f"【對話記憶】\n{mem_txt}\n\n" if mem_txt else "") +
            f"【對話歷史】\n{history_text}\n\n"
            f"【目前問題】\n{user_msg}\n\n"
            "【要求】延續上文已確立的主題/時間範圍/定義；必要時可做合理假設並在 reasoning 說明。"
        )

        agent = get_agent()
        out = agent.run(prompt)
        text = out.get("answer") if isinstance(out, dict) else str(out)

        # 模擬切塊
        for chunk in [text[i:i+100] for i in range(0, len(text), 100)]:
            data = {
                "id": f"chatcmpl-{int(time.time()*1000)}",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

        # 非阻塞：保存會話與更新記憶（串流尾端做即可）
        try:
            if session_id:
                _sessions[session_id].append(ChatMessage(role="user", content=user_msg))
                rendered_full = render_markdown(out, request) if isinstance(out, dict) else str(out)
                assistant_save = _choose_assistant_save(out, rendered_full)
                _sessions[session_id].append(ChatMessage(role="assistant", content=assistant_save))
                if isinstance(out, dict):
                    _last_structured[session_id] = out
                tail_msgs = list(_sessions[session_id])[-6:]
                tail_text = pack_chat_history(tail_msgs, max_chars=4000)
                _update_memory(session_id, tail_text, out if isinstance(out, dict) else None)
        except Exception:
            pass

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