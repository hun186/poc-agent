# api/services/editor_form_config.py
from __future__ import annotations

import fnmatch
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from config.bootstrap import bootstrap_env
from .editor_index_utils import get_index_field_metadata_map


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_form_config_path() -> Path:
    return _project_root() / "config" / "editor_form.default.json"


def form_config_path() -> Path:
    bootstrap_env()
    configured = (os.getenv("SRA_EDITOR_FORM_CONFIG") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return default_form_config_path()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"editor form config must be a JSON object: {path}")
    return data


def load_editor_form_config() -> dict[str, Any]:
    path = form_config_path()
    data = _load_json(path)
    data.setdefault("version", 1)
    data.setdefault("default_schema", "default")
    data.setdefault("index_schema_map", {})
    data.setdefault("schemas", {})
    if not isinstance(data["schemas"], dict) or not data["schemas"]:
        raise ValueError(f"editor form config requires non-empty schemas: {path}")
    if data["default_schema"] not in data["schemas"]:
        data["default_schema"] = next(iter(data["schemas"].keys()))
    data["config_path"] = str(path)
    return data


def _schema_name_for_index(config: dict[str, Any], index: str | None) -> str:
    default = str(config.get("default_schema") or "")
    if not index:
        return default
    mapping = config.get("index_schema_map") or {}
    if not isinstance(mapping, dict):
        return default
    if index in mapping:
        return str(mapping[index])
    for pattern, schema_name in mapping.items():
        if fnmatch.fnmatch(index, str(pattern)):
            return str(schema_name)
    return default


def get_editor_schema(index: str | None = None, schema_name: str | None = None) -> dict[str, Any]:
    config = load_editor_form_config()
    schemas = config.get("schemas") or {}
    selected = schema_name or _schema_name_for_index(config, index)
    if selected not in schemas:
        selected = config.get("default_schema")
    schema = deepcopy(schemas[selected])
    schema.setdefault("label", selected)
    schema.setdefault("description", "")
    schema.setdefault("sections", [])
    schema.setdefault("search_fields", ["title^3", "subject^3", "uuid^2", "content", "full_text", "rawInfo.content"])
    schema.setdefault("search_source_fields", ["uuid", "title", "subject", "communication.subject", "rawInfo.title", "rawInfo.date"])
    schema["name"] = selected
    schema["config_path"] = config.get("config_path")
    return schema


def _field_path_for_mapping(section: dict[str, Any], field: dict[str, Any]) -> str:
    field_path = str(field.get("path") or "").strip()
    section_path = str(section.get("path") or "").strip()
    if section.get("type") == "array" and section_path and field_path and "." not in field_path:
        return f"{section_path}.{field_path}"
    return field_path


def _ui_type_from_mapping(mapping_type: str) -> str | None:
    mt = mapping_type.lower()
    if mt in {"integer", "long", "short", "byte", "double", "float", "half_float", "scaled_float"}:
        return "number"
    if mt == "boolean":
        return "boolean"
    if mt == "date":
        return "date"
    if mt in {"keyword", "constant_keyword", "wildcard", "text", "match_only_text"}:
        return "text"
    return None


def _merge_mapping_metadata(schema: dict[str, Any], index: str | None) -> tuple[dict[str, Any], bool]:
    if not index:
        return {}, False
    field_meta, ok = get_index_field_metadata_map(index)
    if not ok:
        return {}, False

    for section in schema.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_path = str(section.get("path") or "").strip()
        if section_path and section_path in field_meta:
            section["mapping"] = dict(field_meta[section_path])
        for field in section.get("fields") or []:
            if not isinstance(field, dict):
                continue
            mapping_path = _field_path_for_mapping(section, field)
            meta = field_meta.get(mapping_path)
            if not meta:
                continue
            field["mapping_path"] = mapping_path
            field["mapping"] = dict(meta)
            mapping_type = str(meta.get("type") or "")
            inferred_type = _ui_type_from_mapping(mapping_type)
            if inferred_type and field.get("type") in (None, "", "auto", "text"):
                field["type"] = inferred_type

    return field_meta, True


def public_editor_form_config(index: str | None = None, schema_name: str | None = None) -> dict[str, Any]:
    config = load_editor_form_config()
    schema = get_editor_schema(index=index, schema_name=schema_name)
    mapping_fields, mapping_ok = _merge_mapping_metadata(schema, index)
    return {
        "version": config.get("version", 1),
        "default_schema": config.get("default_schema"),
        "selected_schema": schema.get("name"),
        "index": index,
        "config_path": config.get("config_path"),
        "mapping_ok": mapping_ok,
        "mapping_field_count": len(mapping_fields),
        "schema": schema,
    }
