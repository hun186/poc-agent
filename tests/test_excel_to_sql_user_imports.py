from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_ingestion.excel_to_sql import user_imports
from data_ingestion.excel_to_sql import user_import_storage


def _patch_store(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "imports"
    monkeypatch.setattr(user_import_storage, "ROOT", root)
    monkeypatch.setattr(user_import_storage, "ACTIVE_DIR", root / "active")
    monkeypatch.setattr(user_import_storage, "RECORDS_DIR", root / "records")
    monkeypatch.setattr(user_import_storage, "REGISTRY", root / "records.json")


def test_save_and_list_upload_record_uses_compact_registry(monkeypatch, tmp_path):
    _patch_store(monkeypatch, tmp_path)
    config = tmp_path / "cfg.json"
    config.write_text(
        '{"source":{"sheet":"Sheet1"},"destination":{"table":"dbo.t"},"mappings":[{"source_column":"A","dest_field":"a"}],"db":{"driver":"x","server":"s","database":"d","user":"u","password":"p"}}',
        encoding="utf-8",
    )

    record = user_imports.save_upload(
        fileobj=BytesIO(b"excel-bytes"),
        filename="sample.xlsx",
        username="alice",
        config_path=str(config),
    )

    assert record["original_filename"] == "sample.xlsx"
    assert record["stored_filename"] == f"{record['id']}.xlsx"
    assert record["status"] == "uploaded"
    assert "stored_path" not in record
    assert (
        user_imports.list_import_records(username="alice", is_superuser=False)[0]["id"]
        == record["id"]
    )
    assert (
        user_imports.list_import_records(
            username="alice",
            is_superuser=False,
            filename=record["stored_filename"],
        )[0]["id"]
        == record["id"]
    )
    assert user_imports.list_import_records(username="bob", is_superuser=False) == []

    registry = (tmp_path / "imports" / "records.json").read_text(encoding="utf-8")
    assert '"record_ids"' in registry
    assert '"original_filename"' not in registry
    record_path = tmp_path / "imports" / "records" / f"{record['id']}.json"
    assert record_path.exists()
    assert '"original_filename"' in record_path.read_text(encoding="utf-8")


def test_legacy_records_json_migrates_to_per_record_files(monkeypatch, tmp_path):
    _patch_store(monkeypatch, tmp_path)
    root = tmp_path / "imports"
    root.mkdir(parents=True)
    legacy = {
        "records": [
            {
                "id": "legacy-1",
                "original_filename": "legacy.xlsx",
                "stored_path": str(root / "active" / "legacy-1.xlsx"),
                "config_path": "cfg.json",
                "username": "alice",
                "created_at": "2026-06-15T00:00:00+00:00",
                "status": "uploaded",
            }
        ]
    }
    (root / "records.json").write_text(json.dumps(legacy), encoding="utf-8")

    data = user_import_storage.read_registry()

    assert data["records"][0]["id"] == "legacy-1"
    compact = (root / "records.json").read_text(encoding="utf-8")
    assert '"record_ids"' in compact
    assert '"records"' not in compact
    assert (root / "records" / "legacy-1.json").exists()


def test_import_center_static_contains_user_import_controls():
    dashboard_html = Path("sra_api/static/excel_to_sql_dashboard.html").read_text(
        encoding="utf-8"
    )
    html = Path("sra_api/static/excel_to_sql_import_center.html").read_text(
        encoding="utf-8"
    )
    script = Path("sra_api/static/excel_to_sql_import_records.js").read_text(
        encoding="utf-8"
    )
    assert (
        "使用者 Excel 上傳、預掃描、確認匯入 SQL 與匯入記錄管理已移至獨立頁面"
        not in dashboard_html
    )
    assert "前往 Excel 匯入作業中心" not in dashboard_html
    assert "使用者 Excel 匯入操作" not in dashboard_html
    assert "使用者 Excel 匯入操作" in html
    assert (
        "/static/excel_to_sql_import_records.js?v=20260625-pending-task-review" in html
    )
    assert "/v1/excel-to-sql/import-records" in script
    assert "previewImportRecord" in script
    assert "刪除記錄" not in script
    assert "deleteSelectedImportRecords" not in script
    assert "deleteSingleImportRecord" not in script
    assert "recordSelectAll" not in html
    assert "批次刪除勾選記錄" not in html
    assert "錯誤診斷" in html
    assert "匯入任務" in html
    assert "建立 Excel→SQL 任務設定檔" in html
    assert "資料庫連線來源任務" in html
    assert "department/new_task.json" in html
    assert "taskMappings" in html
    assert "sqlTypeOptions" in html
    assert "比對方式說明" in html
    assert "pending" in html
    assert "approveTaskConfigPath" in html
    assert "/v1/excel-to-sql/task-configs" in script
    assert "connection_source_config" in script
    assert "taskConnectionSource" in script
    assert "function createTaskConfig" in script
    assert "function approveTaskConfig" in script
    assert "showMatchHelp" in script
    assert 'list="sqlTypeOptions"' in script
    assert "監控任務" not in html
    assert "Excel→SQL 匯入查詢儀表板" in html
    assert "船舶活動 Excel 匯入任務" in Path(
        "config/excel_to_sql/vessel_activities.example.json"
    ).read_text(encoding="utf-8")
    assert "原始檔名" in html
    assert "導入檔名" in html
    assert 'class="table-wrap import-records-wrap"' in html
    assert 'class="import-records-table"' in html
    assert "table-layout:fixed" in html
    assert "#importRecords .stored-file-col { width:9%; }" in html
    assert "#importRecords .actions-col { width:10%; }" in html
    assert (
        ".record-actions { display:grid; grid-template-columns: minmax(0, 1fr);" in html
    )
    assert "min-width:128px" in html
    assert ".record-actions button:nth-child(2)" not in html
    assert "repeat(3, minmax(0, 1fr))" not in html
    assert "@media (max-width: 760px)" in html
    assert "content:attr(data-label)" in html
    assert "function importRecordDiagnostics" in script
    assert "<details><summary>展開 / 收合錯誤診斷</summary>" in script
    assert "function openAuditForImportRecord" in script
    assert "source_file_filter" in script
    assert "#recentAuditSection" in script
    assert "params.set('days'" not in script
    assert "查詢已匯入條目" not in script
    assert (
        script.index("預掃描")
        < script.index("確認匯入SQL")
        < script.index("查詢已匯入列")
    )
    assert "查詢已匯入列" in script
    assert "window.__importRecordById" in script
    assert 'data-label="導入檔名"' in script
    assert 'data-label="操作"' in script
    assert 'aria-label="選取匯入記錄' not in script
    assets = Path("sra_api/routers/editor.py").read_text(encoding="utf-8")
    router = Path("sra_api/routers/excel_to_sql.py").read_text(encoding="utf-8")
    facade = Path("data_ingestion/excel_to_sql/user_imports.py").read_text(
        encoding="utf-8"
    )
    storage = Path("data_ingestion/excel_to_sql/user_import_storage.py").read_text(
        encoding="utf-8"
    )
    assert "excel_to_sql_import_records.js" in assets
    assert "excel_to_sql_dashboard_app.js" in assets
    assert '@router.delete("/v1/excel-to-sql/import-records")' not in router
    assert "def delete_records" not in storage
    assert "delete_records" not in facade


def test_preview_auto_creates_missing_destination_table(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import sys
    from data_ingestion.excel_to_sql import user_import_preview

    class FakeCursor:
        def __init__(self):
            self.statements = []
            self.closed = False

        def execute(self, sql, *params):
            self.statements.append(str(sql))
            return self

        def fetchone(self):
            # destination_table_exists returns false for the missing table.
            return None

        def close(self):
            self.closed = True

    class FakeConn:
        def __init__(self):
            self.cursor_obj = FakeCursor()
            self.commits = 0
            self.closed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.commits += 1

        def close(self):
            self.closed = True

    fake_conn = FakeConn()
    monkeypatch.setitem(
        sys.modules,
        "pyodbc",
        SimpleNamespace(connect=lambda conn_str: fake_conn),
    )
    monkeypatch.setattr(
        user_import_preview,
        "open_workbook_headers",
        lambda config_path, cfg, excel_path: [
            SimpleNamespace(sheet_name="Sheet1", header_row=1, header_map={"A": "名稱"})
        ],
    )
    monkeypatch.setattr(
        user_import_preview,
        "read_column_mappings",
        lambda cfg, header_map: [{"source_column": "名稱", "dest_field": "name"}],
    )
    monkeypatch.setattr(
        user_import_preview,
        "iter_excel_rows",
        lambda **kwargs: iter([(2, {"name": "A"}, {"名稱": "A"}, "hash-a", "")]),
    )
    monkeypatch.setattr(
        user_import_preview, "get_existing_hashes", lambda *args, **kwargs: set()
    )

    result = user_import_preview._preview_file(
        "cfg.json",
        {
            "destination": {
                "table": "dbo.vessel_activities",
                "auto_create_table": True,
            },
            "db": {
                "driver": "x",
                "server": "s",
                "database": "d",
                "user": "u",
                "password": "p",
            },
            "source": {},
        },
        tmp_path / "sample.xlsx",
    )

    assert result["will_insert"] == 1
    assert any(
        "CREATE TABLE [dbo].[vessel_activities]" in sql
        for sql in fake_conn.cursor_obj.statements
    )
    assert fake_conn.commits == 1


def test_confirm_import_ensures_audit_table_before_processing(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import sys
    from data_ingestion.excel_to_sql import user_import_runner

    _patch_store(monkeypatch, tmp_path)
    config = tmp_path / "cfg.json"
    config.write_text(
        '{"source":{"sheet":"Sheet1"},"destination":{"table":"dbo.t"},"audit":{"enabled":true,"table":"dbo.ExcelImportAudit"},"mappings":[{"source_column":"A","dest_field":"a"}],"db":{"driver":"x","server":"s","database":"d","user":"u","password":"p"}}',
        encoding="utf-8",
    )
    record = user_imports.save_upload(
        fileobj=BytesIO(b"excel-bytes"),
        filename="sample.xlsx",
        username="alice",
        config_path=str(config),
    )

    class FakeCursor:
        def __init__(self):
            self.statements = []
            self.closed = False

        def execute(self, sql, *params):
            self.statements.append(str(sql))
            return self

        def close(self):
            self.closed = True

    class FakeConn:
        def __init__(self):
            self.cursor_obj = FakeCursor()
            self.commits = 0
            self.closed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.commits += 1

        def close(self):
            self.closed = True

    fake_conn = FakeConn()
    captured_process_kwargs = {}

    def fake_process_excel_file(**kwargs):
        captured_process_kwargs.update(kwargs)
        return SimpleNamespace(
            success=1, duplicate=0, failed=0, ok=True, failure_summary={}
        )

    monkeypatch.setitem(
        sys.modules, "pyodbc", SimpleNamespace(connect=lambda conn_str: fake_conn)
    )
    monkeypatch.setattr(
        user_import_runner, "process_excel_file", fake_process_excel_file
    )

    result = user_import_runner.import_record(
        record["id"], username="alice", is_superuser=False
    )

    assert result["import_result"]["inserted_rows"] == 1
    assert captured_process_kwargs["cfg"]["_audit_actor"] == "alice"
    assert fake_conn.closed is True
    assert fake_conn.cursor_obj.closed is True
    assert any(
        "CREATE TABLE [dbo].[ExcelImportAudit]" in sql
        for sql in fake_conn.cursor_obj.statements
    )
    assert fake_conn.commits >= 1


def test_create_excel_to_sql_task_config_writes_enabled_dashboard_json(tmp_path):
    from data_ingestion.excel_to_sql.task_configs import create_task_config

    payload = {
        "filename": "new_task.json",
        "task_name": "新 Excel 匯入任務",
        "db_server": "sql.local",
        "db_database": "OpsDb",
        "db_user": "operator",
        "db_password": "secret-value",
        "source_sheet": "Sheet1",
        "destination_table": "dbo.ImportTarget",
        "mappings": [
            {
                "source_column": "日期",
                "dest_field": "event_date",
                "dest_field_type": "DATE",
                "required": True,
                "value_type": "date",
            },
            {
                "source_column": "敘述",
                "dest_field": "description",
                "dest_field_type": "NVARCHAR(MAX)",
                "match": "prefix",
            },
        ],
    }

    created = create_task_config(payload, actor="operator", root=tmp_path)

    config_path = Path(created["config_path"])
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["dashboard"]["enabled"] is False
    assert data["dashboard"]["status"] == "pending"
    assert data["dashboard"]["name"] == "新 Excel 匯入任務"
    assert data["db"]["server"] == "sql.local"
    assert data["destination"]["table"] == "dbo.ImportTarget"
    assert data["mappings"][0]["dest_field"] == "event_date"


def test_create_excel_to_sql_task_config_supports_subdirectory_and_copies_connection(
    tmp_path,
):
    from data_ingestion.excel_to_sql.task_configs import create_task_config

    source_dir = tmp_path / "shared"
    source_dir.mkdir(parents=True)
    source = source_dir / "base.json"
    source.write_text(
        json.dumps(
            {
                "db": {
                    "driver": "ODBC Driver 18 for SQL Server",
                    "server": "secret-sql.local",
                    "database": "SecretDb",
                    "trusted_connection": False,
                    "user": "secret-user",
                    "password": "secret-password",
                    "encrypt": False,
                    "trust_server_certificate": False,
                },
                "dashboard": {"enabled": True, "name": "Base"},
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "filename": "business/new_task.json",
        "task_name": "業務自建任務",
        "connection_source_config": "shared/base.json",
        "source_sheet": "Sheet1",
        "destination_table": "dbo.ImportTarget",
        "mappings": [{"source_column": "A", "dest_field": "a"}],
    }

    created = create_task_config(payload, actor="operator", root=tmp_path)

    assert Path(created["config_path"]).name == "new_task.json"
    config_path = tmp_path / "business" / "new_task.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["db"] == json.loads(source.read_text(encoding="utf-8"))["db"]
    assert data["dashboard"]["enabled"] is False
    assert data["dashboard"]["status"] == "pending"
    assert data["dashboard"]["name"] == "業務自建任務"


def test_create_excel_to_sql_task_config_direct_connection_stores_user_and_password(
    tmp_path,
):
    from data_ingestion.excel_to_sql.task_configs import create_task_config

    payload = {
        "filename": "direct.json",
        "task_name": "Direct",
        "db_server": "sql.local",
        "db_database": "OpsDb",
        "db_user": "operator",
        "db_password": "secret-value",
        "db_encrypt": False,
        "db_trust_server_certificate": False,
        "source_sheet": "Sheet1",
        "destination_table": "dbo.ImportTarget",
        "mappings": [{"source_column": "A", "dest_field": "a"}],
    }

    created = create_task_config(payload, actor="operator", root=tmp_path)

    data = json.loads(Path(created["config_path"]).read_text(encoding="utf-8"))
    assert data["db"]["user"] == "operator"
    assert data["db"]["password"] == "secret-value"
    assert data["db"]["encrypt"] is False
    assert data["db"]["trust_server_certificate"] is False


def test_create_excel_to_sql_task_config_accepts_root_prefixed_subpath(tmp_path):
    from data_ingestion.excel_to_sql.task_configs import create_task_config

    payload = {
        "filename": "config/excel_to_sql/group/root_prefixed.json",
        "task_name": "Root prefixed",
        "db_server": "sql.local",
        "db_database": "OpsDb",
        "db_user": "operator",
        "db_password": "secret-value",
        "source_sheet": "Sheet1",
        "destination_table": "dbo.ImportTarget",
        "mappings": [{"source_column": "A", "dest_field": "a"}],
    }

    create_task_config(payload, actor="operator", root=tmp_path)

    assert (tmp_path / "group" / "root_prefixed.json").exists()


def test_approve_excel_to_sql_task_config_enables_pending_task(tmp_path):
    from data_ingestion.excel_to_sql.task_configs import (
        approve_task_config,
        create_task_config,
    )

    payload = {
        "filename": "pending.json",
        "task_name": "Pending",
        "db_server": "sql.local",
        "db_database": "OpsDb",
        "db_user": "operator",
        "db_password": "secret-value",
        "source_sheet": "Sheet1",
        "destination_table": "dbo.ImportTarget",
        "mappings": [{"source_column": "A", "dest_field": "a"}],
    }
    create_task_config(payload, actor="operator", root=tmp_path)

    approved = approve_task_config("pending.json", actor="admin", root=tmp_path)

    data = json.loads((tmp_path / "pending.json").read_text(encoding="utf-8"))
    assert approved["enabled"] is True
    assert approved["status"] == "active"
    assert data["dashboard"]["enabled"] is True
    assert data["dashboard"]["status"] == "active"
    assert data["dashboard"]["approved_by"] == "admin"


def test_create_excel_to_sql_task_config_rejects_unsafe_filename(tmp_path):
    from data_ingestion.excel_to_sql.task_configs import create_task_config

    payload = {
        "filename": "../bad.json",
        "task_name": "Bad",
        "db_server": "sql.local",
        "db_database": "OpsDb",
        "db_user": "operator",
        "db_password": "secret-value",
        "source_sheet": "Sheet1",
        "destination_table": "dbo.ImportTarget",
        "mappings": [{"source_column": "A", "dest_field": "a"}],
    }

    try:
        create_task_config(payload, actor="operator", root=tmp_path)
    except ValueError as exc:
        assert "設定檔檔名" in str(exc)
    else:
        raise AssertionError("unsafe filename should be rejected")
