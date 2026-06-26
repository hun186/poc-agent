from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from data_ingestion.excel_to_sql.dashboard_config import _dashboard_name
from data_ingestion.excel_to_sql.dashboard_filters import (
    _audit_chart_bucket,
    _audit_time_window,
    _normalize_destination_table_filters,
)
from data_ingestion.excel_to_sql.dashboard_sql import _audit_table
from data_ingestion.excel_to_sql.ingest import get_nested, load_json_config

MOCK_DESTINATION_TABLE = "MockVesselActivities"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def mock_audit_rows() -> list[dict[str, Any]]:
    base = _now()
    return [
        {
            "audit_id": 1003,
            "run_id": "mock-run-002",
            "source_file": "印尼災害援助事件_mock.xlsx",
            "sheet_name": "事件抽取",
            "row_no": 4,
            "hash_value": "mock-hash-indonesia-003",
            "destination_table": MOCK_DESTINATION_TABLE,
            "status": "duplicate",
            "message": "mock duplicate row matched existing article_title + event_time; no SQL Server write was attempted",
            "row_payload": {"audit_actor": "vercel-demo", "article_title": "潘基文：联合国随时准备向印尼地震海啸和火山喷发地区民众提供援助", "event_time": "2010-10-28", "event_location": "印度尼西亚", "importance_score": 82},
            "username": "vercel-demo",
            "processed_at": (base - timedelta(hours=2)).isoformat(),
        },
        {
            "audit_id": 1002,
            "run_id": "mock-run-001",
            "source_file": "印尼災害援助事件_mock.xlsx",
            "sheet_name": "人物與證據",
            "row_no": 3,
            "hash_value": "mock-hash-indonesia-002",
            "destination_table": MOCK_DESTINATION_TABLE,
            "status": "inserted",
            "message": "mock inserted person/evidence row; no SQL Server write was attempted",
            "row_payload": {"audit_actor": "vercel-demo", "person_name": "扎彻奥", "role": "联合国新闻部驻印尼新闻中心负责人", "evidence_text": "火山导致多达4万多当地人不得不撤离喷发区域。", "confidence": 88},
            "username": "vercel-demo",
            "processed_at": (base - timedelta(days=1)).isoformat(),
        },
        {
            "audit_id": 1001,
            "run_id": "mock-run-001",
            "source_file": "印尼災害援助事件_mock.xlsx",
            "sheet_name": "事件抽取",
            "row_no": 2,
            "hash_value": "mock-hash-indonesia-001",
            "destination_table": MOCK_DESTINATION_TABLE,
            "status": "inserted",
            "message": "mock inserted event timeline row; no SQL Server write was attempted",
            "row_payload": {"audit_actor": "vercel-demo", "event_subject": "联合国", "event_action": "准备随时向灾区提供援助", "event_time": "2010-10-28", "event_location": "印度尼西亚", "core_entities": ["联合国", "印度尼西亚", "默拉皮火山"]},
            "username": "vercel-demo",
            "processed_at": (base - timedelta(days=1, minutes=5)).isoformat(),
        },
    ]


def mock_dashboard_payload(
    config_path: str,
    *,
    days: int = 14,
    limit: int = 100,
    start_ts: str | datetime | None = None,
    end_ts: str | datetime | None = None,
    status_filter: str | None = None,
    source_file_filter: str | None = None,
    username_filter: str | list[str] | None = None,
    destination_table_filter: str | list[str] | None = None,
    row_no_filter: int | None = None,
    message_filter: str | None = None,
    hash_value_filter: str | None = None,
    payload_filter: str | None = None,
    page: int = 1,
    chart_bucket: str | None = "day",
) -> dict[str, Any]:
    cfg = load_json_config(config_path)
    task_name = _dashboard_name(cfg, Path(config_path))
    table = _audit_table(cfg)
    days, start_dt, end_dt = _audit_time_window(days, start_ts, end_ts)
    chart_bucket, chart_bucket_label, _ = _audit_chart_bucket(chart_bucket)
    clean_status = str(status_filter or "").strip()
    clean_source_file = str(source_file_filter or "").strip().lower()
    clean_usernames = _normalize_destination_table_filters(username_filter)
    clean_destination_tables = _normalize_destination_table_filters(destination_table_filter)
    clean_message = str(message_filter or "").strip().lower()
    clean_hash = str(hash_value_filter or "").strip().lower()
    clean_payload = str(payload_filter or "").strip().lower()

    all_rows = mock_audit_rows()
    recent = []
    for row in all_rows:
        if clean_status and row["status"] != clean_status:
            continue
        if clean_source_file and clean_source_file not in row["source_file"].lower():
            continue
        if clean_usernames and row["username"] not in clean_usernames:
            continue
        if clean_destination_tables and row["destination_table"] not in clean_destination_tables:
            continue
        if row_no_filter is not None and row["row_no"] != int(row_no_filter):
            continue
        if clean_message and clean_message not in row["message"].lower():
            continue
        if clean_hash and clean_hash not in row["hash_value"].lower():
            continue
        if clean_payload and clean_payload not in str(row["row_payload"]).lower():
            continue
        recent.append(dict(row))

    limit = max(1, min(int(limit), 1000))
    page = max(1, int(page))
    total = len(recent)
    max_page = max(1, (total + limit - 1) // limit)
    page = min(page, max_page)
    offset = (page - 1) * limit
    page_rows = recent[offset : offset + limit]

    summary = _count_by(all_rows, "status")
    filtered_daily = _bucket_rows(recent)
    return {
        "config_path": str(Path(config_path)),
        "audit_table": table,
        "task_name": task_name,
        "days": days,
        "start_ts": start_dt.isoformat() if start_dt else None,
        "end_ts": end_dt.isoformat() if end_dt else None,
        "audit_time_basis": "Vercel mock SQL audit data (UTC)",
        "chart_bucket": chart_bucket,
        "chart_bucket_label": chart_bucket_label,
        "recent_filters": {
            "status": clean_status,
            "source_file": clean_source_file,
            "username": clean_usernames,
            "destination_table": clean_destination_tables,
            "row_no": row_no_filter,
            "message": clean_message,
            "hash_value": clean_hash,
            "payload": clean_payload,
        },
        "filtered_daily": filtered_daily,
        "filtered_series": filtered_daily,
        "recent_paging": {"page": page, "page_size": limit, "total": total},
        "exists": True,
        "mock_mode": True,
        "summary": summary,
        "daily": _bucket_rows(all_rows, include_status=True),
        "files": [
            {
                "source_file": "印尼災害援助事件_mock.xlsx",
                "last_processed_at": all_rows[0]["processed_at"],
                "total_rows": 3,
                "inserted_rows": 2,
                "duplicate_rows": 1,
                "failed_rows": 0,
                "header_smart_matches": 0,
            }
        ],
        "destination_table_options": [MOCK_DESTINATION_TABLE],
        "username_options": ["vercel-demo"],
        "recent": page_rows,
        "warnings": ["目前使用 Vercel mock SQL Server audit 資料，未連線正式 SQL Server。"],
        "destination_table": str(get_nested(cfg, "destination.table", "") or MOCK_DESTINATION_TABLE),
    }


def mock_delete_imported_sql_row(config_path: str, *, hash_value: str, actor: str, reason: str = "") -> dict[str, Any]:
    load_json_config(config_path)
    return {
        "ok": True,
        "deleted": False,
        "deleted_rows": 0,
        "status": "mock_sql_delete_skipped",
        "deleted_row_payloads": [],
        "mock_mode": True,
        "hash_value": hash_value,
        "actor": actor,
        "reason": reason,
        "message": "Vercel mock SQL mode: no SQL Server row was deleted.",
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return [{key: value, "count": count} for value, count in sorted(counts.items())]


def _bucket_rows(rows: list[dict[str, Any]], *, include_status: bool = False) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        day = str(row.get("processed_at") or "")[:10]
        status = str(row.get("status") or "") if include_status else ""
        counts[(day, status)] = counts.get((day, status), 0) + 1
    out = []
    for (day, status), count in sorted(counts.items(), reverse=True):
        item: dict[str, Any] = {"bucket_start" if not include_status else "day": day, "count": count}
        if include_status:
            item["status"] = status
        out.append(item)
    return out
