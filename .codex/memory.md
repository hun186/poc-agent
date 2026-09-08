# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval lives in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 security, Phase 1A Batch Scheduler, Phase 1B Requirement import, Phase 1C-A control plane, and Phase 1C-B Requirement execution compatibility bridge are present.
- Phase 1C-B uses SQL Server as Requirement lifecycle authority, a transactional audit outbox, an external fenced coordinator, immutable `report_v1` submissions, the existing owner-scoped Report Job HTTP API, and confined root-bound DOCX publication.
- Job Task JT-1 and LangGraph integration remain NOT STARTED. The Requirement Scheduler must remain framework-neutral and must not embed Batch Scheduler or Report Job persistence/worker internals.
- Live Requirement SQL Server acceptance and private Report Job + Agent + DOCX deployment E2E remain NOT EXECUTED because no explicitly authorized environment was supplied. Stateful fake DB-API evidence is repository acceptance only.
- Environment limitations: package-index proxy may return 403; private deployment/Elasticsearch and authorized Requirement SQL are unavailable; Playwright/browser runtime is absent.

## Recent Changes

### 2026-09-07 Phase 1C-B post-PR #214 acceptance closure

- Added a stateful transaction-copy DB-API harness and production-method acceptance for Prepare, Acknowledge, Reconcile, artifact evidence/closure, terminal checkpoint Cases A-E, counter recomputation, fencing, safe audit payloads, and rollback injection.
- Acceptance exposed two production defects: `ScheduleStore` omitted the `ExecutionManifest` import on replay/ACK paths, and Prepare treated every submission insert exception as a duplicate race. The minimal correction imports the type and only reconciles SQL Server duplicate-key errors (`23000` plus `2601`/`2627`); other persistence failures roll back.
- Verification: focused bridge/schema suite 87 passed; Requirement Schedule suite 101 passed with 4 warnings; full repository 644 passed with 10 warnings. `compileall` and final static/security scans are recorded after execution.
- Live SQL Server acceptance: NOT EXECUTED. Private Report Job + Agent + DOCX deployment E2E: NOT EXECUTED. Hosted CI was not available from the unauthenticated checkout.

### 2026-09-07 Phase 1C-B production bridge (PR #214)

- Added canonical schema v3, immutable handoff submissions, coordinator leases/fencing, neutral Report Job gateway, Prepare/ACK/reconciliation transactions, root-bound artifact publication, atomic terminal checkpoint/counter closure, independent CLI coordinator, and neutral management evidence.
- HTTP and filesystem operations remain outside SQL transactions. Same-version/same-RequirementVersion intentional reruns complete without checkpoint conflict; equal version numbers with different immutable IDs fail closed.

### 2026-09-05 Phase 1C-A source-faithful closure

- Canonical schema v2 uses complete SQL Server catalog evidence, transactional migrations, same-schedule integrity, SQL audit outbox authority, and bounded at-least-once JSONL projection.

### 2026-09-04 Phase 1C-A control plane

- Implemented structured recurrence, coalesced due calculation, immutable schedule versions, snapshot-bound materialization, checkpoints, selection/expiry behavior, and authenticated management APIs.

### 2026-09-04 Phase 1B repository closure

- Requirement SQL authority, immutable versions/snapshots, strict import/schema validation, diagnostics, RBAC, and repository acceptance are present. Live SQL remains NOT EXECUTED.

### 2026-09-04 Phase 1A Batch Scheduler Core

- Standalone CSV/XLSX/JSON batch ingestion, SQLite state, Report Job HTTP client, deterministic idempotency, restart reconciliation, and confined atomic DOCX publication are present.

### 2026-09-03 Phase 0 security closure

- Scoped principals, signed capabilities, Service Keys, owner-aware Report Jobs, denial auditing, and migration rollback coverage are present.

## Archived History

- `.codex/archive/memory.md-20260907-120000.md` — complete active memory before the 2026-09-07 acceptance-closure compaction.
- `.codex/archive/memory.md-20260904-220000.md` — earlier detailed history through the Phase 1B/early Phase 1C baseline.
