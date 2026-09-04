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
  callers cannot submit SQL. Every registry entry must use a database principal restricted
  to read-only access for that reviewed source. SQL text parsing is not a security boundary:
  the reviewed registry and least-privilege database permissions are the boundary.

`db_operator+` creates metadata and profile versions. Only `superuser` enables sources or
profiles and approves the explicit active version. Preview may select a draft and is
side-effect free; commit always uses the enabled profile's approved `active_version_id`.

For authoritative sources, omissions affect only new membership. Duplicate identity,
stale timestamp, same-timestamp changed payload, mapping errors, and datetime errors block
activation. Repair, preview, then retry; do not manually change `active_snapshot_id`.
Failed runs retain row-level diagnostics. A stale/same-UPDT anomaly discovered again under
the commit lock rolls back all domain and snapshot writes before a separate failed-run audit
transaction is recorded, so the prior active snapshot remains authoritative.

## Backup, restore, and acceptance

Back up and restore the entire dedicated Requirement schema as a consistent unit. Unknown
schema versions fail closed and need an operator-reviewed migration. A fresh or version-0
schema migrates transactionally to canonical version 1; every version-1 startup validates
the required tables, runtime columns, keys, uniqueness constraints, and foreign keys before
commit. A malformed version-1 schema fails closed without rewriting its version marker.
Live acceptance must
use an explicitly authorized SQL Server and verify schema v1, the deterministic ten-row
profile, invalid-row rollback, and same-UPDT/different-payload rejection. Repository fakes
are not live acceptance; Agent/ES/Word are outside this smoke.
