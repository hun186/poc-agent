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


def test_list_sql_source_rows_combines_filters_sort_and_page_in_sql(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)

    result = table_editor.list_sql_source_rows(
        "config/excel_to_sql/task.json",
        q="舊",
        payload_filter="內容",
        page=3,
        limit=5,
        sort=["title:desc", "row_no:asc"],
        connect=lambda cfg: conn,
    )

    data_calls = [
        (sql, params)
        for sql, params in conn.cursor_obj.calls
        if "ORDER BY" in sql and "OFFSET" in sql
    ]
    assert data_calls
    sql, params = data_calls[-1]
    assert "CAST([title] AS NVARCHAR(MAX)) LIKE ?" in sql
    assert "CAST([content] AS NVARCHAR(MAX)) LIKE ?" in sql
    assert "ORDER BY [title] DESC, [row_no] ASC, [hash_value] ASC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in sql
    assert params[0][-2:] == (10, 5)
    assert result["sort"] == [
        {"field": "title", "direction": "desc"},
        {"field": "row_no", "direction": "asc"},
        {"field": "hash_value", "direction": "asc"},
    ]


def test_list_sql_source_rows_allows_sorting_by_audit_metadata(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)

    result = table_editor.list_sql_source_rows(
        "config/excel_to_sql/task.json",
        sort=["_import_username:asc", "_imported_at:desc", "_source_excel:asc"],
        connect=lambda cfg: conn,
    )

    data_calls = [
        (sql, params)
        for sql, params in conn.cursor_obj.calls
        if "ORDER BY" in sql and "OFFSET" in sql
    ]
    assert data_calls
    sql, _ = data_calls[-1]
    assert "SELECT TOP (1) COALESCE(NULLIF(aud.username, '')," in sql
    assert "SELECT TOP (1) aud.processed_at" in sql
    assert "SELECT TOP (1) aud.source_file" in sql
    assert result["sort"][:3] == [
        {"field": "_import_username", "direction": "asc"},
        {"field": "_imported_at", "direction": "desc"},
        {"field": "_source_excel", "direction": "asc"},
    ]


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
    captured_stats_kwargs = {}

    def fake_sql_source_stats(*args, **kwargs):
        captured_stats_kwargs.update(kwargs)
        return {"ok": True, "total": 3, "groups": []}

    monkeypatch.setattr(
        excel_router,
        "sql_source_stats",
        fake_sql_source_stats,
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
        "/v1/excel-to-sql/source-stats?config=config/excel_to_sql/allowed.json&group_by=username&chart_bucket=week&include_numeric_summaries=true"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert captured_stats_kwargs["chart_bucket"] == "week"
    assert captured_stats_kwargs["include_numeric_summaries"] is True

def test_source_stats_group_by_uses_full_nvarchar_values(monkeypatch):
    """SQL shape regression: two distinct values after 4,000 chars must not coalesce."""
    conn = FakeConnection()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)

    payload = table_editor.sql_source_stats(
        "config/excel_to_sql/task.json",
        group_by=["content", "_source_excel"],
        connect=lambda cfg: conn,
    )

    assert [group["field"] for group in payload["groups"]] == ["content", "_source_excel"]
    grouping_sql = [sql for sql, _ in conn.cursor_obj.calls if " AS group_value" in sql and "GROUP BY" in sql]
    assert len(grouping_sql) == 2
    assert any("GROUP BY COALESCE(NULLIF(CAST([content] AS NVARCHAR(MAX)), ''), '-')" in sql for sql in grouping_sql)
    assert any("GROUP BY COALESCE(NULLIF(CAST(aud.source_file AS NVARCHAR(MAX)), ''), '-')" in sql for sql in grouping_sql)
    assert all("NVARCHAR(4000)" not in sql for sql in grouping_sql)

def test_numeric_summaries_are_opt_in_and_exclude_system_columns(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)
    monkeypatch.setattr(
        table_editor,
        "_load_columns",
        lambda cursor, table: [
            {"name": "hash_value", "data_type": "char"},
            {"name": "title", "data_type": "nvarchar"},
            {"name": "cost", "data_type": "decimal"},
            {"name": "quantity", "data_type": "int"},
            {"name": "row_no", "data_type": "int"},
        ],
    )

    result = table_editor.sql_source_stats(
        "config/excel_to_sql/task.json", group_by=["title"],
        connect=lambda cfg: conn,
    )

    assert result["numeric_summaries_enabled"] is False
    assert result["numeric_summaries"] == []
    assert result["numeric_summary_available_columns"] == 2
    assert all("COUNT_BIG(" not in sql for sql, _ in conn.cursor_obj.calls)


def test_numeric_summaries_use_one_bounded_filtered_aggregate(monkeypatch):
    class NumericCursor(FakeCursor):
        def execute(self, sql, *params):
            if "COUNT_BIG([cost])" in sql:
                self.calls.append((sql, params))
                self.description = [
                    (name,) for name in (
                        "count_0", "min_0", "max_0", "average_0", "sum_0",
                        "count_1", "min_1", "max_1", "average_1", "sum_1",
                    )
                ]
                self._one = (2, 1.25, 3.75, 2.5, 5.0, 1, 7, 7, 7.0, 7.0)
                return self
            return super().execute(sql, *params)

    conn = FakeConnection()
    conn.cursor_obj = NumericCursor()
    monkeypatch.setattr(table_editor, "load_json_config", lambda path: CFG)
    monkeypatch.setattr(
        table_editor,
        "_load_columns",
        lambda cursor, table: [
            {"name": "hash_value", "data_type": "char"},
            {"name": "title", "data_type": "nvarchar"},
            {"name": "cost", "data_type": "decimal"},
            {"name": "quantity", "data_type": "int"},
            {"name": "row_no", "data_type": "int"},
        ],
    )

    result = table_editor.sql_source_stats(
        "config/excel_to_sql/task.json",
        group_by=["title"], q="alpha", include_numeric_summaries=True,
        connect=lambda cfg: conn,
    )

    assert result["numeric_summaries_enabled"] is True
    assert result["numeric_summary_available_columns"] == 2
    assert [item["column"] for item in result["numeric_summaries"]] == ["cost", "quantity"]
    assert result["numeric_summaries"][0] == {
        "column": "cost", "count": 2, "min": 1.25, "max": 3.75,
        "average": 2.5, "sum": 5.0, "approximate": True,
    }
    aggregate_calls = [(sql, args) for sql, args in conn.cursor_obj.calls if "COUNT_BIG([cost])" in sql]
    assert len(aggregate_calls) == 1
    sql, args = aggregate_calls[0]
    assert "COUNT_BIG([quantity])" in sql
    assert "COUNT_BIG([row_no])" not in sql
    assert "FROM [dbo].[Target] WHERE " in sql
    assert args and any("alpha" in str(param) for param in args[0])
