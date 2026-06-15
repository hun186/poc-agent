from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ingest import load_json_config

ROOT = Path("data/excel_to_sql_user_imports")
ACTIVE_DIR = ROOT / "active"
DELETED_DIR = ROOT / "deleted"
REGISTRY = ROOT / "records.json"
ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    DELETED_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRY.exists():
        REGISTRY.write_text(
            json.dumps({"records": []}, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def read_registry() -> dict[str, Any]:
    ensure_dirs()
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {"records": []}
    if not isinstance(data.get("records"), list):
        data["records"] = []
    return data


def write_registry(data: dict[str, Any]) -> None:
    ensure_dirs()
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    tmp.replace(REGISTRY)


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
            and filename.lower() not in str(record.get("original_filename", "")).lower()
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
    with stored_path.open("wb") as fh:
        shutil.copyfileobj(fileobj, fh)
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
        "file_size": stored_path.stat().st_size,
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


def delete_records(
    record_ids: list[str], *, username: str, is_superuser: bool, reason: str = ""
) -> dict[str, Any]:
    data = read_registry()
    deleted = []
    skipped = []
    for record in data["records"]:
        if record.get("id") not in record_ids:
            continue
        if not is_superuser and record.get("username") != username:
            skipped.append({"id": record.get("id"), "reason": "forbidden"})
            continue
        if record.get("status") == "deleted":
            skipped.append({"id": record.get("id"), "reason": "already_deleted"})
            continue
        src = Path(str(record.get("stored_path") or ""))
        suffix = src.suffix or Path(str(record.get("stored_filename", ""))).suffix
        target = DELETED_DIR / f"{record['id']}{suffix}"
        if src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            record["deleted_path"] = str(target)
        record.update(
            {
                "status": "deleted",
                "deleted_at": utc_now(),
                "deleted_by": username,
                "delete_reason": reason,
                "updated_at": utc_now(),
            }
        )
        deleted.append(record.get("id"))
    write_registry(data)
    return {"deleted": deleted, "skipped": skipped}
