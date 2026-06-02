from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_ingestion.excel_to_sql import ingest as ingest_module
from data_ingestion.excel_to_sql.db_ops import is_transient_database_error
from data_ingestion.excel_to_sql.ingest import insert_batch_with_fallback
from data_ingestion.excel_to_sql.models import FileResult


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.fallback_cursor = FallbackCursor(self)

    def cursor(self):
        return self.fallback_cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FastCursor:
    def __init__(self, connection, error=None):
        self.connection = connection
        self.error = error or RuntimeError("batch failed")
        self.fast_executemany = True
        self.executemany_calls = []

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, rows, self.fast_executemany))
        raise self.error


class FallbackCursor:
    def __init__(self, connection):
        self.connection = connection
        self.fast_executemany = True
        self.execute_calls = []
        self.closed = False
        self.row_errors = {("bad",): RuntimeError("row failed")}

    def execute(self, sql, row):
        self.execute_calls.append((sql, row, self.fast_executemany))
        if row in self.row_errors:
            raise self.row_errors[row]

    def close(self):
        self.closed = True


def test_insert_batch_fallback_uses_fresh_non_fast_cursor_for_row_retries():
    connection = FakeConnection()
    cursor = FastCursor(connection)

    results, inserted_rows = insert_batch_with_fallback(
        cursor,
        insert_sql="INSERT INTO t (c) VALUES (?)",
        rows=[("good",), ("bad",)],
        row_contexts=[
            (2, "hash-good", {"destination": {"c": "good"}}),
            (3, "hash-bad", {"destination": {"c": "bad"}}),
        ],
    )

    assert cursor.executemany_calls == [("INSERT INTO t (c) VALUES (?)", [("good",), ("bad",)], True)]
    assert connection.fallback_cursor.execute_calls == [
        ("INSERT INTO t (c) VALUES (?)", ("good",), False),
        ("INSERT INTO t (c) VALUES (?)", ("bad",), False),
    ]
    assert connection.fallback_cursor.closed is True
    assert connection.rollbacks == 2
    assert connection.commits == 1
    assert inserted_rows == [("hash-good", ("good",))]
    assert [result.status for result in results] == ["inserted", "failed"]
    assert "原批次錯誤：batch failed" in results[1].message


def test_transient_batch_error_is_raised_for_file_level_retry():
    connection = FakeConnection()
    cursor = FastCursor(connection, error=TimeoutError("SQL Server did not respond"))

    try:
        insert_batch_with_fallback(
            cursor,
            insert_sql="INSERT INTO t (c) VALUES (?)",
            rows=[("good",)],
            row_contexts=[(2, "hash-good", {"destination": {"c": "good"}})],
        )
    except TimeoutError as exc:
        assert is_transient_database_error(exc)
    else:
        raise AssertionError("transient database errors should propagate to file-level retry")

    assert connection.rollbacks == 1
    assert connection.fallback_cursor.execute_calls == []


def test_transient_row_fallback_error_is_raised_for_file_level_retry():
    connection = FakeConnection()
    connection.fallback_cursor.row_errors = {("bad",): RuntimeError("08S01 communication link failure")}
    cursor = FastCursor(connection)

    try:
        insert_batch_with_fallback(
            cursor,
            insert_sql="INSERT INTO t (c) VALUES (?)",
            rows=[("good",), ("bad",)],
            row_contexts=[
                (2, "hash-good", {"destination": {"c": "good"}}),
                (3, "hash-bad", {"destination": {"c": "bad"}}),
            ],
        )
    except RuntimeError as exc:
        assert is_transient_database_error(exc)
    else:
        raise AssertionError("transient row fallback errors should propagate to file-level retry")

    assert connection.rollbacks == 2
    assert connection.commits == 1
    assert connection.fallback_cursor.closed is True


def test_file_retry_does_not_retry_completed_row_failures(monkeypatch, tmp_path, capsys):
    calls = 0

    def fake_process_excel_file(**kwargs):
        nonlocal calls
        calls += 1
        result = FileResult(file_path=tmp_path / "sample.xlsx", success=8, failed=2)
        result.record_failure(
            "Excel 第 9981 列欄位日期格式錯誤：日期 -> activity_date；"
            "不支援或無效日期格式：02/25/2026"
        )
        result.record_failure(
            "Excel 第 9982 列欄位日期格式錯誤：日期 -> activity_date；"
            "不支援或無效日期格式：02/26/2026"
        )
        return result

    monkeypatch.setattr(ingest_module, "process_excel_file", fake_process_excel_file)

    result = ingest_module.process_excel_file_with_retries(
        config_path="config.json",
        cfg={},
        excel_path=tmp_path / "sample.xlsx",
        conn=object(),
        run_id="run-1",
        log_dir=tmp_path,
        max_attempts=3,
        interval_seconds=0,
    )

    output = capsys.readouterr().out

    assert calls == 1
    assert result.success == 8
    assert result.failed == 2
    assert "資料列錯誤種類統計" in output
    assert "Excel 第 * 列欄位日期格式錯誤：日期 -> activity_date：2 筆" in output


def test_file_retry_still_retries_file_level_exceptions(monkeypatch, tmp_path):
    calls = 0

    def fake_process_excel_file(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("SQL Server did not respond")
        return FileResult(file_path=tmp_path / "sample.xlsx", success=8, failed=0)

    monkeypatch.setattr(ingest_module, "process_excel_file", fake_process_excel_file)
    connection = FakeConnection()

    result = ingest_module.process_excel_file_with_retries(
        config_path="config.json",
        cfg={},
        excel_path=tmp_path / "sample.xlsx",
        conn=connection,
        run_id="run-1",
        log_dir=tmp_path,
        max_attempts=3,
        interval_seconds=0,
    )

    assert calls == 2
    assert connection.rollbacks == 1
    assert result.success == 8
    assert result.failed == 0


def test_bulk_import_prints_separator_between_excel_files(monkeypatch, tmp_path, capsys):
    class BulkCursor:
        def close(self):
            pass

    class BulkConnection:
        def cursor(self):
            return BulkCursor()

        def close(self):
            pass

    class PyodbcModule:
        @staticmethod
        def connect(_conn_str):
            return BulkConnection()

    files = [tmp_path / "first.xlsx", tmp_path / "second.xlsx"]

    def fake_process_excel_file_with_retries(**kwargs):
        excel_path = kwargs["excel_path"]
        print(f"ℹ️ Excel: {excel_path}")
        return FileResult(file_path=excel_path, success=1)

    monkeypatch.setitem(sys.modules, "pyodbc", PyodbcModule)
    monkeypatch.setattr(ingest_module, "discover_excel_files", lambda _config_path, _cfg: files)
    monkeypatch.setattr(ingest_module, "build_conn_str_from_config", lambda _cfg: "DRIVER=fake")
    monkeypatch.setattr(ingest_module, "process_excel_file_with_retries", fake_process_excel_file_with_retries)
    monkeypatch.setattr(
        ingest_module,
        "move_to_archive",
        lambda source_file, _target_dir: tmp_path / "archive" / source_file.name,
    )
    monkeypatch.setattr(ingest_module, "write_log", lambda *_args, **_kwargs: None)

    result = ingest_module.bulk_insert_excel_to_sql_from_config(
        str(tmp_path / "config.json"),
        {
            "audit": {"enabled": False},
            "archive": {"enabled": True},
            "db": {},
            "import": {"truncate_before_load": False},
        },
    )

    output = capsys.readouterr().out

    assert result == (2, 0, 0)
    assert output.count("────────────────────────────────────────") == 1
    assert (
        f"📦 已移動檔案到：{tmp_path / 'archive' / 'first.xlsx'}\n"
        "────────────────────────────────────────\n"
        f"ℹ️ Excel: {files[1]}"
    ) in output
