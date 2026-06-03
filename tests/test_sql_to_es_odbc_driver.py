from pathlib import Path
import importlib
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def import_ingest_sql(monkeypatch):
    elasticsearch = types.ModuleType("elasticsearch")
    elasticsearch.helpers = types.SimpleNamespace(bulk=lambda *args, **kwargs: (0, []))
    monkeypatch.setitem(sys.modules, "elasticsearch", elasticsearch)
    monkeypatch.setitem(sys.modules, "pyodbc", types.ModuleType("pyodbc"))

    es_client = types.ModuleType("agent.es.es_client")
    es_client.ES_INDEX_DEFAULT = "default-index"
    es_client.get_es = lambda: None
    monkeypatch.setitem(sys.modules, "agent.es.es_client", es_client)

    ingest_txt = types.ModuleType("data_ingestion.txt_to_es.ingest_txt")
    ingest_txt.INDEX_MAPPINGS = {"properties": {}}
    monkeypatch.setitem(sys.modules, "data_ingestion.txt_to_es.ingest_txt", ingest_txt)

    sys.modules.pop("data_ingestion.sql_to_es.ingest_sql", None)
    return importlib.import_module("data_ingestion.sql_to_es.ingest_sql")


def minimal_config(driver="auto"):
    return {
        "db": {
            "driver": driver,
            "server": "localhost",
            "database": "TestDB",
            "trusted_connection": False,
            "user": "sa",
            "password": "secret",
        }
    }


def test_sql_to_es_auto_driver_uses_odbc_detection(monkeypatch):
    ingest_sql = import_ingest_sql(monkeypatch)
    detected = []

    def fake_detect(configured_driver):
        detected.append(configured_driver)
        return "ODBC Driver 18 for SQL Server"

    monkeypatch.setattr(ingest_sql, "detect_odbc_driver", fake_detect)

    conn_str = ingest_sql.build_conn_str_from_config(minimal_config("auto"))

    assert detected == ["auto"]
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in conn_str
    assert "SERVER=localhost" in conn_str
    assert "DATABASE=TestDB" in conn_str


def test_sql_to_es_missing_driver_defaults_to_auto_detection(monkeypatch):
    ingest_sql = import_ingest_sql(monkeypatch)
    detected = []

    def fake_detect(configured_driver):
        detected.append(configured_driver)
        return "ODBC Driver 17 for SQL Server"

    monkeypatch.setattr(ingest_sql, "detect_odbc_driver", fake_detect)
    cfg = minimal_config()
    del cfg["db"]["driver"]

    conn_str = ingest_sql.build_conn_str_from_config(cfg)

    assert detected == ["auto"]
    assert "DRIVER={ODBC Driver 17 for SQL Server}" in conn_str
