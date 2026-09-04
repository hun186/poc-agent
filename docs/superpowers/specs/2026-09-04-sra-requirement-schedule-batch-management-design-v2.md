# SRA Requirement Schedule + Batch Management — Design Specification v2

**Repository:** `hun186/poc-agent`<br>
**Authoritative branch:** `main`<br>
**Actual inspected checkout:** branch `work`, clean tree at task start<br>
**Actual baseline HEAD:** `6559e76ad1614b51091624dc84b07c409be8e7bf`<br>
**Baseline provenance:** current checkout equals the PR #198 merge baseline; this checkout has no local `main` ref or configured remote, so hosted advancement could not be fetched. The reviewed PR #198 commit is trivially an ancestor of current HEAD because it equals HEAD.<br>
**Scope:** Phase 1C — Schedule Policy + Batch Management API<br>
**Revision:** v2; corrections required by Phase 1C Design Review v1. It specializes, but does not supersede, the Phase 1B §15 handoff.<br>
**Supersedes:**
`docs/superpowers/specs/2026-09-04-sra-requirement-schedule-batch-management-design-v1.md`<br>
**Dependencies:** Phase 0 Design v3; Phase 1A Design v1 and Plan v1; Phase 1B Design v1 and Plan v1.1.<br>
**Companion Plan:** `docs/superpowers/plans/2026-09-04-sra-requirement-schedule-batch-management-plan-v2.md`<br>
**Execution prompts:** `docs/superpowers/specs/2026-09-04-sra-requirement-schedule-batch-management-codex-prompts-v2.md`<br>
**Entry gate:** Phase 1B repository gate **PASS**.<br>
**Phase 1B live SQL Server acceptance:** **NOT EXECUTED**; this does not block this design.

## 1. Purpose and invariant

Phase 1C turns an approved, active, immutable Phase 1B Requirement snapshot into recurring or manually triggered, historically inspectable Batch Runs. It selects work by an approved schedule policy, preserves deadline evidence, imports deterministic tasks through Phase 1A, and reconciles Phase 1A results. It never executes Agent, Elasticsearch, Report Job worker, or Word-rendering code.

The core invariant is: one scheduled occurrence binds one schedule version and one active snapshot, creates at most one Phase 1A batch, and each selected run item maps to at most one logical Report Job dispatch.

## 2. Roadmap position

Phase 0 supplies authenticated users, canonical Editor RBAC/audit, scoped service credentials, and owner-isolated Report Jobs. Phase 1A supplies the standalone SQLite-backed Report Job HTTP client, crash-safe task state, and DOCX publication. Phase 1B supplies SQL-authoritative immutable Requirements and snapshots. Phase 1C supplies the control plane and bridge between 1B and 1A. Phase 2 may add a UI over the APIs, but does not alter this authority model.

Phase status at this baseline is: Phase 0 present; Phase 1A present; Phase 1B repository gate PASS; Phase 1B live SQL acceptance NOT EXECUTED; Phase 1C not implemented.

## 3. Architecture and data flow

```text
sra_requirement.requirement_sets.active_snapshot_id
              | immutable snapshot membership + RequirementVersion
              v
 sra_schedule.requirement_schedules -> approved immutable schedule version
              | claim due occurrence, coalesce_latest
              v
 immutable Batch Run + immutable Run Item selection evidence
              | expiry recheck + deterministic translation
              v
 requirement_scheduler.phase1a_bridge
              | programmatic import seam only
              v
 batch_scheduler core / SQLite / scoped Report Job HTTP client
              | existing Report Job API and worker
              v
 Router -> Elasticsearch -> Agent -> existing Word renderer
              | Phase 1A status + published relative artifact
              v
 Phase 1C reconciliation/checkpoints/history API
```

No Phase 1C production module may import `agent`, Elasticsearch execution, `ReportJobWorker`, or a Word renderer. `requirement_scheduler` may import public `batch_scheduler` models/store/service interfaces only.

## 4. Process and package boundaries

The implementation package is `requirement_scheduler/`:

| File | Responsibility |
|---|---|
| `models.py` | frozen domain/request models, enums, safe public views |
| `recurrence.py` | recurrence validation and deterministic occurrence calculation |
| `migrations.py` | Phase 1C SQL Server schema v1 DDL and structural validation |
| `store.py` | parameterized SQL transactions, locks, claims, history, checkpoints |
| `policy.py` | pure selection decisions |
| `service.py` | schedule/version/run orchestration |
| `phase1a_bridge.py` | allowlisted RequirementVersion-to-`BatchTaskSpec` mapping and reconciliation |
| `worker.py` | single-process due/handoff/reconcile loop |
| `__main__.py` | `worker` and `worker --once` CLI |

HTTP models/routes live in `sra_api/routers/requirement_schedules.py` and are mounted by `sra_api/main.py`. The API process manages schedules and manual claims but does not run a recurring thread. The explicit worker is a separate process. Phase 1A remains execution/data-plane state; Phase 1C remains Requirement scheduling control-plane state.

## 5. SQL authority and schema boundary

SQL Server is Phase 1C control-plane authority. Use separately configured schema `REQUIREMENT_SCHEDULE_DB_SCHEMA`, default `sra_schedule`, and the reviewed named connection `REQUIREMENT_CONTROL_DB_CONNECTION`. Identifiers pass the existing strict schema-name validation and are bracket quoted; values are parameterized.

`sra_schedule.schema_version` starts at integer 1. Initialization is transactional: bootstrap version container, inspect version, create only from 0, structurally validate every table/column/key/FK, write version 1 last, commit. Unknown or malformed versions roll back and fail closed. Migrations never update/delete Phase 1B `requirements`, `requirement_versions`, `requirement_set_snapshots`, or `requirement_snapshot_items`.

Cross-schema foreign keys bind configured, validated Phase 1B schema objects by bracket-quoted identifiers. The v2 contract validator verifies referenced schema/table/column identities. The deployment principal needs SELECT on the Phase 1B tables and DDL/DML only in Phase 1C schema. If cross-schema FK creation is disallowed by deployment policy, deployment is blocked rather than silently dropping referential integrity; a reviewed Design v2 would be required.

## 6. Schedule models and immutable versions

### 6.1 `requirement_schedules`

| Column | Contract |
|---|---|
| `schedule_id` NVARCHAR(64) PK | opaque stable identity |
| `name` NVARCHAR(240) | mutable only while disabled |
| `requirement_set_id` NVARCHAR(64) | immutable after creation; FK to configured Phase 1B set |
| `enabled` BIT | superuser-controlled |
| `active_version_id` NVARCHAR(64) NULL | FK to a version of this schedule |
| `next_run_at` DATETIMEOFFSET NULL | UTC offset `+00:00`; next unclaimed due instant |
| `created_by`, `updated_by` | authenticated usernames |
| `created_at`, `updated_at` DATETIMEOFFSET | UTC |

Only disabled `name` is safely patchable by `db_operator`. Requirement-set rebinding is forbidden; create a new schedule. Enable requires an approved active version. Schedule lifecycle changes use one transaction and lock the logical schedule row with `UPDLOCK,HOLDLOCK`:

* **Operator disable:** set `enabled=false` and `next_run_at=NULL` atomically. Disabled time is an intentional pause, not a misfire interval, and no disabled occurrence is caught up later.
* **Enable/re-enable:** take `activation_time` from server UTC transaction time, compute `next_run_at=next_occurrence(active_version, activation_time)` (strictly after it), then set `enabled=true` in that transaction. Never reuse the pre-disable value. Immediate work requires an explicit Gate B manual trigger.
* **Worker/system downtime:** when `enabled=true` remains true throughout an outage, persisted `next_run_at` stays authoritative and `coalesce_latest` handles missed enabled occurrences when the worker returns. This is the only normal catch-up case.
* **Approve while disabled:** approve the new immutable version, retire the prior active version as applicable, set `active_version_id`, retain `enabled=false`, and set `next_run_at=NULL` atomically.
* **Approve while enabled:** approve/activate and retire as applicable, take transaction UTC `activation_time`, and set `next_run_at=next_occurrence(new_version, activation_time)` atomically. The new recurrence is authoritative from activation; no old-version occurrence is created or caught up afterward.

Any recurrence calculation, pointer/status update, or audit persistence failure rolls back the whole lifecycle transaction.

### 6.2 `requirement_schedule_versions`

Columns are `schedule_version_id` PK, `schedule_id` FK, monotonic `version_number`, `timezone`, canonical `recurrence_json`, `run_policy`, `model`, `config_sha256`, `status`, `created_by`, `created_at`, `approved_by`, `approved_at`, `retired_at`; version identity is enforced by unique `(schedule_id, version_number)`. `config_sha256` is mandatory audit/comparison/diagnostic evidence and may have a non-unique index, but never defines identity or uniqueness.

Allowed status is `draft|approved|retired`. A created row is immutable, including while draft: correction means a new monotonic version. `db_operator` creates a draft. `superuser` approves it and atomically retires the prior active version, sets the logical `active_version_id`, and recalculates `next_run_at` from the activation transaction's UTC timestamp. Approval is idempotent only when the same already-approved version remains active; attempts to mutate history conflict. Every Batch Run stores the exact `schedule_version_id`.

`config_sha256` is SHA-256 over canonical JSON containing schema version, timezone, recurrence, policy, and model; it excludes audit timestamps/actors. Intentional immutable reversion is valid: versions with hashes A, B, A receive three increasing version numbers, and approving the new A row never mutates or reactivates the retired historical A row. `model` is a non-empty approved schedule value, not a caller-supplied per-run option.

## 7. Structured recurrence grammar

All recurrence documents are frozen, reject extra keys, use an IANA name accepted by `zoneinfo.ZoneInfo`, and contain `kind` plus the exact kind fields:

```json
{"kind":"daily","local_time":"09:30:00"}
{"kind":"weekly","weekdays":[1,3,5],"local_time":"09:30:00"}
{"kind":"monthly","day":31,"local_time":"09:30:00","invalid_day":"last_day"}
{"kind":"interval","every":6,"unit":"minutes","anchor_at":"2026-09-04T00:00:00+00:00"}
```

* `daily`: one occurrence each local calendar day at `local_time`.
* `weekly`: `weekdays` is a sorted unique non-empty list of ISO weekdays 1 (Monday) through 7 (Sunday), at `local_time`.
* `monthly`: `day` is 1..31; `invalid_day` is fixed to `last_day`, so day 31 means the local month's final day when shorter.
* `interval`: `every` is integer 1..10080 and `unit` is `minutes|hours|days`; `anchor_at` is offset-aware. Its instant is normalized to UTC and intervals are elapsed durations from that anchor, not wall-clock calendar arithmetic. The schedule timezone remains required for presentation consistency but does not move interval instants.

Times are second precision. Persisted occurrence/anchor/`next_run_at` values must be offset-aware and stored as UTC. Arbitrary cron, code, SQL, macros, and executable expressions are rejected.

### 7.1 First, next, and daylight transitions

Given exclusive `after_utc`, `next_occurrence(version, after_utc)` returns the least valid occurrence strictly later than it. Approval uses its transaction time as `after_utc`; therefore approval never creates an occurrence in the past. After claiming `scheduled_for`, calculation again uses that exact occurrence as the exclusive boundary.

Calendar recurrences construct local candidates then convert to UTC. An ambiguous local time chooses the earlier instant (`fold=0`). A nonexistent local time advances minute-by-minute to the first valid local instant on that same date; this deterministic DST adjustment is recorded as ordinary recurrence evaluation, not a second occurrence. Monthly shortening happens before DST resolution.

## 8. Due selection and misfires

The only Phase 1C misfire policy is `coalesce_latest`. At worker time `now_utc`, if `next_run_at <= now`, compute all recurrence instants from `next_run_at` through `now` without materializing them; claim only the latest instant. Advance `next_run_at` to the first instant after `now` in the same serializable/locked transaction. A bounded arithmetic implementation is required for interval recurrence; calendar iteration has a defensive cap and fails closed if violated. There is no historical backfill.

Claim uses `UPDLOCK,HOLDLOCK` on the logical schedule and a unique filtered identity on `(schedule_id, scheduled_for)` for scheduled triggers. Not due, disabled, or lacking an approved active version produces no run. A uniqueness race is reread as the existing occurrence rather than creating another. Manual runs use `trigger_type=manual`; their filtered unique identity is `(schedule_id, trigger_request_id)`, generated/accepted at the authenticated service boundary, and they do not advance `next_run_at`. A replay on the same schedule returns the existing run when its normalized request identity agrees; the same request ID on another schedule is independent. Scheduled identity remains the separate filtered unique `(schedule_id, scheduled_for)` where `trigger_type=scheduled`.

## 9. Immutable Batch Run history

### 9.1 `requirement_batch_runs`

Columns: `batch_run_id` PK; `schedule_id`; `schedule_version_id`; `trigger_type` (`scheduled|manual`); `trigger_request_id` nullable; `scheduled_for` UTC; `snapshot_id`; `run_policy`; deterministic `phase1a_batch_id`; nullable `phase1a_source_sha256`; nullable `phase1a_output_root_fingerprint`; lifecycle `state`; `selected_count`, `skipped_count`, `success_count`, `failure_count`; safe `error_code`, bounded `error_message`; `deadline_elapsed_during_execution` BIT; `created_by`; and `created_at`, `materialized_at`, `handoff_started_at`, `handed_off_at`, `reconciled_at`, `completed_at`, `updated_at`.

Unique `(schedule_id, scheduled_for)` applies to `trigger_type=scheduled`. Identity, bindings, policy, counts-as-materialized, and creation fields are immutable. Lifecycle/reconciliation fields are controlled state transitions, not rewrites of historical identity. Run states are `materialized|handoff_pending|handing_off|running|completed|completed_with_errors|failed|blocked_no_snapshot`.

### 9.2 `requirement_batch_run_items`

Columns: `run_item_id` PK; `batch_run_id`; `requirement_id`; `requirement_version_id`; immutable `requirement_version_number`; `source_order`; `selection_status` (`selected|skipped`); `selection_reason`; deterministic nullable `phase1a_task_id`; `execution_state`; nullable `remote_job_id`, `remote_job_state`; safe `artifact_relative_path`; safe `error_code`, bounded `error_message`; `expired_at_selection`, `expired_before_handoff`, `deadline_elapsed_during_execution`; and `created_at`, `evaluated_at`, `handoff_started_at`, `dispatched_at`, `remote_completed_at`, `artifact_reconciled_at`, `completed_at`, `updated_at`.

Unique `(batch_run_id, requirement_id)` and `(batch_run_id, source_order)` preserve membership. The exact RequirementVersion is immutable. Selection rows include skipped policy/expiry evidence, so counts are reproducible. Execution fields transition monotonically through `not_selected|handoff_pending|handing_off|submitted|running|artifact_ready|succeeded|remote_failed|expired_before_handoff|reconciliation_error`.

Snapshot lookup and all item materialization occur in the occurrence claim transaction. A run binds the Phase 1B `active_snapshot_id` observed under lock; later active-snapshot changes cannot alter it. No active snapshot creates `blocked_no_snapshot`, zero items, safe error `no_active_snapshot`, and advances the scheduled occurrence so the worker does not spin.

## 10. Policy semantics

Policy is evaluated against every item in the bound snapshot:

* `all_active`: select every item whose `expires_at` is null or greater than evaluation time. Unchanged successes run again.
* `new_or_changed`: select when the matched checkpoint successful version ID/number pair is null or differs from the current immutable RequirementVersion ID/number pair. Failure does not advance success state, so unchanged failed work retries next occurrence. Success advances successful fields during reconciliation.
* `changed_only`: select when the current immutable RequirementVersion ID/number pair differs from the matched last-seen ID/number pair; null-to-current counts as changed. Advance last-seen at materialization even if execution later fails, so an unchanged failure does not retry until a new RequirementVersion appears.

An expired item is skipped with `expired_at_selection`, regardless of policy. Policy skips use `unchanged_since_success` or `unchanged_since_seen`. Selection is evaluated from the checkpoint state locked in the same transaction that inserts items.

## 11. Explicit checkpoint state

`requirement_schedule_item_state` has composite PK `(schedule_id, requirement_id)`, `last_seen_requirement_version_id`, `last_seen_requirement_version_number`, `last_successful_requirement_version_id`, `last_successful_requirement_version_number`, `last_successful_run_item_id`, `last_successful_at`, and `updated_at`, with FKs to exact history rows. At materialization every Run Item captures the joined Phase 1B `requirement_version_id` and its per-Requirement monotonic immutable `requirement_version_number`; row membership order is preserved separately and is never chronology evidence.

Materialization locks the checkpoint row in the run-creation transaction, evaluates policy against its prior values, inserts immutable item evidence, then upserts both last-seen version ID and number for every evaluated snapshot item. Reconciliation locks the succeeded Run Item and the corresponding `(schedule_id, requirement_id)` checkpoint in one SQL transaction. Successful fields may be written only when:

```text
last_successful_requirement_version_number IS NULL
OR finishing_requirement_version_number > last_successful_requirement_version_number
OR (
  finishing_requirement_version_number == last_successful_requirement_version_number
  AND persisted successful version identity agrees, making this an idempotent replay
)
```

For the equal-number replay, the persisted version ID must equal the finishing version ID; replay of the already recorded Run Item is a no-op, while another succeeded item for that exact immutable version may only preserve the version checkpoint and must not rewrite `last_successful_at` backward. If the finishing number is lower, reconciliation records historical item/run success only and MUST NOT replace any successful checkpoint field. Version chronology alone resolves this race—never row membership order, run creation order, snapshot ordering, or completion time.

Required race proof: materialize run A at Requirement version 3 and run B at version 4; B succeeds first and sets checkpoint 4; A succeeds later and checkpoint remains 4; a following `new_or_changed` evaluation of version 4 skips it rather than spuriously rerunning it.

## 12. Expiry and deadline

Phase 1B `expires_at` is an absolute offset-aware instant. Eligibility is `expires_at IS NULL OR expires_at > check_time`; equality is expired.

Check one occurs at materialization. Check two occurs immediately before the first Phase 1A programmatic import for that selected item. A newly expired item becomes `expired_before_handoff`, is excluded from the seam, and cannot create a Report Job. If every selected item expires, finalize without a Phase 1A batch.

Once an item has entered Phase 1A's persisted `submitting` flow, repeating the same deterministic submit is recovery, not a new occurrence. A remote job created before expiry continues; Phase 1C does not cancel it. If expiry becomes elapsed after dispatch and before terminal reconciliation, set item/run `deadline_elapsed_during_execution=true` without changing the remote result.

## 13. Phase 1A programmatic handoff

Add a public Phase 1A seam implemented above its SQLite internals:

```python
BatchSchedulerStore.import_tasks(
    *, batch_id: str, source_ref: str, source_sha256: str,
    output_root: Path, tasks: Sequence[BatchTaskSpec]
) -> dict
```

`load_batch()` and file CLI construct the same normalized input and call this common insert path. Phase 1C never opens Phase 1A SQLite itself.

Mapping is exact:

| Requirement data | `BatchTaskSpec` |
|---|---|
| `external_item_id` | `task_id` |
| `prompt_content` | `prompt` |
| sanitized title, falling back to external ID | `filename` (display hint only; Phase 1A confinement remains authoritative) |
| `reqrun:{batch_run_id}:{run_item_id}` | `session_id` |
| approved schedule-version `model` | `model` |
| none | `scheduled_at` |
| IDs only | `metadata`: requirement, requirement_version, snapshot, schedule, schedule_version, batch_run, run_item |

Phase 1C emits no `options`, credentials, SQL connection references, prompts in metadata, absolute paths, or arbitrary execution fields. `phase1a_task_id=external_item_id`; duplicate external IDs cannot exist in one Phase 1B set/source snapshot.

`phase1a_output_root_fingerprint` is a deterministic non-secret SHA-256 over a versioned canonical representation of the canonical resolved Phase 1A output root. It is not the path and no absolute root may appear in an API response, log, audit event, or user-visible error. Before the first Phase 1A import attempt, one SQL transaction locks the Batch Run and persists this root fingerprint together with its handoff identity; after that both are immutable.

`phase1a_batch_id = "reqrun-" + batch_run_id`. `source_ref = "requirement-batch-run:" + batch_run_id`. `source_sha256` is SHA-256 of canonical JSON containing bridge contract version, run/schedule/snapshot IDs, the **persisted** root fingerprint, and ordered exact task payloads. It must not recompute identity from mutable runtime configuration. Reimport with the same ID/fingerprint returns the existing batch; a mismatch fails closed as `phase1a_batch_conflict`.

On every resume, reconciliation, or history download, compute the current configured root fingerprint and compare it with the persisted Run value before importing or resolving a relative artifact. Equality permits resume. Inequality fails closed as `phase1a_output_root_mismatch`: do not create/reimport a conflicting Phase 1A batch and do not resolve or serve the artifact under the new root. Missing/unresolvable configured root fails safely as `phase1a_output_root_unavailable`. A crash after Phase 1A import but before the SQL handoff marker reuses the existing batch only after the root match; mismatch never creates a second batch.

## 14. Crash, restart, and idempotency

| Crash window | Recovery |
|---|---|
| SQL run before Phase 1A import | run remains `handoff_pending`; worker deterministically reconstructs and imports it |
| Phase 1A import before SQL marker | same batch ID/fingerprint returns existing batch; SQL marker is then persisted |
| Phase 1A task `submitting` before response persistence | existing Phase 1A deterministic idempotency key replays the same logical Report Job create |
| remote completion before SQL reconciliation | worker reads Phase 1A task/remote state and updates the same run item |
| DOCX published before SQL artifact reconciliation | Phase 1A already owns confined path; reconciliation validates and stores its relative identity |
| restart with partial run | worker scans nonterminal runs, resumes handoff/reconciliation, and finalizes only from persisted terminal items |

The scheduled unique key prevents a second occurrence; deterministic batch ID/fingerprint prevents a second Phase 1A batch; Phase 1A's deterministic per-task idempotency prevents a second remote Report Job. State writes are compare-and-set/locked and replay-safe. Conflicts fail closed rather than replacing prior state.

## 15. Worker lifecycle

Entrypoints are:

```bash
python -m requirement_scheduler worker
python -m requirement_scheduler worker --once
```

Startup loads environment, validates named SQL/schema/output root, initializes/validates Phase 1C schema, opens Phase 1A through its public store/service construction, then recovers nonterminal SQL runs before claiming new due work. One cycle: reconcile existing runs; claim/materialize due schedules; expiry recheck/import; call Phase 1A `run_once` for handed-off batches; reconcile; finalize. Continuous mode sleeps `REQUIREMENT_SCHEDULER_POLL_SECONDS`; `--once` performs one bounded cycle and exits nonzero on configuration/credential/fatal persistence failure.

Phase 1C v2 formally supports one active worker process. It is never started by FastAPI lifespan. SQL locks and unique keys still make duplicate run creation safe. Distributed leasing, HA, and multiple active worker throughput are deferred.

## 16. HTTP API contract

All routes preserve existing Editor bearer authentication and safe error bodies `{"detail":{"code":"..."}}`. IDs are opaque strings.

| Method/path | Request/response contract |
|---|---|
| `GET /v1/requirement-schedules` | filters `enabled`, `requirement_set_id`, bounded pagination; safe logical/version summary |
| `GET /v1/requirement-schedules/{schedule_id}` | schedule plus version summaries; 404 if absent |
| `POST /v1/requirement-schedules` | `{name,requirement_set_id,enabled:false}`; 201 |
| `PATCH /v1/requirement-schedules/{schedule_id}` | `{name?}` for db_operator while disabled; `{enabled}` only superuser |
| `POST /v1/requirement-schedules/{schedule_id}/versions` | `{timezone,recurrence,run_policy,model}`; immutable draft, 201 |
| `POST /v1/requirement-schedules/{schedule_id}/versions/{version_number}/approve` | atomically approve/activate/recalculate; superuser |
| `POST /v1/requirement-schedules/{schedule_id}/runs` | `{request_id}`; superuser manual materialization, 201 or idempotent existing response |
| `GET /v1/requirement-batch-runs` | safe filters/pagination, newest first |
| `GET /v1/requirement-batch-runs/{batch_run_id}` | immutable bindings, lifecycle/counts, no absolute path |
| `GET /v1/requirement-batch-runs/{batch_run_id}/items` | ordered safe item histories |
| `GET /v1/requirement-batch-runs/{batch_run_id}/items/{run_item_id}/word` | authenticated DOCX stream only under §18 |

Manual trigger uses the approved active version and snapshot observed at transaction time, sets `scheduled_for` to server UTC now, never changes recurrence state, and requires a 16..128-character request ID for retry idempotency. Client-supplied schedule version, snapshot, model, options, or time are rejected.

## 17. RBAC and audit

Use `current_user`, `require_db_operator`, `require_superuser`, and `authorize_role`; do not create roles or accept service keys on Editor management routes.

* Any authenticated active user: safe GETs and completed Word history.
* `db_operator`: create a disabled logical schedule, rename it while disabled, create immutable drafts.
* `superuser`: all above plus approve/activate versions, enable/disable, manual trigger.

Audit successful `schedule.created`, `schedule.updated`, `schedule.version_created`, `schedule.version_approved`, `schedule.enabled`, `schedule.disabled`, and `schedule.run_triggered` with actor and safe IDs. Existing dependency audit records denials. Never audit recurrence prompts (none exist), secrets, SQL detail, absolute artifact paths, or credentials.

## 18. Word history boundary

Phase 1C does not copy or render a DOCX. Phase 1A owns the published artifact under configured `SRA_BATCH_OUTPUT_ROOT`; Phase 1C stores only the normalized path relative to that root after reconciliation and the Batch Run stores its immutable `phase1a_output_root_fingerprint`.

The endpoint joins run and item, requires item `succeeded`, non-null reconciled artifact, and Phase 1A remote completion. Before combining any path, it canonicalizes the current configured root, computes its fingerprint, and requires equality with the persisted Run fingerprint. Mismatch/unavailable fails closed; an identical relative filename under another root is not the historical artifact. Only after equality does it resolve `(root / relative).resolve()`, require `relative_to(root.resolve())`, and reject absolute paths, `..`, symlink escape, wrong association, missing/non-file artifacts, and non-DOCX validation failures. Return canonical DOCX MIME, safe generated Content-Disposition, `Cache-Control: no-store`, and no local path in JSON, headers, logs, or errors. Authentication remains mandatory. No signed public capability is introduced in v2.

## 19. Status and error taxonomy

Validation errors (400): `recurrence_invalid`, `timezone_invalid`, `timezone_naive`, `schedule_version_invalid`, `schedule_disabled_edit_required`, `artifact_path_invalid`. Authentication is 401; role denial is 403 and audited. Missing resources are 404. Conflicts (409): `schedule_version_immutable`, `schedule_version_conflict`, `schedule_not_approved`, `occurrence_conflict`, `manual_request_conflict`, `phase1a_batch_conflict`, `phase1a_output_root_mismatch`, `artifact_not_complete`. Dependency unavailable is 503: `requirement_schedule_unavailable`, `phase1a_unavailable`, `phase1a_output_root_unavailable`. Unexpected persistence failures are safe 500 `schedule_persistence_error`; missing/invalid reconciled artifacts are safe 500 `artifact_unavailable`.

Internal history uses bounded safe codes/messages. Raw ODBC, HTTP bodies, secrets, prompts, absolute paths, and tracebacks never enter responses or control-plane error columns.

## 20. Configuration and environment

| Variable | Meaning/default |
|---|---|
| `REQUIREMENT_SCHEDULER_ENABLED` | opt-in API/store availability, default false |
| `REQUIREMENT_CONTROL_DB_CONNECTION` | existing reviewed named connection |
| `REQUIREMENT_DB_SCHEMA` | Phase 1B schema, default `sra_requirement` |
| `REQUIREMENT_SCHEDULE_DB_SCHEMA` | Phase 1C schema, default `sra_schedule` |
| `REQUIREMENT_SQL_REGISTRY_FILE` | existing named registry path |
| `REQUIREMENT_SCHEDULER_POLL_SECONDS` | positive worker interval, default 5 |
| `SRA_BATCH_DB_PATH` | Phase 1A SQLite path |
| `SRA_BATCH_OUTPUT_ROOT` | one shared absolute/resolved publication root |
| existing `SRA_API_BASE`, `SRA_BATCH_SERVICE_KEY`, HTTP timeout/retry variables | consumed only by Phase 1A client construction |

Configuration representations redact keys and connection secrets. API may initialize only the Phase 1C management store when enabled; no Phase 1C worker thread is created.

## 21. Migration and deployment boundary

Phase 1C-A deploys schema v1, store, policy, materialization, and management API with outbound execution disabled by design. Its repository/review gate must PASS before 1C-B begins. Deploy migration using an authorized SQL principal, structurally validate, then deploy API. No outbound Agent/Report Jobs are possible in this gate.

Phase 1C-B first adds the Phase 1A public import seam, then the bridge/worker/manual trigger/Word endpoint. Deploy one worker with the dedicated Phase 1A/Report Job service key and shared Phase 1A DB/output root. Rollback stops worker/API use but preserves both SQL history and Phase 1A state. Schema v1 has no destructive down migration.

## 22. Repository testing

Use TDD with pure recurrence/policy tests, recording fake-ODBC schema/store transaction tests, actual router/RBAC/audit tests, Phase 1A seam and deterministic fingerprint tests, crash-window/restart tests, artifact confinement tests, prohibited-import scans, and Phase 0/1A/1B/full-suite regressions. The authoritative matrix is in Plan v2. Repository fakes prove code contracts only, not live SQL deployment acceptance.

## 23. Real deployment acceptance

From an explicitly authorized environment: initialize/validate `sra_schedule` v1 against the configured Phase 1B schema; create/approve/enable daily and interval schedules; prove one due occurrence under concurrent-style workers; bind a real active snapshot; prove expiry at selection and pre-handoff; hand off through Phase 1A to the real Report Job HTTP API; stop/restart between each crash window; reconcile remote completion and one valid DOCX; verify authenticated Word history and traversal rejection; verify audit and role denial; verify no duplicate run/batch/job. Record database/server identifiers safely, counts, timestamps, and resulting versions without credentials.

Until performed, Phase 1C live acceptance is **NOT EXECUTED**. Phase 1B live SQL acceptance independently remains **NOT EXECUTED**.

## 24. Phase 1C non-goals

No Phase 2 Web UI or Windows GUI; Agent/retrieval/Elasticsearch/Word renderer changes; Report Job engine redesign, cancellation, or automatic failed-job retry; webhooks; Kafka/Celery/RQ/Airflow; arbitrary SQL/options/executable schedules; per-user OpenWebUI propagation; distributed scheduler/HA/multi-worker support; artifact duplication; or unbounded backfill.

## 25. Phase 2 handoff

Phase 2 may consume safe schedule/run/item GETs, invoke authorized mutations, display the explicit status/error taxonomy, and link to authenticated Word history. It must not infer policy checkpoints, edit immutable versions/runs/items, expose local paths, dispatch Report Jobs directly, or move scheduling into browser/API background work.

## 26. Design closure and review flags

Current source is compatible with this contract: Phase 1B exposes active immutable snapshots and expiry; Phase 1A already owns `BatchTaskSpec`, deterministic submit idempotency, HTTP polling, and confined DOCX publication. The required new Phase 1A seam factors its existing insert path rather than bypassing it.

There are **no unresolved design ambiguities or blockers** in v2. Deployment may expose a concrete cross-schema-FK permission policy blocker; per §5 that fails closed and requires an explicit reviewed revision rather than an implementation-time redesign.
