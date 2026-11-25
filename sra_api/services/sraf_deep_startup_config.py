"""Opt-in deep report configuration; validation only, no provider or startup IO.

Do not install a runtime until the separate real ES composition gate passes.
No environment defaults for models, grants or capacity when explicitly enabled.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from urllib.parse import urlsplit

from api.services.sraf_deep_grant_config import DeepOwnerGrant, DeepGrantConfig
from api.services.sraf_nround_local_models import LocalDeepModels


class DeepStartupConfigError(ValueError):
    """Fixed, non-sensitive configuration error."""


@dataclass(frozen=True, repr=False)
class DeepStartupConfig:
    policy: DeepGrantConfig
    models: LocalDeepModels
    chat_auto_base_url: str | None = None


def validate_chat_public_base(value: str) -> str:
    """Operator-owned origin/path only, never a request Host or credential."""
    if (type(value) is not str or not 1 <= len(value) <= 512
            or not re.fullmatch(
                r"https?://(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::[0-9]{1,5})?(?:/[A-Za-z0-9_-]+)*/?",
                value)):
        raise ValueError("deep_chat_public_base_invalid")
    parts = urlsplit(value)
    if (not parts.hostname or parts.hostname.startswith(".")
            or ".." in parts.hostname or parts.hostname.endswith(".")
            or (parts.port is not None and not 1 <= parts.port <= 65535)):
        raise ValueError("deep_chat_public_base_invalid")
    return value.rstrip("/")


def _required(env: Mapping[str, str], name: str, limit: int) -> str:
    value = env.get(name)
    if (type(value) is not str or not 1 <= len(value) <= limit
            or value != value.strip()):
        raise ValueError
    return value


def _integer(env: Mapping[str, str], name: str) -> int:
    value = _required(env, name, 6)
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError
    return int(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def load_deep_startup_config(env: Mapping[str, str]) -> DeepStartupConfig | None:
    """Parse an operator-supplied snapshot. Disabled never reads other keys.

    A malformed opt-in or incomplete enabled configuration is a failure, not
    a silent fallback to default index/model, mock execution or ordinary mode.
    No AuthStore query, provider call, DB write or app-state mutation occurs.
    """
    enabled = env.get("SRAF_DEEP_REPORT_ENABLED", "0")
    if enabled == "0":
        return None
    if enabled != "1":
        raise DeepStartupConfigError("deep_startup_flag_invalid")
    try:
        raw = json.loads(_required(env, "SRAF_DEEP_OWNER_GRANTS_JSON", 262144),
                         object_pairs_hook=_unique_object)
        if type(raw) is not list or not 1 <= len(raw) <= 256:
            raise ValueError
        grants = []
        for entry in raw:
            if (type(entry) is not dict
                    or set(entry) != {"owner_id", "account_created_at", "indexes"}
                    or type(entry["indexes"]) is not list):
                raise ValueError
            grants.append(DeepOwnerGrant(entry["owner_id"], entry["account_created_at"],
                                         tuple(entry["indexes"])))
        policy = DeepGrantConfig(tuple(grants), _integer(env, "SRAF_DEEP_MAX_ACTIVE_JOBS"))
        models = LocalDeepModels(
            endpoint=_required(env, "SRAF_DEEP_OLLAMA_ENDPOINT", 256),
            planner_model=_required(env, "SRAF_DEEP_PLANNER_MODEL", 128),
            semantic_model=_required(env, "SRAF_DEEP_SEMANTIC_MODEL", 128),
            report_model=_required(env, "SRAF_DEEP_REPORT_MODEL", 128),
            num_ctx=_integer(env, "SRAF_DEEP_NUM_CTX"),
        )
        chat_flag = env.get("SRAF_DEEP_CHAT_AUTO_ENABLED", "0")
        if chat_flag not in ("0", "1"):
            raise ValueError
        chat_base = (validate_chat_public_base(_required(env, "PUBLIC_API_BASE", 512))
                     if chat_flag == "1" else None)
        return DeepStartupConfig(policy, models, chat_base)
    except Exception:
        raise DeepStartupConfigError("deep_startup_config_invalid") from None
