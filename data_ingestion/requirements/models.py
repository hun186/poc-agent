from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceType(StrEnum):
    MANUAL_UPLOAD = "manual_upload"
    FILE_PATH = "file_path"
    SQL_QUERY = "sql_query"


class SourceMode(StrEnum):
    AUTHORITATIVE_SNAPSHOT = "authoritative_snapshot"
    UPSERT_DELTA = "upsert_delta"


class ProfileVersionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class WorksheetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str | None = None
    header_row: int = Field(default=1, ge=1)
    first_data_row: int = Field(default=2, ge=1)
    trim_headers: bool = True
    case_sensitive: bool = False


class FieldMappingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: str
    aliases: tuple[str, ...] = ()
    required: bool = False
    type: Literal["text", "int", "datetime", "bool", "json"] = "text"
    match: Literal["exact", "normalized", "prefix", "contains"] = "normalized"
    transforms: tuple[Literal["trim", "normalize_whitespace", "empty_to_null", "to_text", "to_int", "to_datetime"], ...] = ()
    default: Any | None = None


CANONICAL_FIELDS = frozenset({"external_item_id", "title", "prompt_content", "source_updated_at", "expires_at", "source_created_by", "source_updated_by", "source_created_at"})
REQUIRED_FIELDS = frozenset({"external_item_id", "title", "prompt_content", "source_updated_at", "source_created_at"})


class ImportProfileDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    format: Literal["xlsx", "csv", "json", "sql_rows"]
    source_timezone: str
    source_mode: SourceMode = SourceMode.AUTHORITATIVE_SNAPSHOT
    worksheet: WorksheetSpec | None = None
    mapping: dict[str, FieldMappingSpec]

    @field_validator("mapping")
    @classmethod
    def validate_mapping(cls, value: dict[str, FieldMappingSpec]) -> dict[str, FieldMappingSpec]:
        unknown = set(value) - CANONICAL_FIELDS
        missing = REQUIRED_FIELDS - set(value)
        if unknown or missing:
            raise ValueError(f"profile_invalid: unknown={sorted(unknown)} missing={sorted(missing)}")
        return value

    @model_validator(mode="after")
    def validate_worksheet(self) -> "ImportProfileDocument":
        if self.format == "xlsx" and self.worksheet is None:
            raise ValueError("profile_invalid: xlsx requires worksheet settings")
        return self


class CanonicalRequirementRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_row_number: int
    external_item_id: str
    title: str
    prompt_content: str
    source_updated_at: datetime
    expires_at: datetime | None = None
    source_created_by: int | None = None
    source_updated_by: int | None = None
    source_created_at: datetime
    source_row_hash: str
    source_payload_hash: str
    execution_content_hash: str
    source_raw: dict[str, Any]


class RowDiagnostic(BaseModel):
    source_row_number: int | None = None
    external_item_id: str | None = None
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


class NormalizedCandidate(BaseModel):
    rows: list[CanonicalRequirementRow] = Field(default_factory=list)
    diagnostics: list[RowDiagnostic] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(item.severity == "error" for item in self.diagnostics)


class AcquiredSource(BaseModel):
    rows: list[dict[str, Any]]
    source_sha256: str
    source_uri_display: str
    source_row_numbers: list[int] = Field(default_factory=list)
