# Requirement Import Operations (Phase 1B Design v1)

## Boundary and startup

Phase 1B manages sources, immutable profiles, canonical Requirement versions, diagnostics,
and snapshots in SQL Server. It does not schedule recurrence or call Report Jobs, Agent,
Elasticsearch, or Word internals.

The pipeline defaults off. When `REQUIREMENT_PIPELINE_ENABLED=true`, startup loads the
privileged `REQUIREMENT_SQL_REGISTRY_FILE`, opens `REQUIREMENT_CONTROL_DB_CONNECTION`,
validates `REQUIREMENT_DB_SCHEMA`, and initializes schema v1. Invalid configuration,
connectivity, or schema version aborts startup. Disabled startup reads no Requirement SQL.

Excel-to-SQL and Requirement configuration remain separate because they configure different
operations. Their SQL Server connection objects intentionally use the same inner keys
(`driver`, `server`, `database`, `trusted_connection`, `user`, `password`, `encrypt`, and
`trust_server_certificate`) so an operator can copy the database settings without renaming
fields. Requirement retains `connections.requirement_control` because it is a named SQL
registry, and retains the separate `queries` registry. The same SQL Server/database may host
the `sra_requirement` and `sra_schedule` schemas; both use the named control connection.

Copy `config/requirements/sql_registry.example.json` to the ignored deployment file
`config/requirements/sql_registry.json`. Direct inner keys are the canonical operator-friendly
format. `driver` values `auto` and `detect` select an installed SQL Server ODBC driver with the
same resolution used by Excel-to-SQL; an explicit installed driver name is also supported.
`REQUIREMENT_SQL_REGISTRY_FILE` selects the registry file and
`REQUIREMENT_CONTROL_DB_CONNECTION` selects its named connection.

The selected SQL registry is privileged deployment-local configuration, not a
release-managed source-provenance input. Requirement E2E release provenance
does not attest or expose the registry's bytes, digest, resolved path,
credentials, connection details, or query text. The registry is an operator
trust boundary: named reviewed queries and least-privilege database permissions
remain the SQL security boundary. A stronger sanitized registry attestation may
be considered separately in the future; deployments must not publish the
private registry or place it in release provenance.

Legacy `driver_env`, `server_env`, `database_env`, `trusted_connection_env`, `user_env`, and
`password_env` keys remain supported for existing and secret-managed deployments. When a
`*_env` key is present it is authoritative over the matching direct value; a missing referenced
environment variable fails closed instead of exposing or falling back to a direct credential.
Environment-backed secrets remain the safer managed-deployment option. Never commit real
credentials. Resolved credentials belong only in runtime secret configuration—never in
source/profile/audit/API payloads.

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
