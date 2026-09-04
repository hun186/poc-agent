from __future__ import annotations

import csv
from io import BytesIO, StringIO
import json
from typing import Any

from openpyxl import load_workbook

from .models import ImportProfileDocument


def read_xlsx_rows(content: bytes, profile: ImportProfileDocument) -> tuple[list[dict[str, Any]], list[int]]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    settings = profile.worksheet
    if settings is None:
        raise ValueError("profile_invalid")
    if settings.name and settings.name not in workbook.sheetnames:
        raise ValueError("source_format_invalid")
    sheet = workbook[settings.name] if settings.name else workbook.active
    header_values = next(sheet.iter_rows(min_row=settings.header_row, max_row=settings.header_row, values_only=True))
    headers = ["" if value is None else str(value) for value in header_values]
    rows, numbers = [], []
    for row_number, values in enumerate(sheet.iter_rows(min_row=settings.first_data_row, values_only=True), settings.first_data_row):
        if not any(value is not None and value != "" for value in values):
            continue
        # Preserve duplicate labels for strict ambiguity detection instead of overwriting them.
        record: dict[str, Any] = {}
        for position, (header, value) in enumerate(zip(headers, values, strict=False), 1):
            key = header
            while key in record:
                key += " "
            record[key or f"__column_{position}"] = value
        rows.append(record); numbers.append(row_number)
    return rows, numbers


def read_csv_rows(content: bytes) -> tuple[list[dict[str, Any]], list[int]]:
    reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
    if not reader.fieldnames:
        raise ValueError("source_format_invalid")
    rows = [dict(row) for row in reader]
    return rows, list(range(2, len(rows) + 2))


def read_json_rows(content: bytes) -> tuple[list[dict[str, Any]], list[int]]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("source_format_invalid") from exc
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError("source_format_invalid")
    return payload, list(range(1, len(payload) + 1))


def read_bytes(content: bytes, filename: str, profile: ImportProfileDocument) -> tuple[list[dict[str, Any]], list[int]]:
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    expected = {"xlsx": "xlsx", "csv": "csv", "json": "json"}.get(profile.format)
    if expected is None or extension != expected:
        raise ValueError("source_format_invalid")
    if extension == "xlsx": return read_xlsx_rows(content, profile)
    if extension == "csv": return read_csv_rows(content)
    return read_json_rows(content)
