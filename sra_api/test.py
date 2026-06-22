from fastapi import Query

@app.get("/v1/chat/completions")
def chat_completions_get(q: str = Query(..., description="Your question")):
    out = agent.run(q)
    text = out.get("answer") if isinstance(out, dict) else str(out)
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "table-rag-agent",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }