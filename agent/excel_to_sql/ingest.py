# agent/excel_to_sql/ingest.py
# cd /d D:\shared\TopicClassification\poc-agent
# python -m agent.excel_to_sql.ingest --config config/excel_to_sql/vessel_activities.example.json

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple


EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
DEFAULT_AUDIT_TABLE = "dbo.ExcelImportAudit"
DEFAULT_HASH_FIELD = "hash_value"


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


def quote_ident(name: str) -> str:
    if not name:
        raise ValueError("欄位名稱不可為空")
    return f"[{name.replace(']', ']]')}]"


def quote_object_path(name: str) -> str:
    parts = [part.strip() for part in name.split(".") if part.strip()]
    if not parts:
        raise ValueError(f"無效物件名稱: {name}")
    return ".".join(quote_ident(part) for part in parts)


def build_conn_str_from_config(cfg: Dict[str, Any]) -> str:
    driver = get_nested(cfg, "db.driver", "ODBC Driver 18 for SQL Server")
    server = require_nested(cfg, "db.server")
    database = require_nested(cfg, "db.database")
    trusted_connection = bool(get_nested(cfg, "db.trusted_connection", False))
    user = get_nested(cfg, "db.user", "")
    password = get_nested(cfg, "db.password", "")
    encrypt = bool(get_nested(cfg, "db.encrypt", False))
    trust_cert = bool(get_nested(cfg, "db.trust_server_certificate", False))

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
    ]

    if trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        if not user:
            raise ValueError("設定檔缺少 db.user")
        if not password:
            raise ValueError("設定檔缺少 db.password")
        parts.append(f"UID={user}")
        parts.append(f"PWD={password}")

    if encrypt:
        parts.append("Encrypt=yes")
    if trust_cert:
        parts.append("TrustServerCertificate=yes")

    return ";".join(parts)


@dataclass
class RowResult:
    row_no: int
    hash_value: str
    status: str
    message: str = ""
    row_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FileResult:
    file_path: Path
    success: int = 0
    duplicate: int = 0
    failed: int = 0
    skipped: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.failed == 0


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


def is_empty_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def parse_excel_column_ref(column_ref: str) -> int:
    text = str(column_ref).strip()
    if not text:
        raise ValueError("Excel 欄位參照不可為空")
    if text.isdigit():
        index = int(text)
        if index <= 0:
            raise ValueError(f"Excel 欄位序號必須大於 0：{column_ref}")
        return index
    result = 0
    for char in text.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"Excel 欄位字母格式錯誤：{column_ref}")
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result


def read_header_map(ws, header_row: int) -> Dict[str, int]:
    header_cells = next(ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
    header_map: Dict[str, int] = {}
    duplicates: Dict[str, int] = {}

    for idx, value in enumerate(header_cells, start=1):
        header = normalize_header(value)
        if not header:
            continue
        if header in header_map:
            duplicates[header] = duplicates.get(header, 1) + 1
            continue
        header_map[header] = idx

    if duplicates:
        dup_text = ", ".join(f"{k}({v})" for k, v in sorted(duplicates.items()))
        raise ValueError(f"Excel 標題列有重複欄名，請改用 source_column_index 或 source_column_letter：{dup_text}")

    return header_map


def normalize_header_key(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def resolve_header_candidate(
    *,
    mapping_index: int,
    header_map: Dict[str, int],
    expected_names: Sequence[str],
    match_mode: str,
) -> Tuple[int, str, str, str]:
    candidates_to_try = [name for name in expected_names if name]
    if not candidates_to_try:
        raise ValueError(f"mappings[{mapping_index}] 缺少可比對的來源欄名")

    available = ", ".join(header_map.keys())

    for expected in candidates_to_try:
        if expected in header_map:
            return header_map[expected], expected, "exact", ""

    normalized_headers: Dict[str, List[Tuple[str, int]]] = {}
    for header, idx in header_map.items():
        normalized_headers.setdefault(normalize_header_key(header), []).append((header, idx))

    if match_mode in {"smart", "normalized", "prefix", "contains"}:
        for expected in candidates_to_try:
            expected_key = normalize_header_key(expected)
            matches = normalized_headers.get(expected_key, [])
            if len(matches) == 1:
                header, idx = matches[0]
                return idx, header, "normalized", f"設定欄名 {expected} 以正規化欄名比對到 Excel 欄名 {header}"
            if len(matches) > 1:
                header, idx = sorted(matches, key=lambda item: item[1])[0]
                return (
                    idx,
                    header,
                    "ambiguous_normalized",
                    f"設定欄名 {expected} 正規化後符合多個欄名，已選用第 {idx} 欄 {header}；請檢查設定",
                )

    if match_mode in {"smart", "prefix", "contains"}:
        prefix_matches: List[Tuple[str, int, str]] = []
        for expected in candidates_to_try:
            expected_key = normalize_header_key(expected)
            if not expected_key:
                continue
            for header, idx in header_map.items():
                header_key = normalize_header_key(header)
                if header_key.startswith(expected_key):
                    prefix_matches.append((header, idx, expected))
        if len(prefix_matches) == 1:
            header, idx, expected = prefix_matches[0]
            return idx, header, "prefix", f"設定欄名 {expected} 以前綴智慧比對到 Excel 欄名 {header}"
        if len(prefix_matches) > 1:
            header, idx, expected = sorted(prefix_matches, key=lambda item: (len(item[0]), item[1]))[0]
            return (
                idx,
                header,
                "ambiguous_prefix",
                f"設定欄名 {expected} 前綴比對符合多個欄名，已選用第 {idx} 欄 {header}；請檢查設定",
            )

    if match_mode == "contains":
        contains_matches: List[Tuple[str, int, str]] = []
        for expected in candidates_to_try:
            expected_key = normalize_header_key(expected)
            if not expected_key:
                continue
            for header, idx in header_map.items():
                if expected_key in normalize_header_key(header):
                    contains_matches.append((header, idx, expected))
        if len(contains_matches) == 1:
            header, idx, expected = contains_matches[0]
            return idx, header, "contains", f"設定欄名 {expected} 以包含關係比對到 Excel 欄名 {header}"
        if len(contains_matches) > 1:
            header, idx, expected = sorted(contains_matches, key=lambda item: (len(item[0]), item[1]))[0]
            return (
                idx,
                header,
                "ambiguous_contains",
                f"設定欄名 {expected} 包含比對符合多個欄名，已選用第 {idx} 欄 {header}；請檢查設定",
            )

    raise ValueError(
        f"mappings[{mapping_index}] 找不到 Excel 欄名：{candidates_to_try[0]}；"
        f"目前標題列欄名：{available}"
    )


def read_column_mappings(cfg: Dict[str, Any], header_map: Dict[str, int]) -> List[Dict[str, Any]]:
    mappings = get_nested(cfg, "mappings", None)
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("設定檔缺少必要欄位：mappings（至少一筆 source_column/dest_field 對應）")

    resolved: List[Dict[str, Any]] = []
    for index, mapping in enumerate(mappings, start=1):
        if not isinstance(mapping, dict):
            raise ValueError(f"mappings[{index}] 必須是物件")

        dest_field = mapping.get("dest_field") or mapping.get("destination_field")
        if not dest_field or not str(dest_field).strip():
            raise ValueError(f"mappings[{index}] 缺少 dest_field")

        source_name = mapping.get("source_column") or mapping.get("excel_column") or mapping.get("source_column_prefix")
        source_index = mapping.get("source_column_index")
        source_letter = mapping.get("source_column_letter")
        match_mode = str(mapping.get("match", "smart") or "smart").strip().lower()
        if mapping.get("source_column_prefix") and "match" not in mapping:
            match_mode = "prefix"
        if match_mode not in {"exact", "smart", "normalized", "prefix", "contains"}:
            raise ValueError(f"mappings[{index}] match 不支援：{match_mode}")

        if source_index is not None:
            excel_index = parse_excel_column_ref(str(source_index))
            source_label = str(source_index)
            actual_source_label = source_label
            match_type = "index"
            header_message = ""
        elif source_letter:
            excel_index = parse_excel_column_ref(str(source_letter))
            source_label = str(source_letter)
            actual_source_label = source_label
            match_type = "letter"
            header_message = ""
        elif source_name:
            source_label = normalize_header(source_name)
            expected_names = [source_label] + as_list(mapping.get("aliases"))
            excel_index, actual_source_label, match_type, header_message = resolve_header_candidate(
                mapping_index=index,
                header_map=header_map,
                expected_names=expected_names,
                match_mode=match_mode,
            )
        else:
            raise ValueError(
                f"mappings[{index}] 至少要設定 source_column、"
                "source_column_index 或 source_column_letter"
            )

        resolved.append(
            {
                "source_label": source_label,
                "actual_source_label": actual_source_label,
                "source_index": excel_index,
                "dest_field": str(dest_field).strip(),
                "required": bool(mapping.get("required", False)),
                "default": mapping.get("default", None),
                "match_type": match_type,
                "header_message": header_message,
            }
        )

    return resolved


def make_hash_value(row_source_values: Dict[str, Any]) -> str:
    parts = []
    for key in sorted(row_source_values.keys()):
        value = json_safe(row_source_values[key])
        parts.append(f"{key}={'' if value is None else value}")
    basis = "|".join(parts)
    return hashlib.sha256(basis.encode("utf-8", errors="ignore")).hexdigest()


def iter_excel_rows(
    *,
    excel_path: Path,
    sheet_name: str,
    header_row: int,
    start_row: int,
    end_row: int,
    mappings: Sequence[Dict[str, Any]],
    skip_empty_rows: bool,
) -> Generator[Tuple[int, Dict[str, Any], Dict[str, Any], str, str], None, None]:
    from openpyxl import load_workbook

    wb = load_workbook(filename=excel_path, read_only=True, data_only=True)
    try:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"Excel 找不到工作表：{sheet_name}；可用工作表：{', '.join(wb.sheetnames)}")
        ws = wb[sheet_name]

        max_col = max(int(mapping["source_index"]) for mapping in mappings)
        max_row = end_row if end_row > 0 else ws.max_row

        for row_no, row in enumerate(
            ws.iter_rows(
                min_row=start_row,
                max_row=max_row,
                min_col=1,
                max_col=max_col,
                values_only=True,
            ),
            start=start_row,
        ):
            record: Dict[str, Any] = {}
            source_values: Dict[str, Any] = {}
            non_empty = False
            invalid_message = ""

            for mapping in mappings:
                source_idx = int(mapping["source_index"])
                raw_value = row[source_idx - 1] if source_idx - 1 < len(row) else None
                value = normalize_cell_value(raw_value)

                if is_empty_value(value) and mapping.get("default") is not None:
                    value = mapping.get("default")

                if bool(mapping.get("required", False)) and is_empty_value(value):
                    invalid_message = (
                        f"Excel 第 {row_no} 列必要欄位為空："
                        f"{mapping['source_label']} -> {mapping['dest_field']}"
                    )

                if not is_empty_value(value):
                    non_empty = True

                record[str(mapping["dest_field"])] = value
                source_values[str(mapping["source_label"])] = value

            if skip_empty_rows and not non_empty:
                continue

            yield row_no, record, source_values, make_hash_value(source_values), invalid_message
    finally:
        wb.close()


def build_insert_sql(table: str, dest_fields: Sequence[str]) -> str:
    if not dest_fields:
        raise ValueError("目的欄位不可為空")
    columns_sql = ", ".join(quote_ident(field) for field in dest_fields)
    params_sql = ", ".join("?" for _ in dest_fields)
    return f"INSERT INTO {quote_object_path(table)} ({columns_sql}) VALUES ({params_sql})"


def build_select_existing_hashes_sql(table: str, hash_field: str, count: int) -> str:
    params_sql = ", ".join("?" for _ in range(count))
    return f"SELECT {quote_ident(hash_field)} FROM {quote_object_path(table)} WHERE {quote_ident(hash_field)} IN ({params_sql})"


def open_workbook_header(config_path: str, cfg: Dict[str, Any], excel_path: Optional[Path] = None) -> Tuple[Path, str, int, Dict[str, int]]:
    if excel_path is None:
        excel_path_raw = require_nested(cfg, "source.excel_path")
        excel_path = resolve_excel_path(config_path, str(excel_path_raw))
    if not excel_path.exists():
        raise FileNotFoundError(f"找不到 Excel 檔案：{excel_path}")

    sheet_name = str(require_nested(cfg, "source.sheet"))
    header_row = int(get_nested(cfg, "source.header_row", 1) or 1)
    if header_row <= 0:
        raise ValueError("source.header_row 必須大於 0")

    from openpyxl import load_workbook

    wb = load_workbook(filename=excel_path, read_only=True, data_only=True)
    try:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"Excel 找不到工作表：{sheet_name}；可用工作表：{', '.join(wb.sheetnames)}")
        header_map = read_header_map(wb[sheet_name], header_row)
    finally:
        wb.close()

    return excel_path, sheet_name, header_row, header_map


def ensure_audit_table(cursor, audit_table: str):
    object_name = audit_table.replace("'", "''")
    sql = f"""
IF OBJECT_ID(N'{object_name}', N'U') IS NULL
BEGIN
    CREATE TABLE {quote_object_path(audit_table)} (
        audit_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        run_id NVARCHAR(64) NOT NULL,
        source_file NVARCHAR(1024) NOT NULL,
        sheet_name NVARCHAR(255) NULL,
        row_no INT NULL,
        hash_value CHAR(64) NULL,
        destination_table NVARCHAR(512) NOT NULL,
        status NVARCHAR(32) NOT NULL,
        message NVARCHAR(MAX) NULL,
        row_payload NVARCHAR(MAX) NULL,
        processed_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
"""
    cursor.execute(sql)


def insert_audit_rows(
    cursor,
    *,
    audit_table: str,
    run_id: str,
    source_file: Path,
    sheet_name: str,
    destination_table: str,
    row_results: Sequence[RowResult],
):
    if not row_results:
        return

    sql = build_insert_sql(
        audit_table,
        [
            "run_id",
            "source_file",
            "sheet_name",
            "row_no",
            "hash_value",
            "destination_table",
            "status",
            "message",
            "row_payload",
        ],
    )
    params = [
        (
            run_id,
            str(source_file),
            sheet_name,
            result.row_no,
            result.hash_value,
            destination_table,
            result.status,
            result.message,
            json.dumps(result.row_payload, ensure_ascii=False, default=json_safe),
        )
        for result in row_results
    ]
    cursor.executemany(sql, params)


def build_header_audit_results(mappings: Sequence[Dict[str, Any]], header_row: int) -> List[RowResult]:
    results: List[RowResult] = []
    for mapping in mappings:
        match_type = str(mapping.get("match_type", ""))
        if match_type in {"exact", "index", "letter"}:
            continue

        expected = str(mapping.get("source_label", ""))
        actual = str(mapping.get("actual_source_label", ""))
        message = mapping.get("header_message") or f"設定欄名 {expected} 智慧比對到 Excel 欄名 {actual}"
        results.append(
            RowResult(
                row_no=header_row,
                hash_value="",
                status="header_smart_match",
                message=str(message),
                row_payload={
                    "expected_source_column": expected,
                    "actual_source_column": actual,
                    "dest_field": mapping.get("dest_field"),
                    "match_type": match_type,
                    "source_index": mapping.get("source_index"),
                },
            )
        )
    return results


def write_log(log_dir: Path, event: Dict[str, Any]):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"excel_import_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
    payload = {"logged_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", **event}
    with log_file.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False, default=json_safe) + "\n")


def unique_archive_path(target_dir: Path, source_file: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    candidate = target_dir / f"{source_file.stem}_{timestamp}{source_file.suffix}"
    counter = 1
    while candidate.exists():
        candidate = target_dir / f"{source_file.stem}_{timestamp}_{counter}{source_file.suffix}"
        counter += 1
    return candidate


def move_to_archive(source_file: Path, target_dir: Path) -> Path:
    target = unique_archive_path(target_dir, source_file)
    shutil.move(str(source_file), str(target))
    return target


def discover_excel_files(config_path: str, cfg: Dict[str, Any]) -> List[Path]:
    source_dir_raw = get_nested(cfg, "source.directory", "") or get_nested(cfg, "source.excel_dir", "") or ""
    if source_dir_raw:
        source_dir = resolve_path(config_path, str(source_dir_raw))
        if not source_dir.exists():
            raise FileNotFoundError(f"找不到來源目錄：{source_dir}")
        if not source_dir.is_dir():
            raise NotADirectoryError(f"來源目錄不是資料夾：{source_dir}")

        recursive = bool(get_nested(cfg, "source.recursive", False))
        pattern = str(get_nested(cfg, "source.file_pattern", "*.xlsx") or "*.xlsx")
        paths = source_dir.rglob(pattern) if recursive else source_dir.glob(pattern)
        files = [
            path.resolve()
            for path in paths
            if path.is_file() and path.suffix.lower() in EXCEL_SUFFIXES and not path.name.startswith("~$")
        ]
        return sorted(files)

    excel_path_raw = require_nested(cfg, "source.excel_path")
    return [resolve_excel_path(config_path, str(excel_path_raw))]


def get_existing_hashes(cursor, *, table: str, hash_field: str, hash_values: Sequence[str]) -> set[str]:
    hashes = sorted({value for value in hash_values if value})
    if not hashes:
        return set()

    existing: set[str] = set()
    for batch in chunked(hashes, 900):
        cursor.execute(build_select_existing_hashes_sql(table, hash_field, len(batch)), batch)
        existing.update(str(row[0]) for row in cursor.fetchall())
    return existing


def insert_batch_with_fallback(
    cursor,
    *,
    insert_sql: str,
    rows: Sequence[Tuple[Any, ...]],
    row_contexts: Sequence[Tuple[int, str, Dict[str, Any]]],
) -> Tuple[List[RowResult], List[Tuple[str, Tuple[Any, ...]]]]:
    try:
        cursor.executemany(insert_sql, rows)
        return [
            RowResult(row_no=row_no, hash_value=hash_value, status="inserted", row_payload=payload)
            for row_no, hash_value, payload in row_contexts
        ], []
    except Exception as exc:
        cursor.connection.rollback()
        results: List[RowResult] = []
        inserted_rows: List[Tuple[str, Tuple[Any, ...]]] = []
        for row_values, (row_no, hash_value, payload) in zip(rows, row_contexts):
            try:
                cursor.execute(insert_sql, row_values)
                cursor.connection.commit()
                inserted_rows.append((hash_value, row_values))
                results.append(RowResult(row_no=row_no, hash_value=hash_value, status="inserted", row_payload=payload))
            except Exception as row_exc:
                cursor.connection.rollback()
                results.append(
                    RowResult(
                        row_no=row_no,
                        hash_value=hash_value,
                        status="failed",
                        message=f"批次失敗後逐筆重試仍失敗：{row_exc}; 原批次錯誤：{exc}",
                        row_payload=payload,
                    )
                )
        return results, inserted_rows


def process_excel_file(
    *,
    config_path: str,
    cfg: Dict[str, Any],
    excel_path: Path,
    conn,
    run_id: str,
    log_dir: Path,
) -> FileResult:
    result = FileResult(file_path=excel_path)
    excel_path, sheet_name, header_row, header_map = open_workbook_header(config_path, cfg, excel_path)
    mappings = read_column_mappings(cfg, header_map)

    table = str(require_nested(cfg, "destination.table"))
    hash_field = str(get_nested(cfg, "destination.hash_field", DEFAULT_HASH_FIELD) or DEFAULT_HASH_FIELD)
    dest_fields = [mapping["dest_field"] for mapping in mappings]
    if hash_field not in dest_fields:
        dest_fields.append(hash_field)
    insert_sql = build_insert_sql(table, dest_fields)

    batch_size = int(get_nested(cfg, "import.batch_size", 500) or 500)
    if batch_size <= 0:
        raise ValueError("import.batch_size 必須大於 0")

    start_row = int(get_nested(cfg, "source.start_row", header_row + 1) or (header_row + 1))
    end_row = int(get_nested(cfg, "source.end_row", 0) or 0)
    if start_row <= header_row:
        raise ValueError("source.start_row 必須大於 source.header_row")
    if end_row and end_row < start_row:
        raise ValueError("source.end_row 必須大於或等於 source.start_row，或設為 0 表示讀到最後")

    skip_empty_rows = bool(get_nested(cfg, "import.skip_empty_rows", True))
    fast_executemany = bool(get_nested(cfg, "import.fast_executemany", True))
    audit_enabled = bool(get_nested(cfg, "audit.enabled", True))
    audit_table = str(get_nested(cfg, "audit.table", DEFAULT_AUDIT_TABLE) or DEFAULT_AUDIT_TABLE)

    cursor = conn.cursor()
    if fast_executemany:
        cursor.fast_executemany = True

    print(f"ℹ️ Excel: {excel_path}")
    print(f"ℹ️ Sheet: {sheet_name}")
    print(f"ℹ️ SQL: {insert_sql}")
    print(f"ℹ️ 去重機制：以來源欄名與內容組成字串後計算 SHA-256，寫入 {hash_field}，匯入前會檢查避免重複導入。")

    header_audit_results = build_header_audit_results(mappings, header_row)
    if header_audit_results:
        for header_result in header_audit_results:
            print(f"⚠️ 欄名智慧比對：{header_result.message}")
            write_log(
                log_dir,
                {
                    "event": "header_smart_match",
                    "run_id": run_id,
                    "source_file": str(excel_path),
                    "message": header_result.message,
                    "payload": header_result.row_payload,
                },
            )
        if audit_enabled:
            insert_audit_rows(
                cursor,
                audit_table=audit_table,
                run_id=run_id,
                source_file=excel_path,
                sheet_name=sheet_name,
                destination_table=table,
                row_results=header_audit_results,
            )
            conn.commit()

    try:
        row_iter = iter_excel_rows(
            excel_path=excel_path,
            sheet_name=sheet_name,
            header_row=header_row,
            start_row=start_row,
            end_row=end_row,
            mappings=mappings,
            skip_empty_rows=skip_empty_rows,
        )

        seen_in_run: set[str] = set()
        for raw_batch in chunked(row_iter, batch_size):
            batch_results: List[RowResult] = []
            candidates: List[Tuple[int, Dict[str, Any], str]] = []

            existing_hashes = get_existing_hashes(
                cursor,
                table=table,
                hash_field=hash_field,
                hash_values=[hash_value for _row_no, _record, _source_values, hash_value, _invalid in raw_batch],
            )

            for row_no, record, source_values, hash_value, invalid_message in raw_batch:
                payload = {"source": source_values, "destination": record}
                if invalid_message:
                    batch_results.append(
                        RowResult(
                            row_no=row_no,
                            hash_value=hash_value,
                            status="failed",
                            message=invalid_message,
                            row_payload=payload,
                        )
                    )
                    continue
                if hash_value in existing_hashes:
                    batch_results.append(
                        RowResult(
                            row_no=row_no,
                            hash_value=hash_value,
                            status="duplicate",
                            message=f"hash_value 已存在於 {table}.{hash_field}，略過匯入",
                            row_payload=payload,
                        )
                    )
                    continue
                if hash_value in seen_in_run:
                    batch_results.append(
                        RowResult(
                            row_no=row_no,
                            hash_value=hash_value,
                            status="duplicate",
                            message="同次執行中已有相同來源欄名與內容的資料列，略過匯入",
                            row_payload=payload,
                        )
                    )
                    continue
                seen_in_run.add(hash_value)
                record[hash_field] = hash_value
                candidates.append((row_no, record, hash_value))

            if candidates:
                rows = [tuple(record.get(field) for field in dest_fields) for _row_no, record, _hash_value in candidates]
                contexts = [
                    (row_no, hash_value, {"destination": record})
                    for row_no, record, hash_value in candidates
                ]
                insert_results, _inserted_rows = insert_batch_with_fallback(
                    cursor,
                    insert_sql=insert_sql,
                    rows=rows,
                    row_contexts=contexts,
                )
                batch_results.extend(insert_results)

            if audit_enabled:
                insert_audit_rows(
                    cursor,
                    audit_table=audit_table,
                    run_id=run_id,
                    source_file=excel_path,
                    sheet_name=sheet_name,
                    destination_table=table,
                    row_results=batch_results,
                )

            conn.commit()

            inserted = sum(1 for item in batch_results if item.status == "inserted")
            duplicate = sum(1 for item in batch_results if item.status == "duplicate")
            failed = sum(1 for item in batch_results if item.status == "failed")
            result.success += inserted
            result.duplicate += duplicate
            result.failed += failed

            print(
                f"✅ 批次完成：新增 {inserted} 筆，重複略過 {duplicate} 筆，"
                f"失敗 {failed} 筆，累計新增 {result.success} 筆"
            )
            write_log(
                log_dir,
                {
                    "event": "batch_done",
                    "run_id": run_id,
                    "source_file": str(excel_path),
                    "inserted": inserted,
                    "duplicate": duplicate,
                    "failed": failed,
                },
            )
    finally:
        cursor.close()

    print(
        f"🎯 檔案完成：{excel_path.name}，成功新增 {result.success} 筆，"
        f"重複略過 {result.duplicate} 筆，失敗 {result.failed} 筆"
    )
    return result


def get_log_dir(config_path: str, cfg: Dict[str, Any]) -> Path:
    raw = str(get_nested(cfg, "archive.log_dir", "logs/excel_import") or "logs/excel_import")
    return resolve_path(config_path, raw)


def bulk_insert_excel_to_sql_from_config(config_path: str, cfg: Dict[str, Any]) -> tuple[int, int, int]:
    run_id = uuid.uuid4().hex
    files = discover_excel_files(config_path, cfg)
    log_dir = get_log_dir(config_path, cfg)
    if not files:
        print("ℹ️ 沒有找到可匯入的 Excel 檔案")
        write_log(log_dir, {"event": "run_done", "run_id": run_id, "message": "no files"})
        return 0, 0, 0

    import pyodbc

    conn = pyodbc.connect(build_conn_str_from_config(cfg))
    cursor = conn.cursor()
    try:
        audit_enabled = bool(get_nested(cfg, "audit.enabled", True))
        audit_table = str(get_nested(cfg, "audit.table", DEFAULT_AUDIT_TABLE) or DEFAULT_AUDIT_TABLE)
        if audit_enabled:
            ensure_audit_table(cursor, audit_table)
            conn.commit()

        truncate_before_load = bool(get_nested(cfg, "import.truncate_before_load", False))
        if truncate_before_load:
            table = str(require_nested(cfg, "destination.table"))
            truncate_sql = f"TRUNCATE TABLE {quote_object_path(table)}"
            cursor.execute(truncate_sql)
            conn.commit()
            print(f"⚠️ 已先清空目的資料表：{table}")
    finally:
        cursor.close()

    archive_enabled = bool(get_nested(cfg, "archive.enabled", bool(get_nested(cfg, "source.directory", ""))))
    success_dir = resolve_path(config_path, str(get_nested(cfg, "archive.success_dir", "archive/success") or "archive/success"))
    fail_dir = resolve_path(config_path, str(get_nested(cfg, "archive.fail_dir", "archive/failed") or "archive/failed"))

    totals = {"success": 0, "duplicate": 0, "failed": 0}
    try:
        for excel_path in files:
            file_result = FileResult(file_path=excel_path)
            try:
                file_result = process_excel_file(
                    config_path=config_path,
                    cfg=cfg,
                    excel_path=excel_path,
                    conn=conn,
                    run_id=run_id,
                    log_dir=log_dir,
                )
            except Exception as exc:
                conn.rollback()
                file_result.error = str(exc)
                file_result.failed += 1
                print(f"❌ 檔案處理失敗：{excel_path}；{exc}")
                write_log(
                    log_dir,
                    {
                        "event": "file_failed",
                        "run_id": run_id,
                        "source_file": str(excel_path),
                        "error": str(exc),
                    },
                )

            totals["success"] += file_result.success
            totals["duplicate"] += file_result.duplicate
            totals["failed"] += file_result.failed

            if archive_enabled:
                target_dir = success_dir if file_result.ok else fail_dir
                moved_to = move_to_archive(excel_path, target_dir)
                print(f"📦 已移動檔案到：{moved_to}")
                write_log(
                    log_dir,
                    {
                        "event": "file_archived",
                        "run_id": run_id,
                        "source_file": str(excel_path),
                        "target_file": str(moved_to),
                        "status": "success" if file_result.ok else "failed",
                        "inserted": file_result.success,
                        "duplicate": file_result.duplicate,
                        "failed": file_result.failed,
                        "error": file_result.error,
                    },
                )
    finally:
        conn.close()

    print(
        f"🎯 全部完成：成功新增 {totals['success']} 筆，"
        f"重複略過 {totals['duplicate']} 筆，失敗 {totals['failed']} 筆"
    )
    write_log(log_dir, {"event": "run_done", "run_id": run_id, **totals})
    return totals["success"], totals["duplicate"], totals["failed"]


def main():
    parser = argparse.ArgumentParser(description="依設定檔從 Excel 或來源目錄匯入資料到 SQL Server")
    parser.add_argument("--config", required=True, help="JSON 設定檔路徑")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    cfg = load_json_config(args.config)
    bulk_insert_excel_to_sql_from_config(args.config, cfg)


if __name__ == "__main__":
    main()
