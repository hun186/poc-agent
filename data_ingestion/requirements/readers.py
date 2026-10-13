from __future__ import annotations

import csv
from io import BytesIO, StringIO
import json
from importlib import import_module
from importlib.util import find_spec
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

# Match openpyxl's optional lxml parser without a try/except-wrapped import.
# Keep stdlib-only environments supported, and follow AGENTS.md import policy.
LxmlXMLSyntaxError = (
    import_module("lxml.etree").XMLSyntaxError
    if find_spec("lxml") is not None else ParseError
)

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
    header_values = next(
        sheet.iter_rows(
            min_row=settings.header_row,
            max_row=settings.header_row,
            values_only=True,
        ),
        None,
    )
    if header_values is None or not any(value is not None and value != "" for value in header_values):
        workbook.close()
        raise ValueError("source_format_invalid")
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


def _preflight_csv_preview_columns(source: str, *, max_columns: int = 128) -> None:
    """Reject over-wide CSV records before csv.reader constructs field lists.

    Respect RFC-style quoted commas, doubled quotes, and quoted newlines.
    This is a width preflight, not a second CSV parser: csv.reader remains
    responsible for field values and malformed CSV syntax.
    """
    columns = 1
    quoted = False
    field_start = True
    index = 0
    while index < len(source):
        char = source[index]
        if quoted:
            if char == '"':
                if index + 1 < len(source) and source[index + 1] == '"':
                    index += 1
                else:
                    quoted = False
        elif char == '"' and field_start:
            quoted = True
            field_start = False
        elif char == ",":
            columns += 1
            if columns > max_columns:
                raise ValueError("requirement_preview_too_large")
            field_start = True
        elif char in "\\r\\n":
            columns = 1
            field_start = True
            if char == "\\r" and index + 1 < len(source) and source[index + 1] == "\\n":
                index += 1
        else:
            field_start = False
        index += 1


def read_csv_rows(content: bytes, *, max_rows: int | None = None) -> tuple[list[dict[str, Any]], list[int]]:
    try:
        source = content.decode("utf-8-sig")
        if max_rows is not None:
            # Enforce width while scanning the raw logical records. Waiting
            # until csv.reader returns a row can allocate millions of cells.
            _preflight_csv_preview_columns(source)
        parsed = csv.reader(StringIO(source))
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
    if max_rows is None:
        # Preserve the complete/unbounded internal Phase 1B import contract.
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("source_format_invalid") from exc
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ValueError("source_format_invalid")
        return payload, list(range(1, len(payload) + 1))

    # HTTP preview: never json.loads() the *entire* uploaded array. A compact
    # 10-MiB JSON array can contain millions of '{}' elements, producing huge
    # Python object graphs before a post-decode row-limit check.
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("source_format_invalid") from exc
    length = len(source)
    index = 0

    def skip_space(pos: int) -> int:
        while pos < length and source[pos] in " \t\r\n":
            pos += 1
        return pos

    index = skip_space(index)
    if index >= length or source[index] != "[":
        raise ValueError("source_format_invalid")
    index += 1
    rows: list[dict[str, Any]] = []
    total_cells = 0
    total_value_bytes = 0
    total_json_structure_tokens = 0
    # Bound nested objects, lists and scalar separators BEFORE json.loads
    # builds a row: compact arrays of "{}" otherwise amplify dramatically.
    max_row_structure_tokens = 5000
    max_total_structure_tokens = 100000
    while True:
        index = skip_space(index)
        if index >= length:
            raise ValueError("source_format_invalid")
        if source[index] == "]":
            if any(ch not in " \t\r\n" for ch in source[index + 1:]):
                raise ValueError("source_format_invalid")
            return rows, list(range(1, len(rows) + 1))
        if len(rows) >= max_rows:
            raise ValueError("requirement_preview_too_large")

        # Find one top-level JSON element without constructing its objects.
        # Respect nested arrays/objects and strings containing commas, brackets
        # and escaped quotes. A per-item cap prevents a single giant object
        # from being materialized before the cell count can be checked.
        start = index
        fragment_bytes = 0
        row_structure_tokens = 0
        depth = 0
        in_string = False
        escaped = False
        while index < length:
            char = source[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char in "[{":
                depth += 1
            elif char in "]}":
                if depth == 0:
                    break
                depth -= 1
            elif char == "," and depth == 0:
                # The outer comma delimits two rows; it must NOT become
                # part of the JSON fragment decoded for the previous row.
                break
            # Count nested structure only AFTER identifying boundaries:
            # the outer row delimiter must not be consumed by this counter.
            if not in_string and char in "[{:,":
                row_structure_tokens += 1
                total_json_structure_tokens += 1
                if (row_structure_tokens > max_row_structure_tokens
                        or total_json_structure_tokens > max_total_structure_tokens):
                    raise ValueError("requirement_preview_too_large")
            # The cap is measured in the original UTF-8 representation,
            # never decoded Unicode code points. Non-ASCII content can use
            # up to four bytes per code point.
            fragment_bytes += len(char.encode("utf-8"))
            if fragment_bytes > 1024 * 1024:
                raise ValueError("requirement_preview_too_large")
            index += 1
        if index >= length:
            raise ValueError("source_format_invalid")
        # The only legal separators between JSON array elements are ',' and
        # the final ']'. An extra '}' must not silently act like a comma.
        if source[index] not in ",]":
            raise ValueError("source_format_invalid")
        fragment = source[start:index].strip()
        if not fragment:
            raise ValueError("source_format_invalid")
        try:
            row = json.loads(fragment)
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise ValueError("source_format_invalid") from exc
        if not isinstance(row, dict):
            raise ValueError("source_format_invalid")
        total_cells += len(row)
        if len(row) > 128 or total_cells > 50000:
            raise ValueError("requirement_preview_too_large")
        try:
            for key, value in row.items():
                total_value_bytes += len(str(key).encode("utf-8"))
                if isinstance(value, str):
                    total_value_bytes += len(value.encode("utf-8"))
                else:
                    total_value_bytes += len(
                        json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
                    )
                if total_value_bytes > 8 * 1024 * 1024:
                    raise ValueError("requirement_preview_too_large")
        except UnicodeEncodeError as exc:
            # json.loads accepts isolated \\uD800-\\uDFFF escapes, but such
            # values (including nested keys/values) cannot encode as UTF-8.
            # Keep malformed user input separate from backend failures.
            raise ValueError("source_format_invalid") from exc
        rows.append(row)
        delimiter = source[index]
        index += 1
        if delimiter == "]":
            if any(ch not in " \t\r\n" for ch in source[index:]):
                raise ValueError("source_format_invalid")
            return rows, list(range(1, len(rows) + 1))
        # Reject trailing commas and doubled separators before the next row.
        index = skip_space(index)
        if index >= length or source[index] in "],":
            raise ValueError("source_format_invalid")



def read_bytes(content: bytes, filename: str, profile: ImportProfileDocument, *, max_rows: int | None = None) -> tuple[list[dict[str, Any]], list[int]]:
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    expected = {"xlsx": "xlsx", "csv": "csv", "json": "json"}.get(profile.format)
    if expected is None or extension != expected:
        raise ValueError("source_format_invalid")
    if extension == "xlsx":
        try:
            return read_xlsx_rows(content, profile, max_rows=max_rows)
        except (BadZipFile, InvalidFileException, KeyError, IndexError,
                EOFError, UnicodeError, OSError, ParseError,
                LxmlXMLSyntaxError, TypeError) as exc:
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
