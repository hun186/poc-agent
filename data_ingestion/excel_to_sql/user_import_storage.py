from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.services.vercel_mock_runtime import should_prefer_mock_runtime

from .ingest import load_json_config

ROOT = Path("data/excel_to_sql_user_imports")
ACTIVE_DIR = ROOT / "active"
RECORDS_DIR = ROOT / "records"
REGISTRY = ROOT / "records.json"
ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}
_MOCK_RECORDS: list[dict[str, Any]] = []
_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def using_mock_import_store() -> bool:
    return should_prefer_mock_runtime()


def ensure_dirs() -> None:
    if using_mock_import_store():
        return
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRY.exists():
        REGISTRY.write_text(
            json.dumps({"record_ids": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _record_path(record_id: str) -> Path:
    if not _RECORD_ID_RE.fullmatch(str(record_id or "")):
        raise ValueError("匯入記錄 ID 格式錯誤")
    return RECORDS_DIR / f"{record_id}.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback
    return data if isinstance(data, dict) else fallback


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    tmp.replace(path)


def read_registry() -> dict[str, Any]:
    """Load import records from a compact index plus per-record JSON files.

    Older deployments stored all records directly in ``records.json``.  When
    that format is seen, it is migrated lazily so the active registry only keeps
    IDs while larger preview/import payloads live in one JSON file per record.
    """

    if using_mock_import_store():
        return {"records": [dict(r) for r in _MOCK_RECORDS]}

    ensure_dirs()
    data = _read_json(REGISTRY, {"record_ids": []})
    legacy_records = data.get("records")
    if isinstance(legacy_records, list):
        write_registry({"records": [r for r in legacy_records if isinstance(r, dict)]})
        data = _read_json(REGISTRY, {"record_ids": []})

    record_ids = data.get("record_ids")
    if not isinstance(record_ids, list):
        record_ids = []
    records = []
    missing_ids = set()
    for record_id in record_ids:
        if not isinstance(record_id, str) or not _RECORD_ID_RE.fullmatch(record_id):
            continue
        record = _read_json(_record_path(record_id), {})
        if record.get("id") == record_id:
            records.append(record)
        else:
            missing_ids.add(record_id)

    if missing_ids:
        write_registry({"records": records})
    return {"records": records}


def write_registry(data: dict[str, Any]) -> None:
    if using_mock_import_store():
        _MOCK_RECORDS.clear()
        _MOCK_RECORDS.extend(
            [
                dict(r)
                for r in data.get("records", [])
                if isinstance(r, dict) and r.get("id")
            ]
        )
        return
    ensure_dirs()
    records = [
        r for r in data.get("records", []) if isinstance(r, dict) and r.get("id")
    ]
    record_ids: list[str] = []
    for record in records:
        record_id = str(record["id"])
        record_ids.append(record_id)
        _write_json_atomic(_record_path(record_id), record)
    _write_json_atomic(REGISTRY, {"record_ids": record_ids})


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    hidden = dict(record)
    hidden.pop("stored_path", None)
    hidden.pop("deleted_path", None)
    return hidden


def list_import_records(
    *,
    username: str,
    is_superuser: bool,
    config: str = "",
    status: str = "",
    filename: str = "",
    actor: str = "",
    start_ts: str = "",
    end_ts: str = "",
) -> list[dict[str, Any]]:
    result = []
    for record in read_registry()["records"]:
        if not is_superuser and record.get("username") != username:
            continue
        if config and record.get("config_path") != config:
            continue
        if status and record.get("status") != status:
            continue
        if (
            filename
            and filename.lower()
            not in f'{record.get("original_filename", "")} {record.get("stored_filename", "")}'.lower()
        ):
            continue
        if actor and actor.lower() not in str(record.get("username", "")).lower():
            continue
        created = str(record.get("created_at") or "")
        if start_ts and created < start_ts:
            continue
        if end_ts and created > end_ts:
            continue
        result.append(public_record(record))
    return sorted(
        result, key=lambda item: str(item.get("created_at") or ""), reverse=True
    )


def save_upload(
    *, fileobj, filename: str, username: str, config_path: str
) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("僅支援 Excel Open XML 檔案：.xlsx、.xlsm、.xltx、.xltm")
    load_json_config(config_path)
    ensure_dirs()
    record_id = uuid.uuid4().hex
    safe_name = Path(filename).name or f"upload{suffix}"
    stored_path = ACTIVE_DIR / f"{record_id}{suffix}"
    file_size = 0
    if using_mock_import_store():
        data_bytes = fileobj.read()
        file_size = len(data_bytes or b"")
    else:
        with stored_path.open("wb") as fh:
            shutil.copyfileobj(fileobj, fh)
        file_size = stored_path.stat().st_size
    record = {
        "id": record_id,
        "original_filename": safe_name,
        "stored_filename": stored_path.name,
        "stored_path": str(stored_path),
        "config_path": config_path,
        "username": username,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "status": "uploaded",
        "file_size": file_size,
        "mock_mode": using_mock_import_store(),
        "preview": None,
        "import_result": None,
        "deleted_at": None,
        "deleted_by": None,
        "delete_reason": "",
    }
    data = read_registry()
    data["records"].append(record)
    write_registry(data)
    return public_record(record)
