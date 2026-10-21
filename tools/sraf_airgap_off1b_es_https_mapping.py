"""OFF-1B reviewed, strictly bounded Elasticsearch HTTPS/mapping diagnosis.

This is an operator-only, read-only diagnostic; it does NOT certify FULL_LIVE.
Never import the runtime ES client: it currently disables TLS hostname checks.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path
import re
import secrets
import socket
import ssl
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off1b_auto import (  # noqa: E402
    MODE, _effective_runtime_config, _parse_endpoint,
)
from agent.external_capabilities import mapping_compatibility  # noqa: E402

SCHEMA = "sraf_airgap_off1b_es_https_mapping_v1"
DEADLINE_SECONDS = 3.0
MAX_HEADERS = 8192
MAX_BODY = 65536
MAX_CA_BYTES = 1048576
_INDEX_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,254}\Z", re.ASCII)
_FIELD_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")


def _configured_index(value: str | None) -> str | None:
    """Exactly one literal index/alias, never wildcard, comma or URL control."""
    if not value or value != value.strip():
        return None
    if not _INDEX_RE.fullmatch(value) or value in (".", ".."):
        return None
    return value


def _trusted_ca_file(root: Path) -> Path | None:
    """Use only the existing fixed repository ES CA location, no override."""
    try:
        ca = root / "agent" / "certs" / "http_ca.crt"
        if ca.is_symlink() or not ca.is_file():
            return None
        if not 1 <= ca.stat().st_size <= MAX_CA_BYTES:
            return None
        return ca
    except OSError:
        return None


async def _one_https_get(host: str, port: int, path: str,
                         username: str, password: str,
                         context: ssl.SSLContext) -> tuple[int, bytes]:
    """One TLS-validated private numeric IPv4 GET, no redirects/proxy/DNS.

    Outer wait_for enforces one absolute deadline, even for a slow-dripping
    server. Never return raw response headers, exception details or credentials.
    """
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    writer = None
    try:
        await loop.sock_connect(sock, (host, port))
        reader, writer = await asyncio.open_connection(
            sock=sock, ssl=context, server_hostname=host,
            ssl_handshake_timeout=DEADLINE_SECONDS,
            limit=MAX_HEADERS,
        )
        credential = base64.b64encode(
            (username + ":" + password).encode("utf-8")
        ).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            f"Accept: application/json\r\n"
            f"Authorization: Basic {credential}\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        header = await reader.readuntil(b"\r\n\r\n")
        if len(header) > MAX_HEADERS or b"\n" in header.replace(b"\r\n", b""):
            raise ValueError("invalid_http_headers")
        parts = header[:-4].split(b"\r\n")
        match = re.fullmatch(rb"HTTP/1\.[01] ([1-5][0-9]{2}) [\t\x20-\x7e\x80-\xff]*", parts[0])
        if match is None:
            raise ValueError("invalid_http_status")
        status = int(match.group(1))
        lengths: list[int] = []
        for part in parts[1:]:
            if b":" not in part:
                raise ValueError("malformed_http_field")
            name, value = part.split(b":", 1)
            if _FIELD_NAME.fullmatch(name) is None:
                raise ValueError("malformed_http_field")
            if any(ch < 32 and ch not in (9,) for ch in value) or b"\x7f" in value:
                raise ValueError("malformed_http_value")
            lower = name.lower()
            if lower == b"transfer-encoding":
                # Fail closed on unsupported transfer coding, never parse blindly.
                raise ValueError("unsupported_http_framing")
            if lower == b"content-length":
                trimmed = value.strip(b" \t")
                if re.fullmatch(rb"[0-9]{1,10}", trimmed) is None:
                    raise ValueError("invalid_http_length")
                lengths.append(int(trimmed))
        if len(lengths) != 1 or lengths[0] > MAX_BODY:
            raise ValueError("missing_or_oversized_http_body")
        return status, await reader.readexactly(lengths[0])
    finally:
        if writer is not None:
            writer.close()
        else:
            sock.close()


def _https_get(host: str, port: int, path: str,
               username: str, password: str, ca: Path
               ) -> tuple[int | None, bytes | None, str]:
    """Report stable non-secret reasons, never raw transport exceptions."""
    try:
        ctx = ssl.create_default_context(cafile=str(ca))
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
    except (OSError, ssl.SSLError, ValueError):
        return None, None, "es_ca_invalid"
    try:
        code, body = asyncio.run(asyncio.wait_for(
            _one_https_get(host, port, path, username, password, ctx),
            timeout=DEADLINE_SECONDS,
        ))
        return code, body, "https_response_received"
    except ssl.SSLCertVerificationError:
        return None, None, "es_tls_identity_unverified"
    except (TimeoutError, OSError, ssl.SSLError, ValueError,
            asyncio.IncompleteReadError, asyncio.LimitOverrunError,
            RuntimeError):
        return None, None, "es_https_transport_unavailable"


def _mapping_containers_valid(mappings: dict[str, object]) -> bool:
    """Validate only Mapping field-container shape before the shared predicate.

    A syntactically valid ES JSON response can contain a list at `properties`
    or `fields`. The production predicate assumes dicts and would otherwise
    raise AttributeError, leaking a traceback rather than a redacted result.
    Use iterative bounded traversal; leave field-type compatibility to the
    existing application predicate.
    """
    pending: list[dict[str, object]] = [mappings]
    seen = 0
    while pending:
        node = pending.pop()
        seen += 1
        if seen > 4096:
            return False
        for container in ("properties", "fields"):
            if container not in node:
                continue
            children = node[container]
            if not isinstance(children, dict):
                return False
            for child in children.values():
                if not isinstance(child, dict):
                    return False
                pending.append(child)
    return True


def _mapping_result(body: bytes, selector: str) -> tuple[str, str]:
    """Reuse the application mapping predicate, never echo index or fields."""
    try:
        if len(body) > MAX_BODY:
            return "FAIL", "es_mapping_response_oversized"
        mapping = json.loads(body)
        if not isinstance(mapping, dict):
            return "FAIL", "es_mapping_response_invalid"
        if len(mapping) != 1:
            return "SKIP", "es_mapping_target_ambiguous"
        entry = next(iter(mapping.values()))
        if not isinstance(entry, dict) or not isinstance(entry.get("mappings"), dict):
            return "FAIL", "es_mapping_response_invalid"
        if not _mapping_containers_valid(entry["mappings"]):
            return "FAIL", "es_mapping_response_invalid"
        probe = mapping_compatibility(mapping, selector)
        return ("PASS", "es_mapping_compatible") if probe.usable else (
            "FAIL", "mapping_incompatible")
    except (ValueError, TypeError, AttributeError, KeyError,
            RecursionError, UnicodeError):
        # Malformed untrusted JSON must not escape as an operator traceback.
        return "FAIL", "es_mapping_response_invalid"


def _verified_basic_principal(payload: bytes | None, username: str) -> bool:
    """Require the protected ES auth endpoint to attest this Basic principal.

    A 200 from / or /_mapping cannot establish authentication because both
    may be anonymously accessible (or a proxy may ignore Authorization).
    Keep all server-provided principal and realm details out of output.
    """
    try:
        record = json.loads(payload if payload is not None else b"")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return False
    return (
        isinstance(record, dict)
        and record.get("username") == username
        and record.get("authentication_type") == "realm"
        and record.get("enabled") is True
        and isinstance(record.get("authentication_realm"), dict)
        and isinstance(record["authentication_realm"].get("type"), str)
        and bool(record["authentication_realm"]["type"])
    )


def _later_tls_failure(result: dict[str, object], reason: str) -> None:
    """Aggregate TLS across all independent connections, not just first GET."""
    result["tls_validation"] = (
        "FAIL" if reason == "es_tls_identity_unverified" else "NOT_VERIFIED"
    )


def _observe(cfg: dict[str, str], *, no_network: bool,
             root: Path = PROJECT_ROOT,
             verify_credentials: bool = False) -> dict[str, object]:
    endpoint, host = _parse_endpoint(cfg.get("ES_URL"))
    index = _configured_index(cfg.get("ES_INDEX"))
    username, password = cfg.get("ES_USERNAME") or "", cfg.get("ES_PASSWORD") or ""
    ca = _trusted_ca_file(root)
    result: dict[str, object] = {
        "component": "es", "config_key": "ES_URL",
        **endpoint,
        "configuration": endpoint["configuration"],
        "index_configured": bool(index),
        "credentials_configured": bool(username and password),
        "ca_configured": ca is not None,
        "https_probe": "SKIP", "mapping_probe": "SKIP",
        "reason": "configuration_incomplete",
        "tls_validation": "NOT_TESTED", "auth": "NOT_TESTED",
        "credential_control": "NOT_RUN",
        "service_identity": "NOT_TESTED", "feature_acceptance": "NOT_TESTED",
    }
    if endpoint["configuration"] == "INVALID":
        result["reason"] = "es_url_invalid"
        return result
    if endpoint["configuration"] != "RESOLVED":
        result["reason"] = "es_url_missing"
        return result
    if endpoint["scheme"] != "https":
        result["reason"] = "es_https_required"
        return result
    if no_network:
        result["reason"] = "network_disabled"
        return result
    if host is None:
        result["reason"] = "es_endpoint_outside_private_ipv4_scope"
        return result
    if not index:
        result["reason"] = "es_index_selector_unavailable"
        return result
    if not username or not password or ":" in username:
        result["reason"] = "es_basic_auth_unavailable"
        return result
    if not ca:
        result["reason"] = "es_ca_missing"
        return result

    port = int(endpoint["port"])
    status, body, reason = _https_get(host, port, "/", username, password, ca)
    if status is None:
        result["https_probe"] = "FAIL"
        result["reason"] = reason
        result["tls_validation"] = ("FAIL" if reason == "es_tls_identity_unverified"
                                    else "NOT_VERIFIED")
        return result
    result["tls_validation"] = "PASS"
    if status == 401:
        result["https_probe"] = "FAIL"
        result["auth"] = "FAIL"
        result["reason"] = "es_auth_rejected"
        return result
    if status == 403:
        # A gateway can deny GET / before authenticating the Basic header.
        # Root identity check fails, but password validity is unverified.
        result["https_probe"] = "FAIL"
        result["auth"] = "NOT_VERIFIED"
        result["reason"] = "es_root_access_denied"
        return result
    if status != 200:
        result["https_probe"] = "FAIL"
        result["reason"] = "es_identity_http_unexpected"
        return result
    try:
        identity = json.loads(body)
        valid = (isinstance(identity, dict) and
                 isinstance(identity.get("cluster_name"), str) and
                 bool(identity["cluster_name"].strip()) and
                 isinstance(identity.get("version"), dict) and
                 isinstance(identity["version"].get("number"), str) and
                 bool(identity["version"]["number"].strip()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        valid = False
    if not valid:
        result["https_probe"] = "FAIL"
        result["reason"] = "es_identity_unverified"
        return result
    result["https_probe"] = "PASS"
    # Authenticate independently of public index/root HTTP 200. The protected
    # ES Security API attests the *same* Basic principal and realm identity.
    # No mapping request is allowed to proceed without this evidence.
    auth_status, auth_body, auth_reason = _https_get(
        host, port, "/_security/_authenticate", username, password, ca)
    if auth_status is None:
        result["auth"] = "NOT_VERIFIED"
        result["reason"] = "es_auth_transport_unavailable"
        _later_tls_failure(result, auth_reason)
        return result
    if auth_status == 401:
        result["auth"] = "FAIL"
        result["reason"] = "es_auth_rejected"
        return result
    if auth_status == 403:
        # A gateway can deny this route before evaluating Authorization.
        # Access is denied, but password validity remains unverified.
        result["auth"] = "NOT_VERIFIED"
        result["reason"] = "es_auth_access_denied"
        return result
    if auth_status == 404:
        result["reason"] = "es_auth_endpoint_unavailable"
        return result
    if auth_status != 200:
        # 429, 5xx or an intermediary response does not establish whether
        # the supplied Basic credentials are valid. Do not assert auth FAIL.
        result["auth"] = "NOT_VERIFIED"
        result["reason"] = "es_auth_http_unexpected"
        return result
    if not _verified_basic_principal(auth_body, username):
        result["auth"] = "FAIL"
        result["reason"] = "es_principal_unverified"
        return result
    # A matching principal alone does not prove that the supplied password
    # caused authentication: proxies may silently replace Authorization.
    # Default mode never sends deliberately incorrect credentials, since even
    # one failed attempt may be audited or contribute to an account lockout.
    result["auth"] = "NOT_VERIFIED"
    if verify_credentials:
        # Explicit operator opt-in only. Same user, fresh deliberately invalid
        # password. If a proxy ignores Authorization, it can still return 200
        # and cannot produce a false PASS. Never print the challenge value.
        invalid_password = secrets.token_urlsafe(32)
        while invalid_password == password:
            invalid_password = secrets.token_urlsafe(32)
        control_status, _, control_reason = _https_get(
            host, port, "/_security/_authenticate",
            username, invalid_password, ca,
        )
        if control_status is None:
            result["credential_control"] = "INCOMPLETE"
            result["reason"] = "es_credential_control_unavailable"
            _later_tls_failure(result, control_reason)
            return result
        # 403 can be an intermediary authorization denial, not proof the
        # supplied Basic password was rejected by Elasticsearch.
        if control_status != 401:
            result["credential_control"] = "FAIL"
            result["auth"] = "FAIL"
            result["reason"] = "es_credential_control_not_rejected"
            return result
        result["credential_control"] = "PASS"
        result["auth"] = "PASS"
    # Without opted-in negative control, mapping may be inspected read-only
    # but the CLI remains incomplete even if the mapping structure passes.
    # Still an ES-like identity only; neither PID nor service ownership proven.
    mapping_status, mapping_body, mapping_reason = _https_get(
        host, port, f"/{index}/_mapping", username, password, ca)
    if mapping_status is None:
        result["mapping_probe"] = "FAIL"
        result["reason"] = mapping_reason
        _later_tls_failure(result, mapping_reason)
        if mapping_reason == "es_tls_identity_unverified":
            result["auth"] = "NOT_VERIFIED"
    elif mapping_status in (401, 403):
        result["mapping_probe"] = "FAIL"
        result["reason"] = "es_mapping_access_denied"
    elif mapping_status == 404:
        result["mapping_probe"] = "FAIL"
        result["reason"] = "es_index_missing"
    elif mapping_status != 200:
        result["mapping_probe"] = "FAIL"
        result["reason"] = "es_mapping_http_unexpected"
    else:
        result["mapping_probe"], result["reason"] = _mapping_result(
            mapping_body or b"", index)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument(
        "--verify-credentials", action="store_true",
        help="Opt in to one deliberately rejected password check; can create "
             "an authentication-failure audit entry or count toward lockout",
    )
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != PROJECT_ROOT:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "run_from_repository_root"}, sort_keys=True))
        return 2
    try:
        cfg = _effective_runtime_config(PROJECT_ROOT)
    except Exception:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "runtime_configuration_unavailable"}, sort_keys=True))
        return 2
    observation = _observe(
        cfg, no_network=args.no_network, root=PROJECT_ROOT,
        verify_credentials=args.verify_credentials,
    )
    print(json.dumps({"schema": SCHEMA, "mode": MODE,
                      "network_mode": "CONFIG_ONLY" if args.no_network
                                      else "PRIVATE_IPV4_TLS_GET_ONLY",
                      "results": [observation]}, sort_keys=True, ensure_ascii=False))
    if ("FAIL" in (observation["https_probe"], observation["auth"],
                   observation["mapping_probe"], observation["tls_validation"])
            or observation["configuration"] == "INVALID"):
        return 1
    if (observation["https_probe"] == "PASS"
            and observation["auth"] == "PASS"
            and observation["mapping_probe"] == "PASS"):
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
