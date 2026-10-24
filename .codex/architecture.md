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


## 2026-10-22 OFF-1B configured ES selector discovery

- `tools/sraf_airgap_off1b_es_index_discovery.py` reads only bounded loader-selected index YAML declarations via `shared.runtime_provenance.index_config_paths`, combines literal `ES_INDEX` and topic selectors, and recognizes an E2E fixture only if explicitly selected. It does not list cluster indices. Per-selector `/{literal}/_mapping` resolves a single concrete index or reports ambiguity for multiple alias targets.
- The new operator CLI reuses vetted OFF-1B private IPv4/CA/protected-principal transport by calling `tools.sraf_airgap_off1b_es_https_mapping._observe(skip_mapping=True)`. Mapping inspection is role-scoped: RAG reference field, optional multidimensional nested-shape observation, or the existing E2E required subset. Query, writeback, credentials and FULL_LIVE acceptance remain untested. Old `_observe` behavior is unchanged unless the opt-in argument is supplied.
- Maximum 8 config files of 256KiB, 24 declared selectors and 12 network selector GETs; default names are redacted. Partial selector errors do not halt independent selector diagnosis; late TLS identity failure stops remaining ES credential-bearing requests.

## 2026-10-23 OFF-1C operator-only search preflight proposal

- A single optional `--check-readonly-search` check reuses `tools/sraf_airgap_off1b_es_index_discovery.py` and its existing strict-CA numeric-private-IPv4 GET transport; it requires explicit `--strict-ip-san`, a compatible ACTIVE_REQUIRED Mapping and no peer-identity/fixture conflicts. It uses a fixed Elasticsearch zero-document, no-count, terminate-early, one-second query timeout request. There are no document or score outputs and no new HTTP API routes, credentials, search DTOs or storage.
- Query PASS is endpoint-level partial evidence, not real RAG retrieval or FULL_LIVE acceptance. CI exercises mocked network boundaries, not the air-gapped host.

## 2026-10-24 OFF-1D operator matrix proposal

- `tools/sraf_airgap_off1d_readiness_matrix.py` is an operator-only composition layer above existing OFF-1A/OFF-1B bounded probes; it does not import runtime API/workers, create tasks or connect to SQL. Its default is local disk/ODBC and configuration-only observation; `--probe-network` enables configured numeric private-IP TCP for API/ES/LLM plus dependent loopback /healthz. All unimplemented semantic acceptance probes remain literal NOT_TESTED, with fixed `depends_on` links, redacted reasons and overall INCOMPLETE/ISSUES_FOUND only.
