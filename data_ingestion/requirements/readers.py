from __future__ import annotations

import csv
from io import BytesIO, StringIO
import json
from typing import Any

from openpyxl import load_workbook

from .models import ImportProfileDocument


def read_xlsx_rows(content: bytes, profile: ImportProfileDocument, *, max_rows: int | None = None) -> tuple[list[dict[str, Any]], list[int]]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    settings = profile.worksheet
    if settings is None:
        raise ValueError("profile_invalid")
    if settings.name and settings.name not in workbook.sheetnames:
        raise ValueError("source_format_invalid")
    sheet = workbook[settings.name] if settings.name else workbook.active
    if max_rows is not None:
        # XLSX can declare huge sparse dimensions without substantial ZIP size.
        if (sheet.max_column is not None and sheet.max_column > 512
                or sheet.max_row is not None
                and sheet.max_row > settings.first_data_row + max_rows * 4):
            workbook.close()
            raise ValueError("requirement_preview_too_large")
    header_values = next(sheet.iter_rows(min_row=settings.header_row, max_row=settings.header_row, values_only=True))
    headers = ["" if value is None else str(value) for value in header_values]
    rows, numbers = [], []
    for row_number, values in enumerate(sheet.iter_rows(min_row=settings.first_data_row, values_only=True), settings.first_data_row):
        if max_rows is not None and row_number > settings.first_data_row + max_rows * 4:
            workbook.close()
            raise ValueError("requirement_preview_too_large")
        if not any(value is not None and value != "" for value in values):
            continue
        # Preserve duplicate labels for strict ambiguity detection instead of overwriting them.
        record: dict[str, Any] = {}
        for position, (header, value) in enumerate(zip(headers, values, strict=False), 1):
            key = header or f"__column_{position}"
            while key in record:
                key += " "
            record[key] = value
        rows.append(record); numbers.append(row_number)
        if max_rows is not None and len(rows) > max_rows:
            raise ValueError("requirement_preview_too_large")
    return rows, numbers


def read_csv_rows(content: bytes, *, max_rows: int | None = None) -> tuple[list[dict[str, Any]], list[int]]:
    try:
        parsed = csv.reader(StringIO(content.decode("utf-8-sig")))
        headers = next(parsed)
    except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
        raise ValueError("source_format_invalid") from exc
    if not headers or not any(header for header in headers):
        raise ValueError("source_format_invalid")
    keys: list[str] = []
    for position, header in enumerate(headers, 1):
        key = header or f"__column_{position}"
        while key in keys:
            key += " "
        keys.append(key)
    rows: list[dict[str, Any]] = []
    numbers: list[int] = []
    try:
        for row_number, values in enumerate(parsed, 2):
            if not any(value != "" for value in values):
                continue
            if len(values) > len(keys) and any(values[len(keys):]):
                raise ValueError("source_format_invalid")
            rows.append({key: value for key, value in zip(keys, values, strict=False)})
            numbers.append(row_number)
            if max_rows is not None and len(rows) > max_rows:
                raise ValueError("requirement_preview_too_large")
    except csv.Error as exc:
        raise ValueError("source_format_invalid") from exc
    return rows, numbers


def read_json_rows(content: bytes, *, max_rows: int | None = None) -> tuple[list[dict[str, Any]], list[int]]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("source_format_invalid") from exc
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError("source_format_invalid")
    if max_rows is not None and len(payload) > max_rows:
        raise ValueError("requirement_preview_too_large")
    return payload, list(range(1, len(payload) + 1))


def read_bytes(content: bytes, filename: str, profile: ImportProfileDocument, *, max_rows: int | None = None) -> tuple[list[dict[str, Any]], list[int]]:
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    expected = {"xlsx": "xlsx", "csv": "csv", "json": "json"}.get(profile.format)
    if expected is None or extension != expected:
        raise ValueError("source_format_invalid")
    if extension == "xlsx": return read_xlsx_rows(content, profile, max_rows=max_rows)
    if extension == "csv": return read_csv_rows(content, max_rows=max_rows)
    return read_json_rows(content, max_rows=max_rows)
