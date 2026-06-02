from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_ingestion.excel_to_sql.sql_utils import (
    ensure_destination_columns,
    ensure_destination_table,
    infer_auto_created_field_type,
    validate_auto_created_field_type,
)


class FakeCursor:
    def __init__(self, existing_columns=None, existing_tables=None):
        self.existing_columns = set(existing_columns or [])
        self.existing_tables = set(existing_tables or [])
        self.statements = []
        self._fetch_value = None

    def execute(self, sql, *params):
        self.statements.append(sql)
        if sql.startswith("SELECT COL_LENGTH"):
            field = sql.split(", N'", 1)[1].rsplit("'", 1)[0].replace("''", "'")
            self._fetch_value = 1 if field in self.existing_columns else None
            return self
        if sql.startswith("SELECT OBJECT_ID"):
            table = sql.split("(N'", 1)[1].split("'", 1)[0].replace("''", "'")
            self._fetch_value = 1 if table in self.existing_tables else None
            return self
        if sql.startswith("CREATE TABLE"):
            self.existing_tables.add("dbo.vessel_activities")
            for field in ["activity_date", "vessel_count", "vessel_names", "hash_value"]:
                if f"[{field}]" in sql:
                    self.existing_columns.add(field)
            return self
        if sql.lstrip().startswith("IF NOT EXISTS") and "CREATE UNIQUE INDEX" in sql:
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


def test_ensure_destination_table_creates_missing_table_with_mapped_and_hash_fields():
    cursor = FakeCursor()

    created = ensure_destination_table(
        cursor,
        table="dbo.vessel_activities",
        mappings=[
            {"dest_field": "activity_date", "value_type": "date"},
            {"dest_field": "vessel_count", "dest_field_type": "INT"},
            {"dest_field": "vessel_names", "dest_field_type": "NVARCHAR(MAX)"},
        ],
        hash_field="hash_value",
        hash_field_type="CHAR(64)",
        create_hash_index=True,
    )

    assert created == {
        "activity_date": "DATE",
        "vessel_count": "INT",
        "vessel_names": "NVARCHAR(MAX)",
        "hash_value": "CHAR(64)",
    }
    create_table_sql = next(sql for sql in cursor.statements if sql.startswith("CREATE TABLE"))
    assert "CREATE TABLE [dbo].[vessel_activities]" in create_table_sql
    assert "[activity_date] DATE NULL" in create_table_sql
    assert "[vessel_count] INT NULL" in create_table_sql
    assert "[vessel_names] NVARCHAR(MAX) NULL" in create_table_sql
    assert "[hash_value] CHAR(64) NULL" in create_table_sql
    assert any("CREATE UNIQUE INDEX [UX_dbo_vessel_activities_hash_value]" in sql for sql in cursor.statements)


def test_ensure_destination_table_skips_existing_table():
    cursor = FakeCursor(existing_tables={"dbo.vessel_activities"})

    created = ensure_destination_table(
        cursor,
        table="dbo.vessel_activities",
        mappings=[{"dest_field": "activity_date", "value_type": "date"}],
        hash_field="hash_value",
    )

    assert created == {}
    assert not any(sql.startswith("CREATE TABLE") for sql in cursor.statements)
