#!/usr/bin/env python3
"""OFF-1 isolated, read-only dependency observations (NOT OFF-3 acceptance).

Each invocation observes one tightly scoped condition.  This module does not
construct OFF-0 report records or assert that the parent inventory check passed.
Network calls are always anonymous GETs to numeric IPv4 loopback, with no proxy,
redirect following, login, tokens, SQL queries, LLM generation, or writes.
"""
from __future__ import annotations

import argparse
import http.client
import socket
import time
import json
import re
import os
import shutil
from dataclasses import asdict, dataclass
from typing import Any


MAX_HTTP_BYTES = 64 * 1024
TIMEOUT_SECONDS = 3
MIN_DISK_FREE_MIB = 512
# The parent check IDs are references, NOT full-check certification.
PROBES = {
    "sys-disk": ("SYS-01", "disk_free_only", "quick"),
    "odbc-library": ("ENV-02", "native_odbc_library_discovery_only", "quick"),
    "api-health": ("API-01", "healthz_http_only", "quick"),
    "es-transport": ("ES-01", "anonymous_http_reachability_only", "diagnose"),
    "llm-inventory": ("LLM-01", "named_model_inventory_only", "diagnose"),
}


@dataclass(frozen=True)
class Observation:
    check_id: str
    probe: str
    aspect: str
    status: str
    reason: str
    executed: bool
    evidence: dict[str, int | bool]

    def serialize(self) -> dict[str, Any]:
        return {
            "schema": "sraf_airgap_off1_partial_probe_v1",
            "mode": "PARTIAL_ONLY_NOT_ACCEPTANCE",
            **asdict(self),
        }


def _result(probe: str, status: str, reason: str, *,
            executed: bool, evidence: dict[str, int | bool] | None = None) -> Observation:
    check_id, aspect, _ = PROBES[probe]
    # No dynamic exception text, hostname, file paths, URLs, models or secrets.
    if status not in {"PASS", "FAIL", "WARN", "SKIP"}:
        raise ValueError("unsupported_probe_status")
    return Observation(check_id, probe, aspect, status, reason, executed,
                       evidence if evidence is not None else {})


def probe_disk() -> Observation:
    probe = "sys-disk"
    try:
        total, used, free = shutil.disk_usage(os.getcwd())
        cores = os.cpu_count()
    except OSError:
        return _result(probe, "FAIL", "disk_information_unavailable", executed=True)
    if not (isinstance(free, int) and 0 <= free <= total and
            isinstance(cores, int) and cores > 0):
        return _result(probe, "FAIL", "host_information_invalid", executed=True)
    free_mib = free // (1024 * 1024)
    return _result(
        probe, "PASS" if free_mib >= MIN_DISK_FREE_MIB else "WARN",
        "disk_threshold_met" if free_mib >= MIN_DISK_FREE_MIB else "disk_space_low",
        executed=True,
        evidence={"free_mib": min(free_mib, 10**12), "cpu_count": min(cores, 10**12)},
    )


# Only a fixed, small set of familiar *local* Unix library locations is
# observed. ctypes.util.find_library may spawn ldconfig/compiler subprocesses
# with no timeout, so is prohibited in this bounded diagnostics path.
# This can produce false negatives on nonstandard installations by design.
ODBC_LIBRARY_CANDIDATES = (
    "/lib/x86_64-linux-gnu/libodbc.so.2",
    "/usr/lib/x86_64-linux-gnu/libodbc.so.2",
    "/lib/aarch64-linux-gnu/libodbc.so.2",
    "/usr/lib/aarch64-linux-gnu/libodbc.so.2",
    "/usr/lib64/libodbc.so.2",
    "/usr/lib/libodbc.so.2",
    "/usr/local/lib/libodbc.so.2",
    "/opt/homebrew/lib/libodbc.2.dylib",
    "/usr/local/lib/libodbc.2.dylib",
)


def _odbc_platform_supported() -> bool:
    return os.name == "posix"


def _odbc_library_file_exists(path: str) -> bool:
    return os.path.isfile(path)


def probe_odbc_library() -> Observation:
    probe = "odbc-library"
    if not _odbc_platform_supported():
        return _result(probe, "SKIP", "odbc_filesystem_probe_unsupported",
                       executed=False)
    # No dynamic loader, compiler, helper subprocess, glob, or user-supplied path.
    # Merely finding one file is NOT confirmation of loadability or SQL driver.
    try:
        present = any(_odbc_library_file_exists(path) for path in ODBC_LIBRARY_CANDIDATES)
    except (OSError, ValueError):
        return _result(probe, "FAIL", "odbc_discovery_unavailable", executed=True)
    return _result(probe, "PASS" if present else "WARN",
                   "odbc_library_file_observed" if present else "odbc_library_not_found",
                   executed=True, evidence={"odbc_library_found": present})


class _DeadlineSocket(socket.socket):
    """TCP socket whose *every* read/write uses the same absolute deadline.

    http.client wraps the socket in socket.SocketIO for buffered header/body
    reads; SocketIO calls recv_into(), so bounding only HTTPConnection(timeout)
    is insufficient against a peer sending one byte just before each timeout.
    """

    def __init__(self, deadline: float):
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        self._deadline = deadline

    def _enforce_deadline(self) -> None:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("probe_deadline_exceeded")
        self.settimeout(remaining)

    def connect(self, address: tuple[str, int]) -> None:
        self._enforce_deadline()
        return super().connect(address)

    def recv_into(self, buffer: Any, nbytes: int = 0, flags: int = 0) -> int:
        self._enforce_deadline()
        return super().recv_into(buffer, nbytes, flags)

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        self._enforce_deadline()
        return super().recv(bufsize, flags)

    def sendall(self, data: bytes, flags: int = 0) -> None:
        self._enforce_deadline()
        return super().sendall(data, flags)


class _DeadlineHTTPConnection(http.client.HTTPConnection):
    """Single loopback connection; retain http.client parsing and size checks."""

    def __init__(self, port: int, *, deadline: float):
        super().__init__("127.0.0.1", port, timeout=TIMEOUT_SECONDS)
        self._deadline = deadline
        # HTTPConnection.__init__ installs _create_connection as an INSTANCE
        # attribute. Rebind it after super() so the absolute deadline socket
        # is actually used (a subclass method alone is silently shadowed).
        self._create_connection = self._bounded_create_connection

    def _bounded_create_connection(self, address: tuple[str, int], timeout: float,
                                   source_address: Any) -> socket.socket:
        sock = _DeadlineSocket(self._deadline)
        try:
            sock.connect(address)
        except BaseException:
            sock.close()
            raise
        return sock



_CHUNK_LINE_LIMIT = 1024
_CHUNK_TRAILER_LIMIT = 8192
_CHUNK_MAX_FRAGMENTS = 8192
# A deliberately constrained subset of RFC token chunk-extension syntax.
_CHUNK_HEAD = re.compile(
    rb"[0-9A-Fa-f]{1,16}(?:;[!#$%&'*+\-.^_\x60|~0-9A-Za-z]+"
    rb"(?:=[!#$%&'*+\-.^_\x60|~0-9A-Za-z]+)?)*"
)
_CHUNK_TRAILER = re.compile(
    rb"[!#$%&'*+\-.^_\x60|~0-9A-Za-z]+:[ \t]*[\x20-\x7e\t]*"
)


def _read_verified_chunked(fp: Any, deadline: float) -> bytes:
    """Decode only complete, bounded HTTP/1.1 chunks with exact CRLF.

    CPython 3.11 http.client drops post-chunk delimiter bytes without checking
    they are CRLF and accepts EOF inside trailer headers. Bypass its permissive
    chunk reader and read from its existing buffered socket file directly.
    All blocking reads remain bounded by _DeadlineSocket's monotonic deadline.
    """
    if fp is None:
        raise http.client.HTTPException("chunk_stream_missing")
    payload = bytearray()
    for _ in range(_CHUNK_MAX_FRAGMENTS):
        if time.monotonic() >= deadline:
            raise TimeoutError("probe_deadline_exceeded")
        line = fp.readline(_CHUNK_LINE_LIMIT + 1)
        if (len(line) > _CHUNK_LINE_LIMIT or not line.endswith(b"\r\n")
                or _CHUNK_HEAD.fullmatch(line[:-2]) is None):
            raise http.client.HTTPException("chunk_size_invalid")
        chunk_size = int(line[:-2].split(b";", 1)[0], 16)
        if chunk_size == 0:
            trailer_bytes = 0
            while trailer_bytes <= _CHUNK_TRAILER_LIMIT:
                if time.monotonic() >= deadline:
                    raise TimeoutError("probe_deadline_exceeded")
                trailer = fp.readline(_CHUNK_LINE_LIMIT + 1)
                trailer_bytes += len(trailer)
                if (len(trailer) > _CHUNK_LINE_LIMIT
                        or trailer_bytes > _CHUNK_TRAILER_LIMIT
                        or not trailer.endswith(b"\r\n")):
                    raise http.client.HTTPException("chunk_trailer_invalid")
                if trailer == b"\r\n":
                    return bytes(payload)
                if _CHUNK_TRAILER.fullmatch(trailer[:-2]) is None:
                    raise http.client.HTTPException("chunk_trailer_invalid")
            raise http.client.HTTPException("chunk_trailer_oversized")
        if chunk_size > MAX_HTTP_BYTES - len(payload):
            # Keep the existing oversized-body classification at the caller,
            # without allocating or waiting for a massive declared chunk.
            return b"x" * (MAX_HTTP_BYTES + 1)
        chunk_and_crlf = fp.read(chunk_size + 2)
        if (len(chunk_and_crlf) != chunk_size + 2
                or not chunk_and_crlf.endswith(b"\r\n")):
            raise http.client.HTTPException("chunk_delimiter_invalid")
        payload.extend(chunk_and_crlf[:-2])
    raise http.client.HTTPException("too_many_chunks")


def _http_get(port: int, path: str) -> tuple[int | None, bytes | None]:
    """One anonymous loopback GET, bounded by an absolute 3-second deadline."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    conn = _DeadlineHTTPConnection(port, deadline=deadline)
    try:
        conn.request("GET", path, headers={"Accept": "application/json",
                                          "Connection": "close"})
        response = conn.getresponse()
        status = response.status
        # Invalid raw lines (e.g. "Content-Length : -1") are discarded
        # by email.parser and do not appear in get_all(). They do register
        # defects: reject the entire response before inspecting framing or
        # accepting an otherwise plausible JSON service identity.
        if response.headers.defects:
            return None, None
        # http.client silently normalizes a *malformed* Content-Length to
        # response.length=None, indistinguishable from an absent header.
        # Inspect the original parsed header list before accepting JSON.
        # Duplicate lengths and mixed Transfer-Encoding/Content-Length are
        # rejected instead of relying on ambiguous framing precedence.
        lengths = response.headers.get_all("Content-Length", [])
        transfers = response.headers.get_all("Transfer-Encoding", [])
        # HTTP/1.1 chunked transfer is valid without Content-Length.
        # Accept only the single, exact coding supported by http.client and
        # verified as decoded by the parser; reject ambiguous or unsupported
        # codings and all Transfer-Encoding/Content-Length combinations.
        if len(lengths) > 1 or len(transfers) > 1:
            return None, None
        if transfers:
            if (lengths or transfers[0].strip(" \t").lower() != "chunked"
                    or response.chunked is not True or response.version != 11):
                return None, None
            expected_length = None
        elif lengths:
            raw_length = lengths[0].strip(" \t")
            if re.fullmatch(r"[0-9]{1,18}", raw_length) is None:
                return None, None
            expected_length = int(raw_length)
            if response.length != expected_length:
                return None, None
        else:
            # Only an actually absent Content-Length with no transfer coding
            # may use close-delimited framing.
            expected_length = None
        # read(amt) can silently return incomplete bytes on early EOF even
        # when Content-Length declared a larger body. Preserve the expected
        # length BEFORE http.client updates its internal remaining counter.
        if transfers:
            body = _read_verified_chunked(response.fp, deadline)
        else:
            body = response.read(MAX_HTTP_BYTES + 1)
        if time.monotonic() >= deadline:
            return None, None
        if (expected_length is not None and
                len(body) != min(expected_length, MAX_HTTP_BYTES + 1)):
            return None, None
        return status, body
    except (OSError, http.client.HTTPException):
        return None, None
    finally:
        conn.close()


def probe_api_health(port: int) -> Observation:
    status, body = _http_get(port, "/healthz")
    if status is None:
        return _result("api-health", "FAIL", "api_transport_unavailable", executed=True)
    if body is not None and len(body) > MAX_HTTP_BYTES:
        return _result("api-health", "FAIL", "api_response_oversized", executed=True)
    return _result(
        "api-health", "PASS" if status == 200 else "FAIL",
        "healthz_http_200" if status == 200 else "healthz_http_not_200",
        executed=True, evidence={"http_status": status},
    )


def probe_es_transport(port: int) -> Observation:
    status, body = _http_get(port, "/")
    if status is None:
        return _result("es-transport", "FAIL", "es_transport_unavailable", executed=True)
    if body is not None and len(body) > MAX_HTTP_BYTES:
        return _result("es-transport", "FAIL", "es_response_oversized", executed=True)
    if status in (401, 403):
        return _result("es-transport", "SKIP", "es_credentials_not_probed",
                       executed=True, evidence={"http_status": status})
    if status != 200:
        return _result("es-transport", "FAIL", "es_http_unexpected",
                       executed=True, evidence={"http_status": status})
    try:
        payload = json.loads(body if body is not None else b"")
    except (ValueError, UnicodeError, RecursionError):
        return _result("es-transport", "FAIL", "es_identity_unverified",
                       executed=True, evidence={"http_status": status})
    if (not isinstance(payload, dict) or
            not isinstance(payload.get("cluster_name"), str) or
            not payload["cluster_name"].strip() or
            not isinstance(payload.get("version"), dict) or
            not isinstance(payload["version"].get("number"), str) or
            not payload["version"]["number"].strip()):
        return _result("es-transport", "FAIL", "es_identity_unverified",
                       executed=True, evidence={"http_status": status})
    # This confirms only an ES-like HTTP identity, NOT credentials, mapping
    # compatibility, retrieval correctness, cluster health, or TLS.
    return _result("es-transport", "PASS", "es_http_identity_observed",
                   executed=True, evidence={"http_status": status})


def probe_llm_inventory(port: int, model_name: str | None,
                        backend: str = "ollama") -> Observation:
    probe = "llm-inventory"
    if not model_name:
        return _result(probe, "SKIP", "model_name_not_configured", executed=False)
    if backend not in ("ollama", "openai"):
        return _result(probe, "SKIP", "unsupported_inventory_backend", executed=False)
    path = "/api/tags" if backend == "ollama" else "/v1/models"
    status, body = _http_get(port, path)
    if status is None:
        return _result(probe, "FAIL", "model_service_unavailable", executed=True)
    if body is not None and len(body) > MAX_HTTP_BYTES:
        return _result(probe, "FAIL", "model_inventory_oversized", executed=True)
    if status in (401, 403):
        return _result(probe, "SKIP", "model_inventory_auth_required",
                       executed=True, evidence={"http_status": status})
    if status != 200:
        return _result(probe, "FAIL", "model_inventory_http_error",
                       executed=True, evidence={"http_status": status})
    try:
        document = json.loads(body if body is not None else b"")
    except (ValueError, RecursionError, UnicodeError):
        return _result(probe, "FAIL", "model_inventory_invalid", executed=True)
    if not isinstance(document, dict):
        return _result(probe, "FAIL", "model_inventory_invalid", executed=True)
    records = document.get("models" if backend == "ollama" else "data")
    if not isinstance(records, list) or len(records) > 1000:
        return _result(probe, "FAIL", "model_inventory_invalid", executed=True)
    key = "name" if backend == "ollama" else "id"
    if any(not isinstance(item, dict) or not isinstance(item.get(key), str)
           for item in records):
        return _result(probe, "FAIL", "model_inventory_invalid", executed=True)
    found = any(item[key] == model_name for item in records)
    return _result(probe, "PASS" if found else "FAIL",
                   "configured_model_listed" if found else "configured_model_not_listed",
                   executed=True,
                   evidence={"model_available": found,
                             "item_count": len(records), "http_status": 200})


def _port(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("invalid_loopback_port") from None
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError("invalid_loopback_port")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", choices=tuple(PROBES), required=True)
    parser.add_argument("--mode", choices=("quick", "diagnose"), default="quick")
    parser.add_argument("--api-port", type=_port, default=8000)
    parser.add_argument("--es-port", type=_port, default=9200)
    parser.add_argument("--llm-port", type=_port, default=11434)
    parser.add_argument("--llm-backend", choices=("ollama", "openai"), default="ollama")
    parser.add_argument("--model-name", default=None)
    args = parser.parse_args(argv)
    minimum = PROBES[args.check][2]
    if minimum == "diagnose" and args.mode != "diagnose":
        observation = _result(args.check, "SKIP", "diagnose_mode_required",
                              executed=False)
    elif args.check == "sys-disk":
        observation = probe_disk()
    elif args.check == "odbc-library":
        observation = probe_odbc_library()
    elif args.check == "api-health":
        observation = probe_api_health(args.api_port)
    elif args.check == "es-transport":
        observation = probe_es_transport(args.es_port)
    else:
        observation = probe_llm_inventory(args.llm_port, args.model_name,
                                          args.llm_backend)
    print(json.dumps(observation.serialize(), ensure_ascii=False, sort_keys=True))
    # Do not treat skipped checks as operational success; 2 means incomplete.
    return 0 if observation.status == "PASS" else 2 if observation.status == "SKIP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
