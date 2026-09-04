# Requirement Import Operations (Phase 1B Design v1)

## Boundary and startup

Phase 1B manages sources, immutable profiles, canonical Requirement versions, diagnostics,
and snapshots in SQL Server. It does not schedule recurrence or call Report Jobs, Agent,
Elasticsearch, or Word internals.

The pipeline defaults off. When `REQUIREMENT_PIPELINE_ENABLED=true`, startup loads the
privileged `REQUIREMENT_SQL_REGISTRY_FILE`, opens `REQUIREMENT_CONTROL_DB_CONNECTION`,
validates `REQUIREMENT_DB_SCHEMA`, and initializes schema v1. Invalid configuration,
connectivity, or schema version aborts startup. Disabled startup reads no Requirement SQL.

Copy `config/requirements/sql_registry.example.json` to an ignored deployment file. The
registry contains environment-variable names and reviewed SQL. Resolved credentials belong
only in runtime secret configuration—never in source/profile/audit/API payloads.

## Sources, review, and import

* `manual_upload` accepts `.xlsx`, `.csv`, or `.json`; filename is display metadata only.
* `file_path` is confined to `REQUIREMENT_SOURCE_ALLOWED_ROOTS`; directory/pattern lookup
  must resolve exactly one file.
* `sql_query` executes a reviewed registry query through its matching named connection;
  callers cannot submit SQL.

`db_operator+` creates metadata and profile versions. Only `superuser` enables sources or
profiles and approves the explicit active version. Preview may select a draft and is
side-effect free; commit always uses the enabled profile's approved `active_version_id`.

For authoritative sources, omissions affect only new membership. Duplicate identity,
stale timestamp, same-timestamp changed payload, mapping errors, and datetime errors block
activation. Repair, preview, then retry; do not manually change `active_snapshot_id`.

## Backup, restore, and acceptance

Back up and restore the entire dedicated Requirement schema as a consistent unit. Unknown
schema versions fail closed and need an operator-reviewed migration. Live acceptance must
use an explicitly authorized SQL Server and verify schema v1, the deterministic ten-row
profile, invalid-row rollback, and same-UPDT/different-payload rejection. Repository fakes
are not live acceptance; Agent/ES/Word are outside this smoke.
