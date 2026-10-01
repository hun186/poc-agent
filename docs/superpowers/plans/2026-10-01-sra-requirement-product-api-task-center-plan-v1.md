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
10. Do not add new persistent Product Task schema unless current Schedule identity is proven insufficient and Design v1 is revised before implementation.
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
sra_api/main.py
sra_api/routers/editor.py
sra_api/static/editor.html
sra_api/static/editor_*.js/css or shared nav assets
api/security/service_key_store.py
docs/operations/*
.codex/*
```

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

## P1.1 Product presenters and identities

**Files:** create `sra_api/services/requirement_product_service.py`, `tests/test_requirement_product_service.py`.

Implement pure presenters first:

- `task_id` backed by existing logical Schedule identity.
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

Implement one transactionally/replay-safe product flow over existing authorities:

```text
validate request
→ import Requirement snapshot
→ create logical schedule/task
→ create immutable schedule version
→ approve under authorized product policy
→ manual materialize one Run
→ return task/run presenter
```

Do not enable recurrence for a one-time task.

Tests:

- exact snapshot binding,
- manual Run uses server-selected active version/snapshot,
- no direct Report Job call,
- no duplicate work after ambiguous/replayed create,
- failure before Run leaves recoverable deterministic state.

## P1.4 Product create orchestration — recurring

Extend create to:

- create schedule version,
- approve,
- enable recurrence,
- return next-run evidence.

Tests prove recurrence is existing Phase 1C recurrence behavior, not copied product logic.

## P1.5 Prospective task updates

Implement:

- rename,
- enable/disable,
- recurrence/timezone/model/run-policy changes via new immutable Schedule Version,
- input replacement via new Requirement snapshot.

Tests prove historical Runs retain old bindings.

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

## P2.3 Idempotency

**Files:** add `tests/test_requirement_product_idempotency.py`.

For create, input replacement, and trigger:

- missing required idempotency identity for automation mutation → 400/422 according to established API convention,
- same key + same canonical request → same result,
- same key + changed request → 409,
- response loss + replay → existing product object,
- concurrent duplicate → one durable logical mutation.

Prefer existing durable identities/storage. If a new idempotency table is required, STOP and return to design review with source evidence before migration.

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
| preview input | no/default | yes or reviewed policy | yes | yes |
| create/import task | no | no/default | yes | yes |
| create draft schedule changes | no | no | yes | yes |
| approve/enable recurring | no | no | no | yes |
| disable recurring task | no | no | reviewed existing policy | yes |
| service-key management | no | no | no | yes |

If current lower-level policy differs, preserve stricter authority and update this matrix during review.

Denied actions must use existing authz audit.

## P3.2 Service-key scopes

Rebaseline `api.security.service_key_store` and current request-auth support.

Add only through the existing scope validation mechanism:

- `requirement:task:read`
- `requirement:task:write`
- `requirement:run:trigger`
- `requirement:artifact:read`

Tests prove:

- service key cannot impersonate a human user,
- wrong scope denied,
- revoked/expired key denied,
- Handoff worker key not accepted merely because it is a service credential,
- browser session never receives raw service key values.

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
- use Product API/service-key or real product auth,
- real LLM and real ES execution,
- retrieve artifact through Product API.

## P6.2 Product E2E flow

```text
generate runtime XLSX/JSON
→ Product Preview
→ Product Create once-task
→ receive task_id/run_id
→ verify new snapshot binding
→ wait run
→ inspect Run Items
→ completed
→ download DOCX
→ validate ZIP/DOCX + digest
→ verify unique input identity/evidence
```

The harness must fail if it discovers the committed Operator E2E fixture is the execution source.

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
4. External service-key automation is least-privilege and audited.
5. Runtime-generated Product E2E passes against real production dependencies.
6. Browser E2E passes the integrated UI flow.
7. Existing lower-level Requirement APIs and Operator E2E remain valid.
8. Existing SRA ES editor, Excel→SQL management, account management, and Report Job regressions are green.
9. Documentation allows an operator to maintain the system without direct SQL/log inspection for normal operations.
