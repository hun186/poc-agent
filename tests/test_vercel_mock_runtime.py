from __future__ import annotations

from io import BytesIO

from agent.es import es_client
from agent.es.mock_es_client import MOCK_INDEX
from data_ingestion.excel_to_sql import user_imports
from data_ingestion.excel_to_sql import user_import_storage
from data_ingestion.excel_to_sql.dashboard import dashboard_payload, delete_imported_sql_row


def test_vercel_mock_es_activates_when_forced(monkeypatch):
    monkeypatch.setenv("SRA_VERCEL_MOCK_MODE", "force")
    monkeypatch.delenv("ES_URL", raising=False)
    monkeypatch.setattr(es_client, "_ES", None)
    monkeypatch.setattr(es_client, "_USING_MOCK_ES", False)
    monkeypatch.setattr(es_client, "_INDEX_CACHE_READY", False)

    es = es_client.get_es()
    es_client.init_index_cache(live_check=True, force=True)

    assert getattr(es, "is_sra_mock", False) is True
    assert es_client.using_mock_es() is True
    assert es_client.ALL_INDEXES == [MOCK_INDEX]
    result = es.search(index=MOCK_INDEX, body={"query": {"bool": {"must": [{"simple_query_string": {"query": "港口"}}]}}, "size": 10})
    assert result["hits"]["total"]["value"] == 1


def test_vercel_mock_excel_import_store_uses_memory(monkeypatch):
    monkeypatch.setenv("SRA_VERCEL_MOCK_MODE", "force")
    user_import_storage._MOCK_RECORDS.clear()

    record = user_imports.save_upload(
        fileobj=BytesIO(b"fake-xlsx"),
        filename="sample.xlsx",
        username="tester",
        config_path="config/excel_to_sql/vessel_activities.example.json",
    )
    preview = user_imports.preview_record(record["id"], username="tester", is_superuser=False)
    imported = user_imports.import_record(record["id"], username="tester", is_superuser=False)

    assert record["mock_mode"] is True
    assert preview["preview"]["mock_mode"] is True
    assert imported["import_result"]["mock_mode"] is True
    assert imported["import_result"]["inserted_rows"] == 2


def test_vercel_mock_sql_dashboard_and_delete(monkeypatch):
    monkeypatch.setenv("SRA_VERCEL_MOCK_MODE", "force")

    payload = dashboard_payload(
        "config/excel_to_sql/vessel_activities.example.json",
        username_filter=["vercel-demo"],
        destination_table_filter=["MockVesselActivities"],
    )
    deleted = delete_imported_sql_row(
        "config/excel_to_sql/vessel_activities.example.json",
        hash_value="mock-hash-001",
        actor="tester",
        reason="vercel smoke test",
    )

    assert payload["mock_mode"] is True
    assert payload["exists"] is True
    assert payload["recent_paging"]["total"] == 3
    assert payload["destination_table_options"] == ["MockVesselActivities"]
    assert deleted["mock_mode"] is True
    assert deleted["deleted"] is False
