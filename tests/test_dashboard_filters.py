from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_ingestion.excel_to_sql.dashboard import (
    _audit_chart_bucket,
    _audit_time_window,
    _append_time_filters,
    dashboard_payload,
    discover_dashboard_tasks,
)


def test_audit_time_window_converts_aware_timestamps_to_naive_utc():
    days, start_dt, end_dt = _audit_time_window(
        14,
        "2026-06-01T19:24:00+08:00",
        "2026-06-01T19:30:00+08:00",
    )

    assert days == 14
    assert start_dt == datetime(2026, 6, 1, 11, 24)
    assert end_dt == datetime(2026, 6, 1, 11, 30)
    assert start_dt.tzinfo is None


def test_audit_time_window_expands_date_only_end_to_end_of_day():
    _, start_dt, end_dt = _audit_time_window(14, "2026-06-01", "2026-06-02")

    assert start_dt == datetime(2026, 6, 1, 0, 0)
    assert end_dt == datetime(2026, 6, 2, 23, 59, 59, 999999)


def test_audit_time_window_rejects_start_after_end():
    with pytest.raises(ValueError, match="起始時間不可晚於結束時間"):
        _audit_time_window(14, "2026-06-02T00:00:00Z", "2026-06-01T00:00:00Z")


def test_append_time_filters_uses_explicit_range_when_present():
    conditions = []
    params = []
    start = datetime(2026, 6, 1, 11, 24, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 12, 24, tzinfo=timezone.utc)

    _append_time_filters(conditions, params, days=14, start_dt=start, end_dt=end)

    assert conditions == ["processed_at >= ?", "processed_at <= ?"]
    assert params == [start, end]


def test_append_time_filters_falls_back_to_days():
    conditions = []
    params = []

    _append_time_filters(conditions, params, days=14, start_dt=None, end_dt=None)

    assert conditions == ["processed_at >= DATEADD(day, -?, SYSUTCDATETIME())"]
    assert params == [14]


def test_audit_chart_bucket_accepts_common_interval_aliases():
    bucket, label, sql = _audit_chart_bucket("6h")

    assert bucket == "6_hours"
    assert label == "每 6 小時"
    assert "DATEDIFF(hour" in sql


def test_audit_chart_bucket_rejects_unknown_interval():
    with pytest.raises(ValueError, match="不支援的 audit 統計區間"):
        _audit_chart_bucket("quarter")


def _write_dashboard_config(path: Path, *, enabled: bool = True, name: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    dashboard = {"enabled": enabled}
    if name:
        dashboard["name"] = name
    path.write_text(
        json.dumps(
            {
                "dashboard": dashboard,
                "audit": {"table": "dbo.ExcelAudit"},
                "destination": {"table": "dbo.Target"},
                "source": {"directory": "data/incoming"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_dashboard_payload_applies_destination_table_filter(monkeypatch):
    from data_ingestion.excel_to_sql import dashboard as dashboard_module

    cfg = {"audit": {"table": "dbo.ExcelAudit"}}

    class FakeCursor:
        def __init__(self):
            self.description = []
            self.calls = []
            self._rows = []
            self._one = (1,)

        def execute(self, sql, *params):
            self.calls.append((sql, params))
            normalized = " ".join(sql.split())
            if "OBJECT_ID" in normalized:
                self._one = (1,)
                self.description = []
                self._rows = []
            elif "SELECT status, COUNT(1) AS count" in normalized:
                self.description = [("status",), ("count",)]
                self._rows = []
            elif "SELECT CONVERT(date, processed_at) AS day" in normalized:
                self.description = [("day",), ("status",), ("count",)]
                self._rows = []
            elif "GROUP BY source_file" in normalized:
                self.description = [
                    ("source_file",),
                    ("last_processed_at",),
                    ("inserted_rows",),
                    ("duplicate_rows",),
                    ("failed_rows",),
                    ("header_smart_matches",),
                ]
                self._rows = []
            elif "SELECT DISTINCT TOP (200) destination_table" in normalized:
                self.description = [("destination_table",)]
                self._rows = [("dbo.Target",), ("dbo.OtherTarget",)]
            elif "SELECT DISTINCT TOP (200) COALESCE(NULLIF(JSON_VALUE(row_payload, '$.audit_actor'), ''), NULLIF(JSON_VALUE(row_payload, '$.actor'), '')) AS username" in normalized:
                self.description = [("username",)]
                self._rows = [("alice",), ("bob",)]
            elif "AS bucket_start, COUNT(1) AS count" in normalized:
                self.description = [("bucket_start",), ("count",)]
                self._rows = []
            elif "SELECT COUNT(1) AS total" in normalized:
                self.description = [("total",)]
                self._rows = [(0,)]
            elif "WITH ordered_recent AS" in normalized:
                self.description = [
                    ("audit_id",),
                    ("run_id",),
                    ("source_file",),
                    ("sheet_name",),
                    ("row_no",),
                    ("hash_value",),
                    ("destination_table",),
                    ("status",),
                    ("message",),
                    ("row_payload",),
                    ("username",),
                    ("processed_at",),
                ]
                self._rows = []
                assert "AS username" in sql
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

        def cursor(self):
            return self.cursor_obj

        def close(self):
            pass

    conn = FakeConnection()
    monkeypatch.setattr(dashboard_module, "load_json_config", lambda path: cfg)
    monkeypatch.setattr(dashboard_module, "_connect", lambda cfg: conn)

    result = dashboard_payload(
        "config/excel_to_sql/task.json",
        days=7,
        destination_table_filter=["dbo.Target", "dbo.OtherTarget"],
        username_filter=["alice", "bob"],
    )

    filtered_calls = [
        (sql, params)
        for sql, params in conn.cursor_obj.calls
        if "destination_table IN (?, ?)" in sql
    ]
    assert len(filtered_calls) == 3
    assert all(
        "dbo.Target" in call_params[0] and "dbo.OtherTarget" in call_params[0]
        for _, call_params in filtered_calls
    )
    assert result["destination_table_options"] == ["dbo.Target", "dbo.OtherTarget"]
    assert result["username_options"] == ["alice", "bob"]
    assert result["recent_filters"]["destination_table"] == [
        "dbo.Target",
        "dbo.OtherTarget",
    ]
    assert result["recent_filters"]["username"] == ["alice", "bob"]


def test_discover_dashboard_tasks_recursively_loads_enabled_json(tmp_path):
    _write_dashboard_config(tmp_path / "root_task.json", name="Root task")
    _write_dashboard_config(tmp_path / "nested" / "child_task.json", name="Nested task")
    _write_dashboard_config(
        tmp_path / "nested" / "disabled_task.json", enabled=False, name="Disabled task"
    )
    (tmp_path / "nested" / "not_json.txt").write_text("{}", encoding="utf-8")

    tasks = discover_dashboard_tasks(tmp_path)

    assert [task["name"] for task in tasks] == ["Nested task", "Root task"]
    assert {Path(task["config_path"]).name for task in tasks} == {
        "child_task.json",
        "root_task.json",
    }


def test_delete_imported_sql_row_records_deleted_row_payloads(monkeypatch):
    from data_ingestion.excel_to_sql import dashboard as dashboard_module

    cfg = {
        "audit": {"table": "dbo.ExcelAudit"},
        "destination": {"table": "dbo.Target", "hash_field": "hash_value"},
    }
    deleted_at = datetime(2026, 6, 2, 9, 25, 10)

    class FakeCursor:
        def __init__(self):
            self.description = []
            self.rowcount = -1
            self.calls = []
            self.audit_payload = None

        def execute(self, sql, *params):
            self.calls.append((sql, params))
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT * FROM"):
                self.description = [
                    ("id",),
                    ("name",),
                    ("amount",),
                    ("deleted_at",),
                    ("hash_value",),
                ]
                self._rows = [(7, "錯誤資料", 12.5, deleted_at, "abc123")]
            elif normalized.startswith("DELETE FROM"):
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

    conn = FakeConnection()
    monkeypatch.setattr(dashboard_module, "load_json_config", lambda path: cfg)
    monkeypatch.setattr(dashboard_module, "_connect", lambda cfg: conn)

    result = dashboard_module.delete_imported_sql_row(
        "config/excel_to_sql/task.json",
        hash_value="abc123",
        actor="test",
        reason="資料列內容錯誤，人工刪除",
    )

    assert result["status"] == "sql_deleted"
    assert result["deleted_rows"] == 1
    assert conn.commits == 1
    assert conn.rollbacks == 0
    payload = conn.cursor_obj.audit_payload
    assert payload["deleted_rows"] == 1
    assert payload["deleted_row_payloads"] == [
        {
            "id": 7,
            "name": "錯誤資料",
            "amount": 12.5,
            "deleted_at": "2026-06-02T09:25:10",
            "hash_value": "abc123",
        }
    ]
    select_sql, select_params = conn.cursor_obj.calls[0]
    delete_sql, delete_params = conn.cursor_obj.calls[1]
    assert select_sql.startswith("SELECT * FROM")
    assert delete_sql.startswith("DELETE FROM")
    assert select_params == ("abc123",)
    assert delete_params == ("abc123",)
