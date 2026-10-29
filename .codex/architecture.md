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
- Requirement Product API + Task Center work progressed beyond the original schema-only slice: internal create P1.3/P1.4, Task updates P1.5, activation P1.5A and low-level ownership fences P1.6 are in earlier merged PR slices through #286. Product public read/preview P2.1 is on PR #288 review branch; later UI/P2.2 and authorized live SQL/operator E2E are not proven complete. Reuse Phase 1B Requirement Import, Phase 1C Schedule/Handoff, Report Job, existing RBAC/audit and artifact authorities. The schema-v4 control plane uses `requirement_product_tasks` / `requirement_product_requests`, ledger-backed canonical request hashes bind operation and route identities.
- Excel-to-SQL dashboard/task files are operator-managed deployment configuration and mutable workflow state; SQL-to-ES and Requirement source files are explicit operator inputs rather than implicitly auto-loaded release assets.

## Recent Changes

- 2026-10-21: PR #295 introduces isolated operator-side `tools/sraf_airgap_off1b_es_https_mapping.py`, **not** an API route or production ES client replacement. Effective dotenv is resolved using the existing OFF-1B bootstrap; only a literal numeric private IPv4 HTTPS ES origin, fixed repo CA, numeric IP SAN TLS validation, Basic credential and one literal ES_INDEX are permitted. No DNS, public target, index wildcard, ES data mutation or response-content disclosure.
- 2026-10-21: Network sequence makes bounded TLS-validated ES root GET, protected principal GET, and Mapping GET (up to 3 by default). Default principal match remains auth NOT_VERIFIED because an intermediary may substitute Authorization. Explicit `--verify-credentials` adds one randomized wrong-password protected GET (max 4 requests, audit/lockout side effects); only HTTP 401 validates rejection; matching enabled principal on wrong-password HTTP 200 shows ineffective control, while other error codes remain incomplete. Independent TLS failures downgrade aggregate identity status.
- 2026-10-21: ES JSON mapping is checked for top-level dictionary and nested `properties`/`fields` object structure with bounded traversal before calling existing `agent.external_capabilities.mapping_compatibility`. Fail closed with fixed redacted `es_mapping_response_invalid`; no traceback, no FULL_LIVE claim.
- 2026-10-20: OFF-1B configured TCP preflight extracts actual launcher shell PORT (rather than PUBLIC_API_BASE), ES configured private-IP and LLM MODEL_BASE_URL's real backend. TOPIC_LLM_URL is a feature flag, not its own socket. LLM may use safe path prefix, /api/chat or /api/generate; ES requires exact origin. This is TCP reachability only.
- 2026-10-20: OFF-1B API HTTP health is a separate bounded anonymous 127.0.0.1 GET /healthz reusing OFF-1A strict response parser. Neither health nor TCP attests process ownership, scheduling, DB access or service health.
- 2026-10-19: OFF-1A strict HTTP/1.1 response-framing and trailer validation uses total wall-clock deadlines, bounded Content-Length/chunked parsing and strict raw CRLF and status tokens, with tested Proxy-Status/Early-Data edge handling. Independent runtime/live API, ES and LLM acceptance remains separate.
- 2026-10-12: Product P1.6 fencing uses same-transaction locks for low-level Product-owned Schedule/source mutations; P1.7 input replacement uses Requirement-set Snapshot CAS where applicable. Product P2.1 requires consistent Task/Schedule reads, HTTP budget limits and resource-safe JSON/CSV/XLSX preview; public routes are independently reviewed.
- 2026-10-07: Product one-time/recurring create use preallocated cross-authority IDs, immutable Requirement histories, Schedule version authority, atomic release of initial manual Run or enablement, and durable idempotency recover/replay. Product metadata and activation remain distinct authorized actions.

## Archived History

- `.codex/archive/architecture.md-20261021-165000.md` — exact full pre-compaction architecture including provenance, Product, OFF-0/1, authentication and network trust designs; verified identical before active rewrite.
- Prior architecture history and pre-compaction references are preserved verbatim in that archive, which is not needed for routine context load.

## Compaction Record

- 2026-10-21: Archived and condensed >20 dated architecture work blocks per AGENTS.md. Source tree/authorities/trust boundaries remain active; old implemented/reviewed variants are retrievable in archive. Hosted CI and Codex status must be checked for actual current HEAD; Linux deployment and `mapping_incompatible` remain unverified.


- 2026-10-22 Docker ES private-IP relocation option PR #296: default remains CA + IP SAN strict. Explicit warning-only mode permits bounded CA-validated read-only Mapping observation with downgraded TLS/Mapping WARN and exit 2, NEVER verified service identity or FULL_LIVE acceptance. A CA-signed impersonating peer may obtain Basic credentials because IP identity is unverified; do not auto-downgrade, only operator-authorized trusted environments, no DNS/proxy/writes, no runtime Elasticsearch client changes and no simultaneous intentional bad-password challenge.

- 2026-10-22 PR #296: standalone operator ES HTTPS diagnosis offers default CA-valid Quick/Diagnose with IP SAN mismatch WARN and opt-in `--strict-ip-san` required to confirm leaf IP identity. The negative-password `--verify-credentials` path implicitly sets strict TLS. On SAN mismatch, mark identity_warning and never claim official Mapping/TLS PASS even if other ES-like responses are parsed; preserve the warning through all independent GETs and failures. The Quick mode still sends configured Basic credentials to an IP-unverified CA-signed endpoint, which is an explicit reduced assurance. No runtime ES TLS change, no DNS/proxy, no LIVE acceptance promotion.

- 2026-10-22 OFF-1B transport parsing change PR #297: isolate HTTP response entity frame validation and bounded Chunked decoding for Mapping GET, preserve fixed-length parsing. Use same CA-verified numeric private IPv4 endpoint and default Quick IP SAN WARN. Distinguish HTTP frame acceptance from mapping predicate; chunked decoded Mapping <=2MiB while root/auth <=64KiB. Keep absolute GET timeout, trailer bounds, strict no CL+TE and unsupported stacked coding, no decompression, no shell/DNS/proxy/search/index writes. No real Linux acceptance yet.

## 2026-10-24 OFF-1 Operator Architecture (Current)
- OFF-1B/1C diagnostics follow configured ES selectors with CA/TLS awareness, bounded read-only Mapping/search; warn-only IP SAN cannot certify ES identity. OFF-1D composes distinct redacted partial rows and defaults to no network.
- OFF-1E inventory is not LLM inference. OFF-1F local generation requires explicit flags and Linux Ollama listener process/no-cloud attestation; no live Agent/RAG/Word claim.
- OFF-1G uses a separate diagnostic SQL account, strict numeric-private IPv4 IP-SAN ODBC18 TLS, one literal constant SELECT. OFF-1H independently binds bounded local Schedule/Handoff identity files to /proc start, euid, cwd and exact argv; process identity is not job progress.
- OFF-1I separately observes SQL Handoff coordinator lease existence/active heartbeat; OFF-1J measures two renewed SQL lease heartbeat snapshots 15 seconds apart with unchanged fencing generation under *four* explicit flags and prior SQL/lease PASS. It never fetches owner/token, associates a local worker PID, or attests Schedule/Report Job progress.
- SQL Server remains the Requirement Version/Snapshot and Schedule/Handoff authority; API Report Job lifecycle, Agent/LLM/ES, signed Word output and physical airgap remain separate E2E release gates.

## Archived History — 2026-10-24
- `.codex/archive/architecture.md-20261024-180500.md` — original complete 15,245-character architecture, archived and byte/Git-SHA verified before this compaction; includes every previous dated design block.
- Previous archive `.codex/archive/architecture.md-20261021-165000.md` and its history chain remain intact.

## Compaction Record — 2026-10-24
- Complied with AGENTS.md >20 work-record rule; current architecture summary retains active design constraints, original full text is traceable. This documentation change is not Linux deployment acceptance.

## 2026-10-24 OFF-1K partial local owner correlation

- `tools/sraf_airgap_off1k_handoff_owner.py` composes canonical file-bound `verify_worker_identity` Handoff role checks, bounded initial /proc environ read of a single explicitly inherited owner ID, and one known-schema ODBC18/TLS SQL predicate query of lease owner equality. Rechecks PID/start/owner after SQL; no arbitrary path, dotenv evaluation, Worker start/stop, SQL DML/lease mutations or native credential/error exposure. Because bootstrap can load late values, absent initial owner is SKIP, never PID-based guess. `HANDOFF-OWNER` remains independent partial observation, not durable job or process-to-lease-session attestation.

## 2026-10-25 OFF-1L read-only Schedule SQL ledger observation

- Independent tools/sraf_airgap_off1l_schedule_claim.py observes two 15s-separated SQL COUNT_BIG snapshots for one verified canonical schedule ID with scheduled trigger and worker application-actor predicate. Reuses OFF-1G strict TLS private-IP ODBC principal, SQL-READ and WORKERS matrix gates. No SQL mutations, Requirement content, schedule enumeration or new scheduler; the actor label is not an authenticated process identity.

## 2026-10-25 OFF-1M SQL-side Schedule run linkage predicates

- New tools/sraf_airgap_off1m_schedule_run_link.py reuses OFF-1G strict TLS/private-IP operator SQL connection and OFF-1L canonical schedule selector. The extra query selects one Schedule, joins its active version and latest actor-labelled scheduled batch run, and projects only three CASE integer flags. OFF-1D requires all five explicit opt-ins and preceding SCHEDULE-CLAIM PASS. No runtime schema/mutation/daemon changes; the latest run can be different from the one OFF-1L counted and cross-table read is not an atomic identity proof.

## 2026-10-25 OFF-1N Handoff persisted-ack read-only observation

- `tools/sraf_airgap_off1n_handoff_ack.py` adds an independent, default-off, fixed SQL predicate read of latest actor-labelled Schedule batch, existing run items and `requirement_handoff_submissions`. The SQL projects two boolean flags (batch marked handed off and one selected item has a report_v1 submission/remote job ID/dispatched time). It inherits OFF-1G strict TLS/private IPv4 ODBC, OFF-1L schedule ID, OFF-1M prior linkage PASS, does not mutate DB or contact remote API. A persisted submission is not remote execution, owner/PID provenance or atomic system-wide evidence.

## 2026-10-25 OFF-1O Report Job persisted checkpoint

- `tools/sraf_airgap_off1o_report_checkpoint.py` extends the OFF-1D partial readiness matrix with seventh opt-in `--probe-report-checkpoint`. The fixed SQL is bound to the one canonical Schedule ID and checks two only-server-computed flags on the latest actor-labelled run: batch Handoff/reconciliation timestamps, plus ONE matching item with a report_v1 submission and completed remote state, persisted artifact reconciliation, nonempty recorded path and valid-looking SHA256. This is not remote HTTP, DOCX-byte integrity nor actual PID provenance; no new scheduler or execution path.

## 2026-10-25 OFF-1P actual local DOCX integrity (still partial)

- `tools/sraf_airgap_off1p_docx_integrity.py` extends operator-only readiness with eighth flag `--probe-docx-bytes` after REPORT-CHECKPOINT PASS. One fixed SQL query scoped to the canonical schedule extracts *one* already-completed selected item's publisher relative path, digest and frozen output-root fingerprint in process memory. Separately set deployment root must match canonical fingerprint. Linux openat-style fd-relative O_NOFOLLOW reads up to 16MiB, validates bounded DOCX ZIP and recomputes SHA-256. JSON carries only approved reason/checkpoint boolean; real Report Job HTTP and actual E2E remain distinct future gates.

## 2026-10-27 OFF-1Q one authenticated Report Job status observation

- Default-off operator `REPORT-LIVE` matrix row depends on `SQL-READ` and prior `DOCX-BYTES` PASS with nine explicit flags. After a private TLS/ODBC read restricted to one canonical Schedule ID, resolve one matching report_v1 Handoff submission and remotely persisted job ID in-process, then a single localhost-only authenticated bounded no-proxy/no-redirect GET `/v1/report/jobs/{id}`. Require response job_id, metadata submission/workflow identity and completed state. SQL/probe row/order mirrors OFF-1P but its observations are not atomic and cannot guarantee the earlier DOCX check was for identical run_item.

## 2026-10-27 OFF-1R same-item partial correlation

- Add one operator-only `tools/sraf_airgap_off1r_same_item_chain.py` and `REPORT-CHAIN` row after prior `REPORT-LIVE: PASS` and tenth explicit flag. One SQL joined result selects one schedule batch/run item and published DOCX/path/SHA/root, Handoff submission, remote job ID. The pinned local directory descriptor and saved SQL tuple are reused to verify actual DOCX bytes and authenticated fixed localhost Report Job response, then a second identical SQL query must still return the same tuple. No new API routes, mutation, scheduler or worker. SQL and HTTP/filesystem snapshots are sequential; their equivalence is not atomic or cryptographic provenance.

## 2026-10-27 OFF-1S Linux API listener identity partial trust boundary

- New `tools/sraf_airgap_off1s_api_listener.py` independently reads only the launcher-managed API identity file and bounded Linux proc TCP/socket/process attributes, verifying exact run_sra_api.sh Uvicorn argv, effective UID, same cwd root inode and recorded PID/start ticks. The OFF-1D matrix adds an eleventh opt-in `API-LISTENER` row before REPORT-LIVE, and opts into listener guards in both REPORT-LIVE and REPORT-CHAIN. OFF-1Q authenticated fixed 127.0.0.1 GET re-verifies the same proof **on connected TCP socket before sending Authorization** and after response; unverifiable listener yields SKIP without sending token. Existing unguarded OFF-1Q/R flag behavior remains backward compatible when OFF-1S is not requested. No runtime API route, scheduler, SQL mutation or complete service-authentication implementation; synthetic CI cannot prove trusted server binary.


## 2026-10-29 OFF-1S task-level listener ownership verification

Process group leadership does not imply one shared Linux FD table. OFF-1S
exclusive socket-owner proof now inspects every visible
`/proc/<PID>/task/<TID>/fd` (not solely `/proc/<PID>/fd`), with upper limits
for process, thread and FD counts, and fails closed on missing/inaccessible
thread evidence. This guards independent fd tables created by
`close_range(CLOSE_RANGE_UNSHARE)`; it is still not cryptographic
listener authentication, atomic socket-to-process proof, full namespace
visibility, or live SRAF system acceptance.

## 2026-10-29 OFF-1T standalone offline listener probe

- tools/sraf_airgap_off1t_api_listener_check.py invokes the existing OFF-1S probe_api_listener, with only an absolute installed repository path and local numeric API port. This adds no new socket verification, API endpoint, authentication flow or database dependency. It reports redacted status, returns 0 for a corroborated snapshot or 2 for inconclusive observations, and never claims full live acceptance.

## 2026-10-29 Read-only runtime baseline composition (proposed)

- `tools/sraf_runtime_baseline_readonly.py` reuses reviewed OFF-1S API listener, OFF-1A anonymous bounded loopback GET, and OFF-1H worker-identity predicates. It observes independently and never upgrades three point-in-time PASS rows to Agent/LLM/SQL/ES/DOCX/full-airgap acceptance. API listener is re-checked after HTTP to reduce, not eliminate, identity races. No new endpoint, scheduler, database, credential scope or service lifecycle change.

- Operator-only E2E cooperative deadline (2026-10-30): `OperatorPreflightTracker.run` scopes `agent/e2e_preflight_budget.py` ContextVar monotonic time budget; capability LLM/ES calls use bounded per-call timeouts and the same budget check before immutable plan write. Source/root checks precede backend resolution. API-status RUNNING_OVERDUE is process-local/observational, not cancellation or a second job system. Normal SRAF reporting has no E2E budget scope.


- 2026-10-30 Follow-up: `sra_api/services/linux_e2e_preflight_guard.py` holds Linux no-follow same-host `flock` across `OperatorPreflightTracker.run` (including SDK blocks); tracker retains local generation/status, and host-lock observer reports only a busy bit. Separate Linux API processes do **not** share immutable `BackendPlan`. `agent.external_capabilities.prepare_requirement_elasticsearch` pre-checks count and all fixture IDs via `mget`, creates only missing documents, post-checks again. Not a distributed lock or atomic ES fixture transaction.


- 2026-10-30: `agent.external_capabilities.staged_plan_publication/publish_staged_plan` provides request-ContextVar-only candidate while operator preflight runs. Only `OperatorPreflightTracker.run` opts in, publishing after complete evidence handler return and budget checks. Other E2E worker threads/processes continue to fail closed while no local frozen plan exists. Existing immediate `frozen_plan` direct-caller contract unchanged. Cross-process plan dissemination/durable result evidence remains unimplemented.
