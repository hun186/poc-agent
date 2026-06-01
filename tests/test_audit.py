from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.excel_to_sql.audit import insert_audit_rows
from agent.excel_to_sql.models import RowResult


class FastExecutemanyCursor:
    def __init__(self):
        self.fast_executemany = True
        self.fast_modes_during_execute = []
        self.execute_calls = []
        self.closed = False

    def execute(self, sql, params):
        self.fast_modes_during_execute.append(self.fast_executemany)
        self.execute_calls.append((sql, params))

    def close(self):
        self.closed = True


def test_insert_audit_rows_disables_fast_executemany_and_uses_execute():
    cursor = FastExecutemanyCursor()

    insert_audit_rows(
        cursor,
        audit_table="dbo.ExcelImportAudit",
        run_id="run-1",
        source_file=Path("source.xlsx"),
        sheet_name="Sheet1",
        destination_table="dbo.Target",
        row_results=[
            RowResult(
                row_no=1,
                hash_value="",
                status="header_smart_match",
                message="設定欄名 船名 以前綴智慧比對到 Excel 欄名 船名_登記編號",
                row_payload={"expected_source_column": "船名", "actual_source_column": "船名_登記編號"},
            )
        ],
    )

    assert cursor.fast_modes_during_execute == [False]
    assert cursor.fast_executemany is True
    assert len(cursor.execute_calls) == 1


class AuditConnection:
    def __init__(self):
        self.audit_cursor = FastExecutemanyCursor()
        self.cursor_calls = 0

    def cursor(self):
        self.cursor_calls += 1
        return self.audit_cursor


class ImportCursor:
    def __init__(self, connection):
        self.connection = connection
        self.fast_executemany = True
        self.execute_calls = []
        self.closed = False

    def execute(self, sql, params):
        self.execute_calls.append((sql, params))


def test_insert_audit_rows_uses_fresh_non_fast_cursor_when_connection_available():
    connection = AuditConnection()
    cursor = ImportCursor(connection)
    insert_audit_rows(
        cursor,
        audit_table="dbo.ExcelImportAudit",
        run_id="run-1",
        source_file=Path("source.xlsx"),
        sheet_name="Sheet1",
        destination_table="dbo.Target",
        row_results=[
            RowResult(row_no=2, hash_value="abc", status="inserted", row_payload={"value": "測試"})
        ],
    )

    assert connection.cursor_calls == 1
    assert cursor.execute_calls == []
    assert connection.audit_cursor.fast_modes_during_execute == [False]
    assert connection.audit_cursor.fast_executemany is True
    assert connection.audit_cursor.closed is True
