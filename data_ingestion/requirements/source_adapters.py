from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .connections import SqlRegistry
from .hashing import canonical_sha256
from .models import AcquiredSource, ImportProfileDocument, SourceType
from .readers import read_bytes


FORBIDDEN_CONFIG_PARTS = ("password", "passwd", "token", "authorization", "secret", "connection_string", "connectionstring")


def validate_source_config(source_type: SourceType | str, config: dict[str, Any]) -> dict[str, Any]:
    kind = SourceType(source_type)
    keys = {str(key).casefold() for key in config}
    if any(any(part in key for part in FORBIDDEN_CONFIG_PARTS) for key in keys) or "sql" in keys or "query" in keys:
        raise ValueError("source_config_secret_or_executable_rejected")
    allowed = {
        SourceType.MANUAL_UPLOAD: {"display_name", "format"},
        SourceType.FILE_PATH: {"path", "directory", "file_pattern", "format"},
        SourceType.SQL_QUERY: {"connection_ref", "query_ref"},
    }[kind]
    if keys - allowed:
        raise ValueError("source_config_invalid")
    if kind == SourceType.SQL_QUERY and set(config) != {"connection_ref", "query_ref"}:
        raise ValueError("source_config_invalid")
    return dict(config)


def _confined_file(config: dict[str, Any], allowed_roots: str | None) -> Path:
    roots = [Path(value).resolve(strict=False) for value in (allowed_roots if allowed_roots is not None else os.getenv("REQUIREMENT_SOURCE_ALLOWED_ROOTS", "")).split(os.pathsep) if value]
    if not roots: raise PermissionError("source_path_outside_allowed_root")
    if config.get("path"):
        matches = [Path(str(config["path"]))]
    else:
        directory = Path(str(config.get("directory") or ""))
        matches = list(directory.glob(str(config.get("file_pattern") or "")))
    if len(matches) != 1: raise ValueError("source_file_match_count_invalid")
    path = matches[0].resolve(strict=False)
    if not any(os.path.normcase(os.path.commonpath([str(path), str(root)])) == os.path.normcase(str(root)) for root in roots):
        raise PermissionError("source_path_outside_allowed_root")
    if not path.is_file(): raise FileNotFoundError("source_unavailable")
    return path


def acquire_source(source: dict[str, Any], profile: ImportProfileDocument, *, upload_bytes: bytes | None = None, upload_filename: str | None = None, registry: SqlRegistry | None = None, allowed_roots: str | None = None) -> AcquiredSource:
    kind = SourceType(source["source_type"])
    config = validate_source_config(kind, source.get("source_config", {}))
    if kind == SourceType.MANUAL_UPLOAD:
        if upload_bytes is None or not upload_filename: raise ValueError("manual_upload_required")
        safe_name = Path(upload_filename).name
        rows, numbers = read_bytes(upload_bytes, safe_name, profile)
        fingerprint = canonical_sha256({"bytes_sha256": __import__("hashlib").sha256(upload_bytes).hexdigest()})
        return AcquiredSource(rows=rows, source_row_numbers=numbers, source_sha256=fingerprint, source_uri_display=safe_name)
    if upload_bytes is not None: raise ValueError("upload_not_allowed")
    if kind == SourceType.FILE_PATH:
        path = _confined_file(config, allowed_roots)
        content = path.read_bytes()
        rows, numbers = read_bytes(content, path.name, profile)
        return AcquiredSource(rows=rows, source_row_numbers=numbers, source_sha256=canonical_sha256({"bytes_sha256": __import__("hashlib").sha256(content).hexdigest()}), source_uri_display=path.name)
    if registry is None: raise RuntimeError("sql_read_error")
    query = registry.query(str(config["query_ref"]))
    if query.get("connection_ref") != config["connection_ref"]: raise ValueError("source_config_invalid")
    connection = registry.open_named_connection(str(config["connection_ref"]))
    try:
        cursor = connection.cursor(); cursor.execute(str(query["sql"])); headers = [column[0] for column in cursor.description]
        rows = [dict(zip(headers, row, strict=True)) for row in cursor.fetchall()]
    finally:
        connection.close()
    return AcquiredSource(rows=rows, source_row_numbers=list(range(1, len(rows) + 1)), source_sha256=canonical_sha256(rows), source_uri_display=f"sql:{config['query_ref']}")
