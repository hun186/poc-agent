# Codex Execution Contract — Requirement Schedule Runtime Automation v1

## Binding

- **Repository:** `hun186/poc-agent`
- **Required work branch:** create a dedicated implementation branch from actual hosted `main`
- **Planning baseline:** `b8bcd779815337bb386a97fc457a5f49663fb2b6` (PR #225 merge)
- **Merge policy:** open a PR; **no auto-merge**
- **Scope:** implement only the reviewed Phase 1C scheduled due-claim runtime driver

The planning baseline is exact, not evergreen. Before modifying anything, run the repository rebaseline commands, fetch hosted refs, and bind the actual current hosted `main` SHA. If `main` advanced, use and report it. If no remote is configured, report that limitation and do not pretend to have queried hosted state. Current source always wins stale path assumptions.

## Mandatory reading and stop gate

Read completely, in repository-prescribed order, `AGENTS.md`, all active `.codex` memory files, then:

1. `docs/superpowers/notes/2026-09-09-phase1-plan-status-reconciliation.md`;
2. `docs/superpowers/specs/2026-09-09-sra-requirement-schedule-runtime-automation-design-v1.md`;
3. `docs/superpowers/plans/2026-09-09-sra-requirement-schedule-runtime-automation-plan-v1.md`;
4. Phase 1C-A Design v5;
5. Job Task Orchestration Boundary Design v1;
6. Phase 1C-B Plan v1.1; and
7. current Requirement Scheduler source, tests, CLI, and operations documentation.

Inspect production source before modification. Verify `ScheduleStore.claim_due()` still exists, still claims at most one occurrence, and has no production automatic caller; verify `handoff-worker` remains current CLI. If the premise is materially false, stop and report source evidence rather than creating duplicate architecture.

## Execution instructions

Follow the Plan task-by-task using strict **RED → minimal GREEN → focused regression → cross-phase regression → review**. Preserve exact failing and passing command output. Implement the smallest source-consistent external `schedule-worker`; an optional `--once` must retain the reviewed semantics. Reuse the existing Requirement SQL registry and `ScheduleStore.claim_due()` boundary. Use aware UTC and interruptible bounded polling. Keep `handoff-worker` compatible and independent.

Do not redesign architecture. In particular, add no schema/migration/dependency, do not change recurrence/materialization/claim semantics, do not embed Phase 1A, do not access Batch Scheduler SQLite, ReportJobStore, ReportJobWorker, Agent, Elasticsearch, Word rendering, or HTTP from schedule-worker, and do not add a FastAPI thread, queue system, retry engine, or cancellation engine. Do not implement JT-1 or LangGraph.

Explicitly preserve:

- PR #223: Report Job create HTTP `202` and native `status` reconciliation;
- PR #224: aware UTC SQL Server clock semantics;
- PR #225: `UPDLOCK,READPAST,READCOMMITTEDLOCK` candidate queue behavior; and
- the operator-verified Phase 1C-B manual single-item Requirement → Report Job → Agent/Elasticsearch → DOCX Golden Path.

Never place credentials, Authorization headers, passwords, cookies, Service Keys, connection strings, or private paths in source, tests, docs, logs, or the PR.

## Required completion evidence

Commit changes and create a PR without merging it. Report:

```text
Repository
Actual baseline commit
Resulting commit
Branch
PR number / URL
Changed files
Behavior implemented
RED commands and actual output
GREEN/focused/cross-phase commands and actual output
Static architecture-boundary checks
Deviations with source evidence
Risks and unexecuted deployment acceptance
Production schema/migration/dependency changes (must be none)
JT-1 work (must be none)
LangGraph work (must be none)
```

Do not describe mocked/fake persistence or transport tests as live acceptance. If authorized live automation acceptance was not executed, say so. End by requesting human/ChatGPT implementation review; do not self-award deployment PASS.
