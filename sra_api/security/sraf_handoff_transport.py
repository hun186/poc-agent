"""Private backend sender with an explicitly selected transport.

Not a mounted route, a proxy trust decision, or an OpenWebUI integration.
Local HTTP is restricted to a literal loopback in a trusted network namespace.
Remote traffic requires direct HTTPS with hostname and CA verification.
No HTTP proxy, redirects, fallback, automatic retries, or user-controlled URL.
"""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
from pathlib import Path
import re
import ssl
from urllib.parse import urlsplit

from api.security.sraf_handoff_assertion import (
    HandoffDenied, HandoffTrust, sign_chat_assertion,
)

_CHAT_PATH = "/v1/chat/completions"
_HEADER = "X-SRAF-Backend-Assertion"
_DNS = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z")
_MAX_RESPONSE = 8 * 1024 * 1024


@dataclass(frozen=True, repr=False)
class HandoffTransport:
    mode: str
    origin: str
    ca_file: Path | None = None
    timeout_seconds: int = 300

    def __post_init__(self):
        if (self.mode not in ("local_http", "verified_https")
                or type(self.origin) is not str or not 1 <= len(self.origin) <= 512
                or any(ord(c) < 33 or ord(c) >= 127 for c in self.origin)
                or any(c in self.origin for c in ("?", "#", "%", "\\"))
                or type(self.timeout_seconds) is not int
                or not 1 <= self.timeout_seconds <= 900):
            raise HandoffDenied("handoff_transport_invalid")
        try:
            parsed = urlsplit(self.origin)
            if (parsed.username is not None or parsed.password is not None
                    or parsed.path not in ("", "/") or not parsed.hostname
                    or parsed.port == 0 or parsed.netloc.endswith(":")):
                raise ValueError
            host = parsed.hostname
            address = None
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if (not _DNS.fullmatch(host) or ".." in host
                        or any(len(label) > 63 or label.startswith("-") or label.endswith("-")
                               for label in host.split("."))):
                    raise ValueError
            if self.mode == "local_http":
                # No DNS alias, host mapping, RFC1918 subnet or IPv4-mapped
                # IPv6 exception. Operator must independently attest the
                # listener and trusted local network namespace.
                if (parsed.scheme != "http" or address is None
                        or host not in ("127.0.0.1", "::1") or self.ca_file is not None):
                    raise ValueError
            elif parsed.scheme != "https":
                raise ValueError
            if self.ca_file is not None:
                if not isinstance(self.ca_file, Path) or not self.ca_file.is_absolute() or not self.ca_file.is_file():
                    raise ValueError
            port = parsed.port or (443 if self.mode == "verified_https" else 80)
            authority = f"[{host}]" if ":" in host else host
            object.__setattr__(self, "origin", f"{parsed.scheme}://{authority}:{port}")
        except (ValueError, OSError):
            raise HandoffDenied("handoff_transport_invalid") from None


def _direct_connection(transport: HandoffTransport, timeout: int):
    if type(transport) is not HandoffTransport:
        raise HandoffDenied("handoff_transport_invalid")
    parts = urlsplit(transport.origin)
    if transport.mode == "verified_https":
        context = ssl.create_default_context(
            cafile=str(transport.ca_file) if transport.ca_file else None)
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise HandoffDenied("handoff_transport_invalid")
        return http.client.HTTPSConnection(parts.hostname, parts.port,
                                           timeout=timeout, context=context)
    return http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)


def probe_handoff_transport(transport: HandoffTransport) -> None:
    """Read-only GET to configured Chat path; no assertion or prompt is sent.

    Matching 405/Allow: POST is only a route/transport observation, not proof
    of private listener identity beyond TLS, authentication, or authorization.
    The same observation may occur on the ordinary API.
    """
    connection = None
    try:
        connection = _direct_connection(transport, 5)
        connection.request("GET", _CHAT_PATH, headers={
            "Accept": "application/json", "Connection": "close",
        })
        # HTTPResponse can own the underlying socket after HTTPConnection
        # detaches it on Connection: close. Close it even for an unread body
        # or rejected status, including when an exception retains the frame.
        with connection.getresponse() as response:
            methods = {part.strip().upper()
                       for part in (response.getheader("Allow") or "").split(",")}
            if response.status != 405 or methods != {"POST"}:
                raise HandoffDenied("handoff_probe_route_unconfirmed")
            # Do not need or expose the response body.
    except HandoffDenied:
        raise
    except Exception:
        raise HandoffDenied("handoff_probe_transport_unavailable") from None
    finally:
        if connection is not None:
            connection.close()


def send_signed_chat(transport: HandoffTransport, trust: HandoffTrust, *,
                     key_id: str, external_subject: str, chat_id: str,
                     message_id: str, body: bytes) -> bytes:
    """Send the exact signed bytes to one operator-configured origin.

    Uses a fresh direct connection, no environment proxies or redirects.
    Timeout is socket inactivity, not an end-to-end execution deadline.
    A caller must separately impose its own request lifecycle/deadline.
    Response is bounded raw JSON bytes, not verified report completion.
    """
    if type(transport) is not HandoffTransport:
        raise HandoffDenied("handoff_transport_invalid")
    connection = None
    try:
        connection = _direct_connection(transport, transport.timeout_seconds)
        assertion = sign_chat_assertion(trust, key_id=key_id,
                                        external_subject=external_subject, chat_id=chat_id,
                                        message_id=message_id, body=body)
        connection.request("POST", _CHAT_PATH, body=body, headers={
            "Content-Type": "application/json", "Accept": "application/json",
            _HEADER: assertion, "Connection": "close",
        })
        # Explicitly release the response-owned socket on rejection, read
        # failure, or success. connection.close() alone is insufficient
        # when getresponse() detached a Connection: close socket.
        with connection.getresponse() as response:
            if (response.status != 200
                    or (response.getheader("Content-Type") or "").partition(";")[0].strip().lower()
                        != "application/json"):
                raise HandoffDenied("handoff_transport_rejected")
            data = response.read(_MAX_RESPONSE + 1)
            if not data or len(data) > _MAX_RESPONSE:
                raise HandoffDenied("handoff_transport_response_invalid")
            return data
    except HandoffDenied:
        raise
    except Exception:
        raise HandoffDenied("handoff_transport_unavailable") from None
    finally:
        if connection is not None:
            connection.close()
