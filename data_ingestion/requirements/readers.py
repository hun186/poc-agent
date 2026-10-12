from __future__ import annotations

import csv
from io import BytesIO, StringIO
import json
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

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
    # HTTP previews only: cap the entire decoded matrix, not just row count.
    # The full internal P1 import paths pass max_rows=None and retain their
    # existing semantics.
    preview_cells = len(headers)
    preview_value_bytes = sum(len(header.encode("utf-8")) for header in headers)
    if max_rows is not None and (len(headers) > 128 or preview_value_bytes > 8 * 1024 * 1024):
        workbook.close()
        raise ValueError("requirement_preview_too_large")
    for row_number, values in enumerate(sheet.iter_rows(min_row=settings.first_data_row, values_only=True), settings.first_data_row):
        if max_rows is not None:
            preview_cells += len(values)
            if len(values) > 128 or preview_cells > 50000:
                workbook.close()
                raise ValueError("requirement_preview_too_large")
            preview_value_bytes += sum(
                len(value.encode("utf-8")) if isinstance(value, str) else 64
                for value in values if value is not None
            )
            if (preview_value_bytes > 8 * 1024 * 1024
                    or row_number > settings.first_data_row + max_rows * 4):
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
            workbook.close()
            raise ValueError("requirement_preview_too_large")
    workbook.close()
    return rows, numbers


def read_csv_rows(content: bytes, *, max_rows: int | None = None) -> tuple[list[dict[str, Any]], list[int]]:
    try:
        parsed = csv.reader(StringIO(content.decode("utf-8-sig")))
        headers = next(parsed)
    except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
        raise ValueError("source_format_invalid") from exc
    if not headers or not any(header for header in headers):
        raise ValueError("source_format_invalid")
    # Only HTTP previews pass max_rows: bound width before building keys.
    # Full internal import paths (max_rows=None) retain their old behavior.
    preview_cells = len(headers)
    preview_value_bytes = sum(len(header.encode("utf-8")) for header in headers)
    if max_rows is not None and (
        len(headers) > 128 or preview_value_bytes > 8 * 1024 * 1024
    ):
        raise ValueError("requirement_preview_too_large")
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
            if max_rows is not None:
                # Count cells and value bytes before constructing dictionaries;
                # sparse CSV must not inflate into millions of copied fields.
                preview_cells += len(values)
                if len(values) > 128 or preview_cells > 50000:
                    raise ValueError("requirement_preview_too_large")
                preview_value_bytes += sum(len(v.encode("utf-8")) for v in values)
                if preview_value_bytes > 8 * 1024 * 1024:
                    raise ValueError("requirement_preview_too_large")
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
    if max_rows is not None:
        if len(payload) > max_rows:
            raise ValueError("requirement_preview_too_large")
        # JSON is already decoded by json.loads, but must also be bounded
        # before Phase 1B normalization duplicates source_raw objects.
        total_cells = 0
        total_value_bytes = 0
        for row in payload:
            total_cells += len(row)
            if len(row) > 128 or total_cells > 50000:
                raise ValueError("requirement_preview_too_large")
            for key, value in row.items():
                total_value_bytes += len(str(key).encode("utf-8"))
                if isinstance(value, str):
                    total_value_bytes += len(value.encode("utf-8"))
                else:
                    total_value_bytes += len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
                if total_value_bytes > 8 * 1024 * 1024:
                    raise ValueError("requirement_preview_too_large")
    return payload, list(range(1, len(payload) + 1))


def read_bytes(content: bytes, filename: str, profile: ImportProfileDocument, *, max_rows: int | None = None) -> tuple[list[dict[str, Any]], list[int]]:
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    expected = {"xlsx": "xlsx", "csv": "csv", "json": "json"}.get(profile.format)
    if expected is None or extension != expected:
        raise ValueError("source_format_invalid")
    if extension == "xlsx":
        try:
            return read_xlsx_rows(content, profile, max_rows=max_rows)
        except (BadZipFile, InvalidFileException, KeyError, IndexError,
                EOFError, UnicodeError, OSError, ParseError, TypeError) as exc:
            # Failures from the *upload parser* are invalid user input,
            # not a missing Product/Run identity or backend persistence error.
            # This boundary is intentionally specific to XLSX decoding.
            # openpyxl also raises TypeError for malformed workbook XML
            # attributes (e.g. a non-integer sheetId).
            raise ValueError("source_format_invalid") from exc
        except ValueError as exc:
            # Preserve stable profile/preview-limit validation codes. Other
            # openpyxl parsing ValueErrors indicate malformed upload content.
            if str(exc).split(":", 1)[0] in {
                "profile_invalid", "source_format_invalid",
                "requirement_preview_too_large",
            }:
                raise
            raise ValueError("source_format_invalid") from exc
    if extension == "csv": return read_csv_rows(content, max_rows=max_rows)
    return read_json_rows(content, max_rows=max_rows)
