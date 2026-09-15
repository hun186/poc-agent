# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval is in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 security, Phase 1A Batch Scheduler, Phase 1B Requirement import, Phase 1C-A control plane, and Phase 1C-B Requirement execution compatibility bridge are implemented. JT-1 and LangGraph remain NOT STARTED.
- Requirement scheduling is driven by separate `schedule-worker` and `handoff-worker` processes. `run_sra_api.sh` is the foreground supervisor for those workers and the API; Report Job Worker remains owned by API lifespan.
- An authorized operator completed the single-item Requirement Golden Path and separately reported three-item automatic technical Golden Path PASS. Full schema/migration, rollback/failure, fencing/failover, race/HA, security-rotation, and production content-quality matrices remain unproven.
- Environment limitations remain: package-index proxy checks may return 403; private deployment/Elasticsearch and authorized Requirement SQL are unavailable; browser/Playwright is absent.

## Recent Changes

### 2026-09-15 Requirement Snapshot recovery field-name hotfix

- Corrected only the operator Harness ambiguous Import recovery to compare durable Snapshot fields `source_snapshot_sha256` and `import_profile_version_id` against the Preview SHA and exact active Profile Version; the production Requirement API and schemas are unchanged.
- The focused fake API regression now models complete durable Snapshot identities, includes two historical same-content/Same-Profile Snapshots, simulates commit-followed-by-timeout, and proves recovery preserves the new `snapshot_id` and `import_run_id` with exactly one Import POST.
- Strict TDD RED failed the new recovery scenario against baseline `1719adea390a5a90ddbd3d38b2dd4f3e9afcf3a3`. GREEN passed the 24-test Harness suite and the prescribed 196-test Requirement API/import/Schedule/worker/Handoff/Report Job/launcher regression. The live deployment Harness was intentionally not executed, so no fresh live E2E PASS is claimed.

### 2026-09-15 Requirement automatic operator E2E harness hotfix

- Kept Schedule enablement ownership separate from immutable Batch polling identity: the harness still disables immediately after proving `next_run_at` advancement, then polls the Batch with its persisted `schedule_id` and `batch_run_id`.
- Made the successfully resolved `E2EConfig.output_dir` authoritative for the invocation lock, artifact copies, and final evidence, while retaining a default/CLI-safe evidence destination when configuration loading fails.
- Import ambiguous-write recovery now snapshots every pre-existing Snapshot ID for the exact E2E Source's Requirement Sets and permits only newly observed IDs to match SHA/profile identity.
- Strict TDD RED reproduced all three defects. GREEN verification passed the focused harness suite (24 tests) and the original Requirement API/import/Schedule Store/API/worker/Handoff/Report Job/launcher regression subset (196 tests). The live deployment E2E was intentionally not executed.

### 2026-09-15 Requirement automatic operator E2E harness v1

- Added the offline deployment-host XLSX harness, stable Profile/Source/Schedule fixtures, unique import/snapshot/version/run evidence, automatic scheduled-Batch identity checks, Handoff/Report Job terminal polling, verified DOCX copies, redacted bounded diagnostics, exit-code/cleanup handling, and operator documentation.
- Extended only the existing Batch GET read projection with already-durable Snapshot, output-root, and remote-job evidence; no schema, migration, or write-semantics change was made.
- Strict TDD recorded focused RED failures before the projection, harness module, and tracked XLSX fixture existed. Focused harness tests passed 21 tests; Schedule projection/API/v5 regression passed 79 tests. The required 196-test regression set had one launcher SIGINT timing failure, and that exact test passed immediately in isolated rerun. No private deployment was available, so no live harness or fresh Agent/ES/LLM/DOCX PASS is claimed.

### 2026-09-15 SRA live acceptance command review v1.4

- Superseded runbook v1.3 with a documentation-only v1.4 correction against the task-supplied PR #243 merge baseline. SD-3 now validates `${PORT:-9002}` and uses bounded, fail-closed exact Linux listener authority before first-run bootstrap; SD-6 now describes cycle-driven renewal accurately and separates its 40-second operational budget from the unchanged temporal correctness proof.
- Static Bash/Python extraction, synthetic port-negative/launcher-exclusion and lease-temporal tests, safety scans, and diff checks passed. No live gate, SRA lifecycle, private SQL, credential, Golden Path, or Agent/ES/LLM/DOCX action was executed; SD-1 through SD-7 remain PENDING. Hosted refresh remained blocked by the HTTP 403 CONNECT proxy.

### 2026-09-14 SRA live acceptance command review v1

- Reviewed every SD-1 through SD-7 operator procedure against current launcher,
  bootstrap, Service Key, SQL lease/fencing, Handoff, artifact, OpenAPI, and test
  source at issuance SHA `2ef993e34629828128ff5244422c3440a4e305f3` after hosted
  refresh failed with CONNECT 403.
- Superseded acceptance package v1 with v1.1. Corrections fail closed for
  package/overlay identity without an authoritative manifest, bind deliberate
  crash signalling with pidfd and exact identity, strengthen runtime/restart
  evidence, correct configurable lease-owner semantics, and prevent inferred
  artifact cleanup or credential revocation.
- Static snippet compilation/syntax and focused repository tests passed; no live
  SD gate, private SQL, runtime lifecycle, credential mutation, or Golden Path was
  executed. SD-1 through SD-7 remain PENDING.

### 2026-09-11 Bootstrap profile logging clarification

- Replaced `bootstrap_env()`'s ambiguous `env:<profile>` line with explicit selector-only profile wording and a dynamic precedence line while preserving file loading, merge, OS-environment precedence, guard, force, and return behavior.
- Strict TDD evidence: the new focused bootstrap tests first failed 2 tests against the old output, then passed 2 tests after the logging-only change. The focused bootstrap/config regression suite passed 29 tests; `git diff --check` also passed.

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

### 2026-09-14 SRA self-bootstrap live acceptance package v1

- Added the documentation-only operator package at `docs/operations/sra-self-bootstrap-live-acceptance-v1.md`, bound to issuance baseline `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`. Hosted `main` refresh was attempted but the environment proxy returned HTTP 403; the checked-out commit exactly matched the supplied baseline.
- The package preserves the authoritative Corrective Implementation Review v5 gate names, provides one-at-a-time conservative commands, separates legacy-key identification/revocation, and records the source gap that no universal legacy output-root path or automatic SQL fingerprint migration exists. It does not replay the Golden Path or mark a live gate PASS.
- Static verification passed: `git diff --check`; changed-scope checks (documentation/memory only, no runtime or historical Design/Plan/Review changes); exactly one heading for each SD gate; required `NOT YET EXECUTED` status; Bash syntax for 26 extracted command blocks; Python syntax for 15 embedded heredocs; and a heuristic added-line secret scan with no match. Live SQL/SRA/Elasticsearch/LLM/DOCX workloads were intentionally not run.

### 2026-09-14 SRA live acceptance corrective command review v1.2

- Superseded v1.1 with v1.2 against the supplied hosted PR #241 merge baseline `30c5c918ff83a9f4f238383419b0db9886d0b872`; hosted refresh was attempted but blocked by the CONNECT 403 network policy, so no newer hosted SHA is claimed.
- Separated runbook identity from the stable reviewed runtime tree, made every Python gate step explicitly fail closed, bound SD-4 pidfd signal authority to the complete launcher identity and actual flock owner, and added an executable owner-bound SD-6 before/after verifier.
- Static validation passed 17/17 Bash fences and 8/8 Python heredocs plus control-flow/forbidden-pattern/status checks. No live gate, SQL connection, runtime lifecycle, credential mutation, Golden Path, Agent, Elasticsearch, LLM, or DOCX execution occurred. SD-1 through SD-7 remain PENDING.

### 2026-09-14 SRA live acceptance command review v1.3

- Corrected the v1.2 runbook without runtime changes: SD-3 now performs a bounded, state-neutral port-9002 preflight immediately before launcher invocation and mirrors bootstrap state ownership/schema/version parsing without exposing secrets.
- SD-6 now snapshots SQL-authoritative time and prior lease expiry, requires a source-derived 40-second pre-restart margin, and proves the replacement generation was acquired strictly before natural expiry. Package manifests now require release-produced, tamper-evident byte-to-source binding.
- Documentation/static validation covered all Bash fences, Python heredocs, failure propagation, synthetic occupied-port and corrupt-state paths, temporal accept/reject cases, forbidden patterns, and diff whitespace. No live SD gate, private SQL, runtime lifecycle, credential, Golden Path, Agent, Elasticsearch, LLM, or DOCX action was executed; SD-1 through SD-7 remain PENDING.

### 2026-09-15 SD-1 package/overlay deployment manifest v1

- Added standard-library release tooling that resolves explicit Git commits, proves the complete policy-managed runtime path/blob/mode map remains equal to reviewed runtime commit `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`, validates staged bytes, emits a deterministic manifest plus external receipt, and verifies deployed bytes without treating local `.git` as package authority.
- Advanced the live-acceptance runbook to v1.5 with an out-of-band `EXPECTED_MANIFEST_SHA256` trust anchor and a standard-library verifier self-hash precheck. SD-1 through SD-7 live execution remains PENDING.
- Verification: manifest/runbook suite passed 36 tests; deployment bootstrap/launcher/Handoff regression suite passed 67 tests with one expected development signing warning. Syntax and diff checks are recorded in the task handoff. No live SD gate, SRA lifecycle, private SQL, credential mutation, Golden Path, or Agent/ES/LLM/DOCX action was executed.
- Synthetic end-to-end release validation archived current `HEAD` into a temporary staged package, built and externally attested a 288-file manifest against the reviewed runtime baseline, and verified all 288 deployed bytes with the package's own pre-hashed verifier; this is repository evidence, not live deployment acceptance.

### 2026-09-15 SD-1 package manifest corrective trust chain v1.1

- Added dual reviewed baselines: fixed runtime authority `edcbc744f71374eaa839b0a31e0cd125fcb6fe52` and hosted reviewed manifest implementation authority `a79198aaff5828dbe54c3ffc4120d10377ea6e77`. The formerly recorded `d170dc7c42cdfc5f454aa00f0ef37743aba34fd7` was local-only and is not release authority. Candidate source must descend from both authoritative hosted/runtime baselines, retain exact reviewed policy blob/mode, and retain exact reviewed release-tool path/blob/mode set.
- Canonical policy allows no unmanaged runtime extras. Package build and verification reject caches/bytecode, use root-anchored component-by-component no-follow reads, and enforce executable-bit semantics for Git modes `100755` and `100644`. CLI build also binds running builder bytes to source Git bytes; manifest and receipt include `reviewed_manifest_commit`, with receipt builder version 2.
- Runbook v1.6.1 binds the hosted PR #246 head as manifest implementation authority and remains `POST-MERGE SOURCE REVIEW REQUIRED; SD-1 THROUGH SD-7 PENDING`. This provenance correction does not execute live acceptance and does not change SRA runtime files or behavior.
- Verification passed: the focused runbook suite passed 6 tests; the combined deployment-manifest/runbook suite passed 50 tests; Python compilation, launcher Bash syntax, whitespace checks, implementation-freeze comparison, and runtime-file comparison passed. Dependency requirements were already installed; pip's upgrade index check repeated the known HTTP 403 proxy warning.
- Final corrective regression verification passed 67 deployment bootstrap/launcher/Handoff tests with one expected development signed-URL fallback warning; Python compilation, Bash syntax, whitespace validation, runtime-scope audit, and implementation-baseline freeze comparison also passed.
- An additional 117-test single-process combined run was not accepted as green: it had 11 cascading launcher timing failures after 106 passes. The required 67-test deployment command had already passed cleanly, and the initiating failed case passed in isolation after cleanup; this limitation is recorded in `known_issues.md` rather than converted to PASS.
