from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_ingestion.excel_to_sql import user_imports
from data_ingestion.excel_to_sql import user_import_storage


def _patch_store(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "imports"
    monkeypatch.setattr(user_import_storage, "ROOT", root)
    monkeypatch.setattr(user_import_storage, "ACTIVE_DIR", root / "active")
    monkeypatch.setattr(user_import_storage, "DELETED_DIR", root / "deleted")
    monkeypatch.setattr(user_import_storage, "REGISTRY", root / "records.json")


def test_save_list_and_delete_upload_record(monkeypatch, tmp_path):
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
    assert record["status"] == "uploaded"
    assert "stored_path" not in record
    assert (
        user_imports.list_import_records(username="alice", is_superuser=False)[0]["id"]
        == record["id"]
    )
    assert user_imports.list_import_records(username="bob", is_superuser=False) == []

    result = user_imports.delete_records(
        [record["id"]], username="alice", is_superuser=False, reason="cleanup"
    )

    assert result == {"deleted": [record["id"]], "skipped": []}
    deleted = user_imports.list_import_records(
        username="alice", is_superuser=False, status="deleted"
    )[0]
    assert deleted["status"] == "deleted"
    assert deleted["deleted_by"] == "alice"
    assert (tmp_path / "imports" / "deleted" / f"{record['id']}.xlsx").exists()


def test_import_center_static_contains_user_import_controls():
    dashboard_html = Path("api/static/excel_to_sql_dashboard.html").read_text(encoding="utf-8")
    html = Path("api/static/excel_to_sql_import_center.html").read_text(encoding="utf-8")
    script = Path("api/static/excel_to_sql_import_records.js").read_text(
        encoding="utf-8"
    )
    assert "使用者 Excel 上傳、預掃描、確認匯入 SQL 與匯入記錄管理已移至獨立頁面" not in dashboard_html
    assert "前往 Excel 匯入作業中心" not in dashboard_html
    assert "使用者 Excel 匯入操作" not in dashboard_html
    assert "使用者 Excel 匯入操作" in html
    assert "/static/excel_to_sql_import_records.js?v=20260615-center" in html
    assert "/v1/excel-to-sql/import-records" in script
    assert "previewImportRecord" in script
    assert "deleteSelectedImportRecords" in script
    assert "recordSelectAll" in html
    assert "錯誤診斷" in html
    assert 'class="table-wrap import-records-wrap"' in html
    assert 'class="import-records-table"' in html
    assert "table-layout:fixed" in html
    assert "#importRecords .actions-col { width:14%; }" in html
    assert "@media (max-width: 760px)" in html
    assert 'content:attr(data-label)' in html
    assert "function importRecordDiagnostics" in script
    assert 'data-label="操作"' in script
    assert 'aria-label="選取匯入記錄' in script
    assets = Path("api/routers/editor.py").read_text(encoding="utf-8")
    assert "excel_to_sql_import_records.js" in assets
    assert "excel_to_sql_dashboard.js" in assets


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
    monkeypatch.setattr(user_import_preview, "get_existing_hashes", lambda *args, **kwargs: set())

    result = user_import_preview._preview_file(
        "cfg.json",
        {
            "destination": {"table": "dbo.vessel_activities", "auto_create_table": True},
            "db": {"driver": "x", "server": "s", "database": "d", "user": "u", "password": "p"},
            "source": {},
        },
        tmp_path / "sample.xlsx",
    )

    assert result["will_insert"] == 1
    assert any("CREATE TABLE [dbo].[vessel_activities]" in sql for sql in fake_conn.cursor_obj.statements)
    assert fake_conn.commits == 1
