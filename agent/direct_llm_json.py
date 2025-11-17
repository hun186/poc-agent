# agent/direct_llm_json.py
import os, json, re
import requests
from typing import List, Dict, Any, Optional

def _extract_json(text: str) -> Any:
    """從 LLM 輸出裡穩健擷取第一個 JSON（去除 ```、前後雜訊）。"""
    if not isinstance(text, str):
        raise ValueError("LLM output is not a string")

    s = text.strip()

    # 去除常見包裹
    s = s.replace("```json", "```").strip()
    if s.startswith("```") and s.endswith("```"):
        s = s[3:-3].strip()

    # 直讀：若本身就是合法 JSON
    try:
        return json.loads(s)
    except Exception:
        pass

    # 從全文擷取第一段 {...} 或 [...]
    brace = re.search(r'\{.*\}', s, re.S)
    bracket = re.search(r'\[.*\]', s, re.S)
    cand = None
    if brace and bracket:
        cand = brace.group(0) if brace.start() < bracket.start() else bracket.group(0)
    else:
        cand = (brace.group(0) if brace else None) or (bracket.group(0) if bracket else None)

    if not cand:
        # 嘗試清掉前後雜訊後再 parse
        raise ValueError("No JSON object/array found in model output")

    # 簡單修補：移除結尾多餘逗號
    cand = re.sub(r',\s*([}\]])', r'\1', cand)

    return json.loads(cand)


class OpenAIStyleOllama:
    """最小兼容器：用 OpenAI messages 風格呼叫 Ollama /api/chat。"""
    def __init__(self,
                 base_url: Optional[str] = None,
                 model: Optional[str] = None,
                 temperature: float = 0.0,
                 timeout: float = 120.0):
        self.base_url = (base_url or os.getenv("MODEL_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.model = model or os.getenv("MODEL_ID") or "llama3.1"
        self.temperature = float(os.getenv("MODEL_TEMPERATURE") or temperature)
        self.timeout = timeout

    def chat(self, messages: List[Dict[str, str]], **options) -> str:
        """
        messages: [{"role":"system/user/assistant", "content":"..."}]
        return: assistant content (string)
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                # 你也可在這裡加 max_tokens、num_ctx 等 Ollama 選項
            }
        }
        # 合併自訂 options（如 num_ctx=32768）
        if options:
            payload["options"].update(options)

        r = requests.post(url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        # Ollama 回傳形如：{"message":{"role":"assistant","content":"..."}}
        msg = (data or {}).get("message", {})
        return msg.get("content", "")  # 取出回答純文字

    # ---------- 嚴格 JSON 任務的 helper ----------

    def generate_json(self,
                      system_prompt: str,
                      user_prompt: str,
                      schema_hint: str = "",
                      max_tries: int = 2,
                      **options) -> Any:
        """
        要求模型「只回傳單一 JSON」，並嘗試解析；失敗時自動重試一次。
        schema_hint: 可放 JSON 範例鍵值說明，幫助模型對齊。
        """
        sys = (
            "You are a JSON-only generator. "
            "Output ONE single raw JSON object or array. "
            "No code fences, no explanations, no extra text."
        )
        if system_prompt:
            sys = system_prompt + "\n\n" + sys

        # 在最後再補一次硬規則
        user = (
            user_prompt.strip() + "\n\n"
            "Constraints:\n"
            "- Return ONLY a single raw JSON object/array.\n"
            "- Do NOT include markdown/code fences.\n"
        )
        if schema_hint:
            user += f"- Schema hint: {schema_hint}\n"

        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": user}
        ]

        last_err = None
        for _ in range(max_tries):
            out_text = self.chat(messages, **options)
            try:
                return _extract_json(out_text)
            except Exception as e:
                last_err = e
                # 強化提示，重試
                messages.append({"role": "assistant", "content": out_text})
                messages.append({"role": "user", "content": "Return only JSON. Remove all extra text and retry."})
        raise ValueError(f"Failed to parse JSON from model output. Last error: {last_err}")


# ---------------- 這裡放幾個現成的任務包裝 ----------------

def task_tags(llm: OpenAIStyleOllama, chat_history: str) -> Dict[str, Any]:
    system = "你是一個分類助手，負責為對話加上 1-3 個高層主題標籤與 1-3 個子題標籤。語言與對話一致。"
    user = (
        "根據以下對話歷史，輸出：{ \"tags\": [\"主題1\", \"主題2\", ...] }。\n"
        "規則：\n"
        "- 先高層（如 科學、科技、政治、商業、健康、教育、娛樂），再視需要加入子領域（如 公共衛生、AI、金融法規）。\n"
        "- 若內容過少或太分散，僅輸出 [\"General\"]。\n"
        f"<chat_history>\n{chat_history}\n</chat_history>"
    )
    schema = '{ "tags": ["..."] }'
    return llm.generate_json(system, user, schema_hint=schema)

def task_title(llm: OpenAIStyleOllama, chat_history: str) -> Dict[str, Any]:
    system = "你是對話命名助手。"
    user = (
        "產出 3-5 字的標題（含一個合適的 emoji），語言與對話一致。"
        "僅輸出：{ \"title\": \"...\" }。\n"
        "避免引號、過度創意。\n"
        f"<chat_history>\n{chat_history}\n</chat_history>"
    )
    schema = '{ "title": "..." }'
    return llm.generate_json(system, user, schema_hint=schema)

def task_followups(llm: OpenAIStyleOllama, chat_history: str) -> Dict[str, Any]:
    system = "你是對話續問建議助手。"
    user = (
        "從使用者視角，提出 3-5 個**不重複**且緊扣主題的後續問題，語言與對話一致。"
        "僅輸出：{ \"follow_ups\": [\"問題1\", \"問題2\", ...] }。\n"
        f"<chat_history>\n{chat_history}\n</chat_history>"
    )
    schema = '{ "follow_ups": ["..."] }'
    return llm.generate_json(system, user, schema_hint=schema)
