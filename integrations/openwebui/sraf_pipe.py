"""
title: SRAF authenticated dual-track report
author: SRAF
version: 0.1.0
requirements: httpx
description: Personal SRAF bearer; scoped chat and stable turn identity; no shared key.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import ssl
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

_PROTOCOL = "sraf-openwebui-scoped-chat-v1"
_MODEL = "SRA-Structured Retrieval Agent"
_ID = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
_MAX_RESPONSE = 8 * 1024 * 1024


class AdapterError(RuntimeError):
    """Only fixed, non-secret error messages may leave this Pipe."""


def _endpoint(value: str) -> str:
    if (type(value) is not str or len(value) > 512
            or not re.fullmatch(
                r"https://(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::[0-9]{1,5})?(?:/[A-Za-z0-9_-]+)*/?",
                value)):
        raise AdapterError("SRAF 轉接器需要管理員設定有效 HTTPS API 網址。")
    try:
        parts = urlsplit(value)
        if not parts.hostname or ".." in parts.hostname or parts.hostname.startswith(".") or parts.hostname.endswith("."):
            raise ValueError
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise ValueError
    except ValueError:
        raise AdapterError("SRAF 轉接器網址無效。") from None
    return value.rstrip("/")


def _messages(body):
    raw = body.get("messages") if type(body) is dict else None
    if type(raw) is not list or not 1 <= len(raw) <= 128:
        raise AdapterError("SRAF 轉接器僅支援有界文字對話。")
    result = []
    total = 0
    for msg in raw:
        if (type(msg) is not dict or msg.get("role") not in ("user", "assistant", "system")
                or type(msg.get("content")) is not str or msg.get("tool_calls")
                or msg.get("function_call")):
            raise AdapterError("SRAF 轉接器不支援多媒體或工具呼叫訊息。")
        total += len(msg["content"])
        if total > 262144:
            raise AdapterError("SRAF 轉接器的文字對話超出上限。")
        result.append({"role": msg["role"], "content": msg["content"]})
    if not any(m["role"] == "user" for m in result):
        raise AdapterError("SRAF 轉接器需要使用者文字訊息。")
    return result


def _valid_id(value) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def _turn_key(chat_id: str, message_id: str) -> str:
    # Use OpenWebUI's assistant message ID, NOT the chat ID alone or prompt
    # text. Retries of the same ID must reproduce the same idempotency key.
    return "owui-v1-" + hashlib.sha256(
        json.dumps([chat_id, message_id], separators=(",", ":")).encode()
    ).hexdigest()


async def _bounded_json(client, method, url, *, headers, payload=None, limit):
    kwargs = {"headers": headers}
    if payload is not None:
        kwargs["json"] = payload
    async with client.stream(method, url, **kwargs) as response:
        if response.status_code in (401, 403):
            raise AdapterError("SRAF 個人授權無效或權限不足；請重新登入 SRAF 並更新個人授權。")
        if response.status_code != 200:
            raise AdapterError("SRAF 服務未接受請求；請確認服務版本、設定及狀態。")
        chunks = bytearray()
        async for block in response.aiter_bytes(chunk_size=65536):
            if len(chunks) + len(block) > limit:
                raise AdapterError("SRAF 回覆超出轉接器上限。")
            chunks.extend(block)
    return json.loads(chunks)


class Pipe:
    class Valves(BaseModel):
        ENABLED: bool = False
        SRAF_API_ROOT: str = Field(default="", description="HTTPS SRAF root, not /v1")
        SRAF_CA_FILE: str = Field(default="", description="Optional administrator-managed PEM CA file")
        TOTAL_TIMEOUT_SECONDS: int = Field(default=300, ge=10, le=900)

    class UserValves(BaseModel):
        SRAF_ACCESS_TOKEN: str = Field(
            default="", repr=False, max_length=4096,
            description="Personal short-lived SRAF access token, not a password or shared key",
            json_schema_extra={"input": {"type": "password"}},
        )

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(self, body: dict, __user__: dict = None,
                   __chat_id__: str = None, __message_id__: str = None,
                   __task__: str = None, __metadata__: dict = None):
        try:
            if not self.valves.ENABLED:
                raise AdapterError("SRAF 轉接器尚未由管理員啟用。")
            # Masked input is NOT encryption. Require the supported OpenWebUI
            # encryption configuration before using any stored personal token.
            if (os.getenv("ENABLE_VALVE_ENCRYPTION", "").lower() != "true"
                    or len(os.getenv("WEBUI_SECRET_KEY", "")) < 32):
                raise AdapterError("SRAF 轉接器要求先完成 OpenWebUI 個人設定加密。")
            root = _endpoint(self.valves.SRAF_API_ROOT)
            valves = __user__.get("valves") if type(__user__) is dict else None
            token = (valves.SRAF_ACCESS_TOKEN if isinstance(valves, self.UserValves)
                     else valves.get("SRAF_ACCESS_TOKEN") if type(valves) is dict else None)
            if (type(token) is not str or not 1 <= len(token) <= 4096
                    or not _TOKEN.fullmatch(token)):
                raise AdapterError("請在個人設定填入有效 SRAF access token；不要在對話中貼上憑證。")
            if not _valid_id(__chat_id__):
                raise AdapterError("缺少有效 OpenWebUI 聊天識別碼；不會退回共用 session。")
            if (type(__metadata__) is dict and (__metadata__.get("files")
                    or __metadata__.get("sources") or __metadata__.get("tools"))
                    or type(body) is dict and (body.get("files") or body.get("tools"))):
                raise AdapterError("SRAF 轉接器目前不接受附加檔案、來源或工具。")
            messages = _messages(body)
            headers = {"Authorization": "Bearer " + token,
                       "Accept": "application/json",
                       "X-SRAF-OpenWebUI-Chat-Id": __chat_id__}
            # Only a fresh text turn can request auto dispatch. Do not
            # remove preceding system/history messages to force eligibility.
            # Internal OpenWebUI task calls never receive the idempotency key.
            meta_task = __task__ is not None or (type(__metadata__) is dict
                                                 and __metadata__.get("task") is not None)
            if not meta_task and _valid_id(__message_id__) and len(messages) == 1 and messages[0]["role"] == "user":
                headers["Idempotency-Key"] = _turn_key(__chat_id__, __message_id__)
            tls = ssl.create_default_context(cafile=self.valves.SRAF_CA_FILE or None)
            payload = {"model": _MODEL, "messages": messages, "stream": False, "format": "markdown"}

            async def run():
                async with httpx.AsyncClient(
                    verify=tls, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(self.valves.TOTAL_TIMEOUT_SECONDS, connect=10.0),
                ) as client:
                    # Do not send the question to an older API that ignores
                    # the scoped-chat header. Probe only the fixed origin.
                    info = await _bounded_json(
                        client, "GET", root + "/v1/sraf/openwebui/capabilities",
                        headers={"Authorization": headers["Authorization"], "Accept": "application/json"},
                        limit=16384,
                    )
                    if info != {"protocol": _PROTOCOL}:
                        raise AdapterError("SRAF 版本不支援帳號隔離轉接協定。")
                    return await _bounded_json(
                        client, "POST", root + "/v1/chat/completions",
                        headers=headers, payload=payload, limit=_MAX_RESPONSE,
                    )
            answer = await asyncio.wait_for(run(), timeout=self.valves.TOTAL_TIMEOUT_SECONDS)
            if (type(answer) is not dict or answer.get("object") != "chat.completion"
                    or type(answer.get("choices")) is not list or len(answer["choices"]) != 1):
                raise AdapterError("SRAF 回覆格式不相容。")
            message = answer["choices"][0]["message"]
            content = message["content"]
            if type(content) is not str or message.get("role") != "assistant":
                raise AdapterError("SRAF 回覆格式不相容。")
            # SRAF is non-streaming. For streaming OpenWebUI callers, return
            # one actual completed Markdown string; never invent progress SSE.
            return content if body.get("stream") is True else answer
        except AdapterError:
            raise
        except Exception:
            # No upstream bodies, request dumps, exceptions, credentials or
            # prompt contents in the UI; no automatic retry or fallback key.
            raise AdapterError("SRAF 轉接器請求失敗或逾時；請確認服務狀態後再試。") from None
