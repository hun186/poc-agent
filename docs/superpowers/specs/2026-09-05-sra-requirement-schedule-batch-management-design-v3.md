# SRA Requirement Schedule + Batch Management — Design Specification v3

**Repository:** `hun186/poc-agent`
**Authoritative branch:** `main`
**Inspected baseline:** `dfa02f495b874f8e62ff5c822825e44c8df42717` (PR #201 merge; inspected checkout branch `work`)
**Scope:** Phase 1C architecture correction and Phase 1C-A v3 Closure Gate
**Companion plan:** `docs/superpowers/plans/2026-09-05-sra-requirement-schedule-batch-management-plan-v3.md`
**Execution contracts:** `docs/superpowers/specs/2026-09-05-sra-requirement-schedule-batch-management-codex-prompts-v3.md`

> **Design v3 supersedes Design v2. Plan v3 supersedes Plan v2. Codex Prompts v3 supersede Codex Prompts v2.** Design v1 and Design v2 remain historical records. This document preserves Design v2 decisions except where this document expressly corrects schema evolution, task-identity width, same-schedule integrity, or lifecycle-audit authority. Plan v3 and Codex Prompts v3 are the only implementation authorities paired with this design.

## 1. Status, purpose, and gate boundary

The merged Phase 1C-A control plane exists, but the repository gate is **NOT PASS** pending this v3 Closure Gate. Phase 1C-B is **NOT STARTED** and may not begin until the closure PR is merged, a post-merge Implementation Review explicitly records PASS, and the new actual `main` baseline is recorded.

The split remains:

```text
Phase 1C-A: SQL control plane, recurrence, policy, immutable schedule/run evidence
Phase 1C-A v3 closure: schema v2 migration + audit outbox + projection integration
Phase 1C-B: Phase 1A bridge, worker, reconciliation, manual execution, Word history
```

The closure may implement schema v2, fresh-v2 bootstrap, recognized-v1 migration, identity widening, same-schedule constraints, SQL audit outbox, bounded JSONL projection, success/denial audit integration, and tests. It must not implement a Phase 1A import seam or bridge, Report Job/Agent/Elasticsearch execution, a pre-handoff loop, recurring worker, manual-trigger execution API, remote reconciliation, Word history, Phase 2 UI, or Windows GUI. Audit delivery is not the execution worker, and FastAPI gains no scheduler thread.

## 2. Preserved v2 architecture

Unless corrected below, Design v2 sections 1–4 and 6–24 remain normative through this explicit incorporation. In particular:

* Recurrence is structured `daily|weekly|monthly|interval`, uses an IANA timezone, chooses `fold=0`, deterministically advances nonexistent local time, and supports only `coalesce_latest`.
* Disable atomically sets `enabled=false,next_run_at=NULL`. Re-enable chooses the first occurrence strictly after activation transaction time. Approval while disabled leaves `next_run_at=NULL`; approval while enabled recalculates strictly after new-version activation time.
* Schedule versions are immutable and monotonically numbered; `config_sha256` is evidence rather than identity, so A→B→A is valid.
* Policies remain `all_active|new_or_changed|changed_only`; `requirement_version_number` alone supplies chronology; selection-time expiry remains mandatory.
* Scheduled identity is `(schedule_id,scheduled_for)` and future manual identity is `(schedule_id,trigger_request_id)`.
* `phase1a_batch_id = "reqrun-" + batch_run_id`; `phase1a_output_root_fingerprint` remains persisted and immutable once handoff begins.
* The future worker is an explicit one-active process, never a FastAPI scheduler thread. Phase 1C never imports Agent, Elasticsearch execution, `ReportJobWorker`, or Word rendering, and never writes Phase 1A SQLite directly.

Phase 0 remains authentication/RBAC authority. Phase 1A remains execution and artifact authority. Phase 1B remains independently versioned immutable Requirement authority. The configured Phase 1B schema is `REQUIREMENT_DB_SCHEMA` (default `sra_requirement`); the configured Phase 1C schema is `REQUIREMENT_SCHEDULE_DB_SCHEMA` (default `sra_schedule`). Both identifiers are independently validated and bracket quoted; values are parameterized.

## 3. Canonical SQL schema v2

The canonical Phase 1C target is **`sra_schedule schema_version = 2`** (using the configured schedule schema, not a hard-coded name). Schema version 1 is historical input, never the new target. Phase 1B's version and schema are independent.

All v1 tables and fields remain, subject to these canonical-v2 corrections:

1. `requirement_batch_run_items.phase1a_task_id NVARCHAR(240) NULL`.
2. Same-schedule composite relational constraints described in §4.
3. `requirement_schedule_audit_outbox` and its pending-delivery index described in §5.

No Batch Run or Run Item history is destructively rewritten. No down migration or downgrade exists.

### 3.1 Fresh initialization

A fresh/uninitialized database creates canonical v2 directly in one transaction:

```text
BEGIN
bootstrap and validate schema/version container
lock/read version authority and prove fresh state
create canonical v2 tables, keys, FKs, and indexes in dependency order
validate the complete canonical v2 catalog and required data invariants
INSERT schema_version(version=2) last
re-read and validate the single marker row
COMMIT
```

Any failure rolls back all transaction-visible work and leaves no partial canonical-version claim. Creating v1 and immediately migrating it is forbidden.

### 3.2 Recognized v1 classification

`version=1` is not proof of structure. Before DDL, startup reads the marker under `UPDLOCK,HOLDLOCK`, inspects the exact catalog, and classifies the database as one of two supported repository-era shapes:

* **PR #200-era v1:** required core v1 tables/columns/keys/indexes exist, `phase1a_task_id` is nullable `NVARCHAR(128)`, with the older known FK-validation/physical-FK shape.
* **PR #201-era v1:** the strict PR #201 column/key/filtered-index/cross-schema FK shape, also with nullable `NVARCHAR(128)` task identity.

The classifier is an allowlist, not name counting. It validates core table ownership, exact columns/type/byte length/nullability/ordinal, PK/UQ ordered columns, filtered unique index keys and normalized predicates, and each present FK's parent and referenced schema/table/ordered columns. Only the documented harmless FK difference may distinguish the two classes. Missing core objects, unexpected bindings, wrong types/nullability, ambiguous keys, extra marker rows, or arbitrary hybrids fail closed before mutation.

### 3.3 Transactional v1→v2 migration

For either recognized v1 shape:

```text
BEGIN
lock the singleton schema_version authority with UPDLOCK,HOLDLOCK
classify and fully validate the supported v1 structure
validate data: no orphan/mismatched schedule-version or run-version pairs
ALTER phase1a_task_id NVARCHAR(128) -> NVARCHAR(240) NULL
create ordered composite UQs, drop/replace only superseded known FKs, create composite FKs
create audit outbox table, PK, and pending index
validate complete canonical v2 catalog and data
UPDATE schema_version SET version=2 WHERE version=1
require exactly one affected row; re-read marker and canonical state
COMMIT
```

Every DDL/DML step is in that transaction. Failure rolls back, marker remains 1, and no partial v2 claim survives. A restart sees either recognized v1 and retries the whole migration, or complete v2 and performs validation only.

### 3.4 Version dispatch

| Observed state | Deterministic action |
|---|---|
| no marker/fresh | create canonical v2 directly; marker 2 last |
| version 0 | supported only when the version container is otherwise empty/uninitialized; transactionally create canonical v2 and write 2 last |
| version 1 | classify known v1, migrate transactionally, validate v2, write 2 last |
| version 2 | read-only structural/data-contract validation; no DDL or marker write |
| version >2, multiple rows, malformed or unknown structure | rollback/fail closed |

## 4. Identity width and same-schedule integrity

Phase 1B permits `requirements.external_item_id NVARCHAR(240)`. A selected Run Item stores that exact value as nullable `phase1a_task_id NVARCHAR(240)`; a skipped item stores `NULL`. Truncation, hashing, substitution with internal `requirement_id`, or rejection solely due to the old 128-character Phase 1C width is forbidden. Widening preserves every historical value byte-for-byte.

SQL Server enforces schedule/version ownership with composite relationships:

* Retain `PK_requirement_schedule_versions(schedule_version_id)` and `UQ_requirement_schedule_version(schedule_id,version_number)`.
* Add `UQ_requirement_schedule_version_owner(schedule_id,schedule_version_id)` in that exact order.
* Replace the simple active-version FK with nullable composite `FK_schedule_active_version_owner` from `requirement_schedules(schedule_id,active_version_id)` to `requirement_schedule_versions(schedule_id,schedule_version_id)`. SQL Server's default `MATCH SIMPLE` behavior allows the disabled/no-version `NULL`, while non-null values must belong to the same schedule.
* Replace the simple Run-to-version FK with `FK_run_schedule_version_owner` from `requirement_batch_runs(schedule_id,schedule_version_id)` to the same ordered pair. Retain the separate Run-to-schedule FK because it expresses ownership and supports clear catalog validation.
* Use `NO ACTION` for update/delete; no cascade is introduced. Historical identity/bindings remain immutable.

Migration validates all active pointers and run bindings before creating the UQ/FKs. Constraint operations are ordered referenced UQ first, then dependent composite FKs. Any orphan/mismatch aborts the whole migration.

## 5. Transactional SQL audit outbox

### 5.1 Authority model

Successful Phase 1C state-change audit authority is SQL, not the filesystem. Each create schedule, rename, create version, approve/activate, enable, and disable transaction inserts one required outbox event in the same SQL transaction as its durable transition. Future Gate B manual trigger creation uses the same rule.

```text
BEGIN SQL transaction
domain mutation + INSERT outbox event
COMMIT
          -> durable domain state + durable audit evidence
bounded delivery -> append_audit_event(event_dict) -> editor_audit.jsonl projection
```

An outbox insertion failure rolls back the mutation; a mutation failure rolls back the outbox insert. An exact idempotent replay that produces no new state transition returns existing state and emits no duplicate state-transition event. Event identity is allocated before insertion and remains stable through every delivery attempt.

Authorization denial has no SQL mutation and continues through `authorize_role(...)` and the existing direct `append_audit_event()` denial path. Authentication and RBAC authority do not move into Phase 1C SQL. Thus:

```text
successful Phase 1C state change -> transactional SQL outbox authority
authorization denial/no SQL mutation -> canonical direct denial audit
```

### 5.2 Canonical table

Table name is `requirement_schedule_audit_outbox`: it is explicit, scoped to this subsystem, and does not imply a general event bus.

| Column | Exact SQL contract |
|---|---|
| `audit_event_id` | `NVARCHAR(64) NOT NULL` PK; opaque stable identity |
| `action` | `NVARCHAR(96) NOT NULL` |
| `actor` | `NVARCHAR(128) NOT NULL` |
| `schedule_id` | `NVARCHAR(64) NOT NULL`, FK to logical schedule |
| `schedule_version_id` | `NVARCHAR(64) NULL` |
| `batch_run_id` | `NVARCHAR(64) NULL` |
| `safe_payload_json` | `NVARCHAR(2000) NOT NULL` canonical allowlisted JSON object |
| `created_at` | `DATETIMEOFFSET NOT NULL`, UTC |
| `delivery_attempt_count` | `INT NOT NULL DEFAULT 0`, nonnegative |
| `last_delivery_attempt_at` | `DATETIMEOFFSET NULL`, UTC |
| `last_delivery_error_code` | `NVARCHAR(64) NULL`, allowlisted bounded code only |
| `delivered_at` | `DATETIMEOFFSET NULL`, UTC |

`PK_requirement_schedule_audit_outbox(audit_event_id)` is canonical. `FK_audit_outbox_schedule(schedule_id)` uses `NO ACTION`. Nullable version/run IDs are audit evidence rather than deletion ownership; application validation requires supplied IDs to match the transaction's affected schedule, while future Gate B may add reviewed relational bindings without changing existing history. `IX_requirement_schedule_audit_pending(delivered_at,created_at,audit_event_id)` is non-unique and ordered exactly as shown, permitting bounded deterministic pending reads.

Actions are stable: `requirement_schedule.created`, `.updated` (rename only), `.version_created`, `.version_approved`, `.enabled`, and `.disabled`. Enablement does not hide behind generic `.updated`. Safe payload is built from an action-specific allowlist of IDs, version number, prior/new lifecycle status, enabled state, and bounded recurrence timing evidence. It never contains credentials, connection strings, bearer tokens, service keys, prompts or `prompt_content`, raw SQL/ODBC errors, absolute paths, tracebacks, arbitrary request bodies, or unreviewed metadata.

Immutable outbox fields are identity, action, actor, entity IDs, payload, and creation time. Delivery alone may monotonically increment attempt count, update attempt time/safe error code, and set `delivered_at` once. Delivered rows are evidence and are not rewritten or deleted by Phase 1C.

### 5.3 Delivery component and projection semantics

`requirement_scheduler/audit_delivery.py` is a small isolated adapter. It consumes committed pending rows and an injected sink compatible with `append_audit_event(event_dict)`. It owns neither authentication nor lifecycle authority and starts no background FastAPI thread.

A bounded drain:

1. reads at most configured `limit` pending rows ordered by `(created_at,audit_event_id)`; its short SQL transaction may use `UPDLOCK,READPAST` while updating only delivery metadata;
2. projects an allowlisted record containing the stable `audit_event_id` through the existing sink;
3. after successful append, marks `delivered_at` in a new SQL transaction after verifying the same event is still pending;
4. after sink failure, leaves it pending and records only an allowlisted code such as `audit_sink_write_failed`, incremented count, and attempt time; raw exception text/path is never persisted or returned.

Gate A may invoke a bounded best-effort drain after a successful lifecycle transaction and/or at startup after schema validation. Projection failure does not change the committed domain response: domain mutation and durable outbox evidence remain committed while JSONL is pending.

SQL-to-filesystem projection is **at-least-once**, never exactly-once. If append succeeds and the process crashes before `delivered_at`, retry may append a duplicate JSONL record. Every duplicate carries the same stable `audit_event_id`, allowing consumers to deduplicate. The SQL outbox row is authoritative whenever JSONL delivery is delayed. No public API exposes raw payload/error internals, and Phase 1C adds no audit UI, Kafka, webhook, distributed queue, or external event infrastructure.

## 6. Canonical v2 validation

Startup preserves PR #201's strict evidence model and expands it. Validation proves exact configured schemas and all canonical-v2 tables; column names, SQL types, byte lengths/`MAX`, nullability and ordinal; PK/UQ names and ordered columns; filtered unique indexes and normalized filter semantics; every FK's parent schema/table/ordered columns and referenced schema/table/ordered columns; outbox PK/index; and exactly one `schema_version=2` row.

Validation never accepts counts/names alone, never hard-codes `sra_schedule` instead of the configured schedule schema, and independently binds cross-schema FKs to configured `REQUIREMENT_DB_SCHEMA`. Existing v2 startup is read-only: observed DDL or marker mutation is a defect.

## 7. Failure, retry, security, and operator visibility

All public failures use existing bounded safe taxonomy. Unknown/malformed schemas, failed pre-migration data validation, failed DDL, failed post-validation, or marker compare-and-set failure roll back. Domain mutation/outbox insertion is one transaction; delivery happens only after commit. Projection retries are bounded per invocation and at-least-once. The stable event ID is not a secret.

Operators may use SQL outbox state as durable evidence when JSONL lags, but Phase 1C exposes no raw outbox payload or delivery error through public APIs. Live SQL acceptance remains independently NOT EXECUTED until performed with explicitly authorized access; repository fake-ODBC tests are not deployment acceptance.

## 8. Required acceptance evidence

The closure must prove: fresh direct v2; PR #200 and PR #201 v1 classification/migration; malformed-v1 rollback with marker 1 and no partial v2; existing-v2 read-only validation; future-version rejection; ordered composite integrity; exact 240-character external identity and unchanged historical IDs; mutation/outbox rollback coupling; no outbox on domain failure/no-op replay; projection success/failure/crash duplicate with stable identity; safe payload/error exclusion; RBAC success-vs-denial authority; and no Gate B/runtime execution surface.

Completion of implementation may say only: **“Phase 1C-A v3 closure repository gate ready for post-merge Implementation Review. Phase 1C-B NOT STARTED.”** The implementation may not self-award PASS.
