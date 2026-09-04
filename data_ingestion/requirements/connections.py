from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pyodbc


class SqlRegistry:
    def __init__(self, document: dict[str, Any]):
        self._document = document

    @classmethod
    def load(cls, path: str | Path) -> "SqlRegistry":
        with Path(path).open(encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict) or not isinstance(value.get("connections"), dict) or not isinstance(value.get("queries", {}), dict):
            raise ValueError("invalid SQL registry")
        return cls(value)

    def public_view(self) -> dict[str, Any]:
        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items() if not any(word in key.casefold() for word in ("password", "token", "secret", "sql"))}
            return value
        return clean(self._document)

    def query(self, reference: str) -> dict[str, Any]:
        try: return dict(self._document["queries"][reference])
        except KeyError as exc: raise KeyError("unknown_query_ref") from exc

    def open_named_connection(self, name: str):
        try: config = self._document["connections"][name]
        except KeyError as exc: raise KeyError("unknown_connection_ref") from exc
        def env(key: str) -> str:
            env_name = config.get(f"{key}_env")
            return os.getenv(env_name, "") if env_name else str(config.get(key, ""))
        parts = [f"DRIVER={{{env('driver') or 'ODBC Driver 18 for SQL Server'}}}", f"SERVER={env('server')}", f"DATABASE={env('database')}"]
        trusted = env("trusted_connection").casefold() in {"1", "true", "yes"}
        if trusted: parts.append("Trusted_Connection=yes")
        else: parts.extend((f"UID={env('user')}", f"PWD={env('password')}"))
        parts.extend((f"Encrypt={'yes' if config.get('encrypt', True) else 'no'}", f"TrustServerCertificate={'yes' if config.get('trust_server_certificate', False) else 'no'}"))
        return pyodbc.connect(";".join(parts), autocommit=False)
