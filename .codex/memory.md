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

### 2026-09-04 Phase 1C-A Review v1 closure correction

- Closed schema/FK/index/column validation, scheduled duplicate-race reconciliation, canonical `reqrun-`/external-item identities, direct configuration validation, transactional fake-ODBC evidence, bounded API list/detail and RBAC/audit regressions, and safe resource taxonomy findings.
- Finding G remains a Design-level blocker: lifecycle SQL commits and the canonical filesystem JSONL audit append cannot form one atomic transaction. No distributed transaction or second audit authority was invented; Phase 1C-B remains prohibited.
- Verification: focused 28 passed/0 failed/0 errors/2 warnings; Phase 1B 88 passed/0 failed/0 errors/2 warnings; Phase 1A 24 passed/0 failed/0 errors/0 warnings; Phase 0 27 passed/0 failed/0 errors/3 warnings; full suite before the final audit-matrix test 485 passed/0 failed/0 errors/10 warnings. Final full/static results are recorded in the task report.
- Phase 1C and Phase 1B live SQL Server acceptance: NOT EXECUTED; no explicitly authorized SQL Server access was supplied.
- Final rerun after the HTTP audit matrix: full repository 486 passed/0 failed/0 errors/10 warnings.

### 2026-09-05 Phase 1C Design/Plan v3 correction

- Phase 1C Design v3 supersedes v2 because lifecycle success requires transactional SQL audit authority, Phase 1C needs formal schema v2 evolution with recognized-v1 migration, and `phase1a_task_id` must match the Phase 1B 240-character external identity contract. Historical v1/v2 documents remain unchanged.
- Authored the documentation-only v3 Design, incremental C1–C8 TDD closure Plan, and two execution contracts. The design selects composite same-schedule version ownership and an SQL outbox with at-least-once projection through existing `append_audit_event()` using stable event IDs.
- Phase 1C-A implementation exists, but its repository gate is NOT PASS pending v3 closure implementation and post-merge review. Phase 1C-A v3 closure implementation is NOT STARTED. Phase 1C-B is NOT STARTED.
- Verification was documentation/static only: `git diff --check`, placeholder/contract consistency scans, and runtime-scope status inspection passed; no runtime pytest was required or used to claim implementation.

### 2026-09-05 Phase 1C Design/Plan v4 compatibility correction

- Design/Plan/Prompts v4 supersede v3; v1–v3 remain historical. The architecture remains canonical schema v2 with direct fresh-v2 initialization, transactional v1→v2 migration, same-schedule composite integrity, and a transactional SQL audit outbox projected at least once through existing JSONL audit.
- v4 corrects exact PR #200/#201 catalog classification, a narrow PR #200 persisted-identity repair guarded by proof that Gate B never ran, legacy active/approved configuration validation, outbox-created lifecycle timestamp projection, and pending-row CAS delivery metadata.
- Documentation only: no closure implementation or tests were changed. Phase 1C-A repository gate remains NOT PASS; Phase 1C-A v4 closure implementation is NOT STARTED; Phase 1C-B is NOT STARTED.
- Verification: `git diff --check`, placeholder/cross-document scans, and changed-file scope inspection passed; no runtime tests were used to claim implementation.

### 2026-09-05 Phase 1C-A v4 closure implementation

- Raised the Requirement Schedule authority to canonical schema v2, with direct fresh-v2 DDL, strict reviewed-v1 descriptor classification, marker-last migration ordering, same-schedule ownership constraints, exact 240-character selected external identities, and guarded PR #200 identity repair statements. Phase 1C-B remains not started.
- Added same-transaction lifecycle audit outbox writes and bounded at-least-once JSONL projection. Projection preserves immutable outbox `created_at` as lifecycle `ts`; success and failure delivery metadata use pending-row compare-and-set and never claim SQL/filesystem atomicity or JSONL exactly-once behavior.
- Repository verification: Phase 1C focused 33 passed with 2 warnings; focused cross-phase regression 172 passed with 3 warnings; full repository 491 passed with 10 warnings. Compile/static checks were completed after the final edits. Live SQL Server acceptance was NOT EXECUTED because no explicit authorization or connection was supplied.

### 2026-09-05 Phase 1C Design/Plan v5 source-baseline correction

- Rebaselined documentation against actual `main` merge `d56a8a061446400e324384f2719af3c95ba7d0af` (PR #204) and re-read PR #200/#201 source. Design/Plan/Prompts v5 supersede v4 and correct the false claim that PR #201 widened vocabulary/state columns; both v1 DDLs use the same reviewed widths.
- v5 documents PR #204 closure defects: fake-only catalog access, transformed rather than explicit v2 DDL, incomplete shape-specific migration/marker/Gate-B validation, persisted RunPolicy conversion, outbox schema/index drift, dead projection wiring, and incomplete CAS result semantics/closure coverage.
- The architecture is unchanged: canonical schema v2, transactional recognized-v1 migration, 240-character task identity, same-schedule composites, transactional SQL outbox, and stable at-least-once JSONL projection.
- This was documentation-only; no production or test code changed. Phase 1C-A remains **NOT PASS** pending v5 implementation and post-merge review. Phase 1C-B remains **NOT STARTED**.
- Documentation verification passed: `git diff --check`, unresolved-placeholder scan, cross-document contract scan, and changed-file scope inspection. No runtime tests were run because this task changes no production/test code and makes no runtime completion claim.

### 2026-09-05 Phase 1C-A v5 closure correction

- Rebaselined the available checkout at `974be3555ca0bb4a4699cbe9b8758c08c02d2f04` (`work`, merge of PR #205); this checkout has no configured remotes, so hosted `main` could not be fetched independently. Source history contains PR #200/#201/#204 and the v5 documentation baseline.
- Replaced the fake-only v1 classifier hook with parameterized SQL Server `sys.*` DB-API catalog reads, corrected source-derived widths, added complete descriptor matching, explicit fresh-v2 DDL, separate PR #200/#201 migration operations, complete repair guards, explicit `RunPolicy` coercion, and the exact v5 outbox/index contract.
- Added action-specific payload allowlists and bounded best-effort startup/post-commit audit projection; pending delivery success/failure use CAS and lost races are neutral. Phase 1C-B remains NOT STARTED.
- TDD evidence: the pre-change focused migration/audit run failed 1 test because the old classifier required `requirement_schedule_catalog`; after correction the focused closure matrix passed 10 tests. Phase 1C passed 43 tests with 2 warnings; cross-phase passed 182 tests with 3 warnings; full repository passed 501 tests with 10 warnings. Compile/static and scope evidence is recorded in the task handoff.
- Live SQL Server acceptance was NOT EXECUTED because no explicitly authorized SQL Server connection was supplied; realistic DB-API scripted/recording tests are repository evidence, not deployment acceptance.
