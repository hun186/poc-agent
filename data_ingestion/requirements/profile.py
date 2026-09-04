from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.parser import parse as parse_datetime

from .hashing import canonical_sha256
from .models import CanonicalRequirementRow, FieldMappingSpec, ImportProfileDocument, NormalizedCandidate, RowDiagnostic


def normalize_source_datetime(value: Any, timezone_name: str) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("profile_invalid: unknown source_timezone") from exc
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = parse_datetime(value.strip())
        except (ValueError, OverflowError) as exc:
            raise ValueError("datetime_parse_error") from exc
    else:
        raise ValueError("datetime_parse_error")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc)


def _normalized_header(value: str, *, trim: bool, case_sensitive: bool) -> str:
    result = value.strip() if trim else value
    return result if case_sensitive else result.casefold()


def _resolve_header(headers: list[str], spec: FieldMappingSpec, profile: ImportProfileDocument) -> str | None:
    ws = profile.worksheet
    trim, case_sensitive = (ws.trim_headers, ws.case_sensitive) if ws else (True, False)
    wanted = [spec.source, *spec.aliases]
    normalized_wanted = {_normalized_header(value, trim=trim, case_sensitive=case_sensitive) for value in wanted}
    normalized_matches = [header for header in headers if _normalized_header(header, trim=trim, case_sensitive=case_sensitive) in normalized_wanted]
    if len(normalized_matches) > 1:
        raise ValueError("mapping_ambiguous_column")
    levels = ["exact", "normalized", "prefix", "contains"]
    max_level = levels.index(spec.match)
    for level in levels[: max_level + 1]:
        matches: list[str] = []
        for header in headers:
            for candidate in wanted:
                if level == "exact":
                    matched = header == candidate
                else:
                    left = _normalized_header(header, trim=trim, case_sensitive=case_sensitive)
                    right = _normalized_header(candidate, trim=trim, case_sensitive=case_sensitive)
                    matched = left == right if level == "normalized" else (left.startswith(right) if level == "prefix" else right in left)
                if matched:
                    matches.append(header)
                    break
        matches = list(dict.fromkeys(matches))
        if len(matches) > 1:
            raise ValueError("mapping_ambiguous_column")
        if matches:
            return matches[0]
    return None


def _convert(value: Any, spec: FieldMappingSpec, timezone_name: str) -> Any:
    for transform in spec.transforms:
        if transform == "trim" and isinstance(value, str): value = value.strip()
        elif transform == "normalize_whitespace" and isinstance(value, str): value = re.sub(r"\s+", " ", value).strip()
        elif transform == "empty_to_null" and (value is None or (isinstance(value, str) and not value.strip())): value = None
        elif transform == "to_text" and value is not None: value = str(value).strip()
        elif transform == "to_int" and value is not None: value = int(value)
        elif transform == "to_datetime" and value is not None: value = normalize_source_datetime(value, timezone_name)
    if value is None:
        return None
    if spec.type == "datetime" and not isinstance(value, datetime): return normalize_source_datetime(value, timezone_name)
    if spec.type == "int" and not isinstance(value, int): return int(value)
    if spec.type == "text" and not isinstance(value, str): return str(value)
    if spec.type == "bool" and not isinstance(value, bool):
        normalized = str(value).strip().casefold()
        if normalized not in {"true", "false", "1", "0", "yes", "no"}: raise ValueError("type_conversion_error")
        return normalized in {"true", "1", "yes"}
    if spec.type == "json" and isinstance(value, str): return json.loads(value)
    return value


def normalize_rows(raw_rows: list[dict[str, Any]], profile: ImportProfileDocument, source_row_numbers: list[int] | None = None) -> NormalizedCandidate:
    rows, diagnostics = [], []
    try:
        ZoneInfo(profile.source_timezone)
    except ZoneInfoNotFoundError:
        return NormalizedCandidate(diagnostics=[RowDiagnostic(code="profile_invalid", message="Unknown source timezone")])
    for index, raw in enumerate(raw_rows):
        row_no = source_row_numbers[index] if source_row_numbers else index + 1
        mapped: dict[str, Any] = {}
        try:
            headers = [str(key) for key in raw]
            for name, spec in profile.mapping.items():
                header = _resolve_header(headers, spec, profile)
                value = raw.get(header) if header is not None else spec.default
                if header is None and spec.required and value is None: raise ValueError("mapping_missing_required_column")
                value = _convert(value, spec, profile.source_timezone)
                if spec.required and (value is None or value == ""): raise ValueError("mapping_missing_required_value")
                mapped[name] = value
            full = {key: mapped.get(key) for key in sorted(mapped)}
            row_hash = canonical_sha256(full)
            payload_hash = canonical_sha256({key: value for key, value in full.items() if key != "source_updated_at"})
            execution_hash = canonical_sha256({key: mapped.get(key) for key in ("title", "prompt_content", "expires_at")})
            rows.append(CanonicalRequirementRow(source_row_number=row_no, source_row_hash=row_hash, source_payload_hash=payload_hash, execution_content_hash=execution_hash, source_raw={str(k): v for k, v in raw.items()}, **mapped))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            code = str(exc).split(":", 1)[0]
            diagnostics.append(RowDiagnostic(source_row_number=row_no, external_item_id=str(mapped.get("external_item_id") or "") or None, code=code, message=code))
    seen: dict[str, int] = {}
    for row in rows:
        if row.external_item_id in seen:
            diagnostics.append(RowDiagnostic(source_row_number=row.source_row_number, external_item_id=row.external_item_id, code="duplicate_external_item_id", message="Duplicate external item identity"))
        seen[row.external_item_id] = row.source_row_number
    return NormalizedCandidate(rows=rows, diagnostics=diagnostics)
