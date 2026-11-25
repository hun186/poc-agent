"""Explicit private ASGI Chat ingress candidate; no listener is started here.

The existing API app keeps its own lifecycle and authentication. A dedicated
Uvicorn configuration disables proxy header trust and serves only the signed
Chat route. Startup/stop supervision, operator config and live acceptance are
separate gates. Never mount this application on a shared public listener.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import ssl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import uvicorn

from api.security.sraf_handoff_assertion import HandoffDenied, HandoffTrust
from api.security.sraf_handoff_mapping import HandoffSubjectMap
from api.security.sraf_handoff_replay import HandoffReplayStore

_PATH = "/v1/chat/completions"
_LIMIT = 2 * 1024 * 1024
_MODEL = "SRA-Structured Retrieval Agent"


@dataclass(frozen=True, repr=False)
class HandoffListener:
    mode: str
    bind_host: str
    port: int
    cert_file: Path | None = None
    key_file: Path | None = None

    def __post_init__(self):
        if (self.mode not in ("local_http", "verified_https")
                or type(self.bind_host) is not str or "%" in self.bind_host
                or type(self.port) is not int or not 1024 <= self.port <= 65535):
            raise HandoffDenied("handoff_listener_invalid")
        try:
            address = ipaddress.ip_address(self.bind_host)
            if str(address) != self.bind_host:
                raise ValueError
            if self.mode == "local_http":
                if (self.bind_host not in ("127.0.0.1", "::1")
                        or self.cert_file is not None or self.key_file is not None):
                    raise ValueError
            else:
                for path in (self.cert_file, self.key_file):
                    if not isinstance(path, Path) or not path.is_absolute() or not path.is_file():
                        raise ValueError
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(str(self.cert_file), str(self.key_file))
        except (ValueError, OSError, ssl.SSLError):
            raise HandoffDenied("handoff_listener_invalid") from None


def _channel_allowed(request: Request, listener: HandoffListener) -> bool:
    """Only valid under the dedicated no-proxy-header server config.

    Never infer TLS/identity from forwarded headers, Host or a private IP.
    The listener must actually be deployed as configured; ASGI tests alone
    cannot establish that an operator has done so.
    """
    scope = request.scope
    server = scope.get("server")
    if (not isinstance(server, (tuple, list)) or len(server) != 2
            or server[1] != listener.port):
        return False
    if (scope.get("path") != _PATH
            or scope.get("raw_path", _PATH.encode("ascii")) != _PATH.encode("ascii")
            or scope.get("query_string", b"") != b""):
        return False
    if any(name.lower() == b"forwarded" or name.lower().startswith(b"x-forwarded-")
           or name.lower() == b"x-real-ip" for name, _ in scope.get("headers", ())):
        return False
    try:
        actual = ipaddress.ip_address(server[0])
        bound = ipaddress.ip_address(listener.bind_host)
        if not bound.is_unspecified and actual != bound:
            return False
        if listener.mode == "verified_https":
            return scope.get("scheme") == "https"
        return (scope.get("scheme") == "http" and request.client is not None
                and request.client.host in ("127.0.0.1", "::1")
                and ipaddress.ip_address(request.client.host).version == bound.version)
    except (ValueError, TypeError):
        return False


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError
        obj[key] = value
    return obj


def _parse_payload(body: bytes):
    from api.routers.chat_support import ChatPayload
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique)
        if (type(value) is not dict or not set(value) <= {"model", "messages", "stream", "format"}
                or value.get("model", _MODEL) != _MODEL
                or value.get("stream", False) is not False
                or value.get("format", "markdown") != "markdown"):
            raise ValueError
        messages = value["messages"]
        if type(messages) is not list or len(messages) != 1:
            raise ValueError
        msg = messages[0]
        if (type(msg) is not dict or set(msg) != {"role", "content"}
                or msg["role"] != "user" or type(msg["content"]) is not str
                or not 1 <= len(msg["content"]) <= 65536 or not msg["content"].strip()):
            raise ValueError
        return ChatPayload.model_validate(value)
    except Exception:
        raise HandoffDenied("handoff_payload_invalid") from None


def build_private_ingress(main_app: FastAPI, listener: HandoffListener,
                          trust: HandoffTrust, mapping: HandoffSubjectMap,
                          replay: HandoffReplayStore) -> uvicorn.Config:
    """Return a dedicated server config; do not call run/start or mount it.

    Uses the same process-owned state and the actual existing Chat execution,
    never a second app lifespan/Worker. PUBLIC_API_BASE must be explicit so
    private listener Host/address cannot be used for browser capability links.
    """
    from api.core import url_utils
    from api.services.sraf_deep_startup_config import validate_chat_public_base
    from api.routers.chat import execute_handoff_chat
    from api.security.sraf_handoff_chat_context import prepare_handoff_chat

    if (type(listener) is not HandoffListener or type(trust) is not HandoffTrust
            or type(mapping) is not HandoffSubjectMap or type(replay) is not HandoffReplayStore
            or not isinstance(main_app, FastAPI)):
        raise HandoffDenied("handoff_ingress_invalid")
    try:
        public_base = validate_chat_public_base(url_utils.PUBLIC_API_BASE)
    except Exception:
        raise HandoffDenied("handoff_public_base_required") from None
    ingress = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, redirect_slashes=False)
    # Shared app.state only; do not include public API routers or run lifespan.
    ingress.state = main_app.state

    @ingress.post(_PATH)
    async def receive(request: Request):
        if not _channel_allowed(request, listener):
            raise HTTPException(403, "Backend channel denied")
        if (url_utils.PUBLIC_API_BASE.rstrip("/") != public_base
                or getattr(main_app.state, "deep_chat_auto_base_url", None) not in (None, public_base)):
            raise HTTPException(503, "Backend browser configuration unavailable")
        content_types = request.headers.getlist("content-type")
        if (len(content_types) != 1
                or content_types[0].partition(";")[0].strip().lower() != "application/json"
                or request.headers.getlist("content-encoding")):
            raise HTTPException(400, "Backend payload denied")
        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > _LIMIT:
                    raise HTTPException(413, "Backend payload too large")
                body.extend(chunk)
            raw = bytes(body)
            payload = _parse_payload(raw)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Backend payload denied") from None
        try:
            context = await run_in_threadpool(prepare_handoff_chat, trust, mapping, replay,
                headers=tuple(request.scope.get("headers", ())), body=raw,
                method=request.method, path=request.scope["path"],
                query_string=request.scope.get("query_string", b""))
        except Exception:
            raise HTTPException(401, "Backend assertion denied") from None
        try:
            result = await run_in_threadpool(execute_handoff_chat, payload, request, context, mapping)
        except HandoffDenied:
            raise HTTPException(403, "Backend account denied") from None
        except HTTPException as exc:
            code = exc.status_code if exc.status_code in (400, 401, 403, 429, 503) else 503
            raise HTTPException(code, "Backend chat unavailable") from None
        except Exception:
            raise HTTPException(503, "Backend chat unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store",
                                             "Referrer-Policy": "no-referrer"})

    return uvicorn.Config(
        ingress, host=listener.bind_host, port=listener.port,
        proxy_headers=False, forwarded_allow_ips="", lifespan="off", access_log=False,
        ssl_certfile=str(listener.cert_file) if listener.cert_file else None,
        ssl_keyfile=str(listener.key_file) if listener.key_file else None,
    )
