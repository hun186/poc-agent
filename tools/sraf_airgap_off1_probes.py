#!/usr/bin/env python3
"""OFF-1 isolated, read-only dependency observations (NOT OFF-3 acceptance).

Each invocation observes one tightly scoped condition.  This module does not
construct OFF-0 report records or assert that the parent inventory check passed.
Network calls are always anonymous GETs to numeric IPv4 loopback, with no proxy,
redirect following, login, tokens, SQL queries, LLM generation, or writes.
"""
from __future__ import annotations

import argparse
import ctypes.util
import http.client
import json
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


def probe_odbc_library() -> Observation:
    probe = "odbc-library"
    # Discovery is not a Driver Manager load nor evidence of a SQL Server driver.
    # The absolute native library path, if found, is never recorded.
    try:
        present = bool(ctypes.util.find_library("odbc"))
    except (OSError, ValueError):
        return _result(probe, "FAIL", "odbc_discovery_unavailable", executed=True)
    return _result(probe, "PASS" if present else "WARN",
                   "odbc_library_discovered" if present else "odbc_library_not_found",
                   executed=True, evidence={"odbc_library_found": present})


def _http_get(port: int, path: str) -> tuple[int | None, bytes | None]:
    """One real loopback GET, no redirects/proxies/auth, bounded body/time."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT_SECONDS)
    try:
        conn.request("GET", path, headers={"Accept": "application/json",
                                          "Connection": "close"})
        response = conn.getresponse()
        status = response.status
        body = response.read(MAX_HTTP_BYTES + 1)
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
    return _result("es-transport", "PASS" if status == 200 else "FAIL",
                   "es_http_reachable" if status == 200 else "es_http_unexpected",
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
