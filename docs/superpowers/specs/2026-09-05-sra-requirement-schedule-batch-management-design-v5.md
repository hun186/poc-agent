# SRA Requirement Schedule + Batch Management — Design Specification v5

**Repository:** `hun186/poc-agent`
**Authoritative branch:** `main`
**Inspected hosted baseline:** `d56a8a061446400e324384f2719af3c95ba7d0af` (PR #204 merge)
**Scope:** documentation-only Phase 1C-A source-baseline correction

> Design v5, Plan v5, and Prompts v5 supersede v4. Older versions remain historical and must not be executed. Actual PR #200, #201, and #204 source was re-read; source wins stale design claims.

## 1. Status and invariant architecture

PR #204 does not earn Gate A PASS. Phase 1C-A remains **NOT PASS** pending a v5 implementation and post-merge Implementation Review. Phase 1C-B is **NOT STARTED**.

The architecture is unchanged: canonical `schema_version=2`; fresh databases initialize directly at v2; only recognized v1 shapes migrate transactionally; `phase1a_task_id NVARCHAR(240) NULL`; same-schedule composite integrity; lifecycle mutation plus SQL audit outbox in one transaction; bounded at-least-once JSONL projection; stable `audit_event_id`; lifecycle `ts = outbox.created_at`; pending-row CAS; and separate 1C-A/1C-B gates. This correction does not authorize a Phase 1A bridge, scheduler/execution worker, manual execution, reconciliation, or Word history.

## 2. Source-derived schema shapes

Classification occurs while the singleton marker is locked and before mutation. A marker value alone is insufficient. Catalog evidence comes from ordinary DB-API `execute`, `fetchone`, and `fetchall` calls against SQL Server `sys.schemas`, `sys.tables`, `sys.columns`, `sys.types`, `sys.key_constraints`, `sys.indexes`, `sys.index_columns`, `sys.foreign_keys`, and `sys.foreign_key_columns`. Production must not call `cursor.requirement_schedule_catalog()` or any fake-only hook.

The classifier compares the complete schema: exact table set; every column's name, type, SQL Server byte `max_length`, nullability, and ordinal; named PK/UQ and ordered columns; each filtered index's name, table, ordered keys, normalized predicate, and `is_unique`; and every FK's name, parent schema/table/ordered columns and referenced schema/table/ordered columns. Unexpected tables, keys, indexes, FKs, equivalent duplicate relationships, alternate bindings, and hybrids fail closed.

### 2.1 Corrected common physical widths

Actual PR #200 (`b47607602`) and PR #201 (`70ac46349`) DDL use the **same** vocabulary/state widths:

| Field | Both recognized v1 shapes | Canonical v2 |
|---|---:|---:|
| version `run_policy` | `NVARCHAR(32)` | `NVARCHAR(32)` |
| version `status` | `NVARCHAR(20)` | `NVARCHAR(20)` |
| Run `trigger_type` | `NVARCHAR(16)` | `NVARCHAR(16)` |
| Run `run_policy` | `NVARCHAR(32)` | `NVARCHAR(32)` |
| Run `state` | `NVARCHAR(32)` | `NVARCHAR(32)` |
| Item `selection_status` | `NVARCHAR(16)` | `NVARCHAR(16)` |
| Item `execution_state` | `NVARCHAR(32)` | `NVARCHAR(32)` |
| Item `remote_job_state` | `NVARCHAR(32) NULL` | `NVARCHAR(32) NULL` |

Both v1 shapes have `phase1a_task_id NVARCHAR(128) NULL`; only that column widens to 240 characters. Canonical v2 must not widen vocabulary fields based on v4's incorrect statement. Other columns retain their reviewed PR #201 types, lengths, nullability, and ordinals.

Both shapes have the same named PK/UQs and the unique filtered occurrence indexes `UX_schedule_run_scheduled(schedule_id,scheduled_for) WHERE trigger_type='scheduled'` and `UX_schedule_run_manual(schedule_id,trigger_request_id) WHERE trigger_type='manual'` (`is_unique=True`). Their meaningful difference is the internal FK set added by PR #201.

### 2.2 Exact v1 FK distinction

`S` is the configured schedule schema and `R` the separately configured Requirement schema. Both shapes require `FK_schedule_requirement_set`, `FK_schedule_version_schedule`, `FK_run_snapshot`, `FK_run_item_version`, `FK_state_seen_version`, and `FK_state_success_version` with their reviewed bindings. PR #200 must have no equivalent relationship for the following; PR #201 must have each exact named relationship:

* `FK_schedule_active_version`: `S.requirement_schedules(active_version_id)` → `S.requirement_schedule_versions(schedule_version_id)`;
* `FK_run_schedule`: `S.requirement_batch_runs(schedule_id)` → `S.requirement_schedules(schedule_id)`;
* `FK_run_schedule_version`: `S.requirement_batch_runs(schedule_version_id)` → `S.requirement_schedule_versions(schedule_version_id)`;
* `FK_run_item_run`: `S.requirement_batch_run_items(batch_run_id)` → `S.requirement_batch_runs(batch_run_id)`;
* `FK_state_schedule`: `S.requirement_schedule_item_state(schedule_id)` → `S.requirement_schedules(schedule_id)`;
* `FK_state_success_item`: `S.requirement_schedule_item_state(last_successful_run_item_id)` → `S.requirement_batch_run_items(run_item_id)`.

All FKs use `NO ACTION`. Canonical v2 replaces simple active-version and run-version links with ordered owner relationships: `UQ_requirement_schedule_version_owner(schedule_id,schedule_version_id)`, `FK_schedule_active_version_owner(schedule_id,active_version_id)`, and `FK_run_schedule_version_owner(schedule_id,schedule_version_id)`.

## 3. Version authority and explicit v2 DDL

Exactly one marker row is authoritative. Zero rows are allowed only in the explicitly proven fresh/bootstrap state. Zero rows in an established schema, multiple rows, mixed values, future versions, or malformed objects fail closed. Fresh/v0 and migrated-v1 paths write 2 last, then re-read and prove the singleton value and complete canonical catalog. Existing v2 startup is validation-only.

Canonical-v2 DDL is an explicit, ordered statement sequence. It must not be assembled from v1 text followed by broad `.replace()` calls. Fresh execution must be syntactically complete and produce a catalog identical to canonical descriptors, including separately modeled index uniqueness.

## 4. Shape-specific transactional migration

Both paths run with autocommit disabled: lock singleton marker; classify complete v1 catalog; prevalidate configuration, relationships, identities, and data; apply only the shape's operations; validate full canonical v2; update marker `1→2` last with rowcount one; re-read marker and catalog; commit. Any failure rolls back every data and DDL change.

**PR #200:** never drop absent constraints. Prove Gate-B absence, perform the one-time identity repair, widen only `phase1a_task_id`, add its missing canonical internal FKs, add owner UQ/composite FKs in dependency order, and create the canonical outbox.

**PR #201:** preserve valid existing internal FKs; replace only simple `FK_schedule_active_version` and `FK_run_schedule_version` superseded by composite owner FKs; never rewrite canonical Phase1A identities; widen only `phase1a_task_id`; add the owner UQ/composite FKs; and create the canonical outbox.

### 4.1 Complete PR #200 repair guard

Before repair, every Run must prove no handoff/source/root evidence; `handoff_started_at`, `handed_off_at`, `reconciled_at`, and `completed_at` are null; `deadline_elapsed_during_execution=0`; success/failure counters are zero; and state is Gate-A-reachable. Every Item must have a Gate-A-reachable execution state, null remote job IDs/states, null handoff/dispatched/remote-completed/artifact-reconciled/completed timestamps, null artifact path, `expired_before_handoff=0`, and no deadline-during-execution evidence. Every checkpoint has all four success fields null: version ID, version number, run-item ID, and timestamp. Any ambiguity fails closed.

Runs must exactly contain the known `phase1c-<batch_run_id>` placeholder before conversion to `reqrun-<batch_run_id>`. Selected item ID, version ID, version number, and Requirement ID must mutually match one immutable Phase 1B RequirementVersion and Requirement row before its exact `requirements.external_item_id` is used. Selected placeholders must equal their internal Requirement IDs; skipped task IDs remain null. Missing, duplicate, inconsistent, oversized, or other values fail closed. No truncation/hash is allowed.

## 5. Persisted configuration

Migration and every approval/activation reconstruct the persisted row and applies canonical validation. In particular, DB strings are explicitly converted with `RunPolicy(run_policy)` (or equivalent); annotations do not convert values. `all_active`, `new_or_changed`, and `changed_only` are valid; unknown strings fail safely. Invalid active/approved configuration blocks migration. Invalid historical draft/retired evidence may remain only if inaccessible and can never later be approved or enabled.

## 6. Exact audit outbox and projection

Canonical `requirement_schedule_audit_outbox` is:

| Column | Contract |
|---|---|
| `audit_event_id` | `NVARCHAR(64) NOT NULL` PK |
| `action` | `NVARCHAR(96) NOT NULL` |
| `actor` | `NVARCHAR(128) NOT NULL` |
| `schedule_id` | `NVARCHAR(64) NOT NULL`, `FK_audit_outbox_schedule`, `NO ACTION` |
| `schedule_version_id` | `NVARCHAR(64) NULL` |
| `batch_run_id` | `NVARCHAR(64) NULL`, reserved for Gate B |
| `safe_payload_json` | `NVARCHAR(2000) NOT NULL` canonical JSON object |
| `created_at` | `DATETIMEOFFSET NOT NULL` UTC |
| `delivery_attempt_count` | `INT NOT NULL DEFAULT 0`, nonnegative |
| `last_delivery_attempt_at` | `DATETIMEOFFSET NULL` UTC |
| `last_delivery_error_code` | `NVARCHAR(64) NULL`, bounded safe code |
| `delivered_at` | `DATETIMEOFFSET NULL` UTC |

`IX_requirement_schedule_audit_pending(delivered_at,created_at,audit_event_id) WHERE delivered_at IS NULL` is a filtered **non-unique** index (`is_unique=False`) with that exact ordered key/filter contract. It is distinct from the two unique occurrence indexes.

Payload generation uses action-specific positive allowlists for `requirement_schedule.created`, `.updated`, `.version_created`, `.version_approved`, `.enabled`, and `.disabled`; a suspicious-substring blacklist alone is not a security boundary. No credentials, prompts, arbitrary request bodies, raw SQL/ODBC errors, absolute paths, or tracebacks are stored.

Every successful lifecycle mutation inserts its immutable event in the same SQL transaction. Authorization denial, which has no SQL mutation, retains the existing direct audit path. Projection is live Gate-A wiring, not dead code: a bounded best-effort drain runs after successful lifecycle commit and a bounded startup drain runs after successful scheduler initialization, without any FastAPI scheduling thread. Once domain SQL commits, projection failure cannot change its successful response; the row remains pending.

Projection calls the existing JSONL sink outside the lifecycle transaction. It uses stable event ID and canonical UTC `ts` derived from `created_at`. Both success and failure metadata updates include `WHERE audit_event_id=? AND delivered_at IS NULL`. Zero affected rows means another projector delivered first and is a benign lost race; the current attempt must not report misleading failure/delivery. Crash-before-delivered can append a duplicate with the same ID and timestamp, which is permitted by at-least-once semantics.

## 7. Acceptance authority

The v5 closure matrix must prove all contracts in the companion plan against `ScheduleStore.initialize()` and realistic DB-API seams. Repository completion may say only: **“Phase 1C-A v5 closure ready for post-merge Implementation Review. Phase 1C-B NOT STARTED.”** It must not self-award PASS.
