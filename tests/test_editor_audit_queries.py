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


def test_build_audit_time_series_uses_local_timezone_offset() -> None:
    records = [
        {"ts": "2026-06-01T16:30:00+00:00", "action": "editor.save_document"},
    ]

    rows = build_audit_time_series(records, "day", timezone_offset_minutes=480)

    assert rows == [{"bucket_start": "2026-06-02T00:00:00Z", "count": 1}]


def test_normalize_chart_bucket_accepts_alias() -> None:
    assert normalize_chart_bucket("6h") == ("6_hours", "每 6 小時")


def test_usage_stats_returns_filtered_audit_events(monkeypatch) -> None:
    from api.routers import editor as editor_router
    from api.services.auth_store import AuthUser

    records = [
        {
            "ts": "2026-06-01T01:00:00+00:00",
            "action": "editor.save_document",
            "username": "alice",
            "role": "data_editor",
            "index": "idx",
            "id": "doc-1",
            "changed_paths": ["title"],
        },
        {
            "ts": "2026-06-01T02:00:00+00:00",
            "action": "editor.delete_document",
            "username": "bob",
            "role": "data_editor",
            "index": "idx",
            "id": "doc-2",
            "changed_paths": [],
        },
    ]
    monkeypatch.setattr(editor_router, "load_audit_records", lambda limit=20000: records)

    data = editor_router.usage_stats(
        category="document",
        username=None,
        action=None,
        index=None,
        start_ts=None,
        end_ts=None,
        chart_bucket="day",
        events_limit=1,
        user=AuthUser(username="alice", role="data_editor", status="active"),
    )

    assert data["filtered"]["is_restricted_to_self"] is True
    assert data["filtered"]["events_total"] == 1
    assert data["filtered"]["events_limit"] == 1
    assert [event["id"] for event in data["filtered"]["events"]] == ["doc-1"]


def test_list_audit_logs_allows_regular_user_own_account_events(monkeypatch) -> None:
    from api.routers import editor as editor_router
    from api.services.auth_store import AuthUser

    records = [
        {"ts": "2026-06-01T01:00:00+00:00", "action": "auth.login", "username": "alice"},
        {"ts": "2026-06-01T02:00:00+00:00", "action": "auth.login", "username": "bob"},
        {"ts": "2026-06-01T03:00:00+00:00", "action": "editor.save_document", "username": "alice"},
    ]
    monkeypatch.setattr(editor_router, "load_audit_records", lambda limit=5000: records)

    data = editor_router.list_audit_logs(
        username="bob",
        action=None,
        action_prefix="auth.",
        index=None,
        id=None,
        changed_path=None,
        start_ts=None,
        end_ts=None,
        limit=100,
        user=AuthUser(username="alice", role="data_reader", status="active"),
    )

    assert data["total"] == 1
    assert [event["username"] for event in data["hits"]] == ["alice"]
    assert [event["action"] for event in data["hits"]] == ["auth.login"]


def test_list_audit_logs_rejects_regular_user_document_events(monkeypatch) -> None:
    from fastapi import HTTPException

    from api.routers import editor as editor_router
    from api.services.auth_store import AuthUser

    monkeypatch.setattr(editor_router, "load_audit_records", lambda limit=5000: [])

    try:
        editor_router.list_audit_logs(
            username=None,
            action=None,
            action_prefix="editor.",
            index=None,
            id=None,
            changed_path=None,
            start_ts=None,
            end_ts=None,
            limit=100,
            user=AuthUser(username="alice", role="data_reader", status="active"),
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("regular users must not query document audit logs")
