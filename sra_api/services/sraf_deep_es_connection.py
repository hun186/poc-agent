"""Dedicated real Elasticsearch transport for trusted deep Worker composition.

Never use the ordinary ES singleton, Vercel mock fallback, or acceptance
adapter. Construction is local configuration/TLS setup only; it is not a
live ES, mapping, index, or permission acceptance probe.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from inspect import signature
from pathlib import Path
from urllib.parse import urlsplit

from elasticsearch import Elasticsearch


class DeepESConfigError(ValueError):
    """Fixed failure code; do not expose URLs, certificates or credentials."""


def _value(env: Mapping[str, str], key: str, limit: int) -> str:
    value = env.get(key)
    if type(value) is not str or not 1 <= len(value) <= limit or not value.strip():
        raise ValueError
    return value


@dataclass(frozen=True, repr=False)
class DeepESConnection:
    """Own one dedicated SDK connection for a single API lifespan."""
    _client: Elasticsearch

    def __post_init__(self):
        if type(self._client) is not Elasticsearch:
            raise DeepESConfigError("deep_es_real_client_required")

    def get_client(self) -> Elasticsearch:
        if type(self._client) is not Elasticsearch:
            raise DeepESConfigError("deep_es_real_client_required")
        return self._client

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            raise DeepESConfigError("deep_es_close_failed") from None


def build_deep_es_connection(env: Mapping[str, str], *,
                             project_root: Path) -> DeepESConnection:
    """Build once, after explicit opt-in; use existing ES credentials.

    HTTPS, an explicit CA, normal TLS hostname verification, zero retries
    and no sniffing/alternate nodes. PIT calls remain separately admitted
    by the canonical round adapter. No ping/search, fallback or global cache.
    """
    client = None
    try:
        # Explicit deep-only entrypoint permits topology changes without
        # altering legacy ordinary report or ingestion configuration.
        # An explicitly invalid/empty override fails; no fallback on failure.
        url_key = "SRAF_DEEP_ES_URL" if "SRAF_DEEP_ES_URL" in env else "ES_URL"
        url = _value(env, url_key, 512)
        parts = urlsplit(url)
        if (any(ch.isspace() or ord(ch) < 32 for ch in url)
                or parts.scheme != "https" or not parts.hostname or not parts.port
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment or url.endswith(("?", "#"))
                or parts.path not in ("", "/") or "%" in parts.netloc):
            raise ValueError
        username = _value(env, "ES_USERNAME", 256)
        password = _value(env, "ES_PASSWORD", 4096)
        if username != username.strip():
            raise ValueError
        ca_override = env.get("SRAF_DEEP_ES_CA_CERT")
        ca_path = (Path(_value(env, "SRAF_DEEP_ES_CA_CERT", 4096))
                   if ca_override is not None else
                   project_root / "agent" / "certs" / "http_ca.crt")
        if not ca_path.is_absolute():
            ca_path = project_root / ca_path
        if not ca_path.is_file():
            raise ValueError
        # The strict PIT adapter requires this newer SDK argument. Do not
        # silently downgrade to a partial-shard PIT on older clients.
        if "allow_partial_search_results" not in signature(
                Elasticsearch.open_point_in_time).parameters:
            raise DeepESConfigError("deep_es_pit_sdk_unsupported")
        client = Elasticsearch(
            url, basic_auth=(username, password),
            ca_certs=str(ca_path), verify_certs=True,
            request_timeout=20, max_retries=0, retry_on_timeout=False,
            retry_on_status=(), sniff_on_start=False,
            sniff_before_requests=False, sniff_on_node_failure=False,
        )
        return DeepESConnection(client)
    except Exception:
        if type(client) is Elasticsearch:
            try:
                client.close()
            except Exception:
                pass
        raise DeepESConfigError("deep_es_config_unverified") from None
