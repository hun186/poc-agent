"""OFF-1G: one explicitly authorized SQL Server constant SELECT, partial only.

No connection or database import side effects. Never executes application SQL,
reads user tables, infers login permissions, starts a transaction or reports
environment values. All SQL connectivity needs BOTH caller flags in the matrix.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any

import pyodbc

from tools.sraf_airgap_off1_probes import Observation


DRIVER = "ODBC Driver 18 for SQL Server"
# Environment variables are *operator-provided*, separate from SRAF's
# privileged runtime SQL registries and ordinary production credentials.
ENV_KEYS = (
    "SRAF_OFF1G_SQL_HOST", "SRAF_OFF1G_SQL_PORT",
    "SRAF_OFF1G_SQL_DATABASE", "SRAF_OFF1G_SQL_USER",
    "SRAF_OFF1G_SQL_PASSWORD",
)
QUERY = "SELECT CAST(1 AS int)"
LOGIN_TIMEOUT_SECONDS = 3
QUERY_TIMEOUT_SECONDS = 3
_ALLOWED_IDENTITY = re.compile(r"[A-Za-z0-9_.@\\-]{1,128}\Z")


def _result(status: str, reason: str, *, executed: bool = False,
            success: bool = False) -> Observation:
    # No endpoint, database, user, secret, SQL text, SQLSTATE or native
    # exception is ever serialized.
    return Observation(
        "SQL-01", "sql-constant-read", "sql_server_constant_select_only",
        status, reason, executed, {"constant_select_observed": success},
    )


def _private_ip(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 15:
        return False
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (isinstance(ip, ipaddress.IPv4Address)
            and (ip.is_loopback or ip in ipaddress.ip_network("10.0.0.0/8")
                 or ip in ipaddress.ip_network("172.16.0.0/12")
                 or ip in ipaddress.ip_network("192.168.0.0/16"))
            and str(ip) == value)


def _valid_secret(value: Any) -> bool:
    # Conservative: no NUL/control/invalid ODBC string characters.
    # Braces below prevent semicolon or closing brace injecting an option.
    return (isinstance(value, str) and 1 <= len(value) <= 256
            and all(32 <= ord(ch) <= 126 for ch in value))


def _quote(value: str) -> str:
    # ODBC keyword-value brace quoting; double right braces.
    return "{" + value.replace("}", "}}") + "}"


def _connection_string(cfg: dict[str, str]) -> str | None:
    host = cfg.get(ENV_KEYS[0])
    port = cfg.get(ENV_KEYS[1])
    db = cfg.get(ENV_KEYS[2])
    user = cfg.get(ENV_KEYS[3])
    passwd = cfg.get(ENV_KEYS[4])
    if not _private_ip(host) or not isinstance(port, str):
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,4}", port):
        return None
    if not 1 <= int(port) <= 65535:
        return None
    if not isinstance(db, str) or not _ALLOWED_IDENTITY.fullmatch(db):
        return None
    if not isinstance(user, str) or not _ALLOWED_IDENTITY.fullmatch(user):
        return None
    if not _valid_secret(passwd):
        return None
    return (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER=tcp:{host},{port};"
        f"DATABASE={_quote(db)};UID={_quote(user)};"
        f"PWD={_quote(passwd)};"
        "Authentication=SqlPassword;"
        "Encrypt=Yes;TrustServerCertificate=No;"
        "ApplicationIntent=ReadOnly;"
        "MultiSubnetFailover=No;Connection Timeout=3;"
    )


def probe_sql_constant_read(cfg: dict[str, str]) -> Observation:
    """A single SQL round trip; no ability to attest principal read-onlyness.

    A *dedicated restricted account* is required by the operator contract.
    The driver enforces normal TLS peer/hostname validation: on a numeric IP,
    the server certificate must be valid for that IP. No fallback to
    TrustServerCertificate=Yes, host name resolution or DSN overrides.
    """
    connection = _connection_string(cfg)
    if connection is None:
        return _result("SKIP", "sql_read_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "sql_read_driver_unavailable")
    except Exception:
        return _result("SKIP", "sql_read_driver_unavailable")

    db = None
    cursor = None
    try:
        # Strict driver config: no DSN, no TrustServerCertificate override.
        db = pyodbc.connect(
            connection, timeout=LOGIN_TIMEOUT_SECONDS,
            autocommit=True,
        )
        # pyodbc's query timeout belongs to Connection, not Cursor.
        # Set it *before* cursor creation; a fake cursor attribute would
        # silently pass tests while always failing on real SQL Server.
        db.timeout = QUERY_TIMEOUT_SECONDS
        cursor = db.cursor()
        cursor.execute(QUERY)
        row = cursor.fetchone()
        additional = cursor.fetchone()
        if (row is None or type(row[0]) is not int or row[0] != 1
                or additional is not None):
            return _result("FAIL", "sql_read_response_invalid",
                           executed=True)
    except Exception:
        # SQLSTATE/native error strings can contain host, user and SQL text.
        # A timeout also cannot prove that a remote query was cancelled.
        return _result("SKIP", "sql_read_connection_unverified", executed=True)
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    return _result("PASS", "sql_constant_select_observed",
                   executed=True, success=True)
