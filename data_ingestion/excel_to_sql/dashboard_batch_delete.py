from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def delete_imported_sql_rows_batch(
    config_path: str,
    *,
    hash_values: list[str],
    actor: str,
    reason: str = "",
    delete_one: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    cleaned = []
    seen = set()
    for value in hash_values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            cleaned.append(clean)
            seen.add(clean)
    if not cleaned:
        raise ValueError("至少需要一筆 hash_value 才能批次刪除。")
    if len(cleaned) > 500:
        raise ValueError("單次批次刪除最多支援 500 筆 hash_value。")

    deleted_at = datetime.now(timezone.utc).isoformat()
    report_rows = []
    total_deleted = 0
    for hash_value in cleaned:
        row = {
            "deleted_at": deleted_at,
            "actor": actor,
            "config_path": str(Path(config_path)),
            "hash_value": hash_value,
            "reason": reason,
        }
        try:
            result = delete_one(
                config_path, hash_value=hash_value, actor=actor, reason=reason
            )
            row.update(result)
            total_deleted += int(result.get("deleted_rows") or 0)
        except Exception as exc:
            row.update({
                "ok": False,
                "status": "error",
                "error": str(exc),
                "deleted_rows": 0,
            })
        report_rows.append(row)
    return {
        "ok": True,
        "processed": len(report_rows),
        "deleted_rows": total_deleted,
        "report": {
            "generated_at": deleted_at,
            "actor": actor,
            "config_path": str(Path(config_path)),
            "reason": reason,
            "rows": report_rows,
        },
    }
