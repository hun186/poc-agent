"""OFF-1B runtime-configured, bounded TCP preflight (NOT service acceptance).

Run from the deployed repository root:
    python tools/sraf_airgap_off1b_auto.py

This first OFF-1B slice discovers the SAME effective dotenv configuration used
by the launcher. It performs only numeric RFC1918/loopback IPv4 TCP connects:
no HTTP request, TLS handshake, authentication, database query, model invocation,
application initialization, DNS resolution, or worker operation.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.bootstrap import bootstrap_env  # noqa: E402

SCHEMA = "sraf_airgap_off1b_configured_tcp_preflight_v1"
MODE = "PARTIAL_ONLY_NOT_ACCEPTANCE"
SERVICE_KEYS = {
    "api": "PUBLIC_API_BASE",
    "es": "ES_URL",
    "llm": "MODEL_BASE_URL",
    "topic-llm": "TOPIC_LLM_URL",
}
ALLOWED_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
TIMEOUT_SECONDS = 2.0


def _effective_runtime_config(root: Path) -> dict[str, str]:
    """Invoke the real runtime dotenv bootstrap, suppressing path-bearing logs.

    The real rule is: OS environment > .env.local > .env.APP_ENV > .env.
    Use a separate CLI process rather than importing the API or workers.
    """
    profile = (os.getenv("APP_ENV") or "dev").strip().lower()
    if re.fullmatch(r"[a-z0-9_-]{1,32}", profile) is None:
        raise ValueError("invalid_profile")
    # The shell launcher sets PORT before the Python dotenv bootstrap. A PORT
    # defined only in .env is not applied to run_sra_api.sh's listener.
    launcher_port = os.environ.get("PORT", "")
    with redirect_stdout(io.StringIO()):
        bootstrap_env(project_root=root)
    cfg = dict(os.environ)
    cfg["_OFF1B_LAUNCHER_PORT"] = launcher_port
    return cfg


def _parse_endpoint(
    raw: str | None, *, allowed_paths: tuple[str, ...] = ("", "/")
) -> tuple[dict[str, object], str | None]:
    info: dict[str, object] = {
        "configuration": "MISSING",
        "scheme": None,
        "port": None,
        "host_scope": "UNRESOLVED",
    }
    if raw is None or not raw.strip():
        return info, None

    # Never let urlsplit silently strip CR/LF or process embedded credentials.
    if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7f for c in raw):
        info["configuration"] = "INVALID"
        return info, None
    try:
        url = urlsplit(raw)
        host = url.hostname
        port = url.port
        if url.scheme not in ("http", "https") or not host:
            raise ValueError("unsupported_scheme")
        if url.username is not None or url.password is not None:
            raise ValueError("userinfo_forbidden")
        if url.path not in allowed_paths or url.query or url.fragment:
            raise ValueError("unexpected_url_component")
        if port is None:
            port = 443 if url.scheme == "https" else 80
        if not 1 <= port <= 65535:
            raise ValueError("port_out_of_range")
        info["configuration"] = "RESOLVED"
        info["scheme"] = url.scheme
        info["port"] = port
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            info["host_scope"] = "DNS_NAME_NOT_PROBED"
            return info, None
        if not isinstance(address, ipaddress.IPv4Address):
            info["host_scope"] = "NON_IPV4_NOT_PROBED"
            return info, None
        if not any(address in network for network in ALLOWED_NETWORKS):
            info["host_scope"] = "NON_PRIVATE_IPV4_NOT_PROBED"
            return info, None
        info["host_scope"] = (
            "LOOPBACK_IPV4" if address.is_loopback else "RFC1918_IPV4"
        )
        return info, str(address)
    except ValueError:
        # Never include raw URL, exception, path, host, or userinfo.
        info["configuration"] = "INVALID"
        info["scheme"] = None
        info["port"] = None
        return info, None


def _api_bind_endpoint(cfg: dict[str, str]) -> tuple[dict[str, object], str | None]:
    """Model launcher bind target (loopback available for host=0.0.0.0).

    This is not PUBLIC_API_BASE (a URL-generation / reverse-proxy setting).
    Port is shell PORT, NOT a value injected by the Python dotenv bootstrap.
    """
    raw_port = cfg.get("_OFF1B_LAUNCHER_PORT", "")
    if raw_port == "":
        port = 9002
    elif re.fullmatch(r"[0-9]{1,5}", raw_port) is not None:
        port = int(raw_port)
    else:
        port = 0
    if not 1 <= port <= 65535:
        return {
            "configuration": "INVALID", "scheme": None,
            "port": None, "host_scope": "UNRESOLVED",
        }, None
    return _parse_endpoint(f"http://127.0.0.1:{port}")


def _tcp_connect(host: str, port: int) -> bool:
    # Numeric validated IPv4 only; no DNS lookup, proxy, TLS, or HTTP.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT_SECONDS)
            sock.connect((host, port))
        return True
    except OSError:
        return False


def _observe(service: str, cfg: dict[str, str], *, no_network: bool) -> dict[str, object]:
    key = SERVICE_KEYS[service]
    if service == "topic-llm":
        # query_terms uses TOPIC_LLM_URL only as a truthy enablement flag;
        # the actual call_llm client connects to MODEL_BASE_URL. Do not open
        # an unrelated socket just because TOPIC_LLM_URL contains an address.
        return {
            "component": service, "config_key": key,
            "configuration": "FEATURE_ENABLED" if cfg.get(key) else "FEATURE_DISABLED",
            "scheme": None, "port": None, "host_scope": "NOT_AN_ENDPOINT",
            "feature_enabled": bool(cfg.get(key)),
            "model_configured": bool(cfg.get("MODEL_ID")),
            "tcp_probe": "SKIP", "reason": "feature_flag_only",
            "service_identity": "NOT_TESTED", "tls_validation": "NOT_TESTED",
            "auth": "NOT_TESTED", "feature_acceptance": "NOT_TESTED",
        }
    if service == "api":
        endpoint, host = _api_bind_endpoint(cfg)
        key = "PORT"
    else:
        allowed_paths = ("", "/", "/api/chat", "/api/generate") if service == "llm" else ("", "/")
        endpoint, host = _parse_endpoint(cfg.get(key), allowed_paths=allowed_paths)
    evidence: dict[str, object] = {
        "component": service,
        "config_key": key,
        **endpoint,
        "tcp_probe": "SKIP",
        "reason": "config_not_resolved",
        "service_identity": "NOT_TESTED",
        "tls_validation": "NOT_TESTED",
        "auth": "NOT_TESTED",
        "feature_acceptance": "NOT_TESTED",
    }
    if service == "es":
        evidence["credentials_configured"] = any(
            bool(cfg.get(k)) for k in ("ES_USERNAME", "ES_PASSWORD", "ES_SERVICE_TOKEN")
        )
    elif service == "llm":
        evidence["model_configured"] = bool(cfg.get("MODEL_ID"))
     if evidence["configuration"] != "RESOLVED":
        return evidence
    if no_network:
        evidence["reason"] = "network_disabled"
        return evidence
    if host is None:
        evidence["reason"] = "endpoint_outside_bounded_tcp_scope"
        return evidence
    evidence["tcp_probe"] = "PASS" if _tcp_connect(host, int(endpoint["port"])) else "FAIL"
    evidence["reason"] = (
        "configured_tcp_connected" if evidence["tcp_probe"] == "PASS"
        else "configured_tcp_unavailable"
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", choices=("all", *SERVICE_KEYS), default="all")
    parser.add_argument("--no-network", action="store_true")
    args = parser.parse_args(argv)

    if Path.cwd().resolve() != PROJECT_ROOT:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "run_from_repository_root"}, sort_keys=True))
        return 2
    try:
        cfg = _effective_runtime_config(PROJECT_ROOT)
    except (ValueError, OSError):
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "runtime_configuration_unavailable"}, sort_keys=True))
        return 2

    # Topic LLM is a feature flag, not an independent TCP service. The
    # all-services TCP check includes only real configured network endpoints.
    names = ("api", "es", "llm") if args.check == "all" else (args.check,)
    observations = [_observe(name, cfg, no_network=args.no_network) for name in names]
    result = {"schema": SCHEMA, "mode": MODE,
              "network_mode": "CONFIG_ONLY" if args.no_network else "BOUNDED_TCP_ONLY",
              "results": observations}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if any(obs["tcp_probe"] == "FAIL" or obs["configuration"] == "INVALID"
           for obs in observations):
        return 1
    return 0 if all(obs["tcp_probe"] == "PASS" for obs in observations) else 2


if __name__ == "__main__":
    raise SystemExit(main())
