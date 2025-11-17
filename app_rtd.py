# app.py
# for AnkInt open webui, run api/main.py
# cd D:\shared\TopicClassification\poc-agent; uvicorn api.main:app --host 0.0.0.0 --port 8000
# python -m uvicorn app:app --host 0.0.0.0 --port 8081
from dotenv import load_dotenv
load_dotenv()

import time, uuid, os, json
from typing import List, Literal, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 先載入 .env，再 import 你的 agent
from dotenv import load_dotenv
load_dotenv()

from agent.agent import get_agent

# === FastAPI 基本設定 ===
app = FastAPI(title="Agentic RAG API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === OpenAI 相容模型 ===
class Message(BaseModel):
    role: Literal["system","user","assistant"]
    content: str

class ChatRequest(BaseModel):
    model: Optional[str] = "gov-agent"
    messages: List[Message]
    temperature: Optional[float] = 0.0

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    """
    最小 /v1/chat/completions 實作（非串流）。
    Open WebUI：設定 OPENAI_API_BASE_URL 指到本服務的 /v1。
    """
    # 取最後一則 user 訊息（必要時可串接整段訊息傳入代理人）
    question = next((m.content for m in reversed(req.messages) if m.role == "user"), "")

    agent = get_agent()
    result = agent.run(question)

    if isinstance(result, (dict, list)):
        answer = json.dumps(result, ensure_ascii=False)
    else:
        answer = str(result)

    return {
        "id": f"cmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }
