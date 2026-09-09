from __future__ import annotations

import json
import os
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyodbc

from data_ingestion.sql_server import detect_odbc_driver


_SQL_SS_TIMESTAMPOFFSET = -155


def _decode_datetimeoffset(value: bytes | None) -> datetime | None:
    if value is None:
        return None

    (
        year,
        month,
        day,
        hour,
        minute,
        second,
        fraction,
        offset_hours,
        offset_minutes,
    ) = struct.unpack("<6hI2h", value)
    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        fraction // 1000,
        tzinfo=timezone(
            timedelta(hours=offset_hours, minutes=offset_minutes)
        ),
    )


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
        try:
            config = self._document["connections"][name]
        except KeyError as exc:
            raise KeyError("unknown_connection_ref") from exc

        def resolve(key: str) -> str:
            env_key = f"{key}_env"
            if env_key in config:
                env_name = str(config.get(env_key, "")).strip()
                return os.getenv(env_name, "") if env_name else ""
            value = config.get(key, "")
            return "" if value is None else str(value).strip()

        server = resolve("server")
        database = resolve("database")
        if not server:
            raise ValueError("SQL connection requires server")
        if not database:
            raise ValueError("SQL connection requires database")

        trusted = resolve("trusted_connection").casefold() in {"1", "true", "yes"}
        user = password = ""
        if not trusted:
            user = resolve("user")
            password = resolve("password")
            if not user:
                raise ValueError("SQL authentication requires user")
            if not password:
                raise ValueError("SQL authentication requires password")

        configured_driver = resolve("driver")
        if "driver_env" in config and not configured_driver:
            raise ValueError("SQL connection requires driver")
        driver = detect_odbc_driver(configured_driver or "auto")
        parts = [f"DRIVER={{{driver}}}", f"SERVER={server}", f"DATABASE={database}"]
        if trusted:
            parts.append("Trusted_Connection=yes")
        else:
            parts.extend((f"UID={user}", f"PWD={password}"))
        parts.extend((f"Encrypt={'yes' if config.get('encrypt', True) else 'no'}", f"TrustServerCertificate={'yes' if config.get('trust_server_certificate', False) else 'no'}"))
        connection = pyodbc.connect(";".join(parts), autocommit=False)
        connection.add_output_converter(
            _SQL_SS_TIMESTAMPOFFSET,
            _decode_datetimeoffset,
        )
        return connection
