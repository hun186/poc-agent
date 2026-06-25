from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from agent.es import es_client
from agent.es.evidence_core.json_utils import json_load_maybe

_MAPPING_FIELD_PATHS_CACHE_TTL_SEC = 60.0
_mapping_field_paths_cache: dict[str, tuple[float, set[str], bool]] = {}


def make_uuid_from_source(source: dict[str, Any]) -> str:
    """Generate deterministic sha1 id from source payload.

    `importDT` is runtime metadata and should not affect duplicate detection.
    """
    normalized = dict(source)
    normalized.pop("importDT", None)
    basis = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def pick_source_uuid(source: dict[str, Any]) -> str | None:
    value = source.get("uuid")
    if isinstance(value, list) and value:
        candidate = str(value[0] or "").strip()
        return candidate or None
    if isinstance(value, str):
        candidate = value.strip()
        return candidate or None
    return None


def utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def mapping_object_paths(properties: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for name, definition in (properties or {}).items():
        if not isinstance(definition, dict):
            continue
        path = f"{prefix}.{name}" if prefix else name
        field_type = str(definition.get("type") or "")
        child_props = definition.get("properties")
        if field_type in {"object", "nested"} or isinstance(child_props, dict):
            paths.add(path)
            if isinstance(child_props, dict):
                paths |= mapping_object_paths(child_props, path)
    return paths


def get_index_object_paths(index: str) -> set[str]:
    try:
        mapping = es_client.get_es().indices.get_mapping(index=index)
    except Exception:
        return set()

    object_paths: set[str] = set()
    for _, body in (mapping or {}).items():
        m = body.get("mappings") if isinstance(body, dict) else {}
        props = m.get("properties") if isinstance(m, dict) else {}
        if isinstance(props, dict):
            object_paths |= mapping_object_paths(props)
    return object_paths


def get_index_field_paths(index: str) -> tuple[set[str], bool]:
    now = time.time()
    cached = _mapping_field_paths_cache.get(index)
    if cached and now - cached[0] <= _MAPPING_FIELD_PATHS_CACHE_TTL_SEC:
        return cached[1], cached[2]

    try:
        mapping = es_client.get_es().indices.get_mapping(index=index)
    except Exception:
        _mapping_field_paths_cache[index] = (now, set(), False)
        return set(), False

    paths: set[str] = set()

    def _walk(props: dict[str, Any], prefix: str = "") -> None:
        for name, definition in (props or {}).items():
            if not isinstance(definition, dict):
                continue
            path = f"{prefix}.{name}" if prefix else name
            paths.add(path)
            child_props = definition.get("properties")
            if isinstance(child_props, dict):
                _walk(child_props, path)

    for _, body in (mapping or {}).items():
        m = body.get("mappings") if isinstance(body, dict) else {}
        props = m.get("properties") if isinstance(m, dict) else {}
        if isinstance(props, dict):
            _walk(props)

    _mapping_field_paths_cache[index] = (now, paths, True)
    return paths, True


def get_index_field_type_map(index: str, targets: list[str]) -> dict[str, str]:
    try:
        mapping = es_client.get_es().indices.get_mapping(index=index)
    except Exception:
        return {}

    out: dict[str, str] = {}

    def _walk(props: dict[str, Any], prefix: str = "") -> None:
        for name, definition in (props or {}).items():
            if not isinstance(definition, dict):
                continue
            path = f"{prefix}.{name}" if prefix else name
            ftype = str(definition.get("type") or "")
            if path in targets and ftype:
                out[path] = ftype
            child_props = definition.get("properties")
            if isinstance(child_props, dict):
                _walk(child_props, path)

    for _, body in (mapping or {}).items():
        m = body.get("mappings") if isinstance(body, dict) else {}
        props = m.get("properties") if isinstance(m, dict) else {}
        if isinstance(props, dict):
            _walk(props)

    return out


def coerce_source_by_mapping(source: dict[str, Any], object_paths: set[str]) -> dict[str, Any]:
    patched = dict(source)
    for path in sorted(object_paths):
        parts = path.split(".")
        node: Any = patched
        ok = True
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                ok = False
                break
            node = node.get(part)
        if not ok or not isinstance(node, dict):
            continue
        leaf = parts[-1]
        if leaf not in node:
            continue
        value = node.get(leaf)
        if value is None or isinstance(value, dict) or isinstance(value, list):
            continue
        node[leaf] = {"value": value}
    return patched


def normalize_sra_source_shapes(source: dict[str, Any], field_type_map: dict[str, str]) -> dict[str, Any]:
    """Normalize known SRP fields based on Elasticsearch mapping types.

    - nested  -> list[dict]
    - object  -> dict
    """
    normalized = dict(source)

    def _to_list_of_dict(value: Any) -> list[dict[str, Any]]:
        value = json_load_maybe(value)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        if isinstance(value, dict):
            return [value]
        return []

    def _to_dict(value: Any) -> dict[str, Any]:
        value = json_load_maybe(value)
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    return item
        return {}

    for key in ("multidim_event_json", "route_audit_json"):
        if key not in normalized:
            continue
        ftype = (field_type_map.get(key) or "").lower()
        if ftype == "nested":
            normalized[key] = _to_list_of_dict(normalized.get(key))
        elif ftype == "object":
            normalized[key] = _to_dict(normalized.get(key))

    return normalized


def current_indexes() -> list[str]:
    """Return currently-live ES indexes for editor dropdown (excluding hidden/system indexes)."""
    es_client.init_index_cache(live_check=True, force=True)
    live_from_cache = list(es_client.ALL_INDEXES)
    default_live = es_client.ES_INDEX_DEFAULT

    try:
        alias_map = es_client.get_es().indices.get_alias(index="*")
        raw_indexes = list((alias_map or {}).keys())
    except Exception:
        raw_indexes = live_from_cache

    merged: list[str] = []
    for idx in raw_indexes:
        s = str(idx or "").strip()
        if not s or s.startswith("."):
            continue
        if s not in merged:
            merged.append(s)

    if default_live and default_live not in merged:
        merged.insert(0, default_live)

    return merged


def ensure_allowed_index(index: str) -> None:
    indexes = current_indexes()
    if index not in indexes:
        raise HTTPException(status_code=400, detail=f"不允許或不存在的 index：{index}")
