"""Configuration and access helpers for a document's context-rich reference text."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from typing import Any


REFERENCE_TEXT_FIELD_ENV = "SRA_REFERENCE_TEXT_FIELD"
DEFAULT_REFERENCE_TEXT_FIELD = "rawInfo.content"
_VALID_FIELD_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


def get_reference_text_field() -> str:
    """Return the ES field used as the agent's coherent reference text.

    The value is read at call time so process launch configuration and tests can
    change it without relying on module import order. Invalid field paths fall
    back to the backwards-compatible default rather than entering an ES query.
    """
    configured = (os.getenv(REFERENCE_TEXT_FIELD_ENV) or "").strip()
    if configured and _VALID_FIELD_PATH.fullmatch(configured):
        return configured
    return DEFAULT_REFERENCE_TEXT_FIELD


def get_by_dot_path(source: Any, path: str) -> Any:
    current = source
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def get_reference_text(source: Any, *, field: str | None = None) -> str:
    """Read and normalize the configured coherent reference text from `_source`."""
    value = get_by_dot_path(source, field or get_reference_text_field())
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return ""


def set_reference_text(source: dict[str, Any], text: str, *, field: str | None = None) -> None:
    """Write reference text to a configured dot path without flattening the field name."""
    parts = (field or get_reference_text_field()).split(".")
    current: dict[str, Any] = source
    for part in parts[:-1]:
        existing = current.get(part)
        if existing is None:
            existing = {}
            current[part] = existing
        if not isinstance(existing, dict):
            raise ValueError(f"Reference text path conflicts with non-object field: {part}")
        current = existing
    existing_leaf = current.get(parts[-1])
    if isinstance(existing_leaf, dict):
        raise ValueError(f"Reference text path conflicts with object field: {'.'.join(parts)}")
    current[parts[-1]] = text


def set_ingested_text(source: dict[str, Any], text: str) -> None:
    """Preserve raw input and seed the configured reference field.

    Keeping ``rawInfo.content`` makes newly ingested documents readable by old
    deployments and retains audit material. When the configured reference field
    differs, it is initially seeded with the same input and may later be replaced
    by the cleaning/refinement pipeline without mutating the raw layer.
    """
    set_reference_text(source, text, field=DEFAULT_REFERENCE_TEXT_FIELD)
    reference_field = get_reference_text_field()
    if reference_field != DEFAULT_REFERENCE_TEXT_FIELD:
        set_reference_text(source, text, field=reference_field)


def add_reference_text_mapping(
    mappings: dict[str, Any], *, field: str | None = None,
) -> dict[str, Any]:
    """Return a mapping copy containing a `text` leaf for the reference field."""
    result = deepcopy(mappings)
    properties = result.setdefault("properties", {})
    parts = (field or get_reference_text_field()).split(".")
    for part in parts[:-1]:
        node = properties.setdefault(part, {})
        if not isinstance(node, dict) or node.get("type") not in (None, "object", "nested"):
            raise ValueError(f"Reference text mapping conflicts at: {part}")
        properties = node.setdefault("properties", {})
    leaf = properties.get(parts[-1])
    if leaf is not None and (not isinstance(leaf, dict) or leaf.get("type") != "text"):
        raise ValueError(f"Reference text mapping conflicts at: {'.'.join(parts)}")
    if leaf is None:
        properties[parts[-1]] = {"type": "text"}
    return result
