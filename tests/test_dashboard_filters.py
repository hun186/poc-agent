from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.excel_to_sql.dashboard import (
    _audit_chart_bucket,
    _audit_time_window,
    _append_time_filters,
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
