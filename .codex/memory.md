# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval is in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 security, Phase 1A Batch Scheduler, Phase 1B Requirement import, Phase 1C-A control plane, and Phase 1C-B Requirement execution compatibility bridge are implemented. JT-1 and LangGraph remain NOT STARTED.
- Requirement scheduling uses separate `schedule-worker` and `handoff-worker` processes supervised with the API by `run_sra_api.sh`; the Report Job Worker remains owned by API lifespan.
- Operator-supplied evidence covers the single-item Requirement Golden Path and three-item automatic technical Golden Path. Complete schema/migration, rollback/failure, fencing/failover, race/HA, security-rotation, and production content-quality matrices remain unproven.
- The automatic operator E2E harness remains an observer of deployed public APIs and existing workers. Repository verification must not be described as fresh live deployment acceptance.
- Environment limitations remain: package-index proxy checks may return 403; private deployment/Elasticsearch and authorized Requirement SQL are unavailable; browser/Playwright is absent.

## Recent Changes

### 2026-09-16 Operator E2E configuration and platform UX hotfix

- Added a tracked, credential-free common `operator_e2e/e2e.env.example` for Phase 0 and Requirement operator tools while retaining the ignored local secret file. Phase 0 now prefers `SRA_E2E_BASE_URL` with the legacy base-name fallback; Phase 0 Service Keys remain explicitly separate from Requirement Editor authentication.
- The Requirement harness now imports without `fcntl` on unsupported systems, but live execution fails closed as `unsupported_platform` during `CONFIG_PREFLIGHT` before lock acquisition or `Harness.run()`. Missing local configuration similarly reports `configuration_file_missing` with copy/setup guidance unless process variables alone form usable Requirement configuration.
- Strict TDD RED was recorded as the expected missing `validate_live_platform` collection error. GREEN passed 42 focused Harness tests and 466 Requirement API/import/Schedule/worker/Handoff/Report Job/launcher regressions (six pre-existing warnings), plus help, compilation, ignore-policy, protected-file, and diff checks. Package requirements were already installed; the pip index lookup repeated the known HTTP 403 proxy warning.
- The live deployment Harness was deliberately not executed. No fresh live Requirement, Agent, Elasticsearch, LLM, or DOCX E2E PASS is claimed.

### 2026-09-15 Requirement E2E reviewed-worktree hardening

- When an externally supplied reviewed runtime SHA and local Git identity are available, source preflight now requires both exact `HEAD` equality and a clean worktree. A dirty reviewed worktree fails as `runtime_source_dirty` at `CONFIG_PREFLIGHT` with exit code 2 before `Harness.run()` or live mutation; mismatches remain `runtime_source_identity_mismatch`.
- The runbook retains the stable XLSX SHA-256 but uses a non-literal runtime placeholder. Runtime identity comes from the completed post-merge review/acceptance handoff, must equal the deployment worktree `git rev-parse HEAD`, and may not be self-attested or copied from stale repository history.
- Strict TDD RED produced two expected focused failures (dirty worktree and literal runbook SHA). GREEN passed 34 focused Harness tests, a broader 313-test Requirement API/import/Schedule/worker/Handoff/Report Job/launcher regression, and Python compilation. The live deployment Harness was not executed; no fresh live E2E PASS is claimed.
- Compacted the prior `memory.md` to `.codex/archive/memory.md-20260915-170533.md` after it exceeded 20 dated/work-record sections; active conclusions and recent high-value changes remain here.

### 2026-09-15 Requirement E2E input/runtime identity separation

- `SRA_E2E_EXPECTED_SOURCE_SHA` binds only the optional 64-character lowercase XLSX byte SHA-256; `SRA_E2E_EXPECTED_RUNTIME_SHA` independently binds reviewed Git identity. Malformed identities fail during `CONFIG_PREFLIGHT`, and available local Git SHA mismatches fail before live API mutation.

### 2026-09-15 Requirement Snapshot recovery correction

- Ambiguous Import recovery compares durable Snapshot fields `source_snapshot_sha256` and `import_profile_version_id`, excludes every pre-existing Snapshot ID in the exact Source/Requirement Set context, and accepts only a newly observed matching Snapshot.

### 2026-09-15 Requirement automatic operator E2E harness

- The harness uses immutable Schedule/Batch identities, disables its Schedule immediately after recurrence advancement, uses resolved output configuration for lock/evidence/artifacts, emits bounded redacted diagnostics, and independently verifies three DOCX artifacts.
- Package/overlay deployment identity remains governed by its separately approved externally anchored manifest mechanism; this harness hotfix does not change that boundary.

### 2026-09-15 SRA live acceptance command review

- The v1.4 runbook correction validates `${PORT:-9002}` with bounded exact Linux listener authority and describes cycle-driven renewal accurately. SD-1 through SD-7 remain PENDING and were not executed here.

### 2026-09-10 Deployment bootstrap and unified launcher

- The launcher supervises API, Schedule Worker, and Handoff Worker with positive process/listener identity, durable owner-only records, bounded cleanup, serialized takeover, and fail-closed bootstrap. Report Job Worker ownership remains with API lifespan.
- Requirement Handoff credential repair uses journaled, durable, serialized transactions. Live deployment acceptance of these paths remains pending.

### 2026-09-09 Requirement scheduling and handoff

- Schedule materialization uses a separate bounded-poll worker and DB-time/second-precision claim clock. Handoff uses durable queue leasing/fencing and owner-scoped Report Job compatibility without changing Agent/Elasticsearch/LLM boundaries.

## Verification Summary

- Latest focused result: 42 Requirement operator Harness tests passed.
- Latest broader related regression: 466 Requirement API/import/Schedule/worker/Handoff/Report Job/launcher tests passed with six pre-existing warnings.
- Python compilation and protected-file/diff checks passed for the latest Harness hardening.
- Dependency requirements were installed already; pip's upgrade lookup repeated the known HTTP 403 proxy warning.
- No live Requirement E2E, private SQL, Elasticsearch, LLM, Agent, deployment bootstrap, or credential mutation was performed by the latest task.

## Archived History

- `.codex/archive/memory.md-20260915-170533.md` — compacted 2026-09-15; full pre-hardening history through the Requirement E2E source-identity split and prior deployment/runbook verification.
- Earlier archives listed in that file remain available under `.codex/archive/` for traceability.

### 2026-09-16 Requirement Automatic Operator E2E Harness v2

- Added baseline-bound Design/Plan v2, a shared local/remote evidence-provider architecture, default canonical XLSX with automatic digest binding, mandatory reviewed runtime authority, cross-platform operator locking, and result schema v2.
- Added authenticated superuser-only read-only deployment runtime evidence and reused the existing Report Job download route for remote DOCX bytes. No DB or Scheduler/Handoff/Report Job execution semantics changed.
- Strict RED was represented by the initial focused compatibility failures before v2 updates; GREEN passed 50 focused tests, 68 API/launcher/bootstrap tests, and 514 broad Requirement/Report Job/launcher/bootstrap tests. Compilation and diff checks passed. Pip package-index lookup warned HTTP 403, but dependencies were already installed.
- No live deployment Harness was executed and no fresh live Requirement/Agent/Elasticsearch/LLM/DOCX PASS is claimed.

### 2026-09-16 Harness v2 authoritative Handoff artifact hotfix

- Remote acceptance no longer uses upstream Report Job `/word` bytes as artifact authority. A new GET-only, authenticated superuser route binds immutable Batch/Run Item IDs to existing durable Handoff metadata and returns bytes only after configured-root fingerprint, relative-path confinement, non-symlink file, DOCX ZIP safety/integrity, and SHA-256 validation.
- The remote provider downloads through that route, preserves distinguishable authentication/authorization and artifact failure categories, independently validates DOCX/SHA, and copies exact verified bytes into invocation evidence. No DB schema or Schedule/Handoff/Report Job execution semantics changed.
- Strict RED reproduced 10 failures, including the missing endpoint and the old provider's attempted Report Job `/word` request while a source DOCX could exist. GREEN passed 68 focused Harness/store tests, 41 API/store/Handoff/Report Job tests, and 531 broad Requirement/Report Job/launcher/bootstrap regressions (four pre-existing warnings). Python compilation, diff whitespace, hosted-base ancestry, and canonical XLSX unchanged checks passed.
- Dependency packages were already installed; pip's upgrade lookup repeated the known HTTP 403 proxy warning. No live Agent/ES/LLM/DOCX acceptance was executed and no fresh live E2E PASS is claimed.

### 2026-09-16 Remote Deployment Acceptance blocked at configuration preflight

- Confirmed the clean operator checkout was exactly reviewed Git SHA `2925065c71abbd7ea8aeee6d0d1189568c05adee`, and the canonical XLSX SHA-256 was exactly `2d50bed20a3e697020107ece218e7c001580e1df03adc1c30f8060c4e9118d03` before invocation.
- Ran the single authorized command `python operator_e2e/test_requirement_schedule_e2e.py --mode remote` with both expected identities bound. It stopped before `Harness.run()` at `CONFIG_PREFLIGHT` with `configuration_file_missing` because no `operator_e2e/e2e.env.local` or usable process configuration supplied the actual deployment URL, model, and superuser user-session credential.
- Evidence is retained under the ignored invocation directory `operator_e2e/output/requirement_e2e/20260916T041830Z-a7e5e61a/`. No deployment request, runtime-evidence verification, production write, Golden Path, cleanup, or live PASS occurred; the acceptance result is BLOCKED pending authorized configuration.

### 2026-09-16 Harness v2 source/deployment evidence corrective hotfix

- Replaced literal operator SHA/clean-tree gates with reviewed-ancestor, repository-role committed/dirty classification. Exact and documentation-only descendants pass; runtime commits or dirty runtime/importable files block.
- Added deterministic incremental-package provenance plus server-side runtime byte and active-module/path checks. Inactive residual Python files warn rather than block; changed reviewed files, loaded residual modules, and shadow paths block. External reviewed Git objects remain the independent hash authority.
- RED: 12 focused tests failed before implementation. GREEN: focused Harness/source/deployment/manifest suite passed 119 tests; broader verification is recorded with the final task result. No live Golden Path was executed.
- Final verification: focused source/Harness/deployment suite passed 119 tests; compilation and diff checks passed. Full `tests` run passed 938 and failed 12 due to documented pre-existing/order-dependent missing-file, namespace-guard, and dependency-override identity issues; no live Golden Path was run.
