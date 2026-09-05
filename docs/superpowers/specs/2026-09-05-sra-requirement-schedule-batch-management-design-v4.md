# SRA Requirement Schedule + Batch Management — Design Specification v4

**Repository:** `hun186/poc-agent`
**Authoritative branch:** `main`
**Inspected baseline:** `fe621409f52b8387a833f502b7ff47c128000583` (PR #202 merge; checkout branch `work`)
**Scope:** Phase 1C architecture compatibility correction and Phase 1C-A v4 Closure Gate
**Companion plan:** `docs/superpowers/plans/2026-09-05-sra-requirement-schedule-batch-management-plan-v4.md`
**Execution contracts:** `docs/superpowers/specs/2026-09-05-sra-requirement-schedule-batch-management-codex-prompts-v4.md`

> **Design v4 supersedes Design v3. Plan v4 supersedes Plan v3. Codex Prompts v4 supersede Codex Prompts v3.** v1–v3 remain immutable historical records and must not be executed. This document preserves the v3 architecture and corrects only recognized-v1 compatibility, exact classification, legacy configuration validation, JSONL event time, and delivery-metadata concurrency.

## 1. Status and unchanged boundary

The merged Phase 1C-A source exists, but its repository gate is **NOT PASS**. Phase 1C-A v4 closure implementation is **NOT STARTED**. Phase 1C-B is **NOT STARTED** and remains blocked until the v4 closure PR is merged, a post-merge human/ChatGPT Implementation Review explicitly records PASS, and a new actual `main` baseline is recorded.

The architecture remains: canonical `schema_version=2`; direct fresh-v2 initialization; one-transaction v1→v2 migration; nullable `phase1a_task_id NVARCHAR(240)`; same-schedule composite UQ/FKs; transactional SQL audit outbox; projection through existing `append_audit_event()`; at-least-once delivery with stable `audit_event_id`; and the existing Gate A/Gate B split. Design v2 sections incorporated by v3 remain normative unless v3 or this document expressly corrects them.

This closure does **not** authorize a Phase 1A bridge, Report Job/Agent/Elasticsearch execution, pre-handoff loop, recurring worker, manual-trigger execution API, reconciliation, Word history, UI, Windows GUI, direct Phase 1A SQLite access, or FastAPI scheduler thread. The bounded audit projector is not Gate B execution.

## 2. Canonical schema v2 and initialization

The configured Phase 1C schema (default `sra_schedule`) targets exactly one marker row with `version=2`; Phase 1B remains independently versioned. Fresh or otherwise empty version-0 state creates canonical v2 directly and writes marker 2 last. Existing v2 startup only validates and never mutates. Future versions, multiple markers, unknown structures, or malformed catalog/data fail closed.

Canonical v2 retains the v3 table contracts, including:

* exact selected Phase 1B `requirements.external_item_id` in `requirement_batch_run_items.phase1a_task_id NVARCHAR(240) NULL`; skipped items are `NULL`;
* `UQ_requirement_schedule_version_owner(schedule_id,schedule_version_id)`, composite `FK_schedule_active_version_owner`, and composite `FK_run_schedule_version_owner`, all ordered as written and `NO ACTION`;
* `requirement_schedule_audit_outbox`, its exact v3 columns/PK/FK/pending index, immutable event data, and mutable delivery metadata.

No truncation, hashing, or internal-ID substitution is allowed. Outside the one-time exception in §4, Batch Run and Run Item identities remain immutable.

## 3. Deterministic recognized-v1 classifier

Classification occurs under the locked marker and **before any mutation**. `version=1` alone proves nothing. Exactly two whole-catalog descriptors are supported: the physical schema emitted by PR #200 (`df968cd81` / implementation commit `b47607602`) and that emitted by PR #201 (`dfa02f495` / implementation commit `70ac46349`). A match must satisfy one complete descriptor; mixing rows from them is not allowed.

### 3.1 Exact common objects

Both descriptors require exactly these tables and exact column ordinals: `schema_version(version)`; `requirement_schedules(schedule_id,name,requirement_set_id,enabled,active_version_id,next_run_at,created_by,created_at,updated_by,updated_at)`; `requirement_schedule_versions(schedule_version_id,schedule_id,version_number,timezone,recurrence_json,run_policy,model,config_sha256,status,created_by,created_at,approved_by,approved_at,retired_at)`; `requirement_batch_runs(batch_run_id,schedule_id,schedule_version_id,trigger_type,trigger_request_id,scheduled_for,snapshot_id,run_policy,phase1a_batch_id,phase1a_source_sha256,phase1a_output_root_fingerprint,state,selected_count,skipped_count,success_count,failure_count,error_code,error_message,deadline_elapsed_during_execution,created_by,created_at,materialized_at,handoff_started_at,handed_off_at,reconciled_at,completed_at,updated_at)`; `requirement_batch_run_items(run_item_id,batch_run_id,requirement_id,requirement_version_id,requirement_version_number,source_order,selection_status,selection_reason,phase1a_task_id,execution_state,remote_job_id,remote_job_state,artifact_relative_path,error_code,error_message,expired_at_selection,expired_before_handoff,deadline_elapsed_during_execution,created_at,evaluated_at,handoff_started_at,dispatched_at,remote_completed_at,artifact_reconciled_at,completed_at,updated_at)`; and `requirement_schedule_item_state(schedule_id,requirement_id,last_seen_requirement_version_id,last_seen_requirement_version_number,last_successful_requirement_version_id,last_successful_requirement_version_number,last_successful_run_item_id,last_successful_at,updated_at)`.

Every descriptor records and compares column name, SQL type, SQL Server byte `max_length` (`NVARCHAR(n)=2n`, `MAX=-1`), nullability, and 1-based ordinal. Shared widths are: identifiers `NVARCHAR(64)`; names/models `NVARCHAR(240)`; actor/request IDs `NVARCHAR(128)`; messages/paths `NVARCHAR(500)`; hashes `CHAR(64)`; recurrence `NVARCHAR(MAX)`; integers `INT`; flags `BIT`; and timestamps `DATETIMEOFFSET`. In both v1 descriptors `phase1a_task_id` is nullable `NVARCHAR(128)`. PR #200 alone has `run_policy NVARCHAR(32)`, version `status NVARCHAR(20)`, run `trigger_type NVARCHAR(16)`, run `state NVARCHAR(32)`, item `selection_status NVARCHAR(16)`, item `execution_state NVARCHAR(32)`, and item `remote_job_state NVARCHAR(32)`; PR #201 has respectively `NVARCHAR(64)`, `40`, `32`, `64`, `32`, `64`, and `64`. All other type/length/nullability/ordinal entries must equal the applicable reviewed descriptor.

Both descriptors require exact named PK/UQs and ordered columns: `PK_requirement_schedules(schedule_id)`; `PK_requirement_schedule_versions(schedule_version_id)`; `UQ_requirement_schedule_version(schedule_id,version_number)`; `PK_requirement_batch_runs(batch_run_id)`; `PK_requirement_batch_run_items(run_item_id)`; `UQ_requirement_batch_run_item(batch_run_id,requirement_id)`; `UQ_requirement_batch_run_order(batch_run_id,source_order)`; and `PK_requirement_schedule_item_state(schedule_id,requirement_id)`. They also require unique filtered indexes `UX_schedule_run_scheduled(schedule_id,scheduled_for) WHERE trigger_type='scheduled'` and `UX_schedule_run_manual(schedule_id,trigger_request_id) WHERE trigger_type='manual'`, compared with a semantics-preserving normalized predicate and no extra key columns.

### 3.2 Exact FK allowlist

`S` means the configured schedule schema and `R` the independently validated configured Requirement schema. Every present FK must have the exact name, parent, ordered local columns, referenced schema/table/ordered columns, and no cascade. Absence means no FK with that name **and no equivalent extra FK** on that relationship.

| FK | Exact relationship | PR #200 | PR #201 |
|---|---|:---:|:---:|
| `FK_schedule_requirement_set` | `S.requirement_schedules(requirement_set_id)` → `R.requirement_sets(requirement_set_id)` | required | required |
| `FK_schedule_version_schedule` | `S.requirement_schedule_versions(schedule_id)` → `S.requirement_schedules(schedule_id)` | required | required |
| `FK_schedule_active_version` | `S.requirement_schedules(active_version_id)` → `S.requirement_schedule_versions(schedule_version_id)` | absent | required |
| `FK_run_schedule` | `S.requirement_batch_runs(schedule_id)` → `S.requirement_schedules(schedule_id)` | absent | required |
| `FK_run_schedule_version` | `S.requirement_batch_runs(schedule_version_id)` → `S.requirement_schedule_versions(schedule_version_id)` | absent | required |
| `FK_run_snapshot` | `S.requirement_batch_runs(snapshot_id)` → `R.requirement_set_snapshots(snapshot_id)` | required | required |
| `FK_run_item_run` | `S.requirement_batch_run_items(batch_run_id)` → `S.requirement_batch_runs(batch_run_id)` | absent | required |
| `FK_run_item_version` | `S.requirement_batch_run_items(requirement_version_id)` → `R.requirement_versions(requirement_version_id)` | required | required |
| `FK_state_schedule` | `S.requirement_schedule_item_state(schedule_id)` → `S.requirement_schedules(schedule_id)` | absent | required |
| `FK_state_seen_version` | `S.requirement_schedule_item_state(last_seen_requirement_version_id)` → `R.requirement_versions(requirement_version_id)` | required | required |
| `FK_state_success_version` | `S.requirement_schedule_item_state(last_successful_requirement_version_id)` → `R.requirement_versions(requirement_version_id)` | required | required |
| `FK_state_success_item` | `S.requirement_schedule_item_state(last_successful_run_item_id)` → `S.requirement_batch_run_items(run_item_id)` | absent | required |

No count-only check, “older FK shape” shortcut, unexpected object, alternate binding, or arbitrary PR #200/#201 hybrid is accepted. The implementation must encode these two immutable descriptors rather than relax the canonical-v2 validator.

## 4. Narrow PR #200 persisted-identity compatibility repair

PR #200 materialized known future-handoff placeholders: every run used `phase1a_batch_id='phase1c-'+batch_run_id`, and a selected item used internal `requirement_id` as `phase1a_task_id`; PR #201 corrected these to `reqrun-` and immutable Phase 1B `requirements.external_item_id`. Therefore only an **exactly classified PR #200 v1 database** receives this one-time, reviewed migration exception.

Before changing any identity, validate all affected history proves Gate B never ran. At minimum every run must have `phase1a_source_sha256 IS NULL`, `phase1a_output_root_fingerprint IS NULL`, `handoff_started_at IS NULL`, and `handed_off_at IS NULL`; every item must have `remote_job_id IS NULL`, `remote_job_state IS NULL`, `artifact_relative_path IS NULL`, `handoff_started_at IS NULL`, `dispatched_at IS NULL`, `remote_completed_at IS NULL`, `artifact_reconciled_at IS NULL`, and no remote completion/artifact evidence. Run/item states, counters, completion/reconciliation timestamps, expiry-before-handoff flags, checkpoint success fields, and any other evidence must also be restricted to values reachable in Gate A. Any Gate-B-only state or evidence fails closed and no identity is rewritten.

After proving absence, every PR #200 Run—including `blocked_no_snapshot`—must match exactly `phase1a_batch_id='phase1c-'+batch_run_id`; otherwise fail closed rather than guess. Repair it to `phase1a_batch_id='reqrun-'+batch_run_id`. Every selected item must match exactly `phase1a_task_id=requirement_id`; join its immutable Phase 1B `requirements` row and repair to the exact `external_item_id`. Require the join to resolve exactly one row consistent with the item's Requirement identity/version evidence. Skipped items must have and retain `phase1a_task_id IS NULL`. A missing/ambiguous join, unexpected selected/skipped identity pattern, or value that cannot fit canonical 240 characters fails closed. Never truncate or hash.

PR #201-classified values are already canonical and are validated, then preserved byte-for-byte; the repair path must not issue identity updates for that class. This exception does not create general identity mutability and cannot run once marker 2 is written.

## 5. Legacy schedule-configuration validation

Before DDL or identity repair, migration parses persisted version evidence using the same canonical domain validation used by current creation and approval. Every `approved` version and every version referenced by an enabled schedule's active pointer must have: a valid IANA timezone; exact supported recurrence grammar and canonical parseable recurrence/config evidence; interval anchor with an offset; second precision; a valid nonblank model of at most 240 characters; a supported run policy; and internally consistent persisted status/approval/active-pointer evidence. Invalid active or approved data fails closed. Immutable configuration is never silently repaired.

An exact recognized-v1 database may retain an invalid `draft` or `retired` version only as inaccessible historical evidence: it must not be active/approved, must not violate relational safety, and migration records no correction to its immutable configuration. Every post-v4 approval/activation path reconstructs and revalidates the **persisted row**, not merely request DTOs, under current canonical rules before changing status/pointer—even while the logical schedule is disabled. Consequently an invalid legacy draft can migrate but can never be approved or activated.

## 6. Required v1→v2 transaction order

The migration is exactly one SQL transaction in this order:

```text
BEGIN
lock singleton version authority (UPDLOCK,HOLDLOCK)
classify exact supported v1
validate the complete recognized-v1 catalog
validate schedule/version configuration data
validate same-schedule bindings and all other pre-migration data invariants
validate Gate-B absence wherever PR #200 identity repair is required
perform the exact PR #200 legacy identity repair, if and only if classified PR #200
widen phase1a_task_id to NVARCHAR(240) NULL
create/replace composite ownership constraints in dependency order
create audit outbox, PK/FK, and pending index
validate the complete canonical-v2 catalog and data
UPDATE the sole marker 1 -> 2 LAST with compare-and-set and rowcount=1
re-read and validate the sole marker and canonical state
COMMIT
```

Any error executes `ROLLBACK`: marker remains 1, with no partial identity repair, widening/constraint DDL, outbox, or canonical-v2 claim. Restart observes either intact recognized v1 and retries the entire transaction or complete validated v2.

## 7. Transactional audit authority, event time, and CAS delivery

Successful lifecycle mutation and its immutable `requirement_schedule_audit_outbox` row share one SQL transaction. Authorization denial without SQL mutation continues through the existing direct canonical audit path. This is unchanged from v3 and makes no SQL/filesystem atomicity or exactly-once claim.

`outbox.created_at` is the authoritative lifecycle event time. Every projection record passed to existing `append_audit_event(event_dict)` includes the stable `audit_event_id` and `ts` equal to that stored creation instant serialized in canonical UTC ISO form. Delivery latency and retry never replace it with append time. A duplicate projection therefore has the same event ID **and the same lifecycle `ts`**. `last_delivery_attempt_at` and `delivered_at` are SQL delivery metadata only and never lifecycle time.

Pending reads remain bounded and deterministic by `(created_at,audit_event_id)`, and filesystem append occurs outside the lifecycle transaction. Both success and failure metadata writes use compare-and-set on the still-pending row, equivalent to:

```sql
... WHERE audit_event_id = ? AND delivered_at IS NULL
```

Success may set `delivered_at` once and clear the current pending error according to the canonical implementation; failure may increment attempts/set attempt time/safe error only while pending. A zero-row update means another projector delivered it and is a benign lost race: do not overwrite `delivered_at`, regress it to pending, increment a misleading post-delivery failure, or replace current metadata. Thus projector A may append and mark delivered while projector B later fails; the SQL row remains delivered. No lease or distributed queue is required, and concurrent appends/duplicate JSONL records remain valid at-least-once behavior.

Safe payload/action constraints, immutable outbox fields, bounded error codes, no raw exception/path, and no public outbox internals remain as specified by v3.

## 8. Acceptance and authority

The v4 closure must prove both exact v1 classifiers; PR #200 normal and no-snapshot repair; exact selected external identity including 240 characters; skipped `NULL`; untouched PR #201 identities; unexpected identity and all Gate-B evidence fail closed; active/approved legacy configuration fail-closed behavior; invalid draft historical-only behavior and approval rejection; complete rollback under injected repair/DDL/outbox/marker failures; fresh direct v2 and existing-v2 read-only validation; same-schedule constraints; transactional audit authority; original outbox event time across delayed/duplicate delivery; pending-row CAS monotonicity; security/RBAC regressions; and Gate B absence.

Implementation may report only: **“Phase 1C-A v4 closure repository gate ready for post-merge Implementation Review.”** It cannot self-award PASS. **Phase 1C-B NOT STARTED.**
