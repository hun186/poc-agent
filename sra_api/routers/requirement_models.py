from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from data_ingestion.requirements.models import ImportProfileDocument, SourceMode, SourceType


class ManualUploadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = None
    format: Literal["xlsx", "csv", "json"] | None = None

class FilePathConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None = None
    directory: str | None = None
    file_pattern: str | None = None
    format: Literal["xlsx", "csv", "json"] | None = None

class SqlQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_ref: str
    query_ref: str

class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=240)
    source_type: SourceType
    source_mode: SourceMode = SourceMode.AUTHORITATIVE_SNAPSHOT
    source_config: ManualUploadConfig | FilePathConfig | SqlQueryConfig
    import_profile_id: str
    enabled: bool = False

class SourcePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    source_mode: SourceMode | None = None
    source_config: dict[str, Any] | None = None
    import_profile_id: str | None = None
    enabled: bool | None = None

class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    enabled: bool = False

class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None

class ProfileVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: ImportProfileDocument
