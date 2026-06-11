from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.editor_audit_queries import (
    build_audit_time_series,
    filter_audit_records,
    normalize_chart_bucket,
)


def test_filter_audit_records_accepts_action_prefix() -> None:
    records = [
        {"ts": "2026-06-01T00:00:00+00:00", "action": "editor.save_document", "username": "alice"},
        {"ts": "2026-06-01T01:00:00+00:00", "action": "auth.login", "username": "alice"},
    ]

    filtered = filter_audit_records(records, action_prefix="auth.")

    assert [row["action"] for row in filtered] == ["auth.login"]


def test_build_audit_time_series_groups_by_bucket() -> None:
    records = [
        {"ts": "2026-06-01T01:10:00+00:00", "action": "editor.save_document"},
        {"ts": "2026-06-01T05:59:00+00:00", "action": "editor.save_document"},
        {"ts": "2026-06-01T06:01:00+00:00", "action": "auth.login"},
    ]

    rows = build_audit_time_series(records, "6_hours")

    assert rows == [
        {"bucket_start": "2026-06-01T00:00:00Z", "count": 2},
        {"bucket_start": "2026-06-01T06:00:00Z", "count": 1},
    ]


def test_normalize_chart_bucket_accepts_alias() -> None:
    assert normalize_chart_bucket("6h") == ("6_hours", "每 6 小時")
