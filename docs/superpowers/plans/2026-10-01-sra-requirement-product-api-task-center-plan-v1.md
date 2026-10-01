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
- `product_state` checked to `active|disabled`,
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
- idempotency uniqueness and hash conflict,
- Product request reservation ID columns have no FK constraints to not-yet-created domain rows and are bounded/validated by the application,
- two distinct service keys with the same display name use distinct idempotency namespaces because ledger `principal_id` is immutable `key_id`,
- no Product table duplicates Requirement snapshots, Schedule Versions/Runs, Handoff, Report Job, or artifact payloads,
- catalog validator requires both new tables/keys/checks/FKs.

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
)

RequirementStore.commit_candidate(
    ...,
    import_run_id: str | None = None,
    snapshot_id: str | None = None,
)

RequirementStore.record_failed_import(
    ...,
    import_run_id: str | None = None,
)
```

Required behavior:

- no supplied IDs → preserve all existing low-level behavior exactly;
- supplied IDs absent → commit using those exact IDs;
- supplied `import_run_id/snapshot_id` already represent the same source/profile/input SHA semantics → return the existing terminal result without importing again or changing the active snapshot;
- supplied identity exists with different semantics → fail closed;
- failed-import recording uses the preallocated `import_run_id` and is same-ID replay safe;
- replay of an old Product input-replacement request after a newer snapshot is active returns the old request's existing result and MUST NOT reactivate that old snapshot.

Add crash-window regression tests simulating:

1. authority commit succeeds,
2. Product progress write is lost,
3. same Product request re-enters the authority with the persisted preallocated IDs,
4. no duplicate import/snapshot/version rows are created and active state is not rolled backward.

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
→ insert requirement_product_tasks using task_id + existing source/schedule FK targets
→ create immutable Schedule Version using schedule_version_id
→ approve Schedule Version
→ once: manual materialize one Run using stable trigger_request_id; recurring Schedule remains disabled
→ recurring: enable Schedule
→ mark durable product request succeeded
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
- failure after any durable step can resume from `requirement_product_requests` using preallocated authority IDs without re-importing, duplicating Schedule Versions, or rolling state backward.
- crash after Phase 1B commit but before Product progress update replays the same `import_run_id/snapshot_id` and returns the existing snapshot.
- crash after Schedule Version commit but before Product progress update replays the same `schedule_version_id` and returns the existing version.

## P1.4 Product create orchestration — recurring

Extend create to:

- create schedule version,
- approve,
- enable recurrence,
- return next-run evidence.

Tests prove recurrence is existing Phase 1C recurrence behavior, not copied product logic.

## P1.5 Prospective task updates — revision CAS + atomic finalization

Implement:

- rename,
- enable/disable,
- recurrence/timezone/model/run-policy changes via new immutable Schedule Version,
- input replacement via new Requirement snapshot.

Every `PATCH /v1/requirement-tasks/{task_id}` mutation uses durable operation `task_update` and requires `Idempotency-Key`.

At request reservation:

1. lock/read the Product Task,
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

Do not remove or repurpose current low-level APIs.

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
- same key/hash + `in_progress` or `failed_recoverable` → resume from durable stage references and preallocated authority IDs (`import_run_id`, `snapshot_id`, `schedule_id`, `task_id`, `schedule_version_id` as applicable),
- same key + changed hash → 409 `requirement_idempotency_conflict`,
- `failed_terminal` → same safe terminal result until a new key is supplied,
- response loss + replay → existing product object/result,
- crash after Requirement import commit but before ledger stage advance → same preallocated import/snapshot identity is recovered without duplicate import,
- crash after Schedule Version commit but before ledger stage advance → same preallocated version identity is recovered without duplicate draft,
- concurrent duplicate → one ledger row and one logical mutation,
- different-key task PATCHes reserved at the same `base_task_revision` → at most one finalizes; stale finalization fails CAS without rolling newer state backward,
- task PATCH finalization commits task/schedule state, audit outbox, revision increment, safe result snapshot, and request success in one Schedule SQL transaction,
- replaying an old input-replacement key after newer input exists must never create another snapshot or roll the active input backward.

Canonical request hashing includes semantic payload plus uploaded source digest, never raw credentials or raw file bytes.

The ledger is not polled by workers and is not a second execution queue.

## P2.4 Product error taxonomy

Stable safe codes at minimum:

- `requirement_input_invalid`
- `requirement_preview_rejected`
- `requirement_source_conflict`
- `requirement_task_conflict`
- `requirement_task_disabled`
- `requirement_version_not_approved`
- `requirement_idempotency_conflict`
- `requirement_run_unavailable`
- `requirement_artifact_not_ready`
- `requirement_dependency_unavailable`

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

- task table/cards,
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
7. Existing lower-level Requirement APIs and Operator E2E remain valid.
8. Existing SRA ES editor, Excel→SQL management, account management, and Report Job regressions are green.
9. Documentation allows an operator to maintain the system without direct SQL/log inspection for normal operations.
