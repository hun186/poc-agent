from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.excel_to_sql.audit import insert_audit_rows
from agent.excel_to_sql.models import RowResult


class FastExecutemanyCursor:
    def __init__(self):
        self.fast_executemany = True
        self.fast_modes_during_executemany = []
        self.calls = []

    def executemany(self, sql, params):
        self.fast_modes_during_executemany.append(self.fast_executemany)
        self.calls.append((sql, params))


def test_insert_audit_rows_disables_fast_executemany_temporarily():
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

    assert cursor.fast_modes_during_executemany == [False]
    assert cursor.fast_executemany is True
    assert len(cursor.calls) == 1
