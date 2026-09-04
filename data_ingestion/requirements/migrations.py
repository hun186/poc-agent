from __future__ import annotations

import re

SCHEMA_VERSION = 1


def validate_schema_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        raise ValueError("invalid REQUIREMENT_DB_SCHEMA")
    return value


def migration_v1(schema: str) -> list[str]:
    s = f"[{validate_schema_name(schema)}]"
    return [
        f"IF SCHEMA_ID(N'{schema}') IS NULL EXEC(N'CREATE SCHEMA {s}')",
        f"IF OBJECT_ID(N'{s}.[schema_version]', N'U') IS NULL CREATE TABLE {s}.[schema_version] (version INT NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[requirement_sources]', N'U') IS NULL CREATE TABLE {s}.[requirement_sources] (source_id NVARCHAR(64) NOT NULL PRIMARY KEY, name NVARCHAR(240) NOT NULL, source_type NVARCHAR(32) NOT NULL, source_mode NVARCHAR(32) NOT NULL, source_config_json NVARCHAR(MAX) NOT NULL, import_profile_id NVARCHAR(64) NOT NULL, enabled BIT NOT NULL, created_by NVARCHAR(128) NOT NULL, created_at DATETIMEOFFSET NOT NULL, updated_by NVARCHAR(128) NOT NULL, updated_at DATETIMEOFFSET NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[import_profiles]', N'U') IS NULL CREATE TABLE {s}.[import_profiles] (profile_id NVARCHAR(64) NOT NULL PRIMARY KEY, name NVARCHAR(240) NOT NULL, description NVARCHAR(1000) NOT NULL, enabled BIT NOT NULL, active_version_id NVARCHAR(64) NULL, created_by NVARCHAR(128) NOT NULL, created_at DATETIMEOFFSET NOT NULL, updated_by NVARCHAR(128) NOT NULL, updated_at DATETIMEOFFSET NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[import_profile_versions]', N'U') IS NULL CREATE TABLE {s}.[import_profile_versions] (profile_version_id NVARCHAR(64) NOT NULL PRIMARY KEY, profile_id NVARCHAR(64) NOT NULL, version_number INT NOT NULL, format NVARCHAR(20) NOT NULL, source_mode NVARCHAR(32) NOT NULL, profile_json NVARCHAR(MAX) NOT NULL, profile_sha256 CHAR(64) NOT NULL, status NVARCHAR(20) NOT NULL, created_by NVARCHAR(128) NOT NULL, created_at DATETIMEOFFSET NOT NULL, approved_by NVARCHAR(128) NULL, approved_at DATETIMEOFFSET NULL, retired_at DATETIMEOFFSET NULL, CONSTRAINT UQ_import_profile_version UNIQUE(profile_id, version_number))",
        f"IF OBJECT_ID(N'{s}.[requirements]', N'U') IS NULL CREATE TABLE {s}.[requirements] (requirement_id NVARCHAR(64) NOT NULL PRIMARY KEY, source_id NVARCHAR(64) NOT NULL, external_item_id NVARCHAR(240) NOT NULL, created_at DATETIMEOFFSET NOT NULL, CONSTRAINT UQ_requirement_identity UNIQUE(source_id, external_item_id))",
        f"IF OBJECT_ID(N'{s}.[requirement_versions]', N'U') IS NULL CREATE TABLE {s}.[requirement_versions] (requirement_version_id NVARCHAR(64) NOT NULL PRIMARY KEY, requirement_id NVARCHAR(64) NOT NULL, version_number INT NOT NULL, title NVARCHAR(1000) NOT NULL, prompt_content NVARCHAR(MAX) NOT NULL, source_updated_at DATETIMEOFFSET NOT NULL, expires_at DATETIMEOFFSET NULL, source_created_by BIGINT NULL, source_updated_by BIGINT NULL, source_created_at DATETIMEOFFSET NOT NULL, source_row_hash CHAR(64) NOT NULL, source_payload_hash CHAR(64) NOT NULL, execution_content_hash CHAR(64) NOT NULL, source_raw_json NVARCHAR(MAX) NOT NULL, created_at DATETIMEOFFSET NOT NULL, CONSTRAINT UQ_requirement_version UNIQUE(requirement_id, version_number))",
        f"IF OBJECT_ID(N'{s}.[requirement_sets]', N'U') IS NULL CREATE TABLE {s}.[requirement_sets] (requirement_set_id NVARCHAR(64) NOT NULL PRIMARY KEY, source_id NVARCHAR(64) NOT NULL UNIQUE, name NVARCHAR(240) NOT NULL, active_snapshot_id NVARCHAR(64) NULL, created_at DATETIMEOFFSET NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[import_runs]', N'U') IS NULL CREATE TABLE {s}.[import_runs] (import_run_id NVARCHAR(64) NOT NULL PRIMARY KEY, source_id NVARCHAR(64) NOT NULL, import_profile_version_id NVARCHAR(64) NOT NULL, source_uri_display NVARCHAR(500) NOT NULL, source_sha256 CHAR(64) NOT NULL, status NVARCHAR(20) NOT NULL, row_count INT NOT NULL, accepted_count INT NOT NULL, rejected_count INT NOT NULL, started_at DATETIMEOFFSET NOT NULL, completed_at DATETIMEOFFSET NULL, actor_kind NVARCHAR(20) NOT NULL, actor_id NVARCHAR(128) NOT NULL, error_summary NVARCHAR(1000) NULL)",
        f"IF OBJECT_ID(N'{s}.[import_run_rows]', N'U') IS NULL CREATE TABLE {s}.[import_run_rows] (import_run_id NVARCHAR(64) NOT NULL, source_row_number INT NOT NULL, external_item_id NVARCHAR(240) NULL, row_status NVARCHAR(32) NOT NULL, source_row_hash CHAR(64) NULL, diagnostic_code NVARCHAR(80) NULL, diagnostic_message NVARCHAR(500) NULL)",
        f"IF OBJECT_ID(N'{s}.[requirement_set_snapshots]', N'U') IS NULL CREATE TABLE {s}.[requirement_set_snapshots] (snapshot_id NVARCHAR(64) NOT NULL PRIMARY KEY, requirement_set_id NVARCHAR(64) NOT NULL, import_run_id NVARCHAR(64) NOT NULL, source_snapshot_sha256 CHAR(64) NOT NULL, import_profile_version_id NVARCHAR(64) NOT NULL, created_at DATETIMEOFFSET NOT NULL, activated_at DATETIMEOFFSET NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[requirement_snapshot_items]', N'U') IS NULL CREATE TABLE {s}.[requirement_snapshot_items] (snapshot_id NVARCHAR(64) NOT NULL, requirement_id NVARCHAR(64) NOT NULL, requirement_version_id NVARCHAR(64) NOT NULL, source_order INT NOT NULL, CONSTRAINT PK_requirement_snapshot_items PRIMARY KEY(snapshot_id, requirement_id))",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_profile_version_profile') ALTER TABLE {s}.[import_profile_versions] ADD CONSTRAINT FK_requirement_profile_version_profile FOREIGN KEY(profile_id) REFERENCES {s}.[import_profiles](profile_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_source_profile') ALTER TABLE {s}.[requirement_sources] ADD CONSTRAINT FK_requirement_source_profile FOREIGN KEY(import_profile_id) REFERENCES {s}.[import_profiles](profile_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_source') ALTER TABLE {s}.[requirements] ADD CONSTRAINT FK_requirement_source FOREIGN KEY(source_id) REFERENCES {s}.[requirement_sources](source_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_version_requirement') ALTER TABLE {s}.[requirement_versions] ADD CONSTRAINT FK_requirement_version_requirement FOREIGN KEY(requirement_id) REFERENCES {s}.[requirements](requirement_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_set') ALTER TABLE {s}.[requirement_set_snapshots] ADD CONSTRAINT FK_requirement_snapshot_set FOREIGN KEY(requirement_set_id) REFERENCES {s}.[requirement_sets](requirement_set_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_item_snapshot') ALTER TABLE {s}.[requirement_snapshot_items] ADD CONSTRAINT FK_requirement_snapshot_item_snapshot FOREIGN KEY(snapshot_id) REFERENCES {s}.[requirement_set_snapshots](snapshot_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_item_version') ALTER TABLE {s}.[requirement_snapshot_items] ADD CONSTRAINT FK_requirement_snapshot_item_version FOREIGN KEY(requirement_version_id) REFERENCES {s}.[requirement_versions](requirement_version_id)",
    ]
