"""SQL hub projection tests: never access a live database."""
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1_sql_hub as hub
from tools import sraf_airgap_off1g_sql_read as sql


def _obs(status="PASS", reason="sql_constant_select_observed",
         executed=True, observed=True, **extra):
    return SimpleNamespace(
        check_id=extra.get("check_id", "SQL-01"),
        probe=extra.get("probe", "sql-constant-read"),
        aspect=extra.get("aspect", "sql_server_constant_select_only"),
        status=status, reason=reason, executed=executed,
        evidence=extra.get("evidence", {"constant_select_observed": observed}),
    )


def test_sql_uses_only_dedicated_operator_environment(monkeypatch):
    monkeypatch.setenv("SRAF_OFF1G_SQL_HOST", "192.168.20.40")
    monkeypatch.setenv("SRAF_OFF1G_SQL_PASSWORD", "SECRET")
    monkeypatch.setenv("ES_PASSWORD", "MUST_NOT_READ")
    monkeypatch.setenv("SRA_BOOTSTRAP_SUPERUSER_PASSWORD", "MUST_NOT_READ")
    seen = []
    def fake(cfg):
        seen.append(cfg)
        return _obs()
    monkeypatch.setattr(hub, "probe_sql_constant_read", fake)
    result = hub.sql_constant_read_observation()
    assert len(seen) == 1
    assert set(seen[0]) == set(sql.ENV_KEYS)
    assert seen[0]["SRAF_OFF1G_SQL_PASSWORD"] == "SECRET"
    assert result == {
        "check": "sql_constant_read", "status": "PASS",
        "reason": "sql_constant_select_observed",
        "constant_select_observed": True,
    }
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("status,reason,executed,observed,expected", [
    ("FAIL", "sql_read_response_invalid", True, False, ("FAIL", "sql_read_response_invalid")),
    ("SKIP", "sql_read_driver_unavailable", False, False, ("SKIP", "sql_read_driver_unavailable")),
    ("SKIP", "sql_read_config_invalid", False, False, ("SKIP", "sql_read_config_invalid")),
    ("SKIP", "sql_read_connection_unverified", True, False, ("SKIP", "sql_read_connection_unverified")),
])
def test_closed_sql_statuses(monkeypatch, status, reason, executed, observed, expected):
    monkeypatch.setattr(hub, "probe_sql_constant_read",
                        lambda _: _obs(status, reason, executed, observed))
    out = hub.sql_constant_read_observation()
    assert (out["status"], out["reason"]) == expected
    assert out["constant_select_observed"] is False


@pytest.mark.parametrize("result", [
    _obs("PASS", "sql_constant_select_observed", True, False),
    _obs("PASS", "sql_constant_select_observed", False, True),
    _obs("PASS", "SECRET", True, True),
    _obs("SKIP", "SECRET", False, False),
    _obs("FAIL", "sql_read_response_invalid", True, True),
    _obs("PASS", "sql_constant_select_observed", True, True, check_id="BAD"),
    _obs("PASS", "sql_constant_select_observed", True, True, probe="BAD"),
    _obs("PASS", "sql_constant_select_observed", True, True, aspect="BAD"),
    _obs("PASS", "sql_constant_select_observed", True, True, evidence={"constant_select_observed": "True"}),
    None,
    OSError("SECRET_SQLSTATE_PASSWORD_HOST"),
])
def test_forged_or_failed_probe_is_sanitized(monkeypatch, result):
    def probe(_):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(hub, "probe_sql_constant_read", probe)
    out = hub.sql_constant_read_observation()
    assert out == {
        "check": "sql_constant_read", "status": "SKIP",
        "reason": "sql_read_observation_unavailable",
        "constant_select_observed": False,
    }
    assert "SECRET" not in str(out)
