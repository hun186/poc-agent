# System Architecture

## 2026-09-20 Requirement registry verifier trust boundary

- `shared.runtime_provenance.verify_package_files()` performs generic byte and discovered-input verification without consulting ambient environment for Requirement SQL registry classification. Its optional `selected_registry` input is an explicit trust-boundary value.
- `sra_api.services.requirement_e2e_runtime_evidence.collect_source_evidence()` is the Linux deployment boundary that resolves the actual selector and passes only its repository-relative identity into verification. The identity is used for rejection only and is never returned in runtime evidence. Remote operator preflight performs generic verification, then relies on authenticated deployment evidence and the canonical provenance fingerprint.

## Current Summary

- The repository is a FastAPI + Elasticsearch RAG/agent system. `app.py` is the root ASGI entrypoint; `api/` is a compatibility namespace for the implementation in `sra_api/`. Agent/retrieval lives in `agent/`, ingestion in `data_ingestion/`, Requirement scheduling in `requirement_scheduler/`, and operator acceptance tooling in `operator_e2e/`.
- Chat flows through bounded routing/refinement views while preserving full user content at execution. Agent modes route to report, style, document-follow-up, or direct LLM paths. Elasticsearch supplies retrieval evidence; presenters render Markdown/DOCX.
- Requirement import uses SQL Server-backed immutable Sets, Versions, Snapshots, and Import Runs. Scheduling uses separate launcher-supervised Schedule and Handoff workers; the API lifespan owns the Report Job worker. Durable SQL state is the process boundary.
- `run_sra_api.sh` supervises API, Schedule Worker, and Handoff Worker with fail-closed process/listener identity and deployment bootstrap. Report Job artifacts are root-confined and digest checked.
- The operator E2E Harness supports local Linux and remote/offline operator modes. Canonical release authority is schema-v2 `REQUIREMENT_E2E_PROVENANCE.json`; its canonical SHA-256 fingerprint is cross-host identity. Git SHA is audit metadata, not deployment acceptance authority.
- `shared/runtime_provenance.py` is the shared authority for provenance paths, generated-product exclusions, module namespaces, CRLF source equivalence, exact package-byte checks, and bounded runtime-input discovery.
- The selected Requirement SQL registry is always deployment-local authority. Shared policy derives its repository-relative member only when selected inside the project root; generation excludes exactly that member, and package acceptance rejects a manifest containing it before reading its bytes.
- Bounded runtime-input discovery covers direct-child case-insensitive manual-synonym JSON files and actually selected index YAML and Editor form configuration. The Requirement SQL registry is privileged deployment-local configuration resolved through the shared selector, never release provenance. Existing selected external release-managed files fail closed as unattested. Mutable/deployment-local inputs such as dotenv, credentials, auth/session stores, SQLite databases, generated outputs, and operator-managed import/task data are not release provenance.
- Incremental deployment remains supported: inactive residue is not blanket rejected. Unreviewed inactive Python is warning-only, while an actually imported project module outside provenance remains blocking; namespace shadowing also remains blocking.
- Auth roles are `data_reader`, `data_editor`, `db_operator`, and `superuser`. Editor/session authentication and Service Keys remain distinct boundaries. Signed browser resources use action/representation-bound HMAC capabilities.
- Requirement Product API + Task Center implementation is IN PROGRESS. The first slice implements only Schedule schema v4 persistence/catalog authority (`requirement_product_tasks` and `requirement_product_requests`) on top of the existing `sra_schedule` database. Product service/router/UI and orchestration are not yet implemented. Product v1 continues to reuse Phase 1B Requirement Import, Phase 1C Schedule/Handoff, Report Job, Auth/RBAC, audit, and artifact authorities. Product request admission/replay remains ledger-backed by design; canonical request hashes bind operation + route target identities.
- Excel-to-SQL dashboard/task files are operator-managed deployment configuration and mutable workflow state; SQL-to-ES and Requirement source files are explicit operator inputs rather than implicitly auto-loaded release assets.

## Recent Changes

### 2026-09-22 Handoff lease lifecycle

- Each production coordinator work cycle owns one non-daemon heartbeat thread that renews the same owner/token/fencing generation at the configured heartbeat interval while authoritative work is active. The synchronized in-memory proof may advance only by successful renewal.
- Heartbeat loss invalidates that proof; SQL store mutations remain protected by `_prove_lease`, and coordinator stage boundaries reject missing or changed authority. Exact lease contention/loss returns to bounded acquisition polling, while all other failures remain fatal. Shutdown stops and joins the heartbeat before releasing a valid current lease.
- Joined work/heartbeat errors use fatal-first deterministic precedence, so a recoverable lease error cannot mask an invariant failure. Stop requests are also checked after reconciliation and prepare, preventing shutdown from starting a new prepare or submit stage.
- Process stop and heartbeat stop are distinct: SIGTERM/SIGINT closes future stage/cycle admission, while the non-daemon heartbeat continues renewing throughout the current in-flight authoritative call. Only the work-cycle cleanup boundary sets `heartbeat_stop` and joins the thread.

### 2026-09-20 Deployment registry and empty-synonym correction

- Removed the private Requirement SQL registry from release-provenance discovery while retaining one shared path selector for API, workers, and bootstrap.
- An explicitly empty `MANUAL_SYNONYMS_DIR` now disables external synonym discovery; an absent key still selects `config/synonyms`, and non-empty directories retain direct-child case-insensitive JSON enforcement.

### 2026-09-18 Bounded runtime-input provenance closure

- Added one pure shared resolver policy consumed by runtime loaders, package generation, deployment evidence, and offline package verification.
- Package generation rejects untracked auto-loaded synonym JSON. Deployment and offline verification require all actually selected release-managed inputs to be provenance members before mutation, with stable `unexpected_runtime_input` propagation.
- Exact byte hashing, provenance fingerprinting, active-module membership, namespace shadow checks, worker identity, and artifact-root checks remain unchanged.

### 2026-09-18 Release identity hardening

- Schema-v2 provenance hashes actual package bytes, allows only explicit LF-to-CRLF source equivalence during external generation, and never normalizes deployment verification.
- Generated `operator_e2e/output/**` and root report DOCX files are excluded while operator code/config and the canonical XLSX remain managed.

### 2026-09-16 Requirement operator E2E Harness v2

- Local/remote evidence providers share the same acceptance flow. The authenticated superuser runtime-evidence endpoint exposes bounded provenance, worker, and artifact-root facts; published artifact evidence validates root confinement, DOCX shape, and digest.

### 2026-09-10 Requirement runtime automation

- The unified launcher and deployment bootstrap supervise API, Schedule Worker, and Handoff Worker. Schedule materialization and handoff communicate only through durable SQL-authoritative Batch/Run Item state.

## Archived History

- `.codex/archive/architecture.md-20260918-000000.md` — full pre-compaction architecture through 2026-09-18.
- Earlier archives referenced by that file remain under `.codex/archive/`.

## 2026-09-22 Requirement E2E external capability boundary

- `agent.external_capabilities` owns immutable per-process mode parsing, live probes, backend resolution, stable evidence categories, and FULL_LIVE/HYBRID/OFFLINE classification. It is dormant unless `REQUIREMENT_E2E_EXTERNAL_MODE` is explicitly configured.
- Elasticsearch selection remains at `agent.es.es_client.get_es()`. The semantic backend returns ES hit envelopes and nested `evi` inner hits, so `ESSearchNews`, query construction, parsing, and evidence building remain production code.
- Direct LLM calls inject an `LLMClient` boundary adapter; CodeAgent injects a `Model` boundary adapter that instructs the real CodeAgent to invoke `es_search_news`. Internal Requirement lifecycle, Agent orchestration, report/DOCX generation, and durable reconciliation are not replaced.
- Live mapping authority remains `indices.get_mapping()`. The capability probe checks only the runtime-required E2E subset; enrichment documentation remains semantic rather than field-type authority.

## 2026-09-23 Capability ownership and semantic backend corrective

- The API lifespan and `ReportJobWorker.start()` freeze the deployment-owned external plan before job claiming. Runtime evidence is sourced from that same process; the harness only asserts requested-mode equality.
- Requirement semantic ES uses a distinct root retrieval subset plus a `dynamic: strict` czjLLM MultiDim subtree. Its bounded evaluator supports only production query-builder constructs and raises on unsupported DSL.
- Offline direct-model behavior is contract-specific (router/refiner/field selector/report), while the CodeAgent model derives one of the three business-theme queries and invokes the real retrieval tool.

## 2026-09-23 Requirement E2E verification policy separation

- The shared Harness keeps one production workflow but carries a separate verification policy. `release` requires exact operator/deployment provenance; `functional` permits only explicit package-byte drift while retaining runtime-input, active-module, worker, artifact-root, DOCX, digest, and durable identity fences.
- The authenticated API process remains evidence authority. Its runtime-evidence response includes an attestation status even for advisory byte drift, allowing the Harness to report functional outcome independently from formal deployment acceptance.

## 2026-09-23 Canonical Requirement semantic input boundary

- Operator E2E begins at the production-shaped business workbook, uses the reviewed production import profile, and proves exact prompt-content persistence at the Snapshot boundary before Schedule materialization.
- Deterministic external adapters consume the resulting business Requirement text directly; canonical fixture identity is v2 to avoid mutating historical synthetic durable fixtures.

## 2026-09-30 Verified E2E tool-thread scope bridge

- Production/user Report Jobs and normal Requirement -> Schedule -> Handoff jobs always use the ordinary real LLM and production Elasticsearch paths; E2E semantic mocks and the dedicated fixture are activated only for verified E2E test jobs.
- The verified E2E acceptance bit is captured on each freshly constructed Elasticsearch Tool instance. `smolagents` may execute `Tool.forward()` in a worker thread that does not inherit `ContextVar`; the tool instance crosses that boundary and re-opens `requirement_acceptance_scope()` only for its own call.
- No process-global E2E execution flag is introduced. Production-bound tool instances are marked false, so concurrent production work cannot inherit E2E routing from another job.

## 2026-10-06 Requirement Product presenter boundary

- `sra_api.services.requirement_product_service` is now the Product-facing presentation boundary for P1.1. It consumes already-authoritative Product Task / Schedule / Batch Run rows and returns bounded Product Task/Run views.
- The presenter layer does not own persistence, scheduling, Handoff, Report Job execution, artifact paths, authentication, or routing. Product HTTP routes and orchestration remain future gates.
- Product Run views retain immutable Schedule Version / Requirement Snapshot / Requirement Version identities while suppressing backend-native Report Job state and filesystem/credential details.


## 2026-10-07 Requirement Product preview boundary

- P1.2 extends the Product service façade with a read-only preview orchestration boundary; it does not add a Product HTTP route or persistence.
- The preview boundary selects an approved Requirement Import profile version, constructs only an ephemeral manual-upload descriptor, and delegates parsing/normalization to the existing `data_ingestion.requirements.source_adapters.acquire_source` and `profile.normalize_rows` authorities.
- Direct Requirement JSON is canonicalized to an in-memory JSON upload so JSON and file uploads share the same parser/profile behavior.
- Preview output is whitelisted to canonical Product-safe fields and diagnostics. It does not create or address Requirement Source/Snapshot, Schedule, Product Task, Batch Run, Handoff, Report Job, artifact path, credential, or E2E authority.


## 2026-10-07 Requirement Product one-time create saga

- P1.3 introduces the first durable Product mutation orchestration but still no Product HTTP router. Cross-authority IDs are reserved in `requirement_product_requests` before Requirement/Schedule writes.
- One-time provisioning composes existing authorities in order: approved Requirement profile/preview → task-owned manual-upload Source → exact-ID Requirement import/Snapshot → logical Schedule → provisioning Product Task → exact-ID Schedule Version → approval while recurrence-disabled → atomic Schedule-store finalizer.
- The one-time finalizer is the execution-release + visibility boundary. It verifies the reserved IDs against Product Task, Schedule active version, and exact active Requirement Snapshot, then calls the existing `_materialize_locked()` with a stable request-derived manual trigger inside the same SQL transaction that sets Product Task active and request succeeded.
- Report Job/Handoff remain downstream consumers of the durable Batch Run; Product create does not call either execution subsystem directly.
- P1.3 does not implement recurring finalization, Product routers, low-level ownership fencing, Task PATCH/activation, input replacement, or general Run-trigger admission.
