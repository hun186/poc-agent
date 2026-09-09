# 待辦事項（Backlog）

## 2026-09-04 Phase 1B / 1C handoff

- Historical gate at issuance: execute real SQL Server Phase 1B acceptance and implement Phase 1C in reviewed A/B gates. Superseded current status: both repository gates are implemented, and the supplied operator evidence proves one live import/manual-run/handoff/Report Job/Agent/DOCX Golden Path.
- Remaining acceptance is narrower but still material: automatic due claiming, additional schema/migration/rollback/failure/failover/race shapes, and broader multi-item deployment scenarios require an explicitly authorized environment. Repository fake SQL/transport evidence must not be called deployment acceptance.

## Current Summary

### Phase 1 completion delta

- Phase 1C-B implementation is present. External operator evidence now establishes the single-item Requirement → owner-scoped Report Job → real Agent/Elasticsearch → root-bound verified DOCX live Golden Path as **PASS**. Do not retain older statements that this specific path has never run.
- Automatic scheduled materialization remains missing: `ScheduleStore.claim_due()` exists, but no continuous production caller or `schedule-worker` CLI exists. After human/ChatGPT Design + Plan Review, implement only `docs/superpowers/plans/2026-09-09-sra-requirement-schedule-runtime-automation-plan-v1.md` under its future execution contract.
- Still unexecuted: the complete Phase 0 Service-Key/signed-resource chain and credential hygiene; dedicated Phase 1A two-task/restart acceptance; all Phase 1B/1C schema/migration/rollback/failure-injection, coordinator failover/fencing, concurrency/race, multi-item, and automatic due-claim deployment scenarios. JT-1 and LangGraph remain **NOT STARTED**.

### Phase 0 deployment acceptance

- From an operator environment with private deployment and Elasticsearch access, run the complete Service Key → report/analysis Router → real Elasticsearch evidence → long Agent synthesis → signed Word → valid DOCX chain.
- Only after the real E2E passes, create and smoke-test replacement acceptance credentials, revoke prior credentials, verify their next protected request returns 401, and move the harness to environment/ignored local configuration. Preserve existing working credentials until then.
- Future Phase 0/3 security work includes per-end-user OpenWebUI identity propagation, integration credential rotation, per-principal quotas/rate limits, request size limits, and observability. Batch Scheduler, Server Dashboard, and Windows GUI remain outside Phase 0.

### Report Jobs and retrieval

- Consider Report Job retention/cleanup, capacity/metrics, cancel, retry, webhook, and shared queue/object storage. Current single-process SQLite/local disk is not HA or exactly-once.
- Separately design structured retrieval exclusions/directives before changing Data Agent, Tool, or `query_meta` contracts.
- Continue multi-event event-cluster merging, selectors, Editor event-list workflows, and event-level/nested indexing work described in `docs/multidim_event_json_multi_event_todo.md`.

### Authentication, UI, and audit

- For multi-worker deployments, move login/registration/reset throttles to shared infrastructure; evaluate MFA/re-authentication, CSP/XSS hardening, HttpOnly cookies with CSRF protection, and stronger registration abuse controls.
- Consolidate reusable reset-token, navigation, and audit-tool components; add browser E2E coverage when Playwright/runtime is available.
- If audit volume grows, add server-side category/action and user filtering plus export support.

### Data ingestion and consistency

- Replace remaining naive UTC datetime calls with timezone-aware values.
- Consider downloadable Excel import error rows and clearer alias/match diagnostics.
- Design SQL View mode with explicit schema/name/permissions, safe identifiers, audit/hash/downstream semantics, and no stub claims.
- Define SQL/ES lineage plus delete outbox/tombstone and reviewed reconciliation instead of synchronous cross-system hard deletion.

## Recent Changes

- 2026-09-03: Review v3 repository completion items were implemented and freshly verified; only operator deployment acceptance and post-pass credential hygiene remain for Phase 0.
- 2026-09-02: Unified security-boundary foundations, signed capabilities, Service Keys, and owner-aware Report Jobs were completed. Historical details are archived.

## Archived History

- `.codex/archive/backlog.md-20260903-000000.md` — compacted 2026-09-03; contains all prior Phase 0 audit entries and dated backlog details from 2026-06-11 through 2026-09-03.

## 2026-09-04 Phase 1 deployment follow-up

- From the private operator network, execute the documented two-task tabular-plus-JSON real SRA/Elasticsearch Batch Scheduler acceptance, exercise stop/resume against the same remote job, inspect both DOCX reports, then create/test a replacement key and revoke/verify the old key. Do not treat repository mocked transport tests as this acceptance.

## 2026-09-04 Phase 1C v2 implementation gates

- Phase 1C Design v1 / Plan v1 / Prompts v1 are superseded by v2 after Design Review v1. Implement only v2 in two reviewed gates; 1C-A remains not started, and 1C-B remains prohibited until 1C-A is merged, its Implementation Review is PASS, and the new actual `main` baseline is recorded.

## 2026-09-04 Phase 1C-A follow-up

- Phase 1C-B remains prohibited until Gate A is merged and its human/ChatGPT Implementation Review records PASS. Gate B owns the Phase 1A seam/bridge, pre-handoff expiry, worker, reconciliation, manual trigger execution, and root-bound Word history.
- Execute Phase 1C live SQL Server acceptance only from an explicitly authorized environment; repository fake-ODBC evidence is not deployment acceptance.

## 2026-09-04 Phase 1C-A Review v1 blocker

- Resolve Finding G through a reviewed design change that makes schedule lifecycle mutation and durable audit acceptance atomic (or explicitly redefines the authority contract). Phase 1C-B remains prohibited until this blocker and Gate A review are closed.

## 2026-09-05 Phase 1C-A v3 closure

- Implement Design/Plan v3 C1–C8: canonical schema v2; direct fresh-v2 initialization; recognized PR #200/#201 v1 migration; 240-character exact task identity; same-schedule composite constraints; transactional lifecycle audit outbox; bounded at-least-once JSONL projection; and failure/security/regression evidence.
- Phase 1C-A current implementation exists but repository gate is NOT PASS pending the v3 closure PR and explicit post-merge Implementation Review. Phase 1C-B is NOT STARTED and remains prohibited until that PASS and a new actual `main` baseline are recorded.

## 2026-09-05 Phase 1C-A v4 closure

- Implement Design/Plan v4 C1–C8 only: exact PR #200/#201 catalog descriptors, guarded PR #200 identity repair, legacy configuration validation, ordered transactional schema-v2 migration, original outbox event-time projection, and monotonic pending-row delivery CAS.
- Phase 1C-A repository gate remains NOT PASS and its v4 closure implementation is NOT STARTED. Phase 1C-B is NOT STARTED and remains blocked until closure merge, explicit post-merge Implementation Review PASS, and a new actual `main` baseline.

## 2026-09-05 Phase 1C-A v4 post-merge follow-up

- Run explicitly authorized live SQL Server acceptance for fresh v2, both reviewed v1 migrations, rollback injection, and delayed/duplicate audit projection. Phase 1C-B remains NOT STARTED until the closure is merged and a human/ChatGPT post-merge Implementation Review records PASS.

## 2026-09-05 Phase 1C-A v5 closure

- Implement Design/Plan v5 against PR #204: corrected source-derived widths; real DB-API SQL Server catalog classifier; explicit canonical-v2 DDL; shape-specific migrations and complete Gate-B absence proof; explicit persisted RunPolicy coercion; exact outbox/index; live bounded projection; correct lost-race results; and the comprehensive v5 closure matrix.
- Phase 1C-A remains NOT PASS until implementation is merged and a post-merge human/ChatGPT Implementation Review explicitly records PASS. Phase 1C-B remains NOT STARTED and blocked until that PASS plus a new actual `main` baseline.

## 2026-09-05 Phase 1C-A v5 acceptance-evidence follow-up

- Merge and perform a fresh human/ChatGPT Implementation Review of the stateful `ScheduleStore.initialize()` acceptance-evidence closure; do not self-award PASS from repository test results.
- Execute fresh-v2, exact PR #200/#201 migration, rollback, and audit-projection acceptance against live SQL Server only when an explicitly authorized connection is supplied. Current live SQL status remains NOT EXECUTED.
- Phase 1C-B remains blocked and NOT STARTED. The separately discussed Job Task Orchestration Boundary design/implementation also remains NOT STARTED and is not part of Phase 1C-A v5.

## 2026-09-05 Future Job Task orchestration boundary

- Preserve and review the non-authoritative future architecture discussion in `docs/superpowers/notes/2026-09-05-job-task-orchestration-boundary-discussion-notes.md`; reconcile it against actual `main` before authoring `Job Task Orchestration Boundary Design v1`, then obtain human approval and replace/revise the Gate-B Plan and execution prompt. Do not execute the existing Phase 1C-B Prompt directly. Implementation NOT STARTED; Phase 1C-B NOT STARTED.

## 2026-09-05 Phase 1C-B Plan v1 review gate

- Review `docs/superpowers/plans/2026-09-05-phase1c-b-requirement-execution-bridge-plan-v1.md` against Job Task Orchestration Boundary Design v1 before issuing a new execution prompt. Phase 1C-B implementation, JT-1, and LangGraph remain NOT STARTED; the old Gate-B prompt remains stale and MUST NOT RUN.

## 2026-09-05 Phase 1C-B Plan v1.1 review gate

- Phase 1C-B Plan Review v1 is **NOT PASS** because it treated a legitimate same-RequirementVersion successful re-run as a checkpoint conflict and lacked first-handoff authority to snapshot the output-root fingerprint.
- Review `docs/superpowers/plans/2026-09-05-phase1c-b-requirement-execution-bridge-plan-v1.1.md`. Do not implement until Human/ChatGPT Plan v1.1 Review passes and a fresh execution contract is issued. Phase 1C-B implementation, JT-1, and LangGraph remain NOT STARTED; live SQL Server acceptance remains NOT EXECUTED.

## 2026-09-09 Phase 1C-B Plan history revalidation

- Plan v1 remains **SUPERSEDED / NOT PASS** for the same-version re-run/checkpoint conflict and missing first-Prepare output-root fingerprint binding. Plan v1.1 remains the corrected historical plan and is ready for human/ChatGPT review as a plan artifact.
- Repository history after the plan snapshot contains Phase 1C-B implementation, so do not interpret the historical plan gate as current implementation status. The remaining external gate is explicitly authorized live SQL Server and private Report Job/DOCX acceptance; JT-1 and LangGraph remain NOT STARTED.

## 2026-09-07 Phase 1C-B deployment follow-up

- Execute schema-v3 migration/rollback and coordinator acceptance against an explicitly authorized live SQL Server, then run the private Report Job/DOCX deployment E2E. JT-1 and LangGraph remain NOT STARTED.

## 2026-09-07 Phase 1C-B closure deployment gates

- Run schema-v3 migration/rollback, DB-time expiry, fencing turnover, and transaction failure injection against an explicitly authorized live SQL Server. Status: NOT EXECUTED.
- Historical status at gate issuance: the private owner-scoped Report Job + Agent + valid DOCX end-to-end was NOT EXECUTED. Superseded current status: the operator-supplied single-item Golden Path is PASS; broader multi-item/failover/failure/race deployment acceptance remains pending.
- Job Task JT-1 and LangGraph integration remain NOT STARTED and are separate future gates.
