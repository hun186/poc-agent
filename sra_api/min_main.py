# api/min_main.py
#set AGENT_LOG_LEVEL=DEBUG&&cd D:\shared\TopicClassification\poc-agent&& uvicorn api.min_main:app --host 0.0.0.0 --port 8001
# api/min_main.py（示意）
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from agent.min_agent import run_agent
import traceback, logging, os, json
import uuid
import time

app = FastAPI()
log = logging.getLogger("api")

def _to_openai_format(final: dict, model_name: str = "minimal-agent", debug: bool = False):
    # 將 final["answer"] 映射成標準 Chat Completions 的 content
    content = final.get("answer", "")
    msg = {"role": "assistant", "content": content}
    # 可選：把 debug trace 放到 message.metadata（不影響大多數客戶端）
    if debug and "_debug" in final:
        msg["metadata"] = {"trace": final["_debug"]}
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
    }

@app.post("/v1/chat/completions")
async def chat(payload: dict, request: Request):
    # 讀 debug 開關：?debug=1 或 body.debug=true
    qp = request.query_params
    debug = str(qp.get("debug", "")).lower() in ("1","true","yes") or bool(payload.get("debug"))
    try:
        # 你可能只丟第一則 user message；或自行組合
        user_msg = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                user_msg = m.get("content") or ""
                break
        final = run_agent(user_msg, max_calls=4, debug=debug)
        # 若要把 citations/reasoning 也回給前端，可塞進 metadata
        if debug:
            # 保留 citations / reasoning 供除錯
            final.setdefault("_meta", {
                "citations": final.get("citations", []),
                "reasoning": final.get("reasoning", "")
            })
        return JSONResponse(_to_openai_format(final, debug=debug))
    except Exception as e:
        log.exception("chat route failed")
        if debug:
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "traceback": traceback.format_exc()}
            )
        # 非 debug：維持 500，但不洩漏細節
        return JSONResponse(status_code=500, content={"error": "internal_error"})
