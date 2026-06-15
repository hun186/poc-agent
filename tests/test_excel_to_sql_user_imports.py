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


def test_dashboard_static_contains_user_import_controls():
    html = Path("api/static/excel_to_sql_dashboard.html").read_text(encoding="utf-8")
    assert "使用者 Excel 匯入操作" in html
    script = Path("api/static/excel_to_sql_import_records.js").read_text(
        encoding="utf-8"
    )
    assert "/static/excel_to_sql_import_records.js?v=20260615-split" in html
    assert "/v1/excel-to-sql/import-records" in script
    assert "previewImportRecord" in script
    assert "deleteSelectedImportRecords" in script
    assert "recordSelectAll" in html
    assets = Path("api/routers/editor.py").read_text(encoding="utf-8")
    assert "excel_to_sql_import_records.js" in assets
    assert "excel_to_sql_dashboard.js" in assets
