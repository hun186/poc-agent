from __future__ import annotations

from typing import Any, Dict, Sequence

from .utils import get_nested, require_nested

DEFAULT_HASH_FIELD_TYPE = "CHAR(64)"


def quote_ident(name: str) -> str:
    if not name:
        raise ValueError("欄位名稱不可為空")
    return f"[{name.replace(']', ']]')}]"


def quote_object_path(name: str) -> str:
    parts = [part.strip() for part in name.split(".") if part.strip()]
    if not parts:
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


def destination_hash_field_exists(cursor, *, table: str, hash_field: str) -> bool:
    cursor.execute(
        f"SELECT COL_LENGTH({sql_string_literal(table)}, {sql_string_literal(hash_field)})"
    )
    row = cursor.fetchone()
    return bool(row and row[0] is not None)


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

    return True
