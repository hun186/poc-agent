from __future__ import annotations

import re
from typing import Any, Dict, Sequence

from .utils import get_nested, require_nested

DEFAULT_HASH_FIELD_TYPE = "CHAR(64)"
DEFAULT_AUTO_CREATED_FIELD_TYPE = "NVARCHAR(MAX)"

_NUMERIC_TYPE_RE = re.compile(r"^(?:DECIMAL|NUMERIC)\((\d{1,2})\s*,\s*(\d{1,2})\)$")
_TEXT_TYPE_RE = re.compile(r"^(?:N?VARCHAR|N?CHAR)\((?:MAX|\d{1,4})\)$")
_DATETIME2_TYPE_RE = re.compile(r"^DATETIME2(?:\([0-7]\))?$")


def quote_ident(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("欄位名稱不可為空")
    if len(name) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("欄位名稱包含不允許的字元或超過 128 字元")
    return f"[{name.replace(']', ']]')}]"


def quote_object_path(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError(f"無效物件名稱: {name}")
    parts = [part.strip() for part in name.split(".")]
    if not parts or len(parts) > 3 or any(not part for part in parts):
        raise ValueError(f"無效物件名稱: {name}")
    return ".".join(quote_ident(part) for part in parts)


def detect_odbc_driver(configured_driver: Any = None, *, verbose: bool = True) -> str:
    """Choose an installed SQL Server ODBC driver, preferring the configured one."""

    fallback_drivers = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]

    if isinstance(configured_driver, (list, tuple)):
        configured_drivers = [str(item).strip() for item in configured_driver if str(item).strip()]
    elif configured_driver is None:
        configured_drivers = []
    else:
        raw = str(configured_driver).strip()
        configured_drivers = [] if raw.lower() in {"", "auto", "detect"} else [raw]

    candidates = configured_drivers + [driver for driver in fallback_drivers if driver not in configured_drivers]

    try:
        import pyodbc

        installed = [str(driver) for driver in pyodbc.drivers()]
    except Exception as exc:
        if configured_drivers:
            if verbose:
                print(f"⚠️ 無法列出已安裝 ODBC drivers，沿用設定檔 driver：{configured_drivers[0]}；{exc}")
            return configured_drivers[0]
        raise RuntimeError(f"無法列出已安裝 ODBC drivers，且 db.driver 未指定可用 driver：{exc}") from exc

    installed_lookup = {driver.lower(): driver for driver in installed}
    for candidate in candidates:
        matched = installed_lookup.get(candidate.lower())
        if matched:
            if verbose and configured_drivers and matched.lower() != configured_drivers[0].lower():
                print(
                    f"⚠️ 設定檔 ODBC driver '{configured_drivers[0]}' 未安裝，"
                    f"自動改用已安裝 driver '{matched}'"
                )
            return matched

    configured_text = ", ".join(configured_drivers) if configured_drivers else "auto"
    installed_text = ", ".join(installed) if installed else "（未偵測到任何 ODBC driver）"
    raise RuntimeError(
        "找不到可用的 SQL Server ODBC driver；"
        f"設定值：{configured_text}；已安裝 drivers：{installed_text}。"
        "請安裝 Microsoft ODBC Driver 18/17 for SQL Server，或調整 db.driver。"
    )


def build_conn_str_from_config(cfg: Dict[str, Any]) -> str:
    driver = detect_odbc_driver(get_nested(cfg, "db.driver", "auto"))
    server = require_nested(cfg, "db.server")
    database = require_nested(cfg, "db.database")
    trusted_connection = bool(get_nested(cfg, "db.trusted_connection", False))
    user = get_nested(cfg, "db.user", "")
    password = get_nested(cfg, "db.password", "")
    encrypt = bool(get_nested(cfg, "db.encrypt", False))
    trust_cert = bool(get_nested(cfg, "db.trust_server_certificate", False))

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
    ]

    if trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        if not user:
            raise ValueError("設定檔缺少 db.user")
        if not password:
            raise ValueError("設定檔缺少 db.password")
        parts.append(f"UID={user}")
        parts.append(f"PWD={password}")

    if encrypt:
        parts.append("Encrypt=yes")
    if trust_cert:
        parts.append("TrustServerCertificate=yes")

    return ";".join(parts)


def build_insert_sql(table: str, dest_fields: Sequence[str]) -> str:
    if not dest_fields:
        raise ValueError("目的欄位不可為空")
    columns_sql = ", ".join(quote_ident(field) for field in dest_fields)
    params_sql = ", ".join("?" for _ in dest_fields)
    return f"INSERT INTO {quote_object_path(table)} ({columns_sql}) VALUES ({params_sql})"


def build_select_existing_hashes_sql(table: str, hash_field: str, count: int) -> str:
    params_sql = ", ".join("?" for _ in range(count))
    return (
        f"SELECT {quote_ident(hash_field)} FROM {quote_object_path(table)} "
        f"WHERE {quote_ident(hash_field)} IN ({params_sql})"
    )


def sql_string_literal(value: str) -> str:
    return "N'" + str(value).replace("'", "''") + "'"


def safe_index_name(table: str, hash_field: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in f"UX_{table}_{hash_field}")
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    if not cleaned:
        cleaned = f"UX_{hash_field}"
    return cleaned[:128]


def validate_hash_field_type(field_type: str) -> str:
    normalized = " ".join(str(field_type or DEFAULT_HASH_FIELD_TYPE).strip().upper().split())
    allowed = {
        "CHAR(64)",
        "NCHAR(64)",
        "VARCHAR(64)",
        "NVARCHAR(64)",
    }
    if normalized not in allowed:
        raise ValueError(
            "destination.hash_field_type 僅支援 CHAR(64)、NCHAR(64)、"
            "VARCHAR(64) 或 NVARCHAR(64)，避免 ALTER TABLE 注入風險。"
        )
    return normalized


def destination_column_exists(cursor, *, table: str, field: str) -> bool:
    cursor.execute(f"SELECT COL_LENGTH({sql_string_literal(table)}, {sql_string_literal(field)})")
    row = cursor.fetchone()
    return bool(row and row[0] is not None)


def destination_table_exists(cursor, *, table: str) -> bool:
    cursor.execute(f"SELECT OBJECT_ID({sql_string_literal(table)}, N'U')")
    row = cursor.fetchone()
    return bool(row and row[0] is not None)


def create_destination_hash_index(cursor, *, table: str, hash_field: str) -> None:
    index_name = safe_index_name(table, hash_field)
    index_literal = sql_string_literal(index_name)
    table_literal = sql_string_literal(table)
    cursor.execute(
        f"""
IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = {index_literal}
      AND object_id = OBJECT_ID({table_literal})
)
BEGIN
    CREATE UNIQUE INDEX {quote_ident(index_name)}
    ON {quote_object_path(table)} ({quote_ident(hash_field)})
    WHERE {quote_ident(hash_field)} IS NOT NULL;
END
"""
    )


def validate_auto_created_field_type(field_type: str) -> str:
    normalized = " ".join(str(field_type or DEFAULT_AUTO_CREATED_FIELD_TYPE).strip().upper().split())
    normalized = normalized.replace(" (", "(").replace(" ,", ",").replace(", ", ",")
    simple_allowed = {
        "BIT",
        "TINYINT",
        "SMALLINT",
        "INT",
        "BIGINT",
        "FLOAT",
        "REAL",
        "DATE",
        "DATETIME",
        "SMALLDATETIME",
        "DATETIMEOFFSET",
        "TIME",
        "UNIQUEIDENTIFIER",
        "MONEY",
        "SMALLMONEY",
    }
    if normalized in simple_allowed or _TEXT_TYPE_RE.match(normalized) or _DATETIME2_TYPE_RE.match(normalized):
        return normalized

    numeric_match = _NUMERIC_TYPE_RE.match(normalized)
    if numeric_match:
        precision = int(numeric_match.group(1))
        scale = int(numeric_match.group(2))
        if 1 <= precision <= 38 and 0 <= scale <= precision:
            return normalized

    raise ValueError(
        "SQL 欄位型別不在安全允許清單中；請使用常見純量型別，例如 "
        "NVARCHAR(255)、NVARCHAR(MAX)、INT、BIGINT、DECIMAL(18,2)、DATE 或 DATETIME2。"
    )


def infer_auto_created_field_type(mapping: Dict[str, Any], default_field_type: str = DEFAULT_AUTO_CREATED_FIELD_TYPE) -> str:
    configured_type = (
        mapping.get("dest_field_type")
        or mapping.get("destination_field_type")
        or mapping.get("sql_type")
        or mapping.get("data_type")
    )
    if configured_type:
        return validate_auto_created_field_type(str(configured_type))
    if str(mapping.get("value_type", "")).strip().lower() in {"date", "sql_date"}:
        return "DATE"
    return validate_auto_created_field_type(default_field_type)


def ensure_destination_table(
    cursor,
    *,
    table: str,
    mappings: Sequence[Dict[str, Any]],
    default_field_type: str = DEFAULT_AUTO_CREATED_FIELD_TYPE,
    hash_field: str | None = None,
    hash_field_type: str = DEFAULT_HASH_FIELD_TYPE,
    create_hash_index: bool = True,
) -> Dict[str, str]:
    """Ensure the destination table exists; return created columns and SQL types."""

    if destination_table_exists(cursor, table=table):
        return {}

    columns: Dict[str, str] = {}
    for mapping in mappings:
        field = str(mapping.get("dest_field", "")).strip()
        if not field or field in columns:
            continue
        columns[field] = infer_auto_created_field_type(mapping, default_field_type)

    clean_hash_field = str(hash_field or "").strip()
    if clean_hash_field and clean_hash_field not in columns:
        columns[clean_hash_field] = validate_hash_field_type(hash_field_type)

    if not columns:
        raise ValueError("無法自動建立目的資料表：沒有可建立的目的欄位。")

    column_sql = ",\n    ".join(
        f"{quote_ident(field)} {field_type} NULL"
        for field, field_type in columns.items()
    )
    cursor.execute(
        f"CREATE TABLE {quote_object_path(table)} (\n"
        f"    {column_sql}\n"
        ")"
    )

    if clean_hash_field and create_hash_index and clean_hash_field in columns:
        create_destination_hash_index(cursor, table=table, hash_field=clean_hash_field)

    return columns


def ensure_destination_columns(
    cursor,
    *,
    table: str,
    mappings: Sequence[Dict[str, Any]],
    default_field_type: str = DEFAULT_AUTO_CREATED_FIELD_TYPE,
) -> Dict[str, str]:
    """Ensure mapped destination columns exist; return created columns and SQL types."""

    created: Dict[str, str] = {}
    for mapping in mappings:
        field = str(mapping.get("dest_field", "")).strip()
        if not field or field in created:
            continue
        if destination_column_exists(cursor, table=table, field=field):
            continue
        field_type = infer_auto_created_field_type(mapping, default_field_type)
        cursor.execute(
            f"ALTER TABLE {quote_object_path(table)} "
            f"ADD {quote_ident(field)} {field_type} NULL"
        )
        created[field] = field_type
    return created


def destination_hash_field_exists(cursor, *, table: str, hash_field: str) -> bool:
    return destination_column_exists(cursor, table=table, field=hash_field)


def ensure_destination_hash_field(
    cursor,
    *,
    table: str,
    hash_field: str,
    field_type: str = DEFAULT_HASH_FIELD_TYPE,
    create_unique_index: bool = True,
) -> bool:
    """Ensure the destination table has the configured hash column.

    Returns True when the column was created during this call.
    """
    if destination_hash_field_exists(cursor, table=table, hash_field=hash_field):
        return False

    safe_field_type = validate_hash_field_type(field_type)
    cursor.execute(
        f"ALTER TABLE {quote_object_path(table)} "
        f"ADD {quote_ident(hash_field)} {safe_field_type} NULL"
    )

    if create_unique_index:
        create_destination_hash_index(cursor, table=table, hash_field=hash_field)

    return True
