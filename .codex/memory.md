# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval lives in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 security, Phase 1A Batch Scheduler, Phase 1B Requirement import, Phase 1C-A control plane, and Phase 1C-B Requirement execution compatibility bridge are present.
- Phase 1C-B uses SQL Server as Requirement lifecycle authority, a transactional audit outbox, an external fenced coordinator, immutable `report_v1` submissions, the existing owner-scoped Report Job HTTP API, and confined root-bound DOCX publication.
- Job Task JT-1 and LangGraph integration remain NOT STARTED. The Requirement Scheduler must remain framework-neutral and must not embed Batch Scheduler or Report Job persistence/worker internals.
- Phase 1B live Requirement SQL Server acceptance was initiated by an authorized operator and reproduced a DB-API catalog-row blocker; the repository correction is verified, but its post-fix live retest remains pending. Private Report Job + Agent + DOCX deployment E2E remains NOT EXECUTED.
- Environment limitations: package-index proxy may return 403; private deployment/Elasticsearch and authorized Requirement SQL are unavailable; Playwright/browser runtime is absent.

## Recent Changes

### 2026-09-09 Requirement Handoff SQL Server queue-lock compatibility

- Corrected the Prepare candidate scan from `UPDLOCK,HOLDLOCK,READPAST` to `UPDLOCK,READPAST,READCOMMITTEDLOCK` on `requirement_batch_run_items`; the joined `requirement_batch_runs` row retains `UPDLOCK,HOLDLOCK` and transaction, fencing, state-transition, and external-I/O boundaries are unchanged.
- The focused SQL-emission regression was RED against baseline `c012d17750ba84022dc5a27c64ac76bfbf6c5c67` with 1 failed and 16 passed because `READCOMMITTEDLOCK` was absent. After the production correction, the focused file passed 17 tests; handoff/transaction/deadline tests passed 96 tests; all Requirement tests passed 333 tests with 4 warnings; compileall and static diff checks passed.
- No live SQL integration harness was added. The supplied operator probe is the real-engine evidence for SQL Server error 650; repository CI uses the focused emitted-SQL contract regression. No live Golden Path DB/API records were accessed or mutated during this task.

### 2026-09-09 Requirement Handoff aware SQL clock boundary

- Centralized every Requirement Handoff lease/proof and second pre-handoff deadline clock read on SQL Server expression `TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')`, with fail-closed validation that the DB-API value is an aware UTC datetime.
- Preserved SQL Server clock authority, transaction/lock boundaries, lease fencing predicates, deadline terminal behavior, and the non-authoritative status of caller `now_utc`; no shared connection-layer or schema change was made.
- TDD evidence: focused lease/prepare tests were RED with 19 failures reproducing naive SQL clock versus aware `datetimeoffset` comparisons, then passed 25 tests. Direct handoff/transaction/deadline suites passed 95 tests; all Requirement tests passed 332 tests with 4 warnings; compileall and `git diff --check` passed. No live Golden Path DB/API records were accessed or mutated.

### 2026-09-09 Report Job gateway contract alignment

- Corrected the Requirement Handoff Report Job gateway to accept the API's successful `202` creation response and to reconcile from the native GET response field `status` rather than the nonexistent `state` field.
- Preserved deterministic submission identity/payload semantics, returned job-ID validation, native status translation, fail-closed malformed/unknown status handling, and 401/403/409 behavior.
- TDD evidence: the focused gateway suite was RED with 11 failures (the expected rejected `202`, missing `state`, and wrong unknown-status category), then passed 23 tests. Direct handoff tests passed 71 tests, the broader handoff subset passed 101 tests, and all Requirement tests passed 323 tests with 4 warnings. No live Golden Path records or private APIs were accessed or mutated.

### 2026-09-09 Requirement profile-version INSERT parameter correction

- Corrected `RequirementStore.create_profile_version()` so the 13-column `import_profile_versions` INSERT binds all ten non-NULL values in schema order before the three approval/retirement NULLs.
- Added a regression that verifies the ten SQL markers, bound parameter count and order, serialized profile, canonical digest, draft metadata, and offset-aware creation timestamp. Verification passed: 307 Requirement tests with 2 warnings, Requirement package compileall, and `git diff --check`.

### 2026-09-09 SQL Server DATETIMEOFFSET result decoding

- Fixed Requirement named SQL connections to register a pyodbc output converter for SQL Server `DATETIMEOFFSET` type code `-155`, decoding the driver binary representation into timezone-aware Python `datetime` values without changing the SQL schema or queries.
- TDD evidence: the focused registry suite first failed 6 tests because the converter and decoder were absent, then passed 21 tests. Coverage includes converter registration, UTC, positive and negative offsets, fractional seconds, and NULL.
- Repository verification: all Requirement tests passed 306 tests with 3 warnings; compileall and `git diff --check` passed. The full suite reached 677 passed, 1 failed, and 10 warnings; the sole failure is the pre-existing tracked raw-key operator-harness finding in `tests/test_batch_scheduler_security.py::test_phase0_harness_has_no_raw_key_literal`. Post-fix deployed API retest was NOT EXECUTED and remains required.

### 2026-09-08 Phase 1C SQL Server CHECK-expression normalization

- The operator's Phase 1B post-PR #218 live startup progressed successfully past `RequirementStore.initialize()`; Phase 1B DB-API catalog-row comparison is no longer the active live blocker.
- Phase 1C live startup then reproduced `ScheduleStore.initialize()` rejection because SQL Server reports canonical `<column> NOT LIKE <pattern>` CHECK predicates as the logically equivalent `NOT [<column>] LIKE <pattern>`. The repository correction narrowly rewrites that unquoted operator placement before the existing exact normalization and comparison.
- TDD evidence: the live-equivalent helper and `validate_catalog_evidence()` regressions were RED with 3 failures before production modification, then the focused closure file passed 73 tests. Scheduler tests passed 109 tests with 4 warnings, handoff tests passed 78 tests, and all Requirement tests passed 300 tests with 2 warnings. Negative cases retain fail-closed rejection for wrong column, pattern, length, negation, and NULL condition.
- The full repository result was 671 passed, 1 failed, and 10 warnings; the failure is the pre-existing tracked raw-key operator-harness finding in `tests/test_batch_scheduler_security.py::test_phase0_harness_has_no_raw_key_literal`. Post-fix live SQL startup retest was not executed and remains pending operator execution.

### 2026-09-08 Phase 1B DB-API catalog-row normalization

- Operator live acceptance reproduced a Phase 1B startup blocker: named PK/UQ and FK catalog rows had matching scalar evidence but driver row containers did not compare equal to canonical Python tuples.
- `RequirementStore.initialize()` now converts generic DB-API catalog rows to plain scalar tuples before exact comparison; regression coverage proves canonical sequence rows pass while wrong named-key ownership and wrong FK referenced-table evidence still roll back and fail closed.
- TDD evidence: the new positive regression failed before the production correction and passed afterward. Requirement Store passed 67 tests; the requested focused files passed 1, 1, 10, 7, and 15 tests; all Requirement tests passed 292 tests with 2 warnings. Compileall and diff/static checks passed. The full repository gate stopped at a pre-existing security test because a tracked operator harness contains raw-looking key literals; this task did not modify that harness.
- Live SQL pre-fix blocker reproduction was executed by the operator. Post-fix live SQL retest was not executed and remains required.

### 2026-09-08 Requirement SQL registry DB configuration alignment

- Kept Excel-to-SQL and Requirement/Schedule registries separate while aligning their inner SQL Server keys. Requirement now supports canonical direct keys, shared `auto`/`detect` ODBC selection, explicit drivers, and authoritative fail-closed legacy `*_env` sources.
- Added pre-connect validation for server, database, and SQL-auth credentials; trusted authentication omits UID/PWD, connection creation remains `autocommit=False`, the local password-bearing registry is ignored, and operations guidance documents both configuration modes.
- TDD evidence: the new focused suite initially failed 10 tests for literal `DRIVER={auto}`, absent validation/shared resolution, and the legacy example contract. After implementation, focused SQL suites passed 22 tests; Requirement source/startup/integration passed 7/1/1; schedule and handoff regressions passed 101 and 78 tests (4 schedule warnings); the full repository suite passed 661 tests with 10 warnings. Compileall and `git diff --check` passed. No live SQL Server or private Report Job/Agent/DOCX E2E was executed.

### 2026-09-08 Python 3.10 StrEnum compatibility

- Replaced the three unconditional Python 3.11-only `enum.StrEnum` imports in Requirement import and scheduling production models with one shared compatibility definition. Python 3.11+ retains the stdlib implementation; Python 3.10 uses a string/Enum fallback with value-preserving string behavior.
- Added Requirement enum value and Pydantic parse/JSON serialization regressions. Verification: focused Requirement/API tests 90 passed; all Requirement tests 274 passed; repository `tests/` suite 646 passed with 10 warnings; current-runtime Requirement and SRA API import smoke checks passed; compileall and static checks passed.
- Python 3.10.20 executed the dependency-free compatibility helper smoke successfully. Full Python 3.10 Requirement/SRA imports were not executed because that interpreter lacks project dependencies and the package index returned HTTP 403 while attempting installation.

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
