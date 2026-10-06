# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval is in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 security, Phase 1A Batch Scheduler, Phase 1B Requirement import, Phase 1C-A control plane, and Phase 1C-B Requirement execution compatibility bridge are implemented. JT-1 and LangGraph remain NOT STARTED.
- Requirement scheduling uses separate `schedule-worker` and `handoff-worker` processes supervised with the API by `run_sra_api.sh`; the Report Job Worker remains owned by API lifespan.
- Operator-supplied evidence covers the single-item Requirement Golden Path and three-item automatic technical Golden Path. Complete schema/migration, rollback/failure, fencing/failover, race/HA, security-rotation, and production content-quality matrices remain unproven.
- The automatic operator E2E harness remains an observer of deployed public APIs and existing workers. Repository verification must not be described as fresh live deployment acceptance.
- Environment limitations remain: package-index proxy checks may return 403; private deployment/Elasticsearch and authorized Requirement SQL are unavailable; browser/Playwright is absent.

## Recent Changes

### 2026-09-22 Requirement Handoff lease-heartbeat corrective

- The production Handoff coordinator now renews its SQL-authoritative lease at `heartbeat_interval` while reconciliation, remote inspection/submission, artifact work, and other authoritative work are in flight. Lease proof updates are synchronized, and authority is rechecked between coordinator stages without weakening store fencing.
- Exact `lease_lost` and `lease_unavailable` runtime conditions invalidate in-memory authority and return the worker to a bounded poll/acquire cycle. Unexpected and invariant failures still escape; shutdown stops and joins the heartbeat before releasing a still-current lease.
- Focused lease/coordinator/reconciliation tests passed 25 tests. The broader Handoff, Schedule Worker, and launcher regression passed 178 tests. Dependency installation confirmed all requirements present, while the pip upgrade index check repeated the known proxy HTTP 403 warning.
- PR #267 review correction gives every non-recoverable work or heartbeat error precedence over recoverable coordination errors, with deterministic work-before-heartbeat ordering when both are fatal. A stop requested during reconciliation or prepare now prevents the next prepare/submit stage from starting.
- The corrected focused suite passed 28 tests, both mixed-error concurrency regressions passed ten repeated runs, and the broader Handoff/Schedule/launcher suite passed 181 tests.
- PR #267 shutdown-lifecycle correction separates the process stop request from the heartbeat stop boundary: SIGTERM/SIGINT prevents the next authoritative stage or cycle, but heartbeat renewal continues until the already-started reconciliation/prepare/submit returns and `_run_with_heartbeat()` enters cleanup.
- Stop-during-long-reconciliation and stop-during-long-prepare regressions each passed ten repeated runs; the corrected focused suite passed 31 tests and the broader Handoff/Schedule/launcher suite passed 184 tests.

### 2026-09-20 Remote-operator Requirement registry authority correction

- Generic package verification no longer derives the selected Requirement SQL registry from ambient process environment. Deployment evidence explicitly supplies the repository-relative selection from the Linux deployment environment, preserving fail-closed rejection before registry bytes are read while leaving remote operator preflight independent of workstation selector state.
- Added regressions for absent and differing remote selectors, deployment rejection, sanitized bounded evidence, and remote failure propagation. The focused provenance/runtime-input/Harness suite passed 133 tests; targeted compilation and `git diff --check` passed. The live Requirement Golden Path was deliberately not run.

### 2026-09-20 Selected Requirement SQL registry provenance exclusion

- Enforced `selected Requirement SQL registry ∩ release provenance authority = ∅` for tracked project-local registries as well as ignored/default and external registries. Generation excludes only the selected repository-relative member before reading or hashing it; package verification rejects any schema-v2 manifest that includes that selected member before reading its bytes.
- Added tracked-before-commit generator regressions for the example, custom, and default registry paths; non-selected tracked configuration remains provenance-managed. Added fail-closed verifier, Linux evidence, operator preflight, and bounded non-disclosure regressions.
- Validation passed 30 focused runtime-input tests and 131 combined provenance/runtime-input/Harness/module-policy tests. Dependency installation found all requirements present; pip's upgrade lookup repeated the known HTTP 403 proxy warning. The live Requirement Golden Path was deliberately not run.

### 2026-09-20 Post-merge runtime-input provenance correction

- Classified the Requirement SQL registry as privileged deployment-local configuration rather than Git-derived release provenance, while preserving the shared selector across API, both Requirement workers, and deployment bootstrap. Runtime evidence contains no registry bytes, digest, resolved path, credentials, or query text.
- Restored explicit `MANUAL_SYNONYMS_DIR=""` as disabling external synonym files; absence still defaults to `config/synonyms`, and non-empty directories retain direct-child case-insensitive JSON provenance enforcement.
- RED: the focused runtime-input suite produced the five expected failures for ignored/external registry handling, generator handling, and empty synonym semantics. GREEN: 122 focused provenance/Harness tests and 25 deployment-bootstrap tests passed; compilation and diff checks passed. The live Golden Path and manual worker/API/coordinator commands were not run.

### 2026-09-16 Generated report/runtime provenance boundary hotfix

- Runtime provenance now uses one shared generated-product classifier to exclude every `operator_e2e/output/**` path and every root-level `operator_e2e/*.docx` report while retaining byte-exact authority for runtime Python, configuration, launcher, profile JSON, and canonical input XLSX paths.
- The generator, operator reconstruction, server manifest validator, and operator dirty-source classification share that policy. Modified tracked generated DOCX files no longer block package generation or enter `runtime_files`; modified `operator_e2e/requirement_e2e_support.py` and `run_sra_api.sh` still block.
- Strict RED recorded five expected failures across generation, server validation, and the missing shared classifier. GREEN passed 34 focused tests and 213 Harness/launcher/bootstrap/deployment tests (five pre-existing warnings), plus compilation and diff checks. The live Golden Path was deliberately not run.

### 2026-09-16 Runtime provenance namespace and package-byte hotfix

- Active runtime discovery now classifies `sys.modules` entries by exact project top-level import namespace or an explicitly managed root Python module name. Third-party paths merely containing `api`, `config`, `shared`, or a basename such as `telemetry.py` are ignored, while true project-namespace modules loaded outside the deployment root still fail as shadowing.
- Incremental provenance generation now compares every reviewed tracked runtime Git blob byte-for-byte with the corresponding working-tree file before writing the manifest. CRLF/LF or any other package-byte divergence fails early as `runtime_worktree_bytes_differ_from_reviewed_source` with bounded relative paths and does not mutate source files.
- Strict RED recorded three expected failures for two external namespace collisions and missing CRLF preflight. GREEN passed 26 focused source/provenance tests and 203 combined Harness v2, launcher, deployment bootstrap, and deployment manifest tests; compilation and diff checks passed. The live Golden Path was deliberately not run.

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

### 2026-09-16 Incremental-package root runtime provenance hotfix

- Added one shared bounded runtime provenance policy covering the existing runtime source trees plus root runtime inputs `app.py`, `python_compat.py`, `requirements.txt`, `run_sra_api.sh`, and `telemetry.py`; root `__init__.py`, README/TODO, and other root metadata remain outside runtime authority.
- Provenance generation, operator-side reviewed-map reconstruction, and deployment validation now consume that policy. Incremental evidence hashes every selected file, permits a reviewed matching active `python_compat.py`, and fails closed when either `python_compat.py` or the runtime supervisor `run_sra_api.sh` differs.
- Strict TDD RED first failed because `shared.runtime_provenance` did not exist (and exposed direct-script import requirements). GREEN passed 19 focused source tests and 195 combined source/Harness/launcher/bootstrap/deployment tests with five pre-existing warnings. Compilation and diff checks passed. Dependencies were present; the pip upgrade lookup repeated the known HTTP 403 proxy warning.
- The live Golden Path was deliberately not run. No fresh live deployment, Agent, Elasticsearch, LLM, or DOCX acceptance PASS is claimed.

### 2026-09-18 Requirement E2E offline release provenance correction

- Confirmed `.gitattributes` uses `* text=auto` while `*.sh` is forced LF, reproducing the Windows false-failure model: Git blobs are normalized LF while eligible worktree text may be CRLF without Git modification.
- Added schema-v2 provenance with shared strict LF-to-CRLF source equivalence, exact actual-package SHA-256 entries, strict canonical validation/fingerprinting, offline operator exact-byte verification, and operator/deployment fingerprint comparison. Generated report exclusions and Linux active-module/worker/artifact checks remain intact.
- Focused Harness/source tests passed 101 tests; launcher/bootstrap/deployment tests passed 108 tests. Compilation/diff checks are recorded with this task's final verification. The live Golden Path was deliberately not run.

### 2026-09-18 Bounded runtime-input provenance closure

- Against authoritative baseline `e86601f7ba434c40dbd92a36209a7e0f62c7a96c`, strict RED produced 10 failures: synonym/index/registry/external selected files were not rejected, the generator accepted an untracked auto-loaded synonym, and no shared discovery function existed. One harmless-residue case already passed, confirming the intended non-clean-slate boundary.
- Repository inventory classified manual synonym JSON, selected index YAML, Requirement SQL registry, and Editor form config as release-managed. Dotenv/credentials/bootstrap users/service keys are deployment-local secrets; session/API/auth stores, SQLite, audit/log/trace state, and Excel dashboard task configs are mutable; report/DOCX/output trees are generated; explicit import/source files and inactive residue are not implicit release inputs.
- Added shared bounded selectors/discovery and `unexpected_runtime_input` propagation through generation, exact package verification, Linux runtime evidence, remote evidence, and Harness preflight. Runtime loaders now consume the same pure selectors without importing side-effectful singleton loaders into verification.
- GREEN: `PYTHONPATH=. pytest -q tests/test_requirement_e2e_source_identity_hotfix.py tests/test_requirement_operator_e2e_harness.py tests/test_requirement_operator_e2e_harness_v2.py tests/test_runtime_input_provenance.py` passed 115 tests with two pre-existing dependency deprecation warnings. The live Requirement Golden Path and all real Agent/Elasticsearch/LLM/DOCX paths were not run.
- Compacted architecture, API contract, and backlog after each exceeded 20 work/date sections. Full prior text is archived at `.codex/archive/{architecture,api_contract,backlog}.md-20260918-000000.md`.

### 2026-09-22 Capability-adaptive Requirement E2E

- Added explicit live/auto/offline external dependency planning, frozen per deployment process before the Requirement workflow. Runtime evidence and operator output now distinguish FULL_LIVE, HYBRID, and OFFLINE while preserving workflow failures.
- Added mapping- and dataset-aware live Elasticsearch probing, non-empty live LLM probing, an acceptance-only semantic ES fixture using native Event arrays/event_ids, and deterministic adapters at the ES and both LLM model boundaries. The real CodeAgent/tool/query/parser/evidence path remains active offline.
- Focused capability tests passed 17 tests; the relevant Harness/provenance/nested-mapping regression command passed. A direct offline CodeAgent run executed retrieval and returned all three semantic evidence records. No live SQL Server, Elasticsearch, LLM, deployment, or DOCX E2E was available or claimed.

### 2026-09-23 Capability-adaptive E2E corrective

- Replaced synthetic Requirement phrases with Gaza, Taiwan Strait gray-zone, and US-China/Indo-Pacific semantic fixtures grounded in the business workbook themes. Added a dedicated strict czjLLM MultiDim subtree mapping, fixture validation, and a bounded production-query DSL evaluator with discriminating filters, dates, and evidence inner hits.
- Restored production `LLMClient.generate()`, made deterministic router/refiner/DataAgent/report contracts evidence-aware, and proved the real `execute_agent_turn()` → routing → ReportAgent/DataAgent → ES parser/builder path offline without faking Report Job state or DOCX completion.
- Moved plan ownership to the API/ReportJobWorker process before claims; local and remote harnesses now assert authenticated runtime evidence rather than modifying harness-process environment.
- Focused capability tests passed 39 tests; Agent/ES/LLM/ReportJob tests passed 73 tests; Requirement Harness/provenance/ReportJob regressions passed 157 tests. No live LLM, ES, SQL, Schedule/Handoff, full automatic run, DOCX, or reconciliation acceptance was executed.
- GitHub remained unreachable through the environment proxy, so hosted refs, push, and the required hosted-verifiable provenance regeneration could not be completed. The existing local-only provenance anchor must not be presented as corrected.

### 2026-09-23 Deterministic direct-LLM contract audit

- Audited every direct `call_llm()` contract reachable from SRA_REPORT: router and report are unconditional; query refiner, topic extraction/synonym expansion, and evidence field selection are configuration-conditional. DataAgent remains a distinct smolagents model boundary.
- Corrected the raw field-selector response to include mandatory `ref_no` and `note`; added explicit topic-extractor and synonym-expander JSON contracts; removed the unsafe generic prose catch-all in favor of `unsupported_e2e_llm_contract`.
- Added exact-production-prompt tests for all three router themes, time-context refiner recognition, raw selector validity, production report payload grounding/empty evidence, conditional query-term callers, activation/cache reset, ordinary chat/generate behavior, unknown-contract failure, and the real offline Agent-turn path.
- Verification passed 50 focused capability tests and 89 related LLM/refiner/query-term/turn/ReportJob/Harness tests. No live external dependency or deployment acceptance was executed.

### 2026-09-23 Functional versus release Requirement E2E verification

- Added an explicit `--verification release|functional` policy. Release remains the strict default; functional mode downgrades only ordinary provenance-managed byte drift to visible advisory evidence and still executes the production workflow.
- Deployment runtime evidence now accepts the authenticated verification policy and returns capability, worker, artifact-root, and explicit source-attestation evidence during ordinary byte drift. Malformed/missing provenance, unexpected runtime inputs, unexpected active modules, module shadowing, worker identity, and artifact integrity remain fail closed.
- Validation passed 9 focused policy tests, 150 provenance/Harness regressions, and 56 external-capability/live-progress regressions. Dependency installation found requirements present; the pip index upgrade check repeated the known proxy HTTP 403 warning. No deployment E2E or formal acceptance was run.

### 2026-09-23 Real Requirement semantic-content reconciliation

- The canonical operator XLSX now byte-mirrors `data/要項excel/requirement_e2e_three.xlsx` and uses the production `ITEMNO`/`CONTENT ` business shape with Gaza, Taiwan Strait gray-zone, and US-China/Indo-Pacific Requirements. Its verified SHA-256 is `816ffac9039530a86955c590b0fa68830757a620229d85630f5e42c12f542403`.
- The Harness uses the reviewed Taiwan investment-security import profile, assigns v2 fixture identities, and compares canonical workbook `ITEMNO -> CONTENT` with durable Snapshot `external_item_id -> prompt_content` without emitting prompt bodies. Input and external-mode failures now provide bounded categories/remediation evidence.
- Focused real-content tests passed 9 tests; the combined Requirement content, capability, verification, Harness, provenance, profile, adapter, and integration suite passed 229 tests with two dependency deprecation warnings. No deployment acceptance was run.
### 2026-09-24 DataAgent live capability probe contract correction

- PR #273 corrects the Requirement E2E DataAgent live probe for the deployed smolagents 1.23.0 contract: `LiteLLMModel.generate()` must receive typed block-form text content (`[{"role":"user","content":[{"type":"text","text":"Reply with READY."}]}]`) rather than scalar string content. The scalar form failed locally in smolagents message normalization with `TypeError: string indices must be integers` before any Ollama transport attempt.
- Deployment-host verification confirmed the configured Ollama endpoint was reachable (`/api/tags` returned HTTP 200) and the corrected block-form DataAgent probe reached the configured DataAgent model successfully with response `READY.`.
- Capability evidence now distinguishes local boundary/runtime contract failures such as `TypeError` as sanitized `boundary_error`, while built-in/requests and LiteLLM/OpenAI connection/timeout failures remain `transport_unavailable`; wrapped transport causes are recognized through exception chaining without exposing raw exception details.
- Hosted Codex review identified and the PR addressed LiteLLM-native transport exception classification. No Elasticsearch mapping, Requirement/Schedule/Handoff/Report Job/DOCX flow, provenance, verification-policy, startup-timeout, or dependency behavior is changed by this correction.
- Hosted pytest CI is not configured for this PR; Vercel preview passed. Formal deployment acceptance remains pending because the independent Elasticsearch `mapping_incompatible` blocker is still unresolved.

### 2026-09-30 Production/E2E mock isolation and tool-thread propagation

- PR #275 isolates Requirement E2E semantic LLM/DataAgent/Elasticsearch adapters from ordinary production/user Report Jobs. Normal Requirement -> Schedule -> Handoff jobs stay on real production dependencies and fail rather than silently producing a mock-backed report.
- Codex review found that `ContextVar` acceptance state was lost in `smolagents` LocalPythonExecutor worker threads. The corrective binds the verified-E2E bit to each fresh ES Tool instance and re-opens the E2E scope inside decorated `Tool.forward()` calls, avoiding any process-global fallback signal.
- Regression coverage now includes production-vs-E2E singleton isolation, canonical Handoff production scope, offline Agent-turn integration, and an explicit ThreadPoolExecutor proof that the raw child thread lacks the ContextVar while the bound tool recreates it safely.
- This environment still cannot resolve `github.com` for Git transport, so no local pytest result is claimed for this corrective; hosted Codex review and deployment/operator verification remain required.
### 2026-10-01 E2E CLI follows deployed external mode by default

- The Requirement operator harness no longer hard-codes CLI `--external-mode=auto` when the operator omits the option. It now reads authenticated runtime evidence and adopts the external mode already frozen in the running deployment.
- An explicit `--external-mode live|auto|offline` remains a strict assertion: if it differs from the deployed frozen mode, the harness fails closed at `RUNTIME_WORKERS` before workflow mutation.
- Evidence summaries report the effective deployed mode after runtime preflight, so a successful omitted-flag run against a live deployment records `EXTERNAL_MODE = live` and can still establish `FRESH_LIVE_REQUIREMENT_E2E_PASS = YES`.
- Regression coverage verifies omitted-mode adoption, explicit mismatch rejection, help text, and effective-mode summary output.

### 2026-10-01 Requirement Product API + Task Center planning

- Added docs-only Design v1 and Implementation Plan v1 for a production-facing Requirement Product API and integrated Requirement Task Center. Implementation is NOT STARTED.
- The Task Center is part of the existing SRA management application and reuses the current /editor navigation, bearer-session Auth/RBAC, audit conventions, and role hierarchy; no second login/site is planned.
- Existing ES structured-data editing and Excel→SQL management remain separate modules under the same management shell. Under 匯入管理, the planned Requirement section adds 要項任務中心, 建立要項任務, 執行紀錄, and 要項來源與版本.
- The Product API is an orchestration/presentation façade over existing Phase 1B Requirement Import and Phase 1C Schedule/Handoff/Report Job authorities. It must not create a second scheduler/queue/auth system or permit production jobs to enter E2E mock routing.
- Product E2E is separate from Operator E2E: it must generate runtime input, submit through the Product API, execute against real LLM/ES, and retrieve the resulting artifact without relying on the committed Operator E2E fixture.

### 2026-10-01 Product Task review corrections

- Design review proved Schedule identity alone is insufficient for Product semantics. Product v1 now explicitly plans Schedule schema v4 with `requirement_product_tasks` (task/source/schedule binding plus immutable `execution_kind`) and `requirement_product_requests` (principal-scoped durable idempotency/saga recovery).
- New Product Task provisioning remains superuser-only because Phase 1B source enablement is already a superuser authority and commit requires an enabled source. `db_operator` may operate only within existing lower-level permissions, such as preview/input replacement on an active task/source and prospective draft schedule changes.
- External service keys in v1 operate only on pre-provisioned active tasks; they do not gain source-activation/task-provisioning authority.

### 2026-10-01 Product Task second review corrections

- Product Task provisioning saga order now respects non-null foreign keys: after Requirement source/snapshot creation, create the linked Schedule first, persist `schedule_id` in `requirement_product_requests`, then insert `requirement_product_tasks` and persist `task_id`.
- Product idempotency for service principals is keyed by immutable `AuthPrincipal.credential_id` / stored service-key `key_id`, never by human-readable subject/name; duplicate key names must remain separate replay namespaces.
- Every Product Task PATCH/update is ledger-backed with operation `task_update` and requires `Idempotency-Key`, preventing duplicate immutable Schedule Versions after response loss/retry.
- Product E2E is explicitly two-stage: superuser provisions/activates the task/source, then a scoped service key proves delegated input replacement, Run trigger, reads, and artifact retrieval on that active task.

### 2026-10-01 Product saga authority-level crash recovery

- Product idempotency now requires server-owned durable IDs to be preallocated and written to `requirement_product_requests` before cross-authority commits. Required reservation refs include `import_run_id`, `snapshot_id`, and `schedule_version_id` in addition to source/schedule/task IDs.
- Phase 1B Product-compatible commit paths must accept caller-supplied `import_run_id/snapshot_id` and same-ID replay safely; failed-import recording uses the preallocated import_run_id. ScheduleStore.create_version must accept optional caller-supplied `schedule_version_id` and return the same version on same-ID/same-config replay.
- Product request reservation-reference columns intentionally have no domain FKs because the IDs must be persisted before target rows exist. Resume verifies ownership/config semantics before treating an existing target as complete.
- Manual Run materialization already has authority-level idempotency via unique schedule_id + trigger_request_id; Product trigger reuses that instead of injecting batch_run_id.

### 2026-10-02 Product Task mutable PATCH replay safety

- Product Task metadata/state PATCHes now use monotonic Task `revision` plus ledger `base_task_revision` CAS. The final Product mutation transaction atomically applies rename/enabled/version activation, writes audit outbox, increments revision, stores bounded safe_result_json/result revision, and marks the Product request succeeded.
- Product PATCH routes must not sequence existing low-level `rename_schedule()` / `set_enabled()` and then mark the ledger afterward. Those low-level APIs remain unchanged; Product routes use a new atomic finalizer in the Schedule store.
- If a newer different-key update succeeds before an older unfinished request resumes, the older request fails revision CAS and cannot roll Task state backward. Succeeded replays return stored safe_result_json without reapplying mutable values.

### 2026-10-02 Product-owned low-level mutation fences

- Product-owned Schedule/source resources are read-only through retained public low-level HTTP mutation routes. Schedule PATCH, version create/approve, and manual-run POST return 409 requirement_product_owned_schedule; task-owned Requirement source PATCH/import return 409 requirement_product_owned_source.
- Low-level GET/list/history and Requirement preview remain available; non-Product Schedule/source mutation behavior is unchanged.
- The guard is a public API/service-boundary ownership check. Product orchestration continues to use reviewed internal store operations and the Product atomic finalizer; do not globally disable store methods.
- This closes cross-API races where an operator could otherwise mutate Product-owned Schedule/source state without incrementing Product Task revision or participating in Product idempotency.

### 2026-10-02 Atomic ownership fencing and input-replacement CAS

- Product ownership fences are no longer router/service pre-checks. Low-level Schedule/source mutation stores must check Product Task ownership plus preallocated task-create reservation IDs inside the same SQL transaction/locks as the write. Initial Product provisioning reserves source_id/schedule_id before target creation, so the reservation itself fences the provisioning gap.
- Product v1 relies on Requirement and Schedule schemas sharing REQUIREMENT_CONTROL_DB_CONNECTION; RequirementStore is configured with the Schedule schema for cross-schema ownership checks while Product is enabled.
- input_replace requests persist base_snapshot_id at first reservation. Phase 1B commit accepts expected_base_snapshot_id and, for an uncommitted reserved import, compares it against locked active_snapshot_id before writing. Mismatch is requirement_input_conflict; already-committed same-ID replay is recognized before CAS and returns the existing result.
- Concurrency tests must use separate connections/barriers for provisioning-vs-low-level-write and stale-uncommitted input replacement races.

### 2026-10-02 Recover committed Product imports before Requirement preparation

- For Product commits with preallocated import_run_id/snapshot_id, RequirementImportService.commit must query persisted terminal identity before _prepare(), source acquisition, normalization/classification, candidate.has_errors, record_failed_import, or base-snapshot CAS.
- This is necessary for delayed replay: A commits S1, B later commits S2, then A retries. Re-running _prepare against B's newer Requirement versions can classify A stale and must not occur. A returns its original S1 result while active snapshot remains S2.
- Regression tests explicitly fail if _prepare is invoked during a delayed same-ID committed replay.

### 2026-10-02 Named pre-prepare import recovery helper

- The implementation plan now names a read-only RequirementStore.recover_preallocated_import_result(source_id, import_run_id, snapshot_id) helper. RequirementImportService.commit calls it before _prepare; only an absent persisted identity may proceed to _prepare and commit_candidate/base_snapshot CAS.

### 2026-10-02 Provisioning lifecycle gate

- requirement_product_tasks.product_state is now provisioning|active|disabled. New Product Tasks are inserted as provisioning and are not ordinary Product resources until the owning task_create saga finalizes.
- Ordinary Task list/get hide provisioning Tasks; PATCH, input replacement, Run trigger, artifact/task delegation, and service-key access reject requirement_task_provisioning before reserving competing work.
- Only replay/resume of the same owning task_create request may continue a provisioning Task. A Product-create finalizer atomically verifies initial version/approval plus once-run or recurring-enable evidence, flips product_state to active, stores bounded create safe_result_json, and marks task_create succeeded.
- Required concurrency test pauses create after Task insertion, proves other Product surfaces cannot observe/mutate it, then resumes the same create and exposes the Task only after finalization commits.

### 2026-10-02 Atomic initial execution release + Run presenter provisioning gate

- Product create no longer enables recurring Schedule or materializes the one-time initial Run before finalization. Both execution-release actions happen inside finalize_product_task_create's Schedule SQL transaction together with provisioning→active, bounded create safe_result_json, and task_create=succeeded.
- Before finalizer commit: recurring Schedule remains disabled, no one-time initial Run exists, so scheduler/Handoff workers cannot execute a hidden provisioning Task.
- Product Run list/detail/items/artifact/Word presenters resolve the owning Product Task and omit/reject provisioning owners. Service-key artifact/read scopes do not bypass this gate.
- Concurrency regression runs scheduler/Handoff workers while create is paused immediately before finalization and proves no execution or Product Task/Run/history/artifact visibility occurs until atomic commit.

### 2026-10-05 Draft proposal vs superuser activation; no retry ancestry in v1

- Schedule-affecting Product PATCH (recurrence/timezone/model/run-policy) creates only an immutable draft Schedule Version. It never approves/activates it, does not change active version/next_run_at/enabled state, and does not increment Product Task revision.
- db_operator may create such drafts; activation is a separate superuser-only Product endpoint using durable operation task_version_activate. Activation resolves the originating draft request and CASes current Task revision against that request's persisted base_task_revision before atomically approving/activating and incrementing revision.
- Low-level approval remains fenced for Product-owned Schedules, so the Product activation endpoint is the sole supported approval path.
- Product v1 removes any durable parent_run_id/retry-lineage guarantee. Run again creates an independent new Run; failed Run history remains immutable. Retry ancestry is future schema/API work.

### 2026-10-06 Product Task revision semantics and mixed PATCH validation

- Product Task revision represents committed active Task semantics. It increments once for successful in-place metadata/state PATCH and once for successful task_version_activate. Draft-only schedule proposal PATCH and input replacement do not increment it.
- A draft-only task_update stores base_task_revision and leaves result_task_revision null; activation later CASes current revision against that original base before incrementing.
- Product v1 rejects PATCH payloads that mix in-place fields (for example name/enabled) with schedule-proposal fields (recurrence/timezone/model/run-policy). It returns 422 requirement_task_patch_mixed_modes before durable request reservation, draft ID allocation, or mutation. Same-mode multi-field PATCHes remain allowed.

### 2026-10-06 Product disabled-state mirror and activation retry checklist

- Recurring Product Task state is authoritative and mirrored with Schedule enabled state after provisioning: active/enabled=true, disabled/enabled=false. Superuser enable/disable writes both sides, next_run_at, Task revision, audit, safe result, and request success atomically; rollback cannot split the pair. One-time Tasks remain active in v1.
- Disabled recurring Tasks reject manual run trigger with requirement_task_disabled before reserving run_trigger.
- P2.3 now distinguishes in-place PATCH finalization (revision +1) from schedule-proposal completion (revision unchanged, result_task_revision NULL), and successful task_version_activate performs its own atomic revision increment.
- The cross-cutting idempotency checklist explicitly includes task_version_activate; UI/client must retain the same activation Idempotency-Key across transport retries.

### 2026-10-06 Atomic run-trigger admission versus disable

- First admission of a new run_trigger request is atomic with Product Task lifecycle validation in the Schedule DB: existing same-key replay is resolved first; absent request locks/rechecks the Task and request identity, rejects provisioning/disabled, then inserts the ledger row while holding the Task lock.
- Recurring disable finalization uses a compatible Product Task lock. Disable-first blocks the new trigger with no request row; trigger-admission-first durably accepts exactly one request, which may resume/materialize once after a later disable using its stable request-derived trigger_request_id.
- Same-key replay after disable remains an admitted request; a new idempotency key after disable is rejected. Required regression uses separate DB connections/barriers.
