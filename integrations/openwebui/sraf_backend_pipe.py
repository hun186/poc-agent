"""Source template; build the standalone OpenWebUI Function with the bundle tool.

OpenWebUI v0.13.4 only, saved owner-private root user text and verified pending
assistant placeholder. No personal tokens, UserValves, raw client identity,
fallback to shared bearer, or automatic retry. Do not import this template as
an OpenWebUI Function directly: it reuses SRAF's canonical signing/transport.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import stat

from pydantic import BaseModel

from api.security.sraf_handoff_assertion import HandoffKey, HandoffTrust
from api.security.sraf_handoff_transport import HandoffTransport, send_signed_chat, probe_handoff_transport


_PIPE_ID = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")
_PIPE_MODEL = "SRA-Structured Retrieval Agent"
_PIPE_VERSION = "0.13.4"


class PipeError(RuntimeError):
    """Fixed error messages only; no user/question/token/path details."""


def _pipe_id(value):
    return type(value) is str and _PIPE_ID.fullmatch(value) is not None


def _pipe_unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError
        result[k] = v
    return result


def _pipe_read(path, limit, *, restricted=False):
    # Only operator-owned regular files. The containing directory must be
    # trusted; no user-supplied path or FIFO/device is accepted.
    if not path.is_file():
        raise ValueError
    with path.open("rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= limit:
            raise ValueError
        if restricted and os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError
        raw = handle.read(limit + 1)
        if not 1 <= len(raw) <= limit:
            raise ValueError
        return raw


def _pipe_relative(root, value):
    if type(value) is not str or not value or value != value.strip() or len(value) > 4096:
        raise ValueError
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve(strict=True)


def _pipe_config(explicit_file=None):
    try:
        configured = os.environ.get("SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE", "")
        if explicit_file is not None and type(explicit_file) is not str:
            raise ValueError
        candidates = [value for value in (configured, explicit_file) if value]
        paths = []
        for value in candidates:
            if (value != value.strip() or len(value) > 4096
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
                raise ValueError
            path = Path(value)
            if not path.is_absolute():
                raise ValueError
            paths.append(path.resolve(strict=True))
        if not paths or any(path != paths[0] for path in paths):
            raise ValueError
        path = paths[0]
        obj = json.loads(_pipe_read(path, 32768).decode("utf-8"), object_pairs_hook=_pipe_unique)
        if type(obj) is not dict or set(obj) != {
            "schema", "issuer", "audience", "key_id", "secret_file", "transport",
        } or obj["schema"] != "sraf_openwebui_sender_v1":
            raise ValueError
        secret = _pipe_read(_pipe_relative(path.parent, obj["secret_file"]), 256,
                            restricted=True).strip()
        if not re.fullmatch(rb"[A-Za-z0-9_-]+", secret):
            raise ValueError
        raw = base64.b64decode(secret + b"=" * (-len(secret) % 4),
                               altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).rstrip(b"=") != secret:
            raise ValueError
        trust = HandoffTrust(obj["issuer"], obj["audience"],
                             (HandoffKey(obj["key_id"], raw),))
        cfg = obj["transport"]
        if type(cfg) is not dict or set(cfg) not in (
            {"mode", "origin", "timeout_seconds"},
            {"mode", "origin", "timeout_seconds", "ca_file"},
        ):
            raise ValueError
        ca = _pipe_relative(path.parent, cfg["ca_file"]) if "ca_file" in cfg else None
        timeout = cfg["timeout_seconds"]
        if type(timeout) is not int or not 10 <= timeout <= 900:
            raise ValueError
        transport = HandoffTransport(cfg["mode"], cfg["origin"], ca, timeout)
        return trust, obj["key_id"], transport
    except Exception:
        raise PipeError("SRAF 後端轉接設定不可用，請管理員檢查。") from None


def _pipe_payload(body, metadata, task, files, tools, user, chat, message):
    # Initial pilot is deliberately one fresh, persisted root text turn.
    # Do not erase system/history/tools/files to force eligibility.
    if (task is not None or files or tools or type(metadata) is not dict
            or type(user) is not dict or not _pipe_id(user.get("id"))
            or not _pipe_id(chat) or not _pipe_id(message)
            or metadata.get("user_id") != user["id"]
            or metadata.get("chat_id") != chat or metadata.get("message_id") != message
            or metadata.get("internal") is True or metadata.get("task") is not None
            or metadata.get("automation_id") or metadata.get("tool_approval_resume")
            or metadata.get("files") or metadata.get("sources")
            or metadata.get("tools") or metadata.get("tool_ids")
            or metadata.get("regeneration_message_id")
            or not _pipe_id(metadata.get("user_message_id"))
            or metadata.get("user_message_id") == message
            or not _pipe_id(metadata.get("model_id"))):
        raise PipeError("SRAF 僅接受可驗證的已儲存使用者文字提問，不處理背景任務。")
    if type(body) is not dict or body.get("stream", False) not in (True, False):
        raise PipeError("SRAF 提問格式不相容。")
    for source in (body, metadata):
        if any(source.get(k) for k in ("files", "sources", "tools", "tool_ids",
                                      "tool_choice", "function_call", "functions",
                                      "response_format", "stop")):
            raise PipeError("SRAF 初版不支援附件、工具或自訂生成控制。")
        features = source.get("features")
        if features is not None and (type(features) is not dict or any(
                v is not False and v is not None for v in features.values())):
            raise PipeError("SRAF 初版不支援附加功能或工具上下文。")
    msgs = body.get("messages")
    if type(msgs) is not list or len(msgs) != 1:
        raise PipeError("SRAF 初版僅支援新對話的單輪文字；不會省略歷史或系統提示。")
    msg = msgs[0]
    if (type(msg) is not dict or set(msg) not in ({"role", "content"}, {"id", "role", "content"})
            or msg.get("role") != "user" or type(msg.get("content")) is not str
            or not msg["content"].strip() or len(msg["content"]) > 65536
            or ("id" in msg and msg["id"] != metadata["user_message_id"])):
        raise PipeError("SRAF 提問必須為單一文字訊息。")
    payload = {"model": _PIPE_MODEL, "messages": [{"role": "user", "content": msg["content"]}],
               "stream": False, "format": "markdown"}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return raw, msg["content"]


async def _pipe_verify_owner(user_id, chat_id, message_id, user_message_id, model_id, text):
    # These exact async APIs were inspected at upstream tag v0.13.4.
    # OpenWebUI backend imports are intentionally deferred until Pipe usage.
    from open_webui.env import VERSION
    from open_webui.models.users import Users
    from open_webui.models.chats import Chats
    from open_webui.models.chat_messages import ChatMessages

    if VERSION != _PIPE_VERSION:
        raise PipeError("SRAF 轉接器尚未驗證此 OpenWebUI 版本。")
    user = await Users.get_user_by_id(user_id)
    chat = await Chats.get_chat_by_id_and_user_id(chat_id, user_id)
    if (user is None or user.id != user_id or user.role not in ("user", "admin")
            or chat is None or chat.id != chat_id or chat.user_id != user_id):
        raise PipeError("SRAF 無法確認登入帳號或聊天所有權。")
    # Direct normalized rows only, not frontend-supplied chat blob metadata.
    first = await ChatMessages.get_message_by_id(f"{chat_id}-{user_message_id}")
    reply = await ChatMessages.get_message_by_id(f"{chat_id}-{message_id}")
    if (first is None or reply is None
            or first.id != f"{chat_id}-{user_message_id}"
            or reply.id != f"{chat_id}-{message_id}"
            or first.chat_id != chat_id or reply.chat_id != chat_id
            or first.user_id != user_id or reply.user_id != user_id
            or first.role != "user" or first.parent_id is not None
            or type(first.content) is not str or first.content != text
            or first.files or first.sources or first.embeds or first.output
            or reply.role != "assistant" or reply.parent_id != user_message_id
            or reply.model_id != model_id or reply.done is not False
            or reply.content not in (None, "") or reply.output or reply.files
            or reply.sources or reply.embeds or reply.error):
        raise PipeError("SRAF 無法確認原始提問與待回覆訊息的資料庫關聯。")


class Pipe:
    class Valves(BaseModel):
        ENABLED: bool = False
        # Admin Valve only: non-secret local path; no user credentials.
        CONFIG_FILE: str = ""

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(self, body: dict, __user__: dict = None,
                   __chat_id__: str = None, __message_id__: str = None,
                   __task__: str = None, __metadata__: dict = None,
                   __files__: list = None, __tools__: dict = None):
        try:
            if self.valves.ENABLED is not True:
                raise PipeError("SRAF 後端轉接尚未由管理員啟用。")
            raw, text = _pipe_payload(body, __metadata__, __task__, __files__,
                                      __tools__, __user__, __chat_id__, __message_id__)
            await _pipe_verify_owner(__user__["id"], __chat_id__, __message_id__,
                __metadata__["user_message_id"], __metadata__["model_id"], text)
            trust, key_id, transport = _pipe_config(self.valves.CONFIG_FILE)
            # No user-provided endpoint/key; exact canonical body and trusted
            # backend identity. A timed-out thread may still finish remotely.
            data = await asyncio.wait_for(asyncio.to_thread(
                send_signed_chat, transport, trust, key_id=key_id,
                external_subject=__user__["id"], chat_id=__chat_id__,
                message_id=__message_id__, body=raw), timeout=transport.timeout_seconds)
            answer = json.loads(data, object_pairs_hook=_pipe_unique)
            if (type(answer) is not dict or answer.get("object") != "chat.completion"
                    or type(answer.get("choices")) is not list or len(answer["choices"]) != 1):
                raise ValueError
            msg = answer["choices"][0]["message"]
            if type(msg) is not dict or msg.get("role") != "assistant" or type(msg.get("content")) is not str:
                raise ValueError
            # The receiver is non-streaming. Return completed real Markdown,
            # not synthetic progress or an invented completion event.
            return msg["content"] if body.get("stream") is True else answer
        except PipeError:
            raise
        except asyncio.TimeoutError:
            raise PipeError("SRAF 請求逾時；後端可能仍在執行，請勿直接重複提交。") from None
        except Exception:
            raise PipeError("SRAF 後端轉接未完成，請確認服務狀態；不會自動重試。") from None



def sender_preflight(argv=None):
    """Run in the sender namespace; no login, Job, provider or OpenWebUI DB IO."""
    parser = argparse.ArgumentParser(description="SRAF sender preflight (partial only)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-config", action="store_true")
    mode.add_argument("--probe-transport", action="store_true")
    parser.add_argument("--config-file", help="operator-selected absolute manifest path")
    args = parser.parse_args(argv)
    result = {"schema": "sraf_openwebui_sender_preflight_v1",
              "scope": "LOCAL_CONFIG_AND_OPTIONAL_READONLY_GET",
              "signed_request_sent": False, "job_created": False,
              "account_mapping": "NOT_TESTED", "live_report": "NOT_TESTED",
              "route_observation": "NOT_TESTED", "transport": "NOT_TESTED"}
    if not args.check_config and not args.probe_transport:
        result.update(status="NOT_TESTED", reason="explicit_operation_required")
    else:
        try:
            _, _, transport = _pipe_config(args.config_file)
            result.update(config="PASS", status="PASS_PARTIAL", reason="local_config_only")
            if args.probe_transport:
                probe_handoff_transport(transport)
                result.update(
                    reason="transport_and_method_observation_only",
                    route_observation="GET_405_ALLOW_POST",
                    transport=("TLS_CA_HOST_VERIFIED" if transport.mode == "verified_https"
                               else "LITERAL_LOOPBACK_HTTP"),
                )
        except PipeError:
            result.update(config="FAIL", status="FAIL", reason="sender_config_invalid")
        except Exception:
            result.update(status="FAIL", reason="sender_transport_or_route_unconfirmed")
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(sender_preflight())
