from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict

from .utils import is_empty_value, normalize_header_key


def normalize_cell_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return value.strip()
    return value


def is_date_mapping(source_label: Any, dest_field: Any) -> bool:
    source_key = normalize_header_key(source_label)
    dest_key = str(dest_field or "").strip().lower()
    return source_key in {"日期", "date", "活動日期"} or dest_key == "date" or dest_key.endswith("_date")


def normalize_date_text_for_parser(text: str) -> str:
    normalized = text.strip().replace("年", "/").replace("月", "/").replace("日", "")
    normalized = re.sub(r"[.\-]", "/", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    match = re.match(r"^(?P<year>\d{1,4})(?P<sep>/)(?P<month>\d{1,2})/(?P<day>\d{1,2})(?P<rest>.*)$", normalized)
    if match:
        year = int(match.group("year"))
        if 1 <= year <= 199:
            normalized = (
                f"{year + 1911}/{match.group('month')}/{match.group('day')}"
                f"{match.group('rest')}"
            )
        return normalized

    compact_match = re.match(r"^(?P<digits>\d{8}|\d{7})(?P<rest>.*)$", normalized)
    if compact_match:
        digits = compact_match.group("digits")
        rest = compact_match.group("rest")
        if len(digits) == 7:
            year = int(digits[:3]) + 1911
            return f"{year}/{digits[3:5]}/{digits[5:7]}{rest}"
        return f"{digits[:4]}/{digits[4:6]}/{digits[6:8]}{rest}"

    return normalized


def normalize_sql_date_value(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        raise ValueError("日期不可為空")

    from dateutil import parser as date_parser

    normalized = normalize_date_text_for_parser(text)
    try:
        parsed = date_parser.parse(
            normalized,
            yearfirst=True,
            dayfirst=False,
            fuzzy=False,
            default=datetime(1900, 1, 1),
        )
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"不支援或無效日期格式：{text}") from exc

    return parsed.date()


def normalize_mapping_value(value: Any, mapping: Dict[str, Any]) -> Any:
    value_type = str(mapping.get("value_type", "") or "").strip().lower()
    if value_type in {"date", "sql_date"} and not is_empty_value(value):
        return normalize_sql_date_value(value)
    return value
