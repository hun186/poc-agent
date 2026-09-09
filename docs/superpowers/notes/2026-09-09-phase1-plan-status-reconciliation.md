# Phase 1 Plan Status Reconciliation

**Repository:** `hun186/poc-agent`
**Authority inspected:** hosted `main` snapshot `b8bcd779815337bb386a97fc457a5f49663fb2b6` (PR #225 merge)
**Reconciliation date:** 2026-09-09
**Scope:** documentation/status reconciliation; no implementation authorization

## Rebaseline and evidence rules

The checkout had no configured Git remote, so `git fetch --all --prune` could not independently query a newer hosted ref. The checked-out commit exactly matched the operator-supplied hosted baseline. This note therefore uses `b8bcd779815337bb386a97fc457a5f49663fb2b6`; a future implementation must fetch and bind the then-current hosted `main` again.

Historical checkboxes and issuance-time labels are historical evidence, not a current to-do list. Source wins stale paths and status. Historical reviews retain their original verdicts. The four distinct acceptance layers used below are: **repository implementation**, **repository review**, **single live Golden Path**, and **full deployment acceptance matrix**.

## Authority and current-status matrix

| Artifact / workstream | Historical version | Superseded by | Current architecture authority | Current repository implementation status | Current live/deployment acceptance status | Remaining action | Must old plan be executed? |
|---|---|---|---|---|---|---|---|
| Phase 0 security | Design v3 / Plan v6.1 | No later Phase 0 design; implementation source supersedes plan task state | Security Design v3 plus current source | Present; Implementation Review v5 recorded repository **PASS** | The supplied Phase 1C chain exercised owner-scoped Report Jobs, Agent/ES, and DOCX, but does **not** establish Phase 0's separately defined Service-Key/signed-resource matrix | Execute remaining Phase 0 deployment scenarios and credential hygiene under explicit authorization | **No**; use only remaining acceptance deltas |
| Phase 1A Batch Scheduler | Design / Plan / Prompt v1 | No replacement; current source establishes completion | Batch Scheduler Design v1 and standalone `batch_scheduler/` boundary | Present: config, models, input loader, SQLite store, HTTP client, service, output publication, and CLI | Its concepts participate downstream, but the dedicated historical two-task tabular/JSON, restart, and credential-rotation matrix remains unexecuted | Retain deployment-only acceptance follow-up; do not reimplement | **No** |
| Phase 1B Requirement Import | Design v1 / Plan and Prompt v1.1; historical Review v1 | v1.1 supersedes v1 plan/prompt; later implementation source supersedes old operational status | Requirement Import Design v1, v1.1 execution artifacts, current `data_ingestion/requirements/` and API source | Present: source/profile/version/import/snapshot lifecycle. Historical Review v1 remains truthfully **NOT PASS** for its reviewed snapshot, but is not current implementation status | The supplied live chain proves a real import and immutable Requirement Set/Snapshot on the deployed path. It does not prove every source/migration/rollback case | Complete the unexecuted deployment acceptance matrix and obtain any desired current-snapshot review | **No** |
| Phase 1C-A Schedule Control Plane | Design / Plan / Prompt generations v1–v5 | v2 superseded v1; v3 superseded v2; v4 superseded v3; v5 superseded v4 | Design v5 for closure details plus current source; later Job Task boundary governs orchestration separation | Present: recurrence, `ScheduleStore`, immutable schedule versions, snapshot-bound materialization, policies/checkpoints, `claim_due()`, occurrence uniqueness, manual trigger/status API, and audit | The supplied live chain proves Schedule → Manual Batch Run and terminal lifecycle for one item. Fresh/migration shapes, rollback/failure injection, due-claim races, and the automatic scheduler path are not fully accepted | Implement only the new runtime-driver delta after review; retain remaining SQL acceptance | **No** |
| Phase 1C-B Execution Bridge | historical Plan v1; corrected Plan v1.1 | Plan v1.1 supersedes Plan v1; current implementation supersedes issuance-time `IMPLEMENTATION NOT STARTED` | Job Task Orchestration Boundary Design v1, corrected Plan v1.1 semantics, current source | Present: coordinator/service, neutral gateway, legacy HTTP gateway, leases/fencing, durable submissions, reconciliation, artifact publication, checkpoint and run closure | **Single-item Requirement → Report Job → Agent/Elasticsearch → DOCX live Golden Path: PASS.** Full migration, failure-injection, failover, race, and rollback matrix is not proven | Preserve the bridge and execute remaining deployment acceptance; no redesign | **No** |
| JT-1 Job Task | Job Task Orchestration Boundary Design v1 future gate | None | That design's future boundary | **NOT STARTED**; no Task/Attempt/Event Store implementation found | **NOT EXECUTED** | Separate future design/review/implementation gate only | **No** current plan is authorized |
| LangGraph | Job Task Orchestration Boundary Design v1 future option | None | Framework-neutral execution boundary | **NOT STARTED**; no LangGraph runtime implementation found | **NOT EXECUTED** | Separate future gate; preserve framework neutrality | **No** |
| Scheduled due-claim runtime driver | v2's historical combined-worker concept | Combined scheduling/execution semantics superseded by the independent 1C-B boundary | Phase 1C-A `ScheduleStore.claim_due()`, Job Task Boundary Design v1, and Runtime Automation Design v1 | **MISSING**: `claim_due()` exists, but no continuous process calls it; CLI exposes only `handoff-worker` | **NOT EXECUTED** because no automatic process exists | Review, then implement the focused external `schedule-worker` delta | **No** old combined-worker plan; execute only the new reviewed plan |

## Source findings

### Implemented boundaries

- `batch_scheduler/` remains a standalone Phase 1A controller and includes `config`, `models`, `input_loader`, `store`, `sra_client`, `service`, `output`, and module CLI surfaces. It must not be reimplemented or embedded in Requirement Scheduler.
- `data_ingestion/requirements/` and the Requirement API implement source acquisition, profiles and immutable profile versions, canonical Requirement versions, import runs, Requirement Set snapshots, and activation.
- `requirement_scheduler/store.py` is the SQL Server lifecycle authority. Its current `claim_due(*, now_utc, actor)` selects `TOP 1` enabled due schedule whose active version is approved, using `UPDLOCK,HOLDLOCK`, ordered by `(next_run_at, schedule_id)`. It calls `coalesce_latest`, materializes the scheduled occurrence under the same transaction, advances `next_run_at`, and commits atomically.
- Scheduled identity is unique by `(schedule_id, scheduled_for)` for `trigger_type='scheduled'`. A narrowly recognized SQL Server duplicate-key race rolls back, reads the winning Batch Run and persisted next occurrence, and returns that idempotent winner; other errors become safe `persistence_error` failures.
- Phase 1C-B is implemented by `RequirementHandoffCoordinator`, `RequirementHandoffService`, the neutral `ExecutionGateway`, `LegacyReportJobGateway`, SQL-time leases/fencing, durable immutable submissions, reconciliation, confined/root-bound artifact publication, checkpoint advancement, and terminal run recomputation.
- `python -m requirement_scheduler handoff-worker` is the only current Requirement Scheduler command. It remains the external reconcile → prepare → submit coordinator. No `schedule-worker` command or other automatic `claim_due()` caller exists.

### Supersession reconstruction

Phase 1C v1/v2 described both Gate A and a coupled worker. v3–v5 narrowed later work to Gate-A closure and successively superseded prior closure details. The Job Task Orchestration Boundary Design then prohibited placing the standalone Phase 1A lifecycle controller below Requirement Scheduler and established a neutral, independent handoff coordinator. Corrected Phase 1C-B Plan v1.1 superseded Plan v1's checkpoint/root-binding defects. Current source implements that separated bridge. Consequently, v2 remains useful evidence that due claiming needs an external runtime, but its combined due-claim → Phase 1A handoff → reconciliation worker is not current architecture and must not be revived.

## External operator evidence recorded

The operator reports an authorized live deployed chain:

```text
Requirement import → immutable Requirement Set / Snapshot → Schedule
→ Manual Batch Run → Run Item → Handoff Prepare → SQL Server queue claim
→ owner-scoped Report Job submission → ReportJobWorker → real Agent
→ Elasticsearch → qwen3.8:latest-128k → DOCX → remote completion
→ reconciliation → root-bound publication → SHA-256 verification
→ Run Item completed → Batch Run completed
```

Safe terminal evidence: Batch Run `completed`, `selected_count=1`, `success_count=1`, `failure_count=0`; Run Item and remote state `completed`; DOCX exists, size `42341` bytes; recorded and actual SHA-256 both `a085c5e4d451d6e5a2a0c6446646e987be421dbbb1416af36501dd468c66ff11`; DOCX structural validation **PASS**. This is external operator evidence, not a Codex-executed test.

PR #223 corrected HTTP `202` and native status handling, PR #224 preserved an aware UTC SQL Server clock contract, and PR #225 corrected the `READPAST` locking contract before the successful run. No credential, header, password, Service Key, connection secret, or absolute private path is recorded here.

## What remains unexecuted

- Phase 0's complete Service-Key/signed-resource acceptance and post-pass credential lifecycle.
- Phase 1A's dedicated two-task input/restart acceptance matrix.
- All Phase 1B/1C schema shapes and migrations, rollback and failure injection, coordinator failover/fencing turnover, concurrency/race matrices, and broader multi-item scenarios.
- Automatic scheduled due-claim execution, because its runtime driver does not yet exist.
- JT-1 and LangGraph in all forms.

## Exact completion delta

```text
enabled schedule + persisted next_run_at becomes due
                         ↓
             ScheduleStore.claim_due() exists
                         ↓
              no automatic caller exists
                         ↓
       scheduled Batch Run is not materialized automatically
```

The proposed response is a small external `schedule-worker`, specified separately. It does not change the existing `handoff-worker` or claim ownership of execution.
