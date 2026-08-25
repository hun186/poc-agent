# agent/llm_utils/ollama_client.py

import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, Dict, List, Any

import requests

logger = logging.getLogger(__name__)

class LLMClient:
    """
    簡單的 LLM 呼叫客戶端，支援：
    - /api/chat  多輪對話格式（推薦）
    - /api/generate 單一 prompt 格式（相容用）

    base_url 可以是：
    - http://host:11434
    - http://host:11434/api/chat
    - http://host:11434/api/generate
    都會自動判斷。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        self.base_url = (base_url or os.getenv("MODEL_BASE_URL") or "").rstrip("/")
        self.model = model or os.getenv("MODEL_ID", "gpt-oss:latest-32k")
        self.timeout = timeout

    # ===== URL helpers =====
    def _get_chat_url(self) -> str:
        """
        若 base_url 已經是 /api/chat 或 /api/generate 就直接用；
        否則預設補成 /api/chat。
        """
        if self.base_url.endswith("/api/chat") or self.base_url.endswith("/api/generate"):
            return self.base_url
        return self.base_url + "/api/chat"

    def _get_generate_url(self) -> str:
        if self.base_url.endswith("/api/generate") or self.base_url.endswith("/api/chat"):
            return self.base_url
        return self.base_url + "/api/generate"

    # ===== /api/chat：多輪對話 =====
    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        stream: bool = False,
        extra_params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,   # ★ 新增
    ) -> str:
        """
        使用 /api/chat，多輪對話格式：
        messages: [{"role": "system"|"user"|"assistant", "content": "..."}]

        回傳整段 assistant content（非串流）。
        base_url 沒設定時，直接回空字串。
        """
        if not messages:
            return ""
        if not self.base_url:
            return ""

        url = self._get_chat_url()
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,  # 這個 helper 先固定用非串流
        }
        if extra_params:
            payload.update(extra_params)

        resp = requests.post(url, json=payload, timeout=timeout or self.timeout)
        resp.raise_for_status()
        data = resp.json()

        # Ollama /api/chat 非串流回應格式通常為：
        # {
        #   "model": "...",
        #   "created_at": "...",
        #   "message": {"role": "assistant", "content": "......"},
        #   "done": true,
        #   ...
        # }
        if isinstance(data, dict):
            msg = data.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content

            # 若有其他欄位名稱，也順便試一下
            for key in ("response", "result", "text"):
                if isinstance(data.get(key), str):
                    return data[key]

        # 萬一格式很怪，就回空字串
        return ""

    # ===== /api/generate：舊版單一 prompt =====
    def generate(
        self,
        prompt: str,
        *,
        stream: bool = False,
        extra_params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,   # ★ 新增
    ) -> str:
        """
        傳統 /api/generate 單一 prompt 介面。
        主要是相容用，如果未來全部改用 chat，可以慢慢汰除它。
        """
        prompt = (prompt or "").strip()
        if not prompt:
            return ""
        if not self.base_url:
            return ""

        url = self._get_generate_url()
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if extra_params:
            payload.update(extra_params)

        resp = requests.post(url, json=payload, timeout=timeout or self.timeout)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict):
            for key in ("response", "result", "text"):
                if isinstance(data.get(key), str):
                    return data[key]
        elif isinstance(data, str):
            return data

        return ""


# ---- 全域 singleton ＋ 簡易 wrapper ----

_default_client: Optional[LLMClient] = None


def get_default_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def call_llm(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    model: Optional[str] = None,       # ★ 新增：可選 model 覆寫
    include_current_time: bool = False,
    current_time_context_reason: Optional[str] = None,
) -> str:
    """
    最建議使用的入口：
    - 內部自動組成 /api/chat 的 messages
    - 有需要才另外傳 system_prompt
    - 目前時間預設不注入；只有需要解析相對日期的呼叫端才明確啟用
    """
    #raise RuntimeError("### call_llm WAS CALLED ###")
    prompt = (prompt or "").strip()
    if not prompt:
        return ""

    # ==== 精簡版 debug log（不再印全文） ====
    debug = os.getenv("DEBUG_CALL_LLM", "1") == "1"   # 想完全關掉就設成 0
    if debug:
        sp = (system_prompt or "").replace("\n", " ")
        up = prompt.replace("\n", " ")
        print("=" * 50)
        print(
            "[call_llm] "
            f"sys_len={len(system_prompt or '')}, "
            f"user_len={len(prompt)}, "
            f"user_preview={up[:500]!r}"
        )
        # 如果你想看一點 system_prompt 也可以加（不建議印太多）
        print(f"[call_llm] system_preview={sp[:400]!r}")

    client = get_default_client()

    messages: List[Dict[str, str]] = []
    effective_system_prompt = system_prompt or ""
    if include_current_time:
        timezone_name = (os.getenv("LLM_CURRENT_TIMEZONE") or "Asia/Taipei").strip()
        try:
            now = datetime.now(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            timezone_name = "UTC"
            now = datetime.now(ZoneInfo("UTC"))
        logger.warning(
            "[call_llm] current-time system context enabled; "
            "reason=%s timezone=%s reference_time=%s output_may_change=true",
            (current_time_context_reason or "unspecified").strip() or "unspecified",
            timezone_name,
            now.isoformat(timespec="seconds"),
        )
        time_context = (
            "【系統時間參考】目前時間為 "
            f"{now.isoformat(timespec='seconds')}（{timezone_name}）。"
            "此資訊僅供解讀『本週』、『上週』等相對日期；"
            "不要把它視為使用者輸入的一部分，也不要在與日期無關的回答中主動提及。"
        )
        effective_system_prompt = "\n\n".join(
            part for part in (effective_system_prompt, time_context) if part
        )
    if effective_system_prompt:
        messages.append({"role": "system", "content": effective_system_prompt})
    messages.append({"role": "user", "content": prompt})

    
    # ★ 整理實際要傳給 Ollama 的參數，確保不動到呼叫端的 dict
    params: Dict[str, Any] = {}
    if extra_params:
        params.update(extra_params)
    if model is not None:
        # 這裡覆寫 payload["model"]，優先權高於 LLMClient 自己的 self.model
        params["model"] = model

    try:
        return client.chat(
            messages,
            extra_params=params,
            timeout=timeout,
        )
    except Exception as e:
        print(f"[LLMClient] chat 呼叫失敗：{e}")
        return ""
