"""Safe, opt-in SQL Server OFF-1G constant-read evidence for SRAF hub.

The application connection registry is never used. The caller provides a
separately authorized, least-privilege SQL login through the five exact
SRAF_OFF1G_SQL_* environment variables. This component delegates a single
TLS-checked constant SELECT to the preexisting OFF-1G probe; neither a
successful SELECT nor an ODBC connection attests SQL schema, data lineage,
SELECT-only permissions or scheduled Handoff E2E.
"""
from __future__ import annotations

import os

from tools.sraf_airgap_off1g_sql_read import ENV_KEYS, probe_sql_constant_read


def sql_constant_read_observation() -> dict[str, object]:
    """Return fixed redacted evidence, never native ODBC status or secrets."""
    unavailable = {
        "check": "sql_constant_read", "status": "SKIP",
        "reason": "sql_read_observation_unavailable",
        "constant_select_observed": False,
    }
    try:
        # Do NOT load SRAF's production connection registry or .env.local.
        # Values are read only after the operator explicitly selects this mode.
        cfg = {key: os.environ.get(key, "") for key in ENV_KEYS}
        result = probe_sql_constant_read(cfg)
        if (result.check_id != "SQL-01"
                or result.probe != "sql-constant-read"
                or result.aspect != "sql_server_constant_select_only"
                or type(result.executed) is not bool
                or not isinstance(result.evidence, dict)):
            return unavailable
        passed = (result.status == "PASS"
                  and result.reason == "sql_constant_select_observed"
                  and result.executed is True
                  and result.evidence.get("constant_select_observed") is True)
        if passed:
            return {
                "check": "sql_constant_read", "status": "PASS",
                "reason": "sql_constant_select_observed",
                "constant_select_observed": True,
            }
        if (result.status == "FAIL"
                and result.reason == "sql_read_response_invalid"
                and result.executed is True
                and result.evidence.get("constant_select_observed") is False):
            return {
                "check": "sql_constant_read", "status": "FAIL",
                "reason": "sql_read_response_invalid",
                "constant_select_observed": False,
            }
        skips = {
            "sql_read_config_invalid", "sql_read_driver_unavailable",
            "sql_read_connection_unverified",
        }
        if (result.status == "SKIP" and result.reason in skips
                and result.evidence.get("constant_select_observed") is False):
            return {
                "check": "sql_constant_read", "status": "SKIP",
                "reason": result.reason,
                "constant_select_observed": False,
            }
        return unavailable
    except Exception:
        # Never emit native SQLSTATE, host, user, database, password or query.
        return unavailable
