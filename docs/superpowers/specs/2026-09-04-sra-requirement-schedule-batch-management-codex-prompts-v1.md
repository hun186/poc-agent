# SRA Requirement Schedule + Batch Management — Codex Execution Prompts v1

**Repository:** `hun186/poc-agent`<br>
**Design:** `docs/superpowers/specs/2026-09-04-sra-requirement-schedule-batch-management-design-v1.md`<br>
**Plan:** `docs/superpowers/plans/2026-09-04-sra-requirement-schedule-batch-management-plan-v1.md`<br>
**Purpose:** versioned, copy-paste-ready contracts for the two separately reviewed implementation gates. These prompts do not authorize changing the architecture.

## Prompt A — Phase 1C-A Control Plane implementation

```text
# Codex Execution Contract — Phase 1C-A Control Plane

Repository: hun186/poc-agent
Authoritative branch: main
Scope: implement only Merge Gate Phase 1C-A from the authoritative Phase 1C Design v1 and Plan v1.

Before changing anything:
1. Inspect repository identity, current branch, actual HEAD, full working-tree state, and whether the Design's baseline commit remains an ancestor. Never fabricate a SHA. If main advanced, use and report actual current source.
2. Find every applicable AGENTS.md. Read the repository AGENTS.md and then, in its prescribed order, .codex/memory.md, .codex/architecture.md, .codex/api_contract.md, .codex/known_issues.md, .codex/decisions.md, and .codex/backlog.md.
3. Read completely:
   - docs/superpowers/specs/2026-09-04-sra-requirement-schedule-batch-management-design-v1.md
   - docs/superpowers/plans/2026-09-04-sra-requirement-schedule-batch-management-plan-v1.md
   - their Phase 0, Phase 1A, and Phase 1B dependency documents named in the Design.
4. Inspect actual batch_scheduler/, data_ingestion/requirements/, sra_api/routers/requirements.py, sra_api/main.py, the existing auth/audit helpers, and relevant tests. Current source wins stale path assumptions.

Architecture is fixed by Design v1. Do not redesign it unless actual source proves a blocker. A proposed deviation must include exact source evidence, why the contract is impossible, the smallest alternative, and affected risks; stop for review when it changes an authority/security/idempotency boundary.

Implement Plan tasks A1 through A12 using strict TDD:
- write the specified failing test and run the RED command;
- make the smallest production change;
- run the specified GREEN command;
- commit at the task boundary;
- preserve exact schema/version/recurrence/policy/RBAC contracts.

Gate A is control plane only. It may add requirement_scheduler recurrence/models/migrations/store/policy/service and the schedule/version control API. It MUST NOT:
- create outbound Agent or Report Jobs;
- add the Phase 1A bridge, recurring worker, manual trigger, or Word endpoint;
- import agent, Elasticsearch execution, ReportJobWorker, or a Word renderer;
- write directly to Phase 1A SQLite;
- mutate Phase 1B immutable Requirement/version/snapshot history;
- start recurring work from FastAPI lifespan;
- weaken authentication, canonical Editor RBAC/audit, SQL transactions/locking, structural schema validation, idempotency, path confinement, or safe errors.

Required gate evidence:
- all Phase 1C-A focused tests;
- recurrence matrix including daily/weekly/monthly/interval, timezone and coalesce_latest;
- schema migration/validator and transaction rollback tests;
- due/concurrency, snapshot, policy, checkpoint, expiry tests;
- API 401/403/role/audit tests;
- Phase 0/1A/1B regression selection;
- compileall, git diff --check, prohibited-import scan, credential/runtime-artifact scan;
- final git status and log.

Update persistent project memory only with results actually observed. Preserve Phase 1B live SQL acceptance as NOT EXECUTED unless a newer authorized result exists. Do not claim Phase 1C complete. Commit all intended changes, push/create the PR if repository tooling permits, and report actual PR state rather than inventing one.

Completion report must include:
- repository, branch, initial baseline SHA, resulting SHA, and initial/final tree;
- every changed file;
- implemented behavior and explicit absence of outbound execution;
- exact RED/GREEN/gate commands and counts;
- deviations and source evidence, or "none";
- unresolved risks/blockers;
- Phase 1B/Phase 1C live acceptance status;
- commit list and PR URL/status.

Expected status: "Phase 1C-A control plane repository gate ready for implementation review; Phase 1C implementation incomplete."
```

## Prompt B — Phase 1C-B Execution Bridge implementation

```text
# Codex Execution Contract — Phase 1C-B Execution Bridge

Repository: hun186/poc-agent
Authoritative branch: main
Scope: implement only Merge Gate Phase 1C-B from the authoritative Phase 1C Design v1 and Plan v1.

DO NOT BEGIN UNLESS Phase 1C-A implementation review has PASSed and the new actual main baseline is recorded. If either fact is absent, stop and report the blocker; do not infer PASS from code presence.

Before changing anything:
1. Inspect repository identity, current branch, actual HEAD, full working-tree state, the recorded Phase 1C-A merged SHA, and its ancestry. Never fabricate a SHA. Use actual current main if it advanced.
2. Find every applicable AGENTS.md. Read repository AGENTS.md and then, in its prescribed order, .codex/memory.md, .codex/architecture.md, .codex/api_contract.md, .codex/known_issues.md, .codex/decisions.md, and .codex/backlog.md.
3. Read completely:
   - docs/superpowers/specs/2026-09-04-sra-requirement-schedule-batch-management-design-v1.md
   - docs/superpowers/plans/2026-09-04-sra-requirement-schedule-batch-management-plan-v1.md
   - Phase 1C-A implementation review and dependency documents named by the Design.
4. Inspect actual requirement_scheduler/, batch_scheduler/, data_ingestion/requirements/, sra_api schedule/Requirement routers, sra_api/main.py, auth/audit helpers, Report Job API contract, and relevant tests. Current source wins stale path assumptions.

Architecture is fixed by Design v1. Do not redesign without a concrete blocker. Any deviation needs exact source evidence, impossibility explanation, smallest alternative, and affected risks; stop for review before changing an authority, transaction, security, RBAC, or idempotency boundary.

Implement Plan tasks B1 through B15 using strict TDD:
- add and run each specified failing test first;
- implement the minimum change;
- run its passing command;
- commit at each boundary;
- preserve Gate A contracts and run its tests continuously.

Mandatory boundaries:
- expose one narrow Phase 1A programmatic import seam and make file import reuse its common insert path;
- Phase 1C calls that seam only and never writes Phase 1A SQLite;
- deterministic run/batch/task/session/fingerprint/idempotency identities must survive restart;
- expiry is checked at selection and before first handoff; already-dispatched jobs continue;
- only the explicit `python -m requirement_scheduler worker [--once]` process performs recurrence/handoff; never a FastAPI lifespan scheduling thread;
- reuse Phase 1A's existing Report Job HTTP client/state machine; do not create another Report Job engine;
- no production import from agent, Elasticsearch execution, ReportJobWorker, or Word renderer;
- Word history references the Phase 1A-owned confined artifact; it neither copies nor renders it and never exposes an absolute path;
- use existing authentication, Editor role hierarchy, authorization helpers, and audit path;
- do not weaken security, structural validation, SQL transactions/locks, idempotency, RBAC, safe errors, output confinement, or credential hygiene;
- do not add Phase 2 UI, Windows GUI, cancellation, automatic remote failed-job retry, webhooks, queues, arbitrary options/SQL/schedule expressions, distributed scheduling, or HA.

Required gate evidence:
- exact BatchTaskSpec mapping and absence of arbitrary fields/secrets;
- deterministic fingerprint same/conflict cases;
- both deadline checks and deadline-elapsed-during-execution;
- all six Design crash windows and process restart;
- one occurrence, one Phase 1A batch, one logical remote Job;
- remote/item/checkpoint/finalization reconciliation;
- manual-trigger RBAC/audit/idempotency;
- run/result APIs and all Word confinement/MIME/authentication cases;
- all Phase 1C tests and Phase 0/1A/1B regressions;
- full repository pytest, compileall, git diff --check, prohibited-import scan, credential/runtime-artifact scan;
- optional real deployment acceptance only with explicit authorized access.

Update persistent project memory with exact observed results. Never describe fake ODBC/transport tests as live acceptance. Keep Phase 1B live SQL status independent. If real Phase 1C deployment acceptance is unavailable, mark it NOT EXECUTED with reason and substitute repository evidence.

Commit all intended changes, push/create the PR if repository tooling permits, and report actual PR state. Completion report must include:
- repository, branch, recorded Gate A baseline SHA, initial/final tree, resulting SHA;
- every changed file and behavior change;
- exact RED/GREEN/focused/regression/full commands and counts;
- crash/idempotency/deadline/Word evidence;
- deviations with source evidence, or "none";
- residual risks and live acceptance status;
- commit list and PR URL/status.

Expected repository status after all gates pass: "Phase 1C repository gate ready for implementation review." Deployment PASS may be stated only after the real authorized procedure passes.
```
