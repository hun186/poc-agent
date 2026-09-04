# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval lives in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 unified API security is present: user/service principals, scoped Service Keys, owner-isolated Report Jobs, signed browser capabilities, and canonical Editor RBAC/audit.
- Phase 1A Batch Scheduler Core is present in `batch_scheduler/`. It is a standalone SQLite-backed client of the existing Report Job HTTP API, uses deterministic idempotency, and publishes validated DOCX files under a confined local root.
- Phase 1B Requirement import is present in `data_ingestion/requirements/` with SQL Server authority, immutable RequirementVersion/Snapshot history, strict imports, structural schema validation, authenticated management APIs, and repository gate PASS.
- Phase 1B live Requirement SQL Server acceptance remains **NOT EXECUTED** because no explicitly authorized connection/credential is available. Fake ODBC evidence is repository evidence only.
- Phase 1C is not implemented. Its authoritative Design v1, Plan v1, and execution prompts define a separate `requirement_scheduler/` control plane and two future merge gates.
- Current Report Job worker is a FastAPI-process thread with local SQLite/artifacts. Phase 1C scheduling must not be added to FastAPI lifespan; it uses a separate one-active-worker process and consumes Phase 1A only.
- Roles are `data_reader`, `data_editor`, `db_operator`, `superuser`. New management APIs must reuse existing Editor authentication, authorization helpers, and audit path.
- Environment limitations: private deployment/Elasticsearch and authorized Requirement SQL are unavailable; package-index proxy may return 403; Playwright/browser runtime is absent. Repository tests/static checks are substitutes, not deployment acceptance.

## Recent Changes

### 2026-09-04 Phase 1C Design/Plan v1

- Authored the authoritative documentation-only Phase 1C Schedule Policy + Batch Management design, two-gate TDD implementation plan, and copy-paste-ready Gate A/Gate B Codex execution contracts against actual HEAD `bbaec0bf168ce9dd80f9c0a38dac27ad1542dc6f` (PR #197 present).
- Chose separately versioned SQL schema `sra_schedule`, immutable schedule versions, structured daily/weekly/monthly/interval recurrence, `coalesce_latest`, explicit policy checkpoints, deterministic Phase 1A seam/handoff, an external one-active-worker process, and reference-only Phase 1A-owned Word history.
- Documentation-only verification: `git diff --check`, placeholder scan, consistency/scope scan, and final tree inspection. No runtime tests were used to claim Phase 1C behavior; implementation remains not started. Phase 1B live SQL acceptance remains NOT EXECUTED.
- Compacted this active memory because it contained more than 20 dated/work blocks. The complete pre-compaction text is archived at `.codex/archive/memory.md-20260904-220000.md`; archive equality was verified before this rewrite.

### 2026-09-04 Phase 1B PR #197 compatibility fix

- Actual baseline is merge commit `bbaec0bf168ce9dd80f9c0a38dac27ad1542dc6f`. DB-API row handling supports `pyodbc.Row` while repairing diagnostic nullability.

### 2026-09-04 Phase 1B repository closure

- Canonical PK/UQ/FK validation proves owning tables and ordered columns while accepting narrowly scoped SQL Server-generated legacy key names. Transaction, immutable profile/version/snapshot, diagnostics, error taxonomy, and RBAC regressions passed.
- Recorded repository gates: Requirement store 63 passed; Phase 1B 87 passed with 4 warnings; Phase 0/1A 62 passed with 3 warnings; full repository 457 passed with 10 warnings.

### 2026-09-04 Phase 1A Batch Scheduler Core

- Added standalone CSV/XLSX/JSON batch ingestion, versioned SQLite state, narrow Report Job HTTP client, deterministic idempotency, restart reconciliation, and confined atomic DOCX publication.
- Live two-task private deployment acceptance remains pending.

### 2026-09-03 Phase 0 v3 closure

- Completed scoped principals, signed-resource hardening, service-key administration, owner-aware Report Jobs, denial auditing, migration rollback coverage, and full repository regressions.
- Private deployment acceptance was not executed because the target was intercepted with uniform HTTP 403 responses.

### 2026-09-01 Report Job APIs

- Added synchronous Word and persisted Job create/status/download resources. Chat and synchronous Word share transport-neutral turn execution. Local worker/SQLite/DOCX limits remain explicit.

### 2026-08-27 Reference-text contract

- `SRA_REFERENCE_TEXT_FIELD` coordinates ingestion, Agent, evidence, and document APIs; raw/reference/both layers remain explicit and auditable.

## Archived History

- `.codex/archive/memory.md-20260904-220000.md` — full active memory before 2026-09-04 compaction, covering detailed work records through the Phase 1B PR #197 baseline.
- Other historical architecture/decision/backlog archives remain listed in their respective active files and are loaded only when traceability requires them.

### 2026-09-04 Phase 1C Design Review v1 corrections

- Phase 1C Design v1 / Plan v1 / Prompts v1 are superseded by v2 after Design Review v1; runtime implementation remains NOT STARTED.
- Design/Plan v2 bind checkpoint chronology to immutable RequirementVersion numbers, define pause/re-enable/version-activation transactions, allow monotonic A→B→A configuration reversion, persist and verify `phase1a_output_root_fingerprint`, and scope manual request identity per schedule.
- Documentation verification used `git diff --check`, placeholder and forbidden-semantics scans, cross-document consistency checks, and tree inspection; no runtime pytest was required or used to claim runtime behavior.

### 2026-09-04 Phase 1C-A control plane

- Implemented structured recurrence, coalesced due calculation, separately versioned `sra_schedule` schema evidence, schedule/version lifecycle, snapshot-bound immutable run materialization, policy/checkpoint/selection-expiry behavior, and authenticated control-plane APIs.
- Focused repository verification: 16 passed, 0 failed, 0 errors, 2 warnings. Full/regression verification is recorded in the final task result after execution.
- Phase 1C-A control plane repository gate ready for implementation review.
- Phase 1C implementation incomplete.
- Outbound execution absent.
- Phase 1C live SQL Server acceptance: NOT EXECUTED (no explicitly authorized SQL Server access was supplied). Phase 1B live SQL Server acceptance remains NOT EXECUTED.
- Final verification evidence: Phase 1C-A 16 passed/0 failed/0 errors/2 warnings; Phase 1B 88 passed/0 failed/0 errors/2 warnings; Phase 1A 24 passed/0 failed/0 errors/0 warnings; Phase 0/security 27 passed/0 failed/0 errors/3 warnings; full repository 474 passed/0 failed/0 errors/10 warnings. `compileall`, `git diff --check`, prohibited-import scan, changed-file credential scan (24 files, 0 hits), and tracked runtime-artifact scan (0) passed.
