import json
from pathlib import Path

import pytest

from data_ingestion.requirements import connections
from data_ingestion.requirements.connections import SqlRegistry


class FakePyodbc:
    def __init__(self):
        self.calls = []

    def connect(self, connection_string, *, autocommit):
        self.calls.append((connection_string, autocommit))
        return object()


def registry(connection):
    return SqlRegistry({"connections": {"requirement_control": connection}, "queries": {}})


def open_connection(monkeypatch, config, *, detected="ODBC Driver 18 for SQL Server"):
    fake = FakePyodbc()
    monkeypatch.setattr(connections, "pyodbc", fake)
    requested = []

    def detect(value, *, verbose=True):
        requested.append(value)
        return detected

    monkeypatch.setattr(connections, "detect_odbc_driver", detect)
    registry(config).open_named_connection("requirement_control")
    return fake.calls[0], requested


def direct_config(**overrides):
    value = {
        "driver": "auto",
        "server": "sql.example.invalid",
        "database": "requirements",
        "trusted_connection": False,
        "user": "operator",
        "password": "not-a-real-password",
        "encrypt": True,
        "trust_server_certificate": True,
    }
    value.update(overrides)
    return value


def test_direct_keys_and_auto_driver_use_shared_resolution(monkeypatch):
    (connection_string, autocommit), requested = open_connection(monkeypatch, direct_config())
    assert requested == ["auto"]
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in connection_string
    assert "SERVER=sql.example.invalid" in connection_string
    assert "DATABASE=requirements" in connection_string
    assert "UID=operator" in connection_string
    assert "PWD=not-a-real-password" in connection_string
    assert "Encrypt=yes" in connection_string
    assert "TrustServerCertificate=yes" in connection_string
    assert autocommit is False


def test_detect_alias_and_explicit_driver_are_passed_to_shared_resolution(monkeypatch):
    (_, _), requested = open_connection(monkeypatch, direct_config(driver="detect"))
    assert requested == ["detect"]
    (_, _), requested = open_connection(
        monkeypatch,
        direct_config(driver="ODBC Driver 17 for SQL Server"),
        detected="ODBC Driver 17 for SQL Server",
    )
    assert requested == ["ODBC Driver 17 for SQL Server"]


def test_legacy_environment_keys_work_and_override_direct_values(monkeypatch):
    config = direct_config(
        driver_env="REQ_DRIVER",
        server_env="REQ_SERVER",
        database_env="REQ_DATABASE",
        trusted_connection_env="REQ_TRUSTED",
        user_env="REQ_USER",
        password_env="REQ_PASSWORD",
    )
    values = {
        "REQ_DRIVER": "detect",
        "REQ_SERVER": "environment-server",
        "REQ_DATABASE": "environment-database",
        "REQ_TRUSTED": "false",
        "REQ_USER": "environment-user",
        "REQ_PASSWORD": "environment-password",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    (connection_string, _), requested = open_connection(monkeypatch, config)
    assert requested == ["detect"]
    assert "SERVER=environment-server" in connection_string
    assert "DATABASE=environment-database" in connection_string
    assert "UID=environment-user" in connection_string
    assert "PWD=environment-password" in connection_string
    assert "sql.example.invalid" not in connection_string


@pytest.mark.parametrize("key", ["driver", "server", "database", "user", "password"])
def test_configured_environment_source_fails_closed_when_absent(monkeypatch, key):
    environment_name = f"MISSING_{key.upper()}"
    config = direct_config(**{f"{key}_env": environment_name})
    monkeypatch.delenv(environment_name, raising=False)
    with pytest.raises(ValueError, match=key) as exc:
        registry(config).open_named_connection("requirement_control")
    assert "not-a-real-password" not in str(exc.value)


def test_trusted_connection_omits_sql_credentials(monkeypatch):
    (connection_string, _), _ = open_connection(monkeypatch, direct_config(trusted_connection=True))
    assert "Trusted_Connection=yes" in connection_string
    assert "UID=" not in connection_string
    assert "PWD=" not in connection_string


@pytest.mark.parametrize(("key", "message"), [("server", "server"), ("database", "database")])
def test_missing_address_fails_before_connect(monkeypatch, key, message):
    fake = FakePyodbc()
    monkeypatch.setattr(connections, "pyodbc", fake)
    with pytest.raises(ValueError, match=message):
        registry(direct_config(**{key: "  "})).open_named_connection("requirement_control")
    assert fake.calls == []


@pytest.mark.parametrize("key", ["user", "password"])
def test_sql_authentication_requires_credentials_without_leaking_them(monkeypatch, key):
    fake = FakePyodbc()
    monkeypatch.setattr(connections, "pyodbc", fake)
    with pytest.raises(ValueError, match=key) as exc:
        registry(direct_config(**{key: ""})).open_named_connection("requirement_control")
    assert "not-a-real-password" not in str(exc.value)
    assert fake.calls == []


def test_public_view_redacts_direct_and_environment_password_configuration():
    view = registry(direct_config(password_env="REQ_PASSWORD")).public_view()
    rendered = json.dumps(view)
    assert "not-a-real-password" not in rendered
    assert "REQ_PASSWORD" not in rendered
    assert "password" not in rendered.casefold()


def test_tracked_example_uses_canonical_direct_inner_contract():
    document = json.loads(Path("config/requirements/sql_registry.example.json").read_text(encoding="utf-8"))
    assert set(document) == {"connections", "queries"}
    assert set(document["connections"]) == {"requirement_control"}
    assert document["queries"] == {}
    assert document["connections"]["requirement_control"] == {
        "driver": "auto",
        "server": "YOUR_SQL_SERVER_HOST",
        "database": "YOUR_DATABASE_NAME",
        "trusted_connection": False,
        "user": "YOUR_DB_USERNAME",
        "password": "YOUR_DB_PASSWORD",
        "encrypt": True,
        "trust_server_certificate": True,
    }
