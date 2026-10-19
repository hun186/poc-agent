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


## 2026-10-07 Requirement Product recurring create release boundary

- Recurring Product provisioning deliberately approves its initial Schedule Version while leaving recurrence disabled. The scheduler cannot claim provisioning work because `requirement_schedules.enabled=0` and `next_run_at=NULL`.
- The recurring Product-create finalizer is the single recurrence-release/visibility boundary. It computes the first due time with existing Phase 1C `next_occurrence()` semantics and atomically commits Schedule `enabled=1,next_run_at=<due>`, Product Task `active`, bounded create result, and owning request `succeeded`.
- Unlike one-time create, recurring create does not materialize an initial manual Batch Run. The first Run is created later by the existing scheduler worker when the persisted due occurrence becomes claimable.
- Create replay keeps immutable initial-next-run evidence in the request ledger while Product Task presentation reflects current Schedule state. This prevents scheduler progress from changing the semantic result of the original idempotent create.


## 2026-10-08 Requirement Product P1.5 Task update boundary

- P1.5 adds internal Product Task update orchestration only; there is still no Product HTTP router/UI and no draft activation in this slice.
- Task update payloads are classified before persistence into exactly one mode. In-place fields are `name` and recurring `enabled`; Schedule-affecting fields are `timezone`, `recurrence`, `run_policy`, and `model`. Cross-mode payloads never reserve a Product request.
- `reserve_product_task_update()` is the durable admission point. It locks the Product Task, rejects provisioning, records the current Task revision as `base_task_revision`, and preallocates a Schedule Version identity only for proposal mode.
- `finalize_product_task_update()` is the atomic in-place authority. It locks request/Task/Schedule, enforces revision CAS, updates Schedule name and recurring enable state, mirrors Product Task active/disabled state, writes audit outbox evidence, increments Task revision once, persists bounded result metadata, and marks the request succeeded in one Schedule transaction.
- Schedule-proposal mode never touches active semantics. It builds one immutable draft through existing Phase 1C Schedule Version validation, then `complete_product_task_update_proposal()` verifies the request-owned draft and unchanged originating Task revision before marking only the request succeeded. Product Task revision and `result_task_revision` remain unchanged/NULL.
- Proposal retry uses the preallocated Schedule Version identity as recovery authority. If that exact draft already exists, Product service completes/replays it instead of rebuilding from whatever active config exists later.
- P1.5A remains the only planned Product path that may approve/activate a proposal draft; P1.6 will later fence low-level non-Product mutation routes transactionally.


## 2026-10-08 Requirement Product P1.5A draft activation boundary

- Product draft activation is a separate privileged control-plane operation from P1.5 draft proposal creation. Only superuser callers may reserve `task_version_activate`.
- Activation reservation resolves exactly one successful originating `task_update` proposal by `task_id + schedule_version_id`, validates its bounded proposal result, and copies the proposal's persisted `base_task_revision` into the activation request. Activation never refreshes this CAS anchor from current Task state.
- The activation finalizer locks activation request → Product Task → Schedule → exact Schedule Version → originating proposal request, then enforces current Task revision against the proposal-origin revision.
- Successful activation uses the shared locked Schedule approval helper, retires the prior approved version, approves the exact draft, recomputes `next_run_at` only when the recurring Schedule is currently enabled, increments Product Task revision once, stores `result_task_revision`, and marks the activation request succeeded in the same SQL transaction.
- Stale activation leaves active Schedule/Task semantics unchanged, retires only the stale exact draft when it is still draft, records a version-retired audit event, and terminalizes the activation request with `requirement_task_conflict`.
- The existing low-level Schedule approve route now rejects Product-owned Schedules with 409 through an interim ownership precheck. P1.6 still owns the required same-transaction low-level ownership fence and TOCTOU regressions.

## 2026-10-11 Requirement Product P1.6 ownership-fence boundary

- Public low-level Schedule mutation routes are separated from Product-internal authority through explicit guarded store methods. The guarded path locks/checks Product Task ownership and the durable `task_create` reservation on the same SQL connection/transaction before it locks or mutates the target Schedule/version/run state.
- Public low-level Requirement-source PATCH/import use the same pattern across the configured Schedule schema and Requirement schema in the shared Requirement control database. Requirement-only deployments leave `schedule_schema=None`, so they do not query Product tables that are not enabled.
- Product orchestration deliberately continues to call the existing internal Requirement/Schedule methods. There is no caller-supplied bypass flag on public HTTP routes.
- A Product `task_create` reservation permanently claims its preallocated `schedule_id` and `source_id`; the fence does not discard ownership merely because the request later becomes terminal, since a partially created durable resource may remain.

## 2026-10-12 P1.7 snapshot replacement authority

- Internal Product `input_replace` is a Schedule-schema request-ledger saga coupled to the existing Phase 1B Requirement Import authority; it does not introduce an importer, worker, queue, or new schema revision.
- The reservation transaction locks the Product Task (rejecting provisioning) and then its Requirement set, captures the active snapshot as an immutable `base_snapshot_id`, and stores stable replacement import/snapshot IDs. Independent reservations may share the same base; the Phase 1B Requirement-set row lock and CAS allow at most one winner.
- The Requirement Import service always attempts exact-ID terminal recovery before `_prepare()`. Only a previously unseen import executes normalization and snapshot CAS. A later Product-ledger completion verifies the committed import/snapshot IDs without requiring the snapshot to remain active, supporting delayed response recovery after a newer replacement.

## 2026-10-12 P2.1 Product façade boundary (PR #288)

- `sra_api/routers/requirement_tasks.py` introduces the first high-level HTTP read/preview façade. It composes existing RequirementProductService, Phase 1B import preview, P1 presenters, Schedule SQL-read projections, and existing SRA bearer RBAC.
- API lifespan installs `requirement_product_service` only when both Requirement Import and Schedule control-plane authorities initialize. Product list/detail and Run lookups filter on finalized Product Task states in authoritative SQL; provisioning is not a browser/HTTP visible resource.
- No Product HTTP mutations or second scheduler/worker exist in this PR. The rest of Product API is separately gated P2.2/P2.3/P3; Task Center UI remains P4.

## 2026-10-12 P2.1 Review remediation

- Product preview raw request cap is enforced in a narrowly scoped ASGI middleware before FastAPI's multipart parsing or temporary-file spooling. It is not a generic file-upload policy for unrelated endpoints.
- Product HTTP preview uses an explicit limit-only path through existing Requirement readers. P1 internal normalization and full-data create/replacement flows remain uncapped by these HTTP display limits.
- ScheduleStore adds one-query joined Product Task/Schedule projections with explicit SQL Server `HOLDLOCK` on both joined tables, plus bounded Run Item SQL pagination. Existing full `get_batch_run()` remains the internal authority default; Product public Run summaries explicitly request `include_items=False`, retaining failure-state evidence without loading every item.

## 2026-10-12 P2.1 round-three read-path performance and bounds

- HTTP-only XLSX previews enforce cumulative cell and decoded-value-byte caps in the existing streaming reader, before raw source rows can accumulate into expensive in-memory graphs.
- Public Run pages use `ScheduleStore.list_product_run_summaries` to project finalized Product Task identity, Run summary and P1-compatible failure evidence through one bounded SQL statement; they do not issue one database request per Run. Existing internal batch-run APIs retain their full-item behavior by default.
- Deferred `/artifacts` links are excluded from Product P2.1 responses.

## 2026-10-12 P2.1 round-four hardening boundary

- XLSX parse errors from untrusted upload data are normalized at the format reader, before HTTP error presentation; server projection/store invariants continue to return masked 500 responses.
- The Product preview ASGI cap is applied after CORS in request execution (registered earlier than `CORSMiddleware` in Starlette) so its synthetic 413 rejection inherits normal browser CORS handling, without weakening the pre-parser body limit.

## 2026-10-17 SRAF OFF-1A isolation boundary

- tools/sraf_airgap_off1_probes.py is an independent, single-observation **partial** probe CLI; it does not invoke SRA application initialization, external_capabilities.py's potentially write-producing acceptance path, SQL, Agent/LLM inference, E2E, or OFF-3 unified Runner. The loopback-only no-auth GET channel intentionally avoids arbitrary URL selection and unaudited credential handling. SYS/ODBC probes observe only a subset of their OFF-0 parent check.
- OFF-0 checked registry semantics remain code-authoritative; its make_report_record still cannot emit PASS/FAIL/WARN because it lacks a reviewed trusted execution-to-report boundary. OFF-1A observation JSON declares PARTIAL_ONLY_NOT_ACCEPTANCE and must not be interpreted as the parent's PASS. Subsequent OFF-1B work should provide authorized SQL/ES mapping/LLM diagnostic boundaries before OFF-3 composes verified full-check outcomes.


## 2026-10-19 OFF-1B configured TCP preflight (proposed)

- tools/sraf_airgap_off1b_auto.py is an isolated operator CLI, not application initialization or OFF-3 runner. It calls the existing deployment bootstrap for the effective dotenv precedence from the working repository root, without starting any API/worker/Agent/SQL lifecycle or reading secret values into output.
- First slice sends at most one bounded TCP connect per actual API launcher bind/ES/main-LLM numeric RFC1918/loopback IPv4 target; TOPIC_LLM_URL is strictly a feature flag and never receives a TCP connect. DNS/public/link-local/non-IPv4 targets are skipped; no HTTP/TLS/auth, DNS, proxy, index, model, or task action is performed. Output includes explicit PARTIAL_ONLY_NOT_ACCEPTANCE and separate configuration versus TCP observations. Authenticated read-only service probes remain an independently reviewed subsequent OFF-1B gate.

- 2026-10-19 PR #293 review parity fix: API bounded TCP target is the launcher shell PORT on numeric loopback, not PUBLIC_API_BASE. The probe CLI's PORT snapshot predates Python dotenv bootstrap, as shell run_sra_api.sh does not source .env into PORT; it is still NOT an attestation of the separately running supervisor's process identity. Main LLM TCP target is MODEL_BASE_URL accepting /api/chat or /api/generate suffix; TOPIC_LLM_URL is only a feature enablement flag in query_terms, and the explicit topic-llm check must never open a socket.

- 2026-10-20 OFF-1B Codex parity refinement: main LLM client appends /api/chat to any configured safe reverse-proxy path prefix and accepts existing /api/chat or /api/generate suffix. TCP-only preflight therefore extracts host/port from bounded ordinary prefixed LLM URLs without sending their paths, but ES URL path handling stays exact bare-origin only. No new destinations, HTTP probes or acceptance authority.
