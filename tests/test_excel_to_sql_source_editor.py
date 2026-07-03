import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_ingestion.excel_to_sql import table_editor


CFG = {
    "audit": {"table": "dbo.ExcelAudit"},
    "destination": {"table": "dbo.Target", "hash_field": "hash_value"},
}


class FakeCursor:
    def __init__(self):
        self.description = []
        self.calls = []
        self.rowcount = -1
        self._rows = []
        self._one = None
        self.audit_payload = None
        self.current_row = {"hash_value": "h1", "title": "舊標題", "content": "舊內容", "row_no": 9}

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        normalized = " ".join(sql.split())
        if "INFORMATION_SCHEMA.COLUMNS" in normalized:
            self.description = [("COLUMN_NAME",), ("DATA_TYPE",), ("IS_NULLABLE",)]
            self._rows = [
                ("hash_value", "char", "NO"),
                ("title", "nvarchar", "YES"),
                ("content", "nvarchar", "YES"),
                ("row_no", "int", "YES"),
                ("username", "nvarchar", "YES"),
            ]
        elif normalized.startswith("SELECT DISTINCT TOP (200)") and "FROM [dbo].[ExcelAudit]" in normalized:
            self.description = [("username",)]
            self._rows = [("importer_alice",), ("importer_bob",)]
        elif normalized.startswith("WITH ranked_audit AS") and "FROM [dbo].[ExcelAudit] aud" in normalized:
            self.description = [("hash_value",), ("username",), ("source_file",), ("processed_at",)]
            self._rows = [("h1", "importer_alice", "upload.xlsx", "2026-07-02T01:02:03")]
        elif normalized.startswith("SELECT DISTINCT TOP (200)"):
            self.description = [("username",)]
            self._rows = [("source_username_should_not_be_used",)]
        elif normalized.startswith("SELECT TOP (") and "GROUP BY" in normalized:
            self.description = [("group_value",), ("count",)]
            self._rows = [("alice", 1)]
        elif normalized.startswith("SELECT COUNT(*) AS total"):
            self.description = [("total",)]
            self._one = (1,)
        elif "ORDER BY" in normalized and "OFFSET" in normalized:
            self.description = [("hash_value",), ("title",), ("content",), ("row_no",), ("username",)]
            self._rows = [("h1", self.current_row["title"], self.current_row["content"], 9, "alice")]
        elif normalized.startswith("SELECT * FROM"):
            self.description = [("hash_value",), ("title",), ("content",), ("row_no",), ("username",)]
            self._one = ("h1", self.current_row["title"], self.current_row["content"], 9, "alice")
        elif normalized.startswith("UPDATE"):
            self.current_row["title"] = params[0][0]
            self.rowcount = 1
        elif "OBJECT_ID" in normalized:
            self._one = (1,)
        elif normalized.startswith("INSERT INTO"):
            self.audit_payload = json.loads(params[-1])
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_list_sql_source_rows_uses_task_destination_and_blocks_system_columns(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)

    result = table_editor.list_sql_source_rows(
        "config/excel_to_sql/task.json", q="舊", connect=lambda cfg: conn
    )

    assert result["destination_table"] == "dbo.Target"
    assert result["hash_field"] == "hash_value"
    assert result["total"] == 1
    assert result["rows"][0]["title"] == "舊標題"
    assert result["username_options"] == ["importer_alice", "importer_bob"]
    assert result["rows"][0]["_import_username"] == "importer_alice"
    assert result["rows"][0]["_source_excel"] == "upload.xlsx"
    assert result["rows"][0]["_imported_at"] == "2026-07-02T01:02:03"
    assert {col["name"] for col in result["columns"]} >= {"username", "_import_username", "_imported_at", "_source_excel"}
    assert result["editable_columns"] == ["title", "content", "username"]
    assert any("CAST([title] AS NVARCHAR(MAX)) LIKE ?" in sql for sql, _ in conn.cursor_obj.calls)


def test_list_sql_source_rows_filters_by_import_username_from_audit_even_with_available_user_column(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)

    table_editor.list_sql_source_rows(
        "config/excel_to_sql/task.json", username_filter=["alice", "bob"], connect=lambda cfg: conn
    )

    count_calls = [call for call in conn.cursor_obj.calls if call[0].strip().startswith("SELECT COUNT(*) AS total")]
    assert count_calls
    assert "FROM [dbo].[ExcelAudit] aud" in count_calls[-1][0]
    assert "aud.hash_value = [dbo].[Target].[hash_value]" in count_calls[-1][0]
    assert "aud.username" in count_calls[-1][0]
    assert count_calls[-1][1] == (("dbo.Target", "alice", "bob"),)


def test_update_sql_source_row_writes_audit_and_rejects_system_columns(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)

    result = table_editor.update_sql_source_row(
        "config/excel_to_sql/task.json",
        hash_value="h1",
        changes={"title": "新標題", "hash_value": "evil", "row_no": 10},
        actor="alice",
        reason="修正匯入資料",
        connect=lambda cfg: conn,
        table_exists=lambda cursor, table: True,
    )

    assert result["updated_rows"] == 1
    assert result["blocked_columns"] == ["hash_value", "row_no"]
    assert result["row"]["title"] == "新標題"
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.cursor_obj.audit_payload["action"] == "sql_source_editor.update_row"
    assert conn.cursor_obj.audit_payload["changes"] == {"title": "新標題"}


def test_source_rows_allows_data_reader_as_read_only(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers import editor_dependencies
    from api.services.auth_store import AuthUser
    import sra_api.routers.excel_to_sql as excel_router

    app = FastAPI()
    app.include_router(excel_router.router)
    monkeypatch.setattr(
        excel_router,
        "discover_dashboard_tasks",
        lambda config_dir: [{"name": "Allowed", "config_path": "config/excel_to_sql/allowed.json"}],
    )
    monkeypatch.setattr(
        excel_router,
        "list_sql_source_rows",
        lambda *args, **kwargs: {"ok": True, "columns": [], "rows": [], "total": 0},
    )

    def data_reader_user():
        return AuthUser(username="reader", role="data_reader", status="active")

    app.dependency_overrides[editor_dependencies.current_user] = data_reader_user
    client = TestClient(app)

    response = client.get(
        "/v1/excel-to-sql/source-rows?config=config/excel_to_sql/allowed.json"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["can_edit"] is False
    assert payload["can_delete"] is False
    assert payload["can_batch_delete"] is False

def test_source_rows_rejects_config_outside_enabled_task_whitelist(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers import editor_dependencies
    from api.services.auth_store import AuthUser
    import sra_api.routers.excel_to_sql as excel_router

    app = FastAPI()
    app.include_router(excel_router.router)
    monkeypatch.setattr(
        excel_router,
        "discover_dashboard_tasks",
        lambda config_dir: [{"name": "Allowed", "config_path": "config/excel_to_sql/allowed.json"}],
    )

    def data_editor_user():
        return AuthUser(username="editor", role="data_editor", status="active")

    app.dependency_overrides[editor_dependencies.current_user] = data_editor_user
    client = TestClient(app)

    response = client.get(
        "/v1/excel-to-sql/source-rows?config=config/excel_to_sql/other.json"
    )

    assert response.status_code == 403
    assert "已啟用 Excel→SQL 任務清單" in response.json()["detail"]


def test_source_rows_accepts_enabled_task_config_before_loading_rows(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers import editor_dependencies
    from api.services.auth_store import AuthUser
    import sra_api.routers.excel_to_sql as excel_router

    app = FastAPI()
    app.include_router(excel_router.router)
    monkeypatch.setattr(
        excel_router,
        "discover_dashboard_tasks",
        lambda config_dir: [{"name": "Allowed", "config_path": "config/excel_to_sql/allowed.json"}],
    )
    monkeypatch.setattr(
        excel_router,
        "list_sql_source_rows",
        lambda config, q="", page=1, limit=50: {
            "ok": True,
            "config_path": config,
            "destination_table": "dbo.Target",
            "rows": [],
            "total": 0,
        },
    )

    def data_editor_user():
        return AuthUser(username="editor", role="data_editor", status="active")

    app.dependency_overrides[editor_dependencies.current_user] = data_editor_user
    client = TestClient(app)

    response = client.get(
        "/v1/excel-to-sql/source-rows?config=config/excel_to_sql/allowed.json"
    )

    assert response.status_code == 200
    assert response.json()["destination_table"] == "dbo.Target"

def test_sql_source_stats_groups_selected_columns(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)

    result = table_editor.sql_source_stats(
        "config/excel_to_sql/task.json",
        group_by=["username"],
        connect=lambda cfg: conn,
    )

    assert result["destination_table"] == "dbo.Target"
    assert result["total"] == 1
    assert result["groups"][0]["field"] == "username"
    assert result["groups"][0]["buckets"] == [{"value": "alice", "count": 1}]


def test_source_stats_route_requires_data_editor_and_uses_enabled_task_whitelist(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers import editor_dependencies
    from api.services.auth_store import AuthUser
    import sra_api.routers.excel_to_sql as excel_router

    app = FastAPI()
    app.include_router(excel_router.router)
    monkeypatch.setattr(
        excel_router,
        "discover_dashboard_tasks",
        lambda config_dir: [{"name": "Allowed", "config_path": "config/excel_to_sql/allowed.json"}],
    )
    monkeypatch.setattr(
        excel_router,
        "sql_source_stats",
        lambda *args, **kwargs: {"ok": True, "total": 3, "groups": []},
    )

    def data_reader_user():
        return AuthUser(username="reader", role="data_reader", status="active")

    app.dependency_overrides[editor_dependencies.current_user] = data_reader_user
    client = TestClient(app)

    response = client.get(
        "/v1/excel-to-sql/source-stats?config=config/excel_to_sql/allowed.json&group_by=username"
    )

    assert response.status_code == 403

    def data_editor_user():
        return AuthUser(username="editor", role="data_editor", status="active")

    app.dependency_overrides[editor_dependencies.current_user] = data_editor_user
    response = client.get(
        "/v1/excel-to-sql/source-stats?config=config/excel_to_sql/allowed.json&group_by=username"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 3
