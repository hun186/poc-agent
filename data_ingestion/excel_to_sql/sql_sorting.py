from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class SqlSortSpec:
    field: str
    direction: str
    expression: str


def _parse_sort_item(item: str) -> tuple[str, str]:
    raw = str(item or "").strip()
    if not raw:
        return "", ""
    if ":" in raw:
        field, direction = raw.rsplit(":", 1)
    else:
        field, direction = raw, "asc"
    return field.strip(), direction.strip().lower()


def normalize_sql_sort_specs(
    sort: Sequence[str] | str | None,
    *,
    allowed_expressions: Mapping[str, str],
    default: Sequence[tuple[str, str]],
    max_fields: int = 5,
) -> list[SqlSortSpec]:
    """Validate user controlled SQL sort fields and directions.

    ``allowed_expressions`` maps public field names to already-safe SQL expressions.
    Only keys in that map are accepted; directions are limited to ASC/DESC.
    """
    raw_items: list[str]
    if sort is None:
        raw_items = []
    elif isinstance(sort, str):
        raw_items = [part for part in sort.split(",")]
    else:
        raw_items = []
        for item in sort:
            raw_items.extend(str(item or "").split(","))

    lookup = {str(key).lower(): (str(key), expr) for key, expr in allowed_expressions.items()}
    specs: list[SqlSortSpec] = []
    seen: set[str] = set()
    for item in raw_items:
        field, direction = _parse_sort_item(item)
        if not field:
            continue
        key = field.lower()
        if key not in lookup:
            raise ValueError(f"不支援的排序欄位：{field}")
        if direction not in {"asc", "desc"}:
            raise ValueError(f"排序方向只允許 asc 或 desc：{field}:{direction}")
        if key in seen:
            continue
        public_field, expression = lookup[key]
        specs.append(SqlSortSpec(public_field, direction.upper(), expression))
        seen.add(key)
        if len(specs) >= max_fields:
            break

    for field, direction in default:
        key = str(field).lower()
        if key in seen or key not in lookup:
            continue
        safe_direction = str(direction or "asc").lower()
        if safe_direction not in {"asc", "desc"}:
            safe_direction = "asc"
        public_field, expression = lookup[key]
        specs.append(SqlSortSpec(public_field, safe_direction.upper(), expression))
        seen.add(key)

    return specs


def sql_order_by_clause(specs: Sequence[SqlSortSpec]) -> str:
    if not specs:
        raise ValueError("至少需要一個排序欄位。")
    return ", ".join(f"{spec.expression} {spec.direction}" for spec in specs)


def sort_specs_payload(specs: Sequence[SqlSortSpec]) -> list[dict[str, str]]:
    return [{"field": spec.field, "direction": spec.direction.lower()} for spec in specs]
