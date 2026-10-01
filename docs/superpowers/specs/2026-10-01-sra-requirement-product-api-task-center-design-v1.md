# SRA Requirement Product API + Task Center — Design v1

**Date:** 2026-10-01  
**Status:** Design draft for review; implementation NOT STARTED  
**Repository authority:** current hosted `main`  
**Existing foundations:** Phase 1B Requirement Import, Phase 1C Requirement Schedule/Handoff, Report Jobs, SRA ES structured-data editor, Excel→SQL management UI, existing Auth/RBAC.

## 1. Purpose

Turn the already-working Requirement technical pipeline into a production-facing product workflow that can be operated in two ways:

1. **Automation/API use** — an external system can submit its own Excel/CSV/JSON or Requirement payload, create a one-time or recurring task, query run state, and retrieve completed artifacts through a stable product API.
2. **Human operations** — an authenticated SRA user can perform the same workflow from a Requirement Task Center integrated into the existing SRA management interface.

The product layer MUST reuse the existing Requirement Import, Schedule, Handoff, Report Job, Elasticsearch/Agent/LLM, artifact, audit, and authentication authorities. It MUST NOT create a parallel scheduler, report queue, user database, authentication system, or browser-owned execution path.

## 2. Existing product baseline

The current application already has a unified management surface:

- `/editor` is the primary SRA management entry.
- Top-level navigation currently includes:
  - **ES 資料庫**
  - **匯入管理**
  - **系統管理**
  - **帳號安全**
  - **代理人資料流程圖**
- Existing data-management interfaces include:
  - SRA ES structured-data search/edit/create/delete.
  - Excel→SQL import dashboard.
  - SQL source-data editor.
  - SQL source statistics dashboard.
  - Excel import center.
  - Excel→SQL task JSON management.
- Existing account/security features include:
  - login/registration/password flows,
  - account approval,
  - role management,
  - audit history,
  - service-key management.
- Current role hierarchy includes `data_reader`, `data_editor`, `db_operator`, and `superuser`.
- Requirement import already supports `manual_upload` with `.xlsx`, `.csv`, and `.json`.
- Requirement Schedule already supports logical schedules, immutable versions, approval, enable/disable, manual runs, run status, Handoff execution, and artifact reconciliation.
- Report Jobs already own the actual Agent/LLM/ES execution and DOCX production.
- The Requirement Operator E2E already proves a technical Golden Path, but its input is a committed test fixture and therefore is not a Product Ingress E2E.

This design integrates the new capability into that existing product instead of creating another administration application.

## 3. Product architecture

```text
                     SRA Management UI (/editor)
                              │
                ┌─────────────┴─────────────┐
                │                           │
        Existing data tools          Requirement Task Center
        ES editor / Excel→SQL        create / monitor / maintain
                │                           │
                └─────────────┬─────────────┘
                              │
                       Product API façade
                     /v1/requirement-tasks
                              │
             ┌────────────────┴────────────────┐
             │                                 │
     Phase 1B Requirement Import       Phase 1C Schedule/Run
     source/profile/snapshot           version/approve/trigger
             │                                 │
             └────────────────┬────────────────┘
                              │
                        Handoff Coordinator
                              │
                          Report Job
                              │
                     real Agent / LLM / ES
                              │
                       reconciled DOCX
```

The Product API is orchestration/presentation only. Existing lower-level APIs remain valid administration/integration surfaces.

## 4. Information architecture in the existing UI

Do not add a separate login page or independent site.

### 4.1 Existing top-level navigation

Retain the existing top-level roots.

Under **匯入管理**, keep the existing `Excel 匯入流程管理` section and add a second section:

### 要項與自動化任務

- **要項任務中心**
- **建立要項任務**
- **執行紀錄**
- **要項來源與版本**

The resulting conceptual navigation is:

```text
匯入管理
├─ Excel 匯入流程管理
│  ├─ Excel→SQL 匯入查詢儀表板
│  ├─ SQL 來源資料編輯器
│  ├─ SQL 來源資料統計儀表板
│  ├─ Excel 匯入作業中心
│  └─ 任務 JSON 管理
└─ 要項與自動化任務
   ├─ 要項任務中心
   ├─ 建立要項任務
   ├─ 執行紀錄
   └─ 要項來源與版本
```

This keeps all ingestion and automation operations under one operational area while preserving ES database editing as its own existing domain.

### 4.2 Shared visual and security shell

The Requirement pages MUST reuse:

- the current login/session token behavior,
- current role display and logout,
- the existing global navigation style,
- current audit conventions,
- current responsive layout conventions,
- current error/status component patterns.

No iframe and no second browser-auth state are allowed.

## 5. Product concepts

### 5.1 Requirement Task

A **Requirement Task** is the product-level object an operator or external client understands.

It represents:

- a human-readable task name,
- the current Requirement source/set,
- an execution policy,
- an active schedule version when applicable,
- current enabled/disabled state,
- latest run,
- next run when recurring.

The task is a façade over existing Requirement and Schedule authorities. Do not create a second execution engine.

### 5.2 Task ID

The product API exposes an opaque `task_id`.

Preferred v1 implementation: reuse the underlying Schedule logical identity as the authoritative task identity through a product presenter rather than introducing another persistent mapping table unless implementation evidence proves that mapping is insufficient.

Every one-time task therefore still has a Schedule logical object with an active version; one-time execution is a manual run and does not require enabling recurrence.

### 5.3 Run

A **Run** is one immutable execution occurrence.

A run MUST bind to:

- one Requirement snapshot,
- one schedule/task version,
- one selected Requirement set,
- one model configuration,
- one trigger identity,
- its resulting Run Items and artifact evidence.

Updating a Task never mutates an existing Run.

## 6. Product API principles

1. **High-level API for normal automation.** Clients should not need to orchestrate source → preview → import → requirement set → schedule → version → approve → enable/trigger themselves.
2. **Existing low-level APIs remain available.** They stay the administrative primitives and implementation authority.
3. **Idempotency first.** Product mutations require `Idempotency-Key` or an equivalent explicit request identity.
4. **Server-owned identities.** Clients never choose snapshot IDs, version IDs, Report Job IDs, Handoff owner identities, E2E model markers, or artifact paths.
5. **No E2E-only behavior.** Product API jobs are ordinary production jobs and MUST always use the real production dependencies. E2E semantic mocks are inaccessible from this surface.
6. **Stable safe errors.** Responses expose product error codes, not raw ODBC/HTTP/Python/LLM bodies.
7. **Immutable history.** Updating task input or schedule produces new immutable source/snapshot/version state.
8. **No browser direct execution.** The browser calls the API; workers remain externally supervised.
9. **No direct Report Job creation from Product API.** Product execution must pass through the Requirement Schedule/Handoff authority.

## 7. Product API v1

### 7.1 Preview upload

`POST /v1/requirement-task-previews`

Content type: `multipart/form-data`.

Fields:

- `file` — required for file mode; `.xlsx`, `.csv`, or `.json`.
- `task` — JSON document containing task metadata and selected approved import profile.
- optional `requirements_json` may be supported instead of file upload for direct API payload mode, but file and direct payload are mutually exclusive.

Side effect: none in the Requirement domain.

Response includes:

- normalized source SHA-256,
- filename/display metadata,
- accepted/rejected counts,
- normalized preview rows,
- row-level validation errors,
- selected import-profile identity/version,
- safe warnings.

The Product API MAY internally call the existing Requirement preview service. It must not duplicate the parser.

### 7.2 Create task

`POST /v1/requirement-tasks`

Supports multipart file upload or direct JSON Requirement input.

Required semantic inputs:

- task name,
- input,
- import profile selection or server-configured approved default,
- execution definition,
- model selection permitted by server policy,
- expected source SHA-256 from preview when using the interactive preview/commit flow.

Execution definitions:

```json
{"type":"once"}
```

or:

```json
{
  "type":"recurring",
  "timezone":"Asia/Taipei",
  "recurrence":{
    "kind":"daily",
    "time":"08:00"
  }
}
```

Server workflow:

1. validate auth/RBAC/idempotency,
2. preview/validate input,
3. commit Requirement snapshot through Phase 1B,
4. create the logical Schedule/Task,
5. create immutable Schedule Version,
6. approve according to product RBAC,
7. for `once`: materialize one manual Run without enabling recurrence,
8. for `recurring`: enable the approved schedule,
9. return Product Task and first Run identity when one-time.

The façade does not bypass any existing transaction/approval rules.

### 7.3 List/get tasks

- `GET /v1/requirement-tasks`
- `GET /v1/requirement-tasks/{task_id}`

Filters should include:

- enabled,
- execution type,
- name,
- latest status,
- created/updated by,
- created/updated time,
- next-run range.

Task detail includes safe links/IDs for:

- current input snapshot,
- active version,
- latest Run,
- next run,
- recent execution counts.

No local path, credential, prompt, E2E marker, or backend-native status is returned.

### 7.4 Update task

`PATCH /v1/requirement-tasks/{task_id}`

Allowed changes are prospective only:

- name,
- enabled state,
- recurrence/timezone,
- approved model selection,
- run policy.

Any schedule-affecting change creates a new immutable Schedule Version.

Replacing Requirement input is a separate operation:

`POST /v1/requirement-tasks/{task_id}/input`

This previews/commits a new Requirement snapshot under the same logical task/source authority.

Existing Runs remain bound to their original snapshot/version.

### 7.5 Trigger a run

`POST /v1/requirement-tasks/{task_id}/runs`

Requires an idempotency/request identity and reuses the existing manual materialization authority.

It returns a product Run presenter.

### 7.6 Run status/history

- `GET /v1/requirement-runs`
- `GET /v1/requirement-runs/{run_id}`
- `GET /v1/requirement-runs/{run_id}/items`

Stable product status vocabulary:

- `queued`
- `running`
- `completed`
- `completed_with_errors`
- `failed`
- `recovery_required`

The presenter maps existing neutral Schedule/Handoff state; it does not expose Report Job-native implementation states.

### 7.7 Artifacts

- `GET /v1/requirement-runs/{run_id}/artifacts`
- `GET /v1/requirement-runs/{run_id}/items/{run_item_id}/word`

The Word endpoint reuses the existing confined artifact validation/history authority. No absolute path appears in JSON or headers.

## 8. Authentication and authorization

### 8.1 Human UI

Reuse the current bearer session and role hierarchy.

Baseline UI policy:

- `data_reader`: view task/run histories and completed artifacts permitted by product policy.
- `data_editor`: may preview Requirement input if desired by final RBAC review, but cannot commit/activate automation by default.
- `db_operator`: create/import task input, create disabled tasks, create draft schedule versions, trigger permitted operational actions.
- `superuser`: approve/activate versions, enable recurring automation, disable tasks, manage service keys.

Exact privilege inheritance must reuse `authorize_role` and existing denial audit; do not introduce a second role engine.

### 8.2 Automation clients

Use the existing service-key subsystem rather than human passwords.

Add product scopes through the existing validated service-key store, subject to rebaseline:

- `requirement:task:read`
- `requirement:task:write`
- `requirement:run:trigger`
- `requirement:artifact:read`

Do not reuse the private Handoff worker credential for external clients.

Browser pages never receive service keys.

## 9. Requirement Task Center UX

### 9.1 Task Center dashboard

Main table/cards:

- task name,
- input type,
- active Requirement count,
- once/recurring,
- enabled state,
- schedule summary,
- model,
- last run time/status,
- next run,
- success/failure counts,
- owner/last editor.

Actions:

- open detail,
- run now,
- enable/disable if authorized,
- edit prospective schedule,
- replace input,
- view history.

No destructive deletion of historical Runs.

### 9.2 Create Task wizard

Four steps:

1. **Input**
   - upload Excel/CSV/JSON,
   - or paste/send Requirement JSON,
   - select approved import profile.
2. **Preview**
   - accepted/rejected counts,
   - row errors,
   - normalized Requirement preview,
   - source SHA.
3. **Execution**
   - once or recurring,
   - timezone,
   - recurrence,
   - model,
   - run policy.
4. **Review and create**
   - show immutable summary,
   - show what requires approval,
   - create and optionally start/enable according to user privilege.

Do not hide validation failures behind automatic coercion.

### 9.3 Task detail

Tabs:

- **摘要**
- **要項**
- **排程與版本**
- **執行紀錄**
- **稽核**

Summary includes latest run and next action. Requirement view shows current snapshot and historical versions without allowing mutation of old snapshots.

### 9.4 Run detail

Timeline:

```text
Requirement snapshot
→ Run materialized
→ Handoff
→ Report Job
→ execution
→ artifact reconciliation
→ terminal state
```

For each Run Item show:

- Requirement identity/title,
- neutral execution state,
- safe error category,
- elapsed time,
- artifact state,
- Word download when complete.

Do not expose raw LLM prompt, credentials, absolute filesystem paths, Handoff service identity secrets, or arbitrary stack traces.

## 10. Audit and operations

Product mutations must emit safe audit events using the existing audit mechanism.

Minimum actions:

- `requirement.task.previewed`
- `requirement.task.created`
- `requirement.task.updated`
- `requirement.task.input_replaced`
- `requirement.task.enabled`
- `requirement.task.disabled`
- `requirement.task.run_triggered`
- `requirement.task.artifact_downloaded`

Audit records include actor, safe product IDs, counts, and result category. They exclude source file contents, prompt bodies, credentials, SQL text, local paths, and raw upstream errors.

Task Center should expose operational filters for time, user/service principal, task, run state, and error category.

## 11. Observability and maintainability

A production operator must be able to answer from UI/API without SQL inspection:

- Which tasks are enabled?
- What runs are currently queued/running?
- What failed today?
- Which Requirement item failed?
- What safe error category was recorded?
- When will the task run next?
- Which input snapshot/version did a Run use?
- Which task/version/user created the Run?
- Is an artifact available?
- Is Schedule/Handoff worker health degraded?

Do not expose the Operator E2E runtime-evidence endpoint to ordinary users. Task Center may consume a separate bounded operational-health presenter if needed.

## 12. Idempotency and retry

All external product mutations that can create persistent work must be replay safe.

- Require `Idempotency-Key` for automation-facing create/trigger/input-replace actions.
- Same key + same canonical request returns the existing result.
- Same key + different canonical request returns 409.
- Ambiguous network loss must be recoverable by GET using product identity/idempotency lookup.

Retrying a failed execution creates a new Run:

```text
run_001 failed
└─ retry → run_002
           parent_run_id = run_001
```

Do not mutate failed Run history into success.

## 13. Product E2E

The existing Requirement Operator E2E remains the deployment/technical acceptance harness.

Add a separate **Product API E2E** whose input does not depend on a committed repository fixture.

Each Product E2E run must:

1. generate an input file or direct JSON payload at runtime with a unique marker,
2. authenticate through the same product auth/service-key surface,
3. call Product Preview,
4. create a one-time Requirement Task,
5. obtain `task_id` and `run_id`,
6. verify the Run binds to the newly imported snapshot,
7. wait through real Schedule/Handoff/Report Job execution,
8. require real production LLM and Elasticsearch behavior,
9. verify terminal Run/Run Item API state,
10. download and validate DOCX/artifact evidence,
11. prove the unique runtime input marker is represented in the stored Requirement identity/evidence expected by the test,
12. clean up only reversible task state; never delete immutable run history merely to make the test clean.

No `requirement-e2e:` model marker or semantic mock routing is permitted in Product E2E.

## 14. Browser E2E

After the Product API is stable, add browser E2E for the integrated SRA UI:

```text
login
→ 匯入管理
→ 建立要項任務
→ upload generated Excel
→ preview
→ create one-time task
→ view running status
→ completed
→ download DOCX
```

Browser E2E proves navigation, RBAC, upload, status rendering, and artifact download. It is not a substitute for Product API E2E.

## 15. Compatibility and migration

- Existing `/v1/requirement-sources/*` and `/v1/requirement-schedules/*` remain supported.
- Existing Operator E2E remains unchanged except where shared bug fixes are necessary.
- Existing ES editor and Excel→SQL pages remain unchanged except global navigation integration.
- No Requirement schema migration is assumed by this design until implementation rebaseline proves one necessary.
- Prefer presenter/orchestration code over new persistence.
- If a new persistent Product Task table is proposed during implementation, STOP and return to design review with evidence showing why Schedule identity cannot satisfy the product object.

## 16. Security boundaries

The Product API/UI MUST NOT:

- accept arbitrary SQL,
- accept arbitrary artifact paths,
- accept a Report Job owner/service principal,
- accept E2E model markers,
- select E2E mocks,
- expose worker credentials,
- expose deployment SQL registry details,
- expose absolute file paths,
- invoke Report Jobs directly from browser/API façade,
- run scheduler/handoff loops inside FastAPI background threads,
- weaken existing Requirement approval/version rules.

Uploaded files receive bounded size/type validation and are parsed only by the existing Requirement import authority.

## 17. Out of scope for v1

- generic workflow builder,
- JT-1/LangGraph redesign,
- replacing Report Job execution,
- replacing current AuthStore,
- arbitrary user-defined Python/SQL,
- distributed queue/HA redesign,
- cancellation of already-running Report Jobs,
- webhook delivery (candidate v1.1 after Product API contracts stabilize),
- deleting immutable audit/run history,
- moving Schedule/Handoff worker ownership into FastAPI.

## 18. Acceptance criteria

Product v1 is complete only when all of the following are true:

1. Existing SRA login/RBAC controls the Requirement Task Center.
2. Requirement navigation is integrated under the existing SRA management UI.
3. A user can upload their own Excel/CSV/JSON, preview it, and create a task.
4. An automation client can perform the same flow through Product API/service key.
5. One-time and recurring task creation reuse existing Schedule authority.
6. Run status/history is visible without SQL/log inspection.
7. Completed DOCX is retrievable through authenticated product history.
8. All product mutations are idempotent/replay safe where required.
9. Historical snapshot/version/run bindings remain immutable.
10. Product jobs cannot enter E2E mock routing.
11. Product API E2E passes from runtime-generated external input through real execution and artifact retrieval.
12. Browser E2E passes the integrated SRA UI Golden Path.
13. Existing ES editor, Excel→SQL, Auth, Requirement lower-level APIs, Operator E2E, and Report Job regression suites remain green.

## 19. Design decision summary

The correct product boundary is **one integrated SRA operations console** with multiple data/automation modules, not several disconnected applications.

The Requirement Task Center is therefore a new operational module inside the current management system, while the Product API is a stable orchestration façade over already-reviewed Requirement Import and Schedule/Handoff authorities.
