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
    all_result = es.search(index=MOCK_INDEX, body={"query": {"bool": {"must": []}}, "size": 10})
    assert all_result["hits"]["total"]["value"] == 4
    result = es.search(index=MOCK_INDEX, body={"query": {"bool": {"must": [{"simple_query_string": {"query": "随时准备"}}]}}, "size": 10})
    assert result["hits"]["total"]["value"] == 1
    source = result["hits"]["hits"][0]["_source"]
    event = source["multidim_event_json"][0]
    assert event["evidence_snippets"][0]["confidence"] == 90
    summit = es.search(index=MOCK_INDEX, body={"query": {"bool": {"must": [{"simple_query_string": {"query": "埃博拉"}}]}}, "size": 10})
    assert summit["hits"]["total"]["value"] == 1
    fishing = es.get(index=MOCK_INDEX, id="mock-fishing-fulong-88-003")["_source"]["multidim_event_json"][0]
    assert fishing["Involved_Parties"][0]["party_role"] == "漁船"
    assert fishing["evidence_snippets"][0]["char_end"] == 140
    empty = es.get(index=MOCK_INDEX, id="mock-empty-arrays-002")["_source"]["multidim_event_json"][0]
    assert "evidence_snippets" not in empty


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
        hash_value="mock-hash-indonesia-001",
        actor="tester",
        reason="vercel smoke test",
    )

    assert payload["mock_mode"] is True
    assert payload["exists"] is True
    assert payload["recent_paging"]["total"] == 3
    assert payload["destination_table_options"] == ["MockVesselActivities"]
    assert payload["files"][0]["source_file"] == "印尼災害援助事件_mock.xlsx"
    assert "event_subject" in payload["recent"][-1]["row_payload"]
    assert deleted["mock_mode"] is True
    assert deleted["deleted"] is False
