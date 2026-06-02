"""Shared constants for Excel-to-SQL ingestion."""

EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
DEFAULT_AUDIT_TABLE = "dbo.ExcelImportAudit"
DEFAULT_HASH_FIELD = "hash_value"
DEFAULT_HASH_ALGORITHM = "SHA-256"
DEFAULT_HASH_HEX_LENGTH = 64
DEFAULT_HASH_FIELD_TYPE = "CHAR(64)"
