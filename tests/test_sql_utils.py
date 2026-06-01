from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.excel_to_sql.sql_utils import (
    ensure_destination_columns,
    infer_auto_created_field_type,
    validate_auto_created_field_type,
)


class FakeCursor:
    def __init__(self, existing_columns=None):
        self.existing_columns = set(existing_columns or [])
        self.statements = []
        self._fetch_value = None

    def execute(self, sql, *params):
        self.statements.append(sql)
        if sql.startswith("SELECT COL_LENGTH"):
            field = sql.split(", N'", 1)[1].rsplit("'", 1)[0].replace("''", "'")
            self._fetch_value = 1 if field in self.existing_columns else None
            return self
        if sql.startswith("ALTER TABLE"):
            field = sql.split("ADD [", 1)[1].split("]", 1)[0].replace("]]", "]")
            self.existing_columns.add(field)
            return self
        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return (self._fetch_value,)


def test_ensure_destination_columns_adds_only_missing_columns_with_configured_types():
    cursor = FakeCursor(existing_columns={"activity_date"})

    created = ensure_destination_columns(
        cursor,
        table="dbo.vessel_activities",
        mappings=[
            {"dest_field": "activity_date", "value_type": "date"},
            {"dest_field": "vessel_count", "dest_field_type": "INT"},
            {"dest_field": "vessel_names", "dest_field_type": "NVARCHAR(MAX)"},
        ],
    )

    assert created == {"vessel_count": "INT", "vessel_names": "NVARCHAR(MAX)"}
    assert any("ADD [vessel_count] INT NULL" in sql for sql in cursor.statements)
    assert any("ADD [vessel_names] NVARCHAR(MAX) NULL" in sql for sql in cursor.statements)
    assert not any("ADD [activity_date]" in sql for sql in cursor.statements)


def test_infer_auto_created_field_type_defaults_date_mappings_to_date():
    assert infer_auto_created_field_type({"dest_field": "activity_date", "value_type": "date"}) == "DATE"


def test_validate_auto_created_field_type_rejects_unsafe_sql():
    with pytest.raises(ValueError):
        validate_auto_created_field_type("NVARCHAR(255); DROP TABLE dbo.vessel_activities")
