# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval is in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 security, Phase 1A Batch Scheduler, Phase 1B Requirement import, Phase 1C-A control plane, and Phase 1C-B Requirement execution compatibility bridge are implemented. JT-1 and LangGraph remain NOT STARTED.
- Requirement scheduling is driven by separate `schedule-worker` and `handoff-worker` processes. `run_sra_api.sh` is the foreground supervisor for those workers and the API; Report Job Worker remains owned by API lifespan.
- An authorized operator completed the single-item Requirement Golden Path and separately reported three-item automatic technical Golden Path PASS. Full schema/migration, rollback/failure, fencing/failover, race/HA, security-rotation, and production content-quality matrices remain unproven.
- Environment limitations remain: package-index proxy checks may return 403; private deployment/Elasticsearch and authorized Requirement SQL are unavailable; browser/Playwright is absent.

## Recent Changes

### 2026-09-10 Rewritten SRA runtime-title takeover fix

- Corrected PR #230's stale API identity assumption. `sra_api/main.py` calls `init_proctitle(\"SRA-API\")` at import time; when `setproctitle` is installed, `sra_api/core/proctitle.py` replaces argv/cmdline and comm with `SRA-API | port=<port> | [<model> | ]pid=<os.getpid()> | <socket.gethostname()>`. This is process-title mutation, not a Docker PID namespace defect.
- The launcher now queries LISTEN sockets only; validates listener ownership, resolved cwd, effective UID, exact source-derived title/port/same-namespace PID/hostname (or preserved original uvicorn argv); and records PID/start-time/port atomically for launcher-owned API children. TERM is followed by bounded wait and revalidated KILL only for the same start time and listener identity.
- Strict TDD RED: `python -m pytest -q tests/test_run_sra_api_launcher.py::test_real_rewritten_runtime_title_is_reclaimed --tb=short` failed because the baseline launcher never started the replacement workers. Repository GREEN verification and live-deployment status are recorded below after final checks.

### 2026-09-10 Unified SRA operator launcher

- PR #230 established the single API + Schedule Worker + Handoff Worker supervisor, flock exclusion, direct-child cleanup, capped role logs, append-only kill audit, and fail-closed port takeover. Its original stale identity matcher relied on persistent uvicorn argv and was corrected by the follow-up above.

### 2026-09-10 Requirement Task Center requirements capture

- Recorded FUTURE / NOT STARTED operator-workflow requirements without changing runtime, historical plans, engine boundaries, RBAC, or credential/path exposure rules.

### 2026-09-10 Requirement schedule-worker clock precision hotfix

- Normalized the aware-UTC claim clock to second precision without changing recurrence, store, transaction, audit, or handoff semantics.

### 2026-09-09 Requirement schedule-worker implementation

- Added the external schedule-only runtime and CLI using the fixed `requirement-schedule-worker` actor and bounded poll configuration. Requirement/Batch boundaries remain unchanged.

## Verification

- Rewritten-title launcher verification passed: `bash -n run_sra_api.sh`; 27 focused launcher tests; the 134-test Requirement startup/schedule/handoff regression family; and `git diff --check`. Repository tests cannot substitute for the required post-merge validation inside the actual SRA container.
- Persistent-memory compaction archived the pre-compaction `memory.md` and `known_issues.md` at `.codex/archive/memory.md-20260910-070805.md` and `.codex/archive/known_issues.md-20260910-070805.md`; active files retain current conclusions and unresolved limitations.

## Archived History

- `.codex/archive/memory.md-20260910-070805.md`: complete memory before 2026-09-10 compaction.
- Older archive references remain discoverable from that preserved file.

### 2026-09-10 SRA self-bootstrapping deployment

- Added fail-closed deployment bootstrap provisioning for a persistent, exact-scope `requirement-handoff-runtime` Service Key and owner-only generated Handoff state. Normal restarts validate and reuse the same credential; exceptional same-name repair is explicit.
- The launcher now bootstraps before takeover, imports generated state through a fixed whitelist (never `source`/`eval`), closes flock FD 9 in children/log consumers, waits for API listener readiness, and records/reclaims positively verified Schedule/Handoff worker identities.
- Removed the obsolete duplicate launcher and added shell LF and generated-secret ignore policy.
- Verification: dependency installation completed using already-installed packages despite package-index proxy 403 warnings; deployment-bootstrap tests passed (5); launcher tests passed in bounded groups (29 total); `bash -n` and `git diff --check` passed. Live SD-1 through SD-7 deployment gates were not run because private SQL/runtime infrastructure is unavailable here.

### 2026-09-10 SRA deployment bootstrap implementation-review correction

- Closed the review blockers by requiring one exact active canonical Handoff key, making Python's validated state path authoritative for the shell importer, and reusing deterministic SQL connection plus signed-URL startup validation before runtime takeover.
- Credential repair now creates and persists the replacement before revoking the old key, rolls back an unpersisted replacement when possible, and can deterministically finish an interrupted post-replace old-key revocation. Ordinary bootstrap never repairs ambiguous keys.
- Added focused repair/failure tests and a process-level launcher regression proving SIGKILL releases flock while orphan workers remain available for positive identification and replacement-launcher reclamation.
- Verification: `python -m pytest -q tests/test_deployment_bootstrap.py tests/test_run_sra_api_launcher.py tests/test_requirement_sql_registry.py` passed (67 tests); `bash -n run_sra_api.sh` and `git diff --check` passed. Dependency installation used installed packages; the package-index proxy still returned 403 warnings while checking pip.

### 2026-09-10 SRA deployment bootstrap corrective review v2

- Historical PR #234 verification was reported inconsistently as 67/68 tests. That acceptance claim is superseded by this fresh corrective verification; SD-1 through SD-7 remained pending.
- Repair now journals the exact old/new key IDs before state replacement and re-reads protected state after a write error. It revokes the replacement only when state is proven unchanged; replacement or indeterminate state retains both keys for explicit journal-bound recovery.
- Explicit repair can replace one exact-scope, `deployment-bootstrap`-owned orphan canonical key when first-run state is absent. Recovery no longer infers obsolete keys from name/scopes/creator alone or revokes multiple unknown keys.
- Verification: dependency installation completed from installed packages (pip index checks still warned with proxy 403); `python -m pytest -q tests/test_deployment_bootstrap.py tests/test_run_sra_api_launcher.py tests/test_requirement_sql_registry.py --tb=short` passed 73 tests; `bash -n run_sra_api.sh` and `git diff --check` passed. This is repository evidence only; SD-1 through SD-7 remain pending and the historical Agent/ES/LLM/DOCX Golden Path was not replayed.

### 2026-09-10 SRA deployment bootstrap corrective review v3

- Repair journal v2 now records immutable operation context and whether state existed at transaction start. The repair layer selects the replacement key ID and persists that intent before key creation, so committed-before-response creation and interruption before first state creation remain attributable and restartable without revoking unknown keys.
- Missing-state recovery is allowed only for a journal-proven first-run orphan transaction whose active IDs are exactly the old key alone or the exact old/new pair. A journal originating from normal credential rotation still fails closed if its prior state disappears.
- Verification: dependency installation used installed packages despite pip-index proxy 403 retries; the focused deployment/launcher/SQL-registry suite passed 75 tests, Service Key store/API tests passed 3 tests, and `bash -n run_sra_api.sh` plus `git diff --check` passed. SD-1 through SD-7 remain pending; no Agent/ES/LLM/DOCX Golden Path was replayed.

### 2026-09-10 SRA deployment bootstrap corrective review v4

- Serialized each complete Python bootstrap/repair state-key-journal transaction with a deployment-state lock, including restartable recovery, so concurrent explicit repairs cannot overwrite one another's journal or leave an unattributed active key.
- Made every successful ServiceKeyStore atomic replacement directory-durable before returning; repair therefore retains its authoritative journal if the key-store directory fsync fails.
- Added process-level concurrent-repair coverage, post-replace key-store directory-fsync failure coverage, and direct custom-key-ID validation/collision/default-generation tests.
- Verification: dependency installation completed from installed packages despite pip-index proxy 403 retries; focused bootstrap/launcher/SQL-registry/ServiceKey store/API suite passed 86 tests; `bash -n run_sra_api.sh` and `git diff --check` passed. SD-1 through SD-7 remain pending and the Agent/ES/LLM/DOCX Golden Path was not replayed.

### 2026-09-10 Safe launcher restart and Handoff lease handoff

- A second `run_sra_api.sh` invocation now validates durable owner-only launcher evidence, asks that exact launcher to terminate, waits for flock and port release, and starts one replacement. Concurrent contenders are serialized and a contender older than the replacement cannot restart it again.
- Launcher evidence uses a separate atomic mode-0600 identity record; opening the runtime and takeover lock files is non-truncating. PID, Linux start time, effective UID, resolved cwd, resolved script path, and live cmdline are checked again immediately before SIGTERM. Unverified owners and graceful-shutdown timeouts fail closed without escalation.
- Handoff CLI SIGTERM/SIGINT now sets the coordinator stop event, allowing its existing `finally` block to release the fenced SQL lease before exit.
- Strict TDD RED was observed for missing launcher identity/restart and missing Handoff SIGTERM registration. GREEN verification: launcher/coordinator/lease suite passed 51 tests; deployment-bootstrap/SQL-registry/schedule-worker suite passed 91 tests (one expected development-signing warning); Bash syntax and diff checks passed. Live deployment acceptance was not run.
