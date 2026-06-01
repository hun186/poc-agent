from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.excel_to_sql.ingest import insert_batch_with_fallback


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
    def __init__(self, connection):
        self.connection = connection
        self.fast_executemany = True
        self.executemany_calls = []

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, rows, self.fast_executemany))
        raise RuntimeError("batch failed")


class FallbackCursor:
    def __init__(self, connection):
        self.connection = connection
        self.fast_executemany = True
        self.execute_calls = []
        self.closed = False

    def execute(self, sql, row):
        self.execute_calls.append((sql, row, self.fast_executemany))
        if row == ("bad",):
            raise RuntimeError("row failed")

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
