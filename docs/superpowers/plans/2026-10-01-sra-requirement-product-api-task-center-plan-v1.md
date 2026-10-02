# SRA Requirement Product API + Task Center — Implementation Plan v1

**Date:** 2026-10-01  
**Design authority:** `docs/superpowers/specs/2026-10-01-sra-requirement-product-api-task-center-design-v1.md`  
**Status:** Plan draft for review; implementation NOT STARTED  
**Baseline:** hosted `main` at planning start `ff16e3dd64baff367df7791dc2be23add22f626f`.

## 1. Goal

Implement a production-facing Requirement workflow that is usable both from external automation and from the existing SRA management UI.

The implementation must integrate with, not replace:

- existing `/editor` navigation and visual shell,
- existing Auth/RBAC/audit,
- existing service-key store,
- Phase 1B Requirement Import,
- Phase 1C Schedule/manual-run/Handoff,
- existing Report Job execution,
- existing DOCX artifact validation/history.

The final Golden Path is:

```text
external client or SRA UI
→ upload/push own Requirement input
→ preview
→ create product task
→ once or recurring execution
→ Schedule/Handoff
→ Report Job
→ real LLM + real ES
→ run status/history
→ authenticated DOCX
```

## 2. Non-negotiable constraints

1. Do not create a second authentication system.
2. Do not create a second scheduler, queue, Handoff worker, or Report Job worker.
3. Do not allow Product API callers to supply E2E markers, internal owner identities, snapshot/version IDs, Report Job IDs, or local artifact paths.
4. Product tasks never activate Requirement E2E semantic mocks.
5. Browser pages never hold service keys.
6. FastAPI does not own schedule/handoff background worker loops.
7. Existing low-level Requirement APIs remain backward compatible.
8. Existing ES editor and Excel→SQL workflows remain operational.
9. Product mutations that create work must be replay-safe.
10. Product v1 intentionally extends the existing Requirement Schedule schema from v3 to v4 with only the reviewed `requirement_product_tasks` and `requirement_product_requests` control-plane tables; do not add other Product persistence without another design review.
11. Do not silently widen roles. Reuse current `data_reader/data_editor/db_operator/superuser` hierarchy and existing denial-audit mechanism.
12. Implementation follows RED → minimal GREEN → regression → commit at each task boundary.

## 3. Rebaseline before implementation

Before writing production code:

- read `AGENTS.md`,
- read active `.codex/*.md`,
- read Design v1 and this Plan,
- inspect current hosted `main`,
- inspect:
  - `sra_api/main.py`,
  - `sra_api/routers/requirements.py`,
  - `sra_api/routers/requirement_schedules.py`,
  - `sra_api/routers/editor.py`,
  - `sra_api/routers/editor_dependencies.py`,
  - `sra_api/routers/service_keys.py`,
  - `sra_api/static/editor.html`,
  - `sra_api/static/excel_global_nav.*`,
  - current Requirement/Schedule/Handoff/Report Job tests.
- run repository search for any already-existing product/task presenter before adding files.

If current source materially differs from this Plan, STOP and revise Design/Plan rather than improvising a parallel architecture.

## 4. Planned layout

Preferred new production paths, subject to rebaseline:

```text
sra_api/
  routers/
    requirement_tasks.py
  services/
    requirement_product_service.py
  static/
    requirement_task_center.html
    requirement_task_center.js
    requirement_task_center.css

tests/
  test_requirement_product_api.py
  test_requirement_product_service.py
  test_requirement_product_idempotency.py
  test_requirement_product_security.py
  test_requirement_task_center_contract.py

product_e2e/
  test_requirement_product_e2e.py
```

Existing files modified only as required:

```text
requirement_scheduler/migrations.py
requirement_scheduler/store.py
sra_api/main.py
sra_api/routers/editor.py
sra_api/static/editor.html
sra_api/static/editor_*.js/css or shared nav assets
api/security/service_key_store.py
docs/operations/*
.codex/*
```

The only planned persistence change is Schedule schema v3 → v4, adding `requirement_product_tasks` and `requirement_product_requests`. The Phase 1B Requirement schema remains unchanged.

Avoid adding another frontend framework solely for this feature. Follow the current static HTML/JS/CSS architecture unless a separately reviewed UI migration exists.

# Gate P0 — Product boundary and regression lock

## P0.1 Baseline architecture tests

**Files:** create `tests/test_requirement_product_boundaries.py`.

Write failing/static assertions that lock:

- Product API may depend on Requirement Import/Schedule service layers.
- Product API may not import `ReportJobWorker`, `ReportJobStore`, Agent execution modules, Elasticsearch clients, E2E semantic-mock helpers, or worker-loop entry points.
- Browser/static assets do not contain service keys, Handoff credentials, absolute artifact roots, or E2E model prefixes.
- Existing low-level Requirement routes remain registered.

**RED command**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_product_boundaries.py --tb=short
```

Expected RED: new Product API/module is absent.

No production implementation in P0 other than minimal module stubs required for meaningful RED if necessary.

## P0.2 Existing regression baseline

Run and retain actual output for:

```bash
PYTHONPATH=. pytest -q   tests/test_requirement_api.py   tests/test_requirement_schedule_api.py   tests/test_requirement_handoff_*.py   tests/test_report_job*.py   tests/test_editor*.py   tests/test_excel_to_sql*.py   --tb=short
```

If baseline is red before Product implementation, record and resolve/rebaseline separately. Do not bury pre-existing failures in this feature.

# Gate P1 — Product service façade

## P1.0 Schedule schema v4 — Product Task and idempotency metadata

**Files:** modify `requirement_scheduler/migrations.py`, `requirement_scheduler/store.py`, existing migration/store tests; create focused Product persistence tests if clearer.

Design authority is Design v1 §§5.2, 5.3, and 15.

Migrate current Schedule schema v3 → v4 transactionally and fail closed.

Add `requirement_product_tasks` with:

- `task_id` PK,
- unique `schedule_id` FK to `requirement_schedules`,
- unique `source_id` FK to Phase 1B `requirement_sources`,
- immutable `execution_kind` checked to `once|recurring`,
- `product_state` checked to `provisioning|active|disabled`, with new Product Task rows inserted as `provisioning` and ordinary Product operations allowed only after create finalization,
- monotonic `revision` initialized to 1 and incremented exactly once per successfully finalized Product Task PATCH,
- created/updated actor/timestamps.

Add `requirement_product_requests` with:

- principal kind/id; for human users persist the canonical username/account identity, while for service keys persist `AuthPrincipal.credential_id` / immutable stored `key_id` and never the key display name/subject,
- operation,
- idempotency key,
- canonical request SHA-256,
- durable request state,
- nullable safe progress/result references including `task_id`, `source_id`, `import_run_id`, `snapshot_id`, `schedule_id`, `schedule_version_id`, and `batch_run_id`; these reservation columns are deliberately non-FK so IDs can be durably reserved before target rows exist,
- nullable `base_task_revision` and `result_task_revision` for PATCH compare-and-set/finalization,
- nullable `base_snapshot_id` for `input_replace` CAS,
- nullable bounded `safe_result_json` for exact replay of whitelisted Product mutation responses,
- safe error code,
- timestamps,
- unique `(principal_kind, principal_id, operation, idempotency_key)`.

Tests must prove:

- valid v3 migrates once to v4,
- fresh bootstrap reaches v4,
- malformed/unknown schema fails closed,
- product task schedule/source uniqueness,
- invalid execution kind/state rejected,
- a newly inserted Product Task may persist durably as `provisioning` across crash/restart without appearing as an operable Task,
- idempotency uniqueness and hash conflict,
- Product request reservation ID columns have no FK constraints to not-yet-created domain rows and are bounded/validated by the application,
- two distinct service keys with the same display name use distinct idempotency namespaces because ledger `principal_id` is immutable `key_id`,
- no Product table duplicates Requirement snapshots, Schedule Versions/Runs, Handoff, Report Job, or artifact payloads,
- catalog validator requires both new tables/keys/checks/FKs plus indexes on Product-request `schedule_id` and `source_id` used by atomic ownership fencing.

**RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py tests/test_requirement_product_persistence.py --tb=short
```

**GREEN**

Same command after minimal migration/store implementation.

**Commit boundary:** one focused schema/persistence commit. Do not mix router/UI work.


## P1.0A Authority-level caller-supplied identities

The Product ledger alone is not enough if an underlying authority can commit a random durable ID before the ledger knows it. Add backward-compatible optional server-owned identity parameters before Product orchestration.

### Phase 1B Requirement Import

**Files:** `data_ingestion/requirements/store.py`, `data_ingestion/requirements/service.py`, focused Requirement tests.

Extend the successful/failed import authority so Product callers can preallocate:

- `import_run_id`
- `snapshot_id` for the successful commit path.

Planned backward-compatible signatures:

```python
RequirementImportService.commit(
    ...,
    import_run_id: str | None = None,
    snapshot_id: str | None = None,
    expected_base_snapshot_id: str | None = None,
)

RequirementStore.commit_candidate(
    ...,
    import_run_id: str | None = None,
    snapshot_id: str | None = None,
    expected_base_snapshot_id: str | None = None,
)

RequirementStore.record_failed_import(
    ...,
    import_run_id: str | None = None,
)
```

Required behavior:

- no supplied IDs → preserve all existing low-level behavior exactly;
- when supplied Product IDs are present, `RequirementImportService.commit(...)` first invokes `RequirementStore.recover_preallocated_import_result(source_id, import_run_id, snapshot_id)` (or an equivalently narrow read-only helper) **before `_prepare()`**, source acquisition, normalization/classification, stale/anomaly diagnostics, `candidate.has_errors`, `record_failed_import()`, or base-snapshot CAS;
- the recovery lookup validates server-owned identity linkage (`source_id`, `import_run_id`, committed `snapshot_id` when present) and returns the original terminal safe result; Product request `request_sha256` matching already proves the replay belongs to the same semantic mutation;
- supplied IDs absent → commit using those exact IDs;
- supplied identities absent + `expected_base_snapshot_id` provided → under the same `commit_candidate()` SQL transaction and locked `requirement_sets` row, require current `active_snapshot_id == expected_base_snapshot_id` before inserting/activating the replacement snapshot;
- base-snapshot mismatch → fail closed as `requirement_input_conflict` before any Requirement rows/snapshot activation are written;
- supplied identity exists with different semantics → fail closed;
- failed-import recording uses the preallocated `import_run_id` and is same-ID replay safe;
- replay of an old uncommitted Product input-replacement request after a newer snapshot is active fails CAS and MUST NOT import/reactivate its old input.

Add crash-window/delayed-replay regression tests simulating:

1. A authority commit succeeds as snapshot S1,
2. Product progress/HTTP response for A is lost,
3. B later commits newer snapshot S2,
4. only then A re-enters with its persisted preallocated IDs,
5. A returns its original committed S1 result **without entering `_prepare()` or failed-import recording**,
6. no duplicate/failed import rows are created for A and active snapshot remains S2.

### Schedule Version authority

**Files:** `requirement_scheduler/store.py`, Schedule tests.

Extend:

```python
create_version(..., schedule_version_id: str | None = None)
```

Required behavior:

- omitted ID → preserve existing random-ID behavior;
- supplied absent ID → create with that exact ID;
- supplied existing ID + same schedule/config digest → return existing version;
- supplied existing ID + mismatched schedule/config → fail closed;
- replay after authority commit but before Product progress update creates no second draft/version.

`create_schedule(..., schedule_id=...)` already supports caller-supplied identity; Product orchestration must use it rather than generating a Schedule ID inside the store.

### Manual Run authority

Do not add Product-specific `batch_run_id` injection. Current manual materialization already uses unique `(schedule_id, trigger_request_id)` identity and returns an existing Run on replay. Product Run trigger derives a stable `trigger_request_id` from the durable Product request.


For task-owned Requirement source, logical Schedule, and `requirement_product_tasks` creation, use an ensure-by-preallocated-ID pattern:

1. ledger already contains the server-owned ID,
2. read by that ID,
3. absent → create with the exact ID,
4. present + matching immutable ownership/config → treat as completed,
5. present + mismatch → fail closed.

This explicitly covers crashes after source/Schedule/Product-Task commit but before the Product request stage is advanced.

**RED**

```bash
PYTHONPATH=. pytest -q   tests/test_requirement_import*.py   tests/test_requirement_schedule*.py   tests/test_requirement_product_idempotency.py   --tb=short
```

**Commit boundary:** authority compatibility/idempotency changes are reviewed before Product service orchestration.


### Product Task mutable-state finalization regression

Because `requirement_product_requests` and Product/Schedule state are in the same Schedule database, mutable Task PATCH completion uses one SQL transaction rather than a post-commit ledger write.

Add focused tests around the new finalizer:

- rename-only lost-response replay,
- recurring enable/disable lost-response replay,
- combined rename + schedule-version change,
- old unfinished request vs newer successful request,
- same-key concurrent retry,
- different-key same-base-revision race,
- audit outbox atomicity,
- stored safe-result replay after subsequent Task revisions.

Do not weaken or change the behavior of existing low-level `rename_schedule()` / `set_enabled()`; Product routes use the new atomic finalizer.


## P1.1 Product presenters and identities

**Files:** create `sra_api/services/requirement_product_service.py`, `tests/test_requirement_product_service.py`.

Implement pure presenters first:

- `task_id` loaded from `requirement_product_tasks`, with authoritative persisted `execution_kind`, `product_state`, task-owned `source_id`, and linked `schedule_id`.
- product task view,
- product run view,
- neutral run status mapping,
- safe link/ID presentation.

Tests prove:

- no backend-native Report Job state leaks,
- no absolute paths,
- no E2E marker,
- no credentials,
- immutable snapshot/version binding appears in Run detail.

**RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_product_service.py -k 'present or status or identity' --tb=short
```

**GREEN**

Same command.

## P1.2 Product preview orchestration

**Files:** product service + `tests/test_requirement_product_service.py`.

Implement a side-effect-free preview method that delegates to existing Requirement Import parsing/profile authority.

Inputs:

- uploaded bytes + filename, or
- direct Requirement JSON,
- selected approved import profile.

Output:

- source SHA,
- accepted/rejected counts,
- normalized preview,
- row errors/warnings,
- profile/version identity.

Tests prove no source/snapshot/schedule/run mutation.

## P1.3 Product create orchestration — one-time

Implement one durable-saga Product Task provisioning flow over existing authorities.

**Authority:** brand-new Product Task provisioning is `superuser` only in v1 because it creates and enables a new Phase 1B Requirement source. Do not let `db_operator` or a service key bypass current source-enable authority.

```text
validate superuser + reserve idempotency ledger
→ preview input
→ preallocate + persist source_id
→ preallocate + persist import_run_id + snapshot_id
→ preallocate + persist schedule_id
→ preallocate + persist task_id
→ preallocate + persist initial schedule_version_id
→ create task-owned manual_upload source disabled using source_id
→ enable source under existing superuser authority
→ commit Requirement import using import_run_id + snapshot_id
→ create linked logical Schedule using schedule_id
→ insert requirement_product_tasks using task_id + existing source/schedule FK targets with product_state=provisioning
→ create immutable Schedule Version using schedule_version_id
→ approve Schedule Version while Schedule remains recurrence-disabled
→ atomically finalize provisioning in one Schedule SQL transaction:
   once: materialize the initial Run through the existing locked materialization helper with stable trigger_request_id
   recurring: enable the approved Schedule and persist next_run_at
   then set product_state=active, persist bounded create safe_result_json, mark task_create succeeded
→ return task/run presenter
```

The Product Task row persists `execution_kind`; one-time vs recurring must never be inferred from Schedule `enabled`.

Tests:

- lower roles cannot provision/enable the new source,
- superuser provisioning uses the same or stricter source activation rule as the low-level Requirement API,
- exact task/source/schedule/snapshot binding,
- `execution_kind=once` remains distinguishable from a disabled recurring task,
- manual Run uses server-selected active version/snapshot,
- no direct Report Job call,
- no duplicate work after ambiguous/replayed create,
- failure after any durable step can resume from `requirement_product_requests` using preallocated authority IDs without re-importing, duplicating Schedule Versions, or rolling state backward,
- crash immediately after Product Task row insertion leaves `product_state=provisioning`; ordinary Task list/get/mutation/service-key surfaces cannot expose or operate it,
- while a create saga is paused after Task insertion, concurrent PATCH/input-replace/run-trigger requests cannot reserve competing Product mutation requests for that Task,
- before create finalization commits, recurring Schedule remains disabled and one-time initial Run is not materialized, so scheduler/Handoff workers cannot execute a hidden provisioning Task,
- resuming the same owning `task_create` completes the original version/approval and atomically releases exactly one initial execution path (manual Run for once, enabled recurrence for recurring) together with Task `active` and create request `succeeded`,
- if the finalization transaction rolls back, `product_state=provisioning`, recurrence remains disabled/no initial Run exists, and the create request is non-succeeded; no half-visible or worker-executable Task is produced,
- lost response after successful finalization replays the stored create result without re-running initialization,
- crash after Phase 1B commit but before Product progress update replays the same `import_run_id/snapshot_id` and returns the existing snapshot,
- crash after Schedule Version commit but before Product progress update replays the same `schedule_version_id` and returns the existing version.

## P1.4 Product create orchestration — recurring

Extend create to:

- create schedule version,
- approve it while keeping the Schedule disabled,
- move recurrence enablement and `next_run_at` calculation **inside the Product-create finalization transaction**,
- transition to `active`, store bounded create result, and mark the owning `task_create` request succeeded in that same transaction,
- return next-run evidence only after commit.

Tests prove recurrence is existing Phase 1C recurrence behavior, not copied product logic, and a paused recurring provisioning task cannot be selected by the scheduler worker, patched, input-replaced, manually triggered, or delegated through a service key before finalization.

## P1.4A Provisioning lifecycle gate and create finalizer

**Files:** Product persistence/service methods, Task presenters/queries, Product route tests.

Add a Product-create finalizer, preferred shape subject to rebaseline:

```python
finalize_product_task_create(
    *,
    request_id: str,
    task_id: str,
    actor: str,
    now_utc: datetime,
) -> ProductTaskCreateResult
```

In one Schedule SQL transaction it must:

1. lock the owning `task_create` request and `requirement_product_tasks` row,
2. require `product_state='provisioning'` unless the same request is already `succeeded`,
3. verify the Task/source/Schedule binding matches the IDs reserved by that request,
4. verify the initial Schedule Version exists and is approved/active while the Schedule is still disabled for recurrence,
5. for `once`, call the existing locked materialization helper inside this transaction with the stable request-derived trigger identity, yielding exactly one initial Run; for `recurring`, enable the approved Schedule and calculate/persist `next_run_at` inside this transaction,
6. transition `product_state` to `active`,
7. persist bounded create `safe_result_json` including the initial Run identity or recurring next-run evidence,
8. mark that same `task_create` request `succeeded`,
9. commit execution release + final visibility/operability state atomically.

Ordinary Task visibility/operations use a shared lifecycle predicate:

- list queries include only `active|disabled`,
- direct Product Task GET treats `provisioning` as unavailable/not-found and exposes no partial identities,
- PATCH, input replacement, and Run trigger check lifecycle **before reserving a new Product request** and return `requirement_task_provisioning`,
- service-key task/read/write/run surfaces cannot address provisioning Tasks,
- the only continuation authority for a provisioning Task is the same owning `task_create` request replay/resume.

Required concurrent regression:

```text
A task_create inserts Product Task as provisioning
→ initial Schedule Version is approved but Schedule remains disabled and no one-time initial Run exists
→ barrier/pause immediately before create finalizer while scheduler/Handoff workers are running
→ workers materialize/execute nothing for A
→ B attempts Task GET/PATCH/input-replace/run-trigger/service-key access and Product Run/history/artifact GETs
→ B cannot observe/operate/reserve mutation work or discover partial Run state
→ A resumes same create request
→ finalizer atomically materializes exactly one once-Run OR enables recurrence + next_run_at, then sets active + task_create succeeded
→ Task/Run become visible/operable only after commit
```

Also test crash/lost-response immediately before and immediately after finalization.

## P1.5 Prospective task updates — revision CAS + atomic finalization

Implement:

- rename,
- enable/disable,
- recurrence/timezone/model/run-policy changes via new immutable Schedule Version,
- input replacement via new Requirement snapshot.

Every `PATCH /v1/requirement-tasks/{task_id}` mutation uses durable operation `task_update` and requires `Idempotency-Key`.

At request reservation:

1. lock/read the Product Task and require `product_state != 'provisioning'`; otherwise return `requirement_task_provisioning` without reserving `task_update`,
2. persist current `revision` as `base_task_revision`,
3. preallocate/persist `schedule_version_id` when the patch changes recurrence/timezone/model/run-policy.

For schedule-changing PATCH, create/recover the request-owned draft through `create_version(..., schedule_version_id=...)`.

Add a Product-specific Schedule-store finalizer, preferred shape subject to implementation rebaseline:

```python
finalize_product_task_update(
    *,
    request_id: str,
    task_id: str,
    actor: str,
    patch: ProductTaskPatch,
    now_utc: datetime,
) -> ProductTaskUpdateResult
```

This method runs in **one Schedule SQL transaction** and MUST:

- lock the Product request, Product Task, linked Schedule, and request-owned draft version if present,
- if request already succeeded, return stored bounded `safe_result_json`,
- compare current Task `revision` with ledger `base_task_revision`,
- on mismatch: do not apply requested rename/state/version activation; mark the request `failed_terminal` with `requirement_task_conflict`; retire/abandon only this request's still-draft version when safe,
- on match: apply requested rename/product-state/recurring-enabled changes; validate/activate the request-owned version when applicable; update Schedule `next_run_at` using existing recurrence rules; enqueue the same authoritative Schedule audit-outbox events plus Product audit metadata; increment Task `revision` once,
- persist `result_task_revision` and bounded whitelisted `safe_result_json`,
- set Product request `succeeded`,
- commit all mutations and the ledger success marker atomically.

The Product path must not implement rename/state replay by sequentially calling current `rename_schedule()` or `set_enabled()` and then updating the ledger.

Tests prove:

- historical Runs retain old bindings,
- same PATCH key/hash after lost HTTP response returns the stored original Product result and performs no second mutation,
- same PATCH key with changed canonical request returns 409,
- retry after response loss creates at most one new Schedule Version,
- crash after `create_version()` commit but before finalization reuses the persisted preallocated `schedule_version_id`,
- crash/rollback inside finalization leaves both Task state and request success unapplied,
- successful finalization commits Task/Schedule mutation + audit outbox + `revision+1` + request success together,
- two concurrent/different-key PATCH requests reserved from the same base revision cannot both succeed,
- if a newer different-key PATCH succeeds before an older unfinished request resumes, the old request fails CAS and cannot roll back name/enabled/model/recurrence state,
- a succeeded old request replay after later updates returns its stored `safe_result_json` rather than reapplying old values.


## P1.6 Atomic Product ownership mutation fences

**Files:** `requirement_scheduler/store.py`, `data_ingestion/requirements/store.py`, `sra_api/routers/requirement_schedules.py`, `sra_api/routers/requirements.py`, schema-v4/index validation, focused concurrency tests.

A router/service pre-check is insufficient. The Product ownership/reservation check and each low-level write must share one SQL transaction.

### Reservation authority

Initial Product provisioning already preallocates/persists `source_id` and `schedule_id` before creating either target resource. Treat the `task_create` Product request as a reserved ownership claim during the provisioning gap. Once `requirement_product_tasks` exists, that row is the steady-state ownership authority.

Add catalog-validated indexes over `requirement_product_requests.schedule_id` and `source_id` so guarded transactional lookups are bounded.

Product v1 does not adopt pre-existing low-level Requirement sources or Schedules; every Product Task owns newly allocated identities. Therefore an existing target resource created by Product always has a reservation row that predates its creation.

### Guarded Schedule writes

Refactor public low-level mutations to use explicit guarded store methods/private locked helpers. Inside the same Schedule-store connection/transaction that will mutate the row/version/run:

1. lock/read `requirement_product_tasks` for exact `schedule_id`,
2. lock/read Product `task_create` reservation rows for exact `schedule_id`,
3. if either exists, raise `requirement_product_owned_schedule` before mutation,
4. otherwise continue the existing low-level mutation under the same transaction and locks.

Apply this to:

- rename,
- enable/disable,
- version create,
- version approve,
- manual run materialization.

Public routers call only the guarded methods. Product internal orchestration/finalizer uses separate reviewed internal helpers; there is no public bypass flag.

### Guarded Requirement-source writes

Extend `RequirementStore` with the configured Schedule schema name when Product v1 is enabled; both stores already use the same `REQUIREMENT_CONTROL_DB_CONNECTION`.

Inside the same Requirement-store transaction that will PATCH source metadata or import/advance the snapshot:

1. lock/read `requirement_product_tasks` for exact `source_id`,
2. lock/read Product `task_create` reservation rows for exact `source_id`,
3. if either exists, raise `requirement_product_owned_source`,
4. otherwise perform the existing low-level mutation in that same transaction.

Low-level source GET/list/preview remain unchanged.

### Required TOCTOU/concurrency regressions

Tests must use two connections/barriers, not only sequential mocks:

- low-level Schedule mutation starts while Product provisioning is between reservation and Product Task insert → mutation sees reservation and rejects,
- provisioning reserves/creates Schedule while a competing low-level mutation is blocked → at most one authority path can proceed; low-level write cannot commit after Product claim,
- equivalent Product-owned Requirement-source PATCH/import race,
- steady-state Product Task row fences low-level writes even with no in-progress Product request,
- non-Product resources still mutate under existing RBAC,
- Product internal orchestration remains able to use the internal helpers.

## P1.7 Input replacement base-snapshot CAS

**Files:** Product service/request-store methods, `data_ingestion/requirements/service.py`, `data_ingestion/requirements/store.py`, focused idempotency/concurrency tests.

At first reservation of `operation=input_replace`:

1. resolve the Product Task/source and require `product_state != 'provisioning'`; otherwise return `requirement_task_provisioning` without reserving a replacement request,
2. resolve the current Requirement set,
3. read the current active snapshot,
4. persist it as `base_snapshot_id` together with preallocated `import_run_id` and replacement `snapshot_id`.

On first import attempt call:

```python
RequirementImportService.commit(
    ...,
    import_run_id=reserved_import_run_id,
    snapshot_id=reserved_snapshot_id,
    expected_base_snapshot_id=base_snapshot_id,
)
```

`RequirementImportService.commit()` must perform same-ID terminal recovery **before calling `_prepare()`**. Only when `recover_preallocated_import_result(...)` reports that the reserved import/snapshot does not yet exist may the service call `_prepare()` and then `commit_candidate()`; only that first-commit path locks the Requirement set and compares current active snapshot with `expected_base_snapshot_id`.

Tests:

- A reserves from snapshot S0 and crashes before import; B reserves from S0 and commits S1; A resumes → `requirement_input_conflict`, no A snapshot is created/activated,
- **delayed committed replay:** A reserves from S0 and commits S1; B then reserves from S1 and commits S2; only then A is replayed → A's original S1 success is returned before `_prepare()`, no stale/anomaly diagnostic or failed import is recorded for A, and active snapshot remains S2,
- instrument/mock `_prepare()` so the delayed committed replay test fails if it is called at all,
- A/B reserve concurrently from S0 → at most one advances S0,
- stale replacement conflict leaves the newer active snapshot untouched,
- replaying the stale uncommitted key remains terminal and never allocates fresh import/snapshot IDs.

# Gate P2 — Product API


## P2.1 Router and schemas

**Files:** create `sra_api/routers/requirement_tasks.py`, `tests/test_requirement_product_api.py`; register router in `sra_api/main.py`.

Routes:

```text
POST /v1/requirement-task-previews
POST /v1/requirement-tasks
GET  /v1/requirement-tasks
GET  /v1/requirement-tasks/{task_id}
PATCH /v1/requirement-tasks/{task_id}
POST /v1/requirement-tasks/{task_id}/input
POST /v1/requirement-tasks/{task_id}/runs
GET  /v1/requirement-runs
GET  /v1/requirement-runs/{run_id}
GET  /v1/requirement-runs/{run_id}/items
GET  /v1/requirement-runs/{run_id}/artifacts
GET  /v1/requirement-runs/{run_id}/items/{run_item_id}/word
```

Do not remove current low-level APIs. Their intentional Product-ownership behavior is: reads remain available; mutation routes reject Product-owned Schedule/source identities with stable 409 codes, while non-Product resources retain existing behavior.

Product Task and Product Run/artifact presenters/routes must share the provisioning lifecycle predicate. Ordinary Task list/get omit provisioning rows; PATCH/input/run reject `requirement_task_provisioning` before creating any new durable mutation request. `GET /v1/requirement-runs` excludes Runs whose owning Product Task is provisioning, and direct run/items/artifact/Word lookups for such owners return the same safe unavailable/not-found behavior.

## P2.2 Multipart and direct JSON input

Tests cover:

- valid XLSX,
- valid CSV,
- valid JSON,
- direct Requirement JSON,
- mutually exclusive file/direct modes,
- empty upload,
- oversized upload,
- unsupported media/extension,
- malformed rows,
- expected SHA mismatch,
- filename treated as metadata only.

Product router delegates parsing to Phase 1B.

## P2.3 Durable idempotency and saga resume

**Files:** add `tests/test_requirement_product_idempotency.py`; use the reviewed `requirement_product_requests` v4 table from P1.0.

For task create, every task PATCH/update, input replacement, and Run trigger:

- missing `Idempotency-Key` → safe validation failure,
- first request reserves principal + operation + key + canonical request SHA and all required server-owned durable IDs before the corresponding Phase 1B/1C mutation,
- for service-key principals, the ledger uses `AuthPrincipal.credential_id` / immutable `key_id`; duplicate service-key display names must never share replay state,
- same key/hash + `succeeded` → return stored bounded `safe_result_json` for mutable PATCH results or reconstruct immutable/create results from authoritative IDs,
- same key/hash + `in_progress` or `failed_recoverable` → resume from durable stage references, preallocated authority IDs (`import_run_id`, `snapshot_id`, `schedule_id`, `task_id`, `schedule_version_id` as applicable), and the persisted `base_snapshot_id` / `base_task_revision` CAS anchors,
- same key + changed hash → 409 `requirement_idempotency_conflict`,
- `failed_terminal` → same safe terminal result until a new key is supplied,
- response loss + replay → existing product object/result,
- crash after Requirement import commit but before ledger stage advance → same preallocated import/snapshot identity is recovered without duplicate import,
- crash after Schedule Version commit but before ledger stage advance → same preallocated version identity is recovered without duplicate draft,
- concurrent duplicate → one ledger row and one logical mutation,
- different-key task PATCHes reserved at the same `base_task_revision` → at most one finalizes; stale finalization fails CAS without rolling newer state backward,
- task PATCH finalization commits task/schedule state, audit outbox, revision increment, safe result snapshot, and request success in one Schedule SQL transaction,
- old uncommitted input replacement after newer input exists must fail `base_snapshot_id` CAS without creating/activating its stale snapshot; already-committed same-ID replay must be recovered before `_prepare()`/diagnostics even if a later replacement has already committed.

Canonical request hashing includes semantic payload plus uploaded source digest, never raw credentials or raw file bytes.

The ledger is not polled by workers and is not a second execution queue.

## P2.4 Product error taxonomy

Stable safe codes at minimum:

- `requirement_input_invalid`
- `requirement_preview_rejected`
- `requirement_source_conflict`
- `requirement_input_conflict`
- `requirement_task_conflict`
- `requirement_task_disabled`
- `requirement_task_provisioning`
- `requirement_version_not_approved`
- `requirement_idempotency_conflict`
- `requirement_run_unavailable`
- `requirement_artifact_not_ready`
- `requirement_dependency_unavailable`
- `requirement_product_owned_schedule`
- `requirement_product_owned_source`

No raw ODBC/HTTP/LLM/Python exception text in Product API responses.

# Gate P3 — Auth, service keys, and audit

## P3.1 Human RBAC

**Files:** Product router/service tests.

Use existing dependencies and `authorize_role`.

Acceptance matrix:

| Capability | data_reader | data_editor | db_operator | superuser |
|---|---:|---:|---:|---:|
| list/view tasks/runs | yes | yes | yes | yes |
| download allowed completed artifact | yes | yes | yes | yes |
| preview input | no | no by default | yes | yes |
| provision new Product Task/source | no | no | **no** | **yes** |
| replace input on already active task/source | no | no | yes | yes |
| create prospective draft schedule version | no | no | yes | yes |
| approve/activate schedule version | no | no | no | yes |
| enable/disable recurring task | no | no | no | yes |
| trigger permitted Run on active task | no | no | yes | yes |
| service-key management | no | no | no | yes |

This deliberately preserves current Phase 1B source activation: a new source cannot be enabled/committed by `db_operator`. Product orchestration must not call the store as a lower-privilege principal to evade that rule.

Denied actions must use existing authz audit.

## P3.2 Service-key scopes

Rebaseline `api.security.service_key_store` and current request-auth support.

Add only through the existing scope validation mechanism:

- `requirement:task:read`
- `requirement:task:write` — update/replace input on an already activated pre-provisioned task only
- `requirement:run:trigger`
- `requirement:artifact:read`

There is no service-key task-provisioning/source-activation scope in v1. A superuser must first provision and activate the Product Task. This keeps delegated automation separate from source activation authority.

Tests prove:

- service key cannot impersonate a human user,
- wrong scope denied,
- revoked/expired key denied,
- Handoff worker key not accepted merely because it is a service credential,
- browser session never receives raw service key values,
- two active service keys may share the same human-readable name without sharing Product idempotency/replay state because their immutable `key_id` values differ,
- Product request persistence maps a service principal to `AuthPrincipal.credential_id`, not `principal_id`/subject/name.
- service-key read/write/run scopes cannot discover or operate a Task while `product_state='provisioning'`; access begins only after create finalization.

If current service-key authentication is limited to Report Jobs and cannot safely protect Product routes, add a reviewed shared dependency rather than duplicate key parsing.

## P3.3 Audit

Use current `append_audit_event`.

Add safe Product events specified by Design v1.

Tests prove no upload contents, prompt text, raw errors, credentials, SQL registry, or absolute paths enter audit.

# Gate P4 — Integrated Requirement Task Center UI

## P4.1 Navigation integration

**Files:** `sra_api/static/editor.html` and shared navigation assets/tests.

Under existing **匯入管理**, retain current Excel→SQL section and add:

```text
要項與自動化任務
├─ 要項任務中心
├─ 建立要項任務
├─ 執行紀錄
└─ 要項來源與版本
```

Requirements:

- no second login,
- same logout/whoami,
- same role-aware visibility,
- no duplicate top-level site,
- links work from existing Excel→SQL pages/global nav where shared nav is present.

## P4.2 Task Center page

**Files:** create static Task Center HTML/JS/CSS plus route/static registration following current editor conventions.

UI features:

- task table/cards sourced only from finalized `active|disabled` Product Tasks; provisioning rows are not rendered,
- filter by name/status/type/enabled/owner/time,
- last/next run,
- success/failure counts,
- run-now button,
- authorized enable/disable,
- detail navigation.

No direct SQL/log dependency in browser.

## P4.3 Create Task wizard

Implement four-step flow:

1. Input,
2. Preview,
3. Execution,
4. Review/create.

The browser must call Product API only for the normal product workflow. It must not manually reproduce all low-level source/schedule orchestration in JavaScript.

## P4.4 Task detail

Tabs:

- 摘要
- 要項
- 排程與版本
- 執行紀錄
- 稽核

Read-only historical snapshots/versions; only prospective updates.

## P4.5 Run detail

Show neutral lifecycle, Run Items, safe error category, elapsed time, artifact readiness, Word download.

Run detail/history/artifact views are available only for Runs whose owning Product Task is finalized (`active|disabled`). Provisioning-owned Runs are omitted/rejected by the Product API and therefore cannot appear in the UI.

Do not display Report Job owner internals, local paths, raw tracebacks, or E2E capability data.

## P4.6 UI contract tests

Create `tests/test_requirement_task_center_contract.py`.

Static/route tests cover:

- page route/auth shell,
- nav entries,
- role visibility,
- no service-key literals,
- no `requirement-e2e:`,
- no direct `/v1/report/jobs` call in Task Center JavaScript,
- Product API endpoint usage,
- XSS-safe text rendering pattern for uploaded/user-provided names and errors.

# Gate P5 — Operations and maintainability

## P5.1 Task/run operational queries

Product API/UI must support answering:

- enabled tasks,
- next run,
- current running/queued,
- failures by safe category,
- historical input snapshot/version,
- artifact availability.

Add pagination/filter tests before implementation.

## P5.2 Bounded health presenter

If Task Center needs worker health, create a separate ordinary operational-health presenter.

It may expose only bounded states such as:

- schedule worker healthy/unavailable,
- handoff worker healthy/unavailable,
- last observed heartbeat/time if already available through safe state.

Do not expose the superuser Operator E2E runtime-evidence schema to normal Task Center users.

## P5.3 Operations documentation

Create/update:

- `docs/operations/requirement-task-center.md`
- Product API examples,
- service-key scope examples without secrets,
- one-time and recurring task lifecycle,
- troubleshooting safe error taxonomy,
- worker supervision references,
- backup/restore implications,
- rollback procedure.

# Gate P6 — Product API E2E

## P6.1 Separate Product E2E harness

**Files:** create `product_e2e/test_requirement_product_e2e.py` and support files.

This is separate from `operator_e2e/test_requirement_schedule_e2e.py`.

Hard requirements:

- generate input at runtime,
- unique marker per invocation,
- no committed fixture dependency,
- no E2E model prefix,
- no semantic mock mode,
- use real Product auth: a superuser acceptance principal provisions the new Product Task, then a scoped service key may exercise the delegated automation path on that active task,
- real LLM and real ES execution,
- retrieve artifact through Product API.

## P6.2 Product E2E flow

The acceptance flow is intentionally split so it proves both human provisioning and delegated automation without weakening RBAC.

```text
SUPERUSER PROVISIONING
generate runtime provisioning XLSX/JSON
→ Product Preview
→ Product Create one-time task/source
→ receive active task_id

SCOPED SERVICE-KEY AUTOMATION
generate second runtime XLSX/JSON with distinct automation marker
→ replace input on existing task with Idempotency-Key
→ receive/verify replacement snapshot
→ trigger Run with Idempotency-Key
→ receive run_id
→ verify Run binds replacement snapshot
→ read task/run/items through Product API
→ wait real Schedule/Handoff/Report Job execution
→ completed
→ download DOCX through artifact scope
→ validate ZIP/DOCX + digest
→ verify automation input identity/evidence
```

The harness must fail if:

- it discovers the committed Operator E2E fixture is the execution source,
- a service key can provision/enable a new Requirement source or brand-new Product Task,
- the service-key automation phase cannot operate on the superuser-provisioned active task.

## P6.3 Product E2E evidence

Evidence document records:

- generated input digest,
- task/run/snapshot IDs,
- effective production mode,
- Run Item terminal states,
- artifact digest,
- source attestation where applicable,
- no secrets/input contents beyond bounded marker metadata.

Do not claim formal deployment acceptance merely because Product E2E passes; define its relation to release acceptance explicitly in operations docs.

# Gate P7 — Browser E2E

After Product API E2E is green and reviewed:

- login through existing UI,
- navigate via 匯入管理,
- create runtime input,
- preview,
- create one-time task,
- observe run,
- download DOCX.

Use browser automation available in the repository/tooling at implementation time.

Browser E2E must assert:

- shared auth state,
- correct role restrictions,
- integrated navigation,
- validation rendering,
- task/run status rendering,
- no console errors,
- artifact download.

Browser E2E does not replace API/service tests.

# Gate P8 — Full regression, security, docs, and memory

Run:

```bash
PYTHONPATH=. pytest -q   tests/test_requirement_product_*.py   tests/test_requirement_task_center_contract.py   tests/test_requirement_*.py   tests/test_requirement_schedule_*.py   tests/test_requirement_handoff_*.py   tests/test_report_job*.py   tests/test_editor*.py   tests/test_excel_to_sql*.py   --tb=short
```

Then the repository's normal full suite and compile/static checks.

Explicitly include cross-API ownership-fence regression coverage for `requirements.py` and `requirement_schedules.py`: use concurrent connections/barriers to prove reservation/ownership checks are atomic with low-level writes, Product-owned low-level writes reject, Product-owned reads pass, and non-Product low-level behavior remains unchanged. Also include stale-uncommitted input-replacement base-snapshot CAS races.
Include a provisioning-release concurrency regression with scheduler/Handoff workers active: pause after initial version approval but before create finalization; assert recurring Schedule remains disabled, no one-time initial Run exists, no worker execution occurs, Task and Product Run/history/artifact GETs cannot expose partial state, and PATCH/input/run/service-key surfaces cannot reserve work. Resume the same create request and prove the finalizer atomically releases exactly one execution path plus Task visibility/create success.

Update:

- `.codex/api_contract.md`
- `.codex/architecture.md`
- `.codex/decisions.md`
- `.codex/memory.md`
- `.codex/backlog.md`
- `.codex/known_issues.md` only for real remaining limitations.

## 5. Merge gates

Implementation should be split into reviewable PRs rather than one large UI/API PR.

Recommended sequence:

1. **PR A — Product service/presenters + Product API read/preview**
2. **PR B — create/update/trigger + idempotency + service-key scopes**
3. **PR C — integrated Task Center navigation/UI**
4. **PR D — Product API E2E**
5. **PR E — Browser E2E + operations closure**

Every PR:

- starts from current hosted `main`,
- has focused regression tests,
- receives exact-head Codex review,
- resolves all findings,
- does not merge until explicitly authorized.

## 6. Acceptance matrix

| Requirement | Gate |
|---|---|
| integrated existing SRA auth/nav | P3/P4 |
| Excel/CSV/JSON upload preview | P1/P2 |
| direct Requirement JSON | P1/P2 |
| one-time task | P1/P2 |
| recurring task | P1/P2 |
| immutable snapshots/versions | P1 |
| task/run histories | P1/P2/P4 |
| service-key automation | P3 |
| audit | P3 |
| run-now/idempotency | P1/P2 |
| artifact download | P2/P4 |
| operational maintenance views | P4/P5 |
| real external-input API E2E | P6 |
| integrated browser E2E | P7 |
| no E2E mock leakage | P0/P6/P8 |
| existing ES/Excel→SQL/Auth regressions preserved | P8 |
| Product-owned low-level mutation fence + non-Product compatibility | P1/P2/P8 |
| provisioning Task and Run/history/artifact state hidden/inoperable until atomic execution release + create finalization | P1/P2/P3/P8 |

## 7. Explicit future work

Do not silently include in v1:

- webhook callbacks,
- generic workflow builder,
- cancel-running execution,
- arbitrary retry policy editor,
- HA/distributed queue redesign,
- object storage migration,
- JT-1/LangGraph redesign,
- MFA/SSO redesign.

These require separate design review after Product v1 establishes a stable contract.

## 8. Completion definition

The phase is complete only when:

1. Product API supports preview/create/read/update/trigger/history/artifact flows.
2. Product API uses existing Requirement Import + Schedule/Handoff authorities.
3. Requirement Task Center is integrated in current SRA management navigation and auth.
4. External service-key automation is least-privilege and audited: it operates on a superuser-provisioned active task for input replacement, trigger, read, and artifact access, and cannot provision/activate a new source/task.
5. Runtime-generated Product E2E passes against real production dependencies.
6. Browser E2E passes the integrated UI flow.
7. Existing lower-level Requirement/Schedule APIs and Operator E2E remain valid, with Product-owned resources read-only through low-level HTTP mutation surfaces and non-Product resources retaining their prior mutation behavior.
8. A partially provisioned Product Task is neither visible nor worker-executable: recurrence stays disabled and no one-time initial Run is materialized until the atomic create finalizer releases execution, marks the Task active/create succeeded, and only then exposes Task/Run/history/artifact surfaces.
8. Existing SRA ES editor, Excel→SQL management, account management, and Report Job regressions are green.
9. Documentation allows an operator to maintain the system without direct SQL/log inspection for normal operations.
