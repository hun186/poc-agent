from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List


def get_nested(cfg: Dict[str, Any], path: str, default=None):
    cur = cfg
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def require_nested(cfg: Dict[str, Any], path: str):
    val = get_nested(cfg, path, default=None)
    if val is None or (isinstance(val, str) and not val.strip()):
        raise ValueError(f"設定檔缺少必要欄位：{path}")
    return val


def chunked(iterable, size: int):
    buf = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def load_json_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def resolve_path(config_path: str, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path

    config_relative = (Path(config_path).resolve().parent / path).resolve()
    if config_relative.exists():
        return config_relative

    return (Path.cwd() / path).resolve()


def resolve_excel_path(config_path: str, excel_path: str) -> Path:
    return resolve_path(config_path, excel_path)


def normalize_header(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_header_key(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def is_empty_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value
