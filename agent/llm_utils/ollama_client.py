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

    def generate(
        self,
        prompt: str,
        *,
        stream: bool = False,
        extra_params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Call the ordinary production Ollama-compatible generate endpoint."""
        prompt = (prompt or "").strip()
        if not prompt or not self.base_url:
            return ""
        payload: Dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if extra_params:
            payload.update(extra_params)
        resp = requests.post(self._get_generate_url(), json=payload, timeout=timeout or self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            for key in ("response", "result", "text"):
                if isinstance(data.get(key), str):
                    return data[key]
        return data if isinstance(data, str) else ""


class DeterministicE2ELLMClient:
    """External-boundary replacement; orchestration and report code stay real."""

    def chat(self, messages, **kwargs) -> str:
        import json
        system = "\n".join(str(item.get("content") or "") for item in messages if item.get("role") == "system")
        prompt = "\n".join(str(item.get("content") or "") for item in messages if item.get("role") == "user")
        if "任務分類器" in system:
            topic = "mil_intel" if any(term in prompt for term in ("臺灣海峽", "灰色地帶", "美中戰略", "印太")) else "news_general"
            return json.dumps({"mode": "SRA_REPORT", "reason": "Requirement evidence report", "topic": topic}, ensure_ascii=False)
        if "問句精煉器" in system:
            question = prompt.split("【使用者問句】", 1)[-1].strip()
            return json.dumps({"refined_question": question}, ensure_ascii=False)
        if "欄位選擇器" in system:
            return json.dumps({"fields": ["ref_no", "note", "d", "title"]}, ensure_ascii=False)
        if "通用查詢關鍵字萃取器" in system:
            if any(term in prompt for term in ("加薩", "Gaza")):
                terms = ["加薩", "停火", "人質", "人道援助"]
            elif any(term in prompt for term in ("臺灣海峽", "台灣海峽", "灰色地帶")):
                terms = ["臺灣海峽", "灰色地帶", "軍機", "海警"]
            elif any(term in prompt for term in ("美中戰略", "印太", "US-China")):
                terms = ["美中戰略競爭", "印太", "美軍"]
            else:
                terms = []
            return json.dumps(terms, ensure_ascii=False)
        if "文本檢索查詢關鍵詞同義詞擴充器" in system:
            return "{}"
        try:
            payload = json.loads(prompt)
        except (TypeError, ValueError):
            payload = None
        if ("資料驅動的分析助手" in system and isinstance(payload, dict)
                and isinstance(payload.get("ev"), list)):
            evidence = payload["ev"]
            lines = ["# 情勢研析報告", "", "## 證據摘要"]
            for item in evidence:
                title = str(item.get("title") or "來源")
                note = str(item.get("note") or "").strip()
                ref = item.get("ref_no") or item.get("id") or ""
                if note:
                    lines.append(f"- {title}：{note}（參考 {ref}）")
            lines.extend(["", "## 綜合研判", "以上研判僅依據列示證據，未加入外部事實。"])
            return "\n".join(lines)
        raise RuntimeError("unsupported_e2e_llm_contract")


# ---- 全域 singleton ＋ 簡易 wrapper ----

_default_client: Optional[LLMClient | DeterministicE2ELLMClient] = None


def get_default_client() -> LLMClient | DeterministicE2ELLMClient:
    global _default_client
    from agent.external_capabilities import (
        frozen_plan, requirement_acceptance_active, resolve_environment_plan,
    )
    plan = frozen_plan(resolve_environment_plan)
    if (requirement_acceptance_active() and plan is not None
            and plan.llm_backend == "semantic_mock"):
        # Semantic LLM replacement is only valid inside a verified E2E test job.
        # Do not cache it into the production singleton.
        return DeterministicE2ELLMClient()
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def reset_default_client_for_tests() -> None:
    """Reset the process singleton only for isolated backend-selection tests."""
    global _default_client
    _default_client = None


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
            "此資訊僅供解讀『今天』、『本週』、『上週』、『今年』、『去年』等相對日期；"
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
        from agent.external_capabilities import frozen_plan, requirement_acceptance_active
        plan = frozen_plan()
        if (requirement_acceptance_active() and plan is not None
                and plan.llm_backend == "live"):
            raise RuntimeError("e2e_live_llm_runtime_failure") from e
        # Production execution must never silently downgrade to an E2E mock or
        # convert a real LLM transport failure into an apparently successful
        # empty response.
        raise RuntimeError("llm_runtime_failure") from e
