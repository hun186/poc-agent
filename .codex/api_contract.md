# API Contract

## Current Summary

- FastAPI routes live primarily under `sra_api/routers/`; `api/` preserves compatibility imports.
- Public integration surfaces include `GET /healthz`, `GET /v1/models`, `POST /v1/chat/completions`, document/fulltext retrieval, and synchronous Word export. Editor/Auth and data-management routes use bearer authentication and role checks.
- Persisted Report Jobs use `POST /v1/report/jobs`, `GET /v1/report/jobs/{job_id}`, and `GET /v1/report/jobs/{job_id}/word`. Jobs are owner scoped; completed artifacts must pass confinement and DOCX validation.
- Requirement import and schedule APIs expose authenticated source/profile/import, immutable snapshot/version, schedule lifecycle, manual run materialization, neutral Batch/Run Item status, and authorized artifact history without exposing credentials, prompts, absolute roots, or backend-native state.
- Product v1 internal authority interfaces include schema v4, preview, one-time/recurring create, Task updates, draft activation and low-level ownership fences in preceding P1 slices merged through PR #286. Public Task/Run read and preview are on P2.1 PR #288 review branch; do not claim its HTTP endpoints are merged or live-accepted without checking that PR. Product mutations require durable `Idempotency-Key`, canonical `request_sha256` binding operation + path/target identities + semantic payload/input digest. Later Product mutation routes, UI and browser E2E require independent acceptance.
- Excel-to-SQL endpoints provide dashboard task/config management, upload/preview/confirm, audit dashboards, controlled source-row reads/edits/deletes, and source statistics. Enabled-task allowlists and role boundaries remain authoritative.
- `GET /v1/operator-e2e/runtime-evidence` is authenticated, superuser-only, and read-only. Schema `requirement_e2e_runtime_evidence_v1` reports bounded deployment provenance identity, Schedule/Handoff worker identity, and artifact-root fingerprint.
- Runtime-evidence source failures include `release_provenance_missing`, `release_provenance_invalid`, `active_runtime_source_mismatch`, `unexpected_active_runtime_module`, `runtime_module_shadowing`, and `unexpected_runtime_input`. The last category means an actually selected/discovered release-managed input is absent from provenance.
- Requirement runtime evidence never reports the deployment-local SQL registry's contents, hash, resolved path, credentials, connection details, or query text; release provenance does not attest that privileged registry.
- `GET /v1/operator-e2e/batches/{batch_run_id}/items/{run_item_id}/artifact` is authenticated, superuser-only, accepts no path, and returns only the durable Handoff-published DOCX after metadata/root/confinement/ZIP/SHA-256 validation.
- Signed resource requests reject duplicate/unsupported query keys and substitutions before lookup, and successful responses use no-store/no-referrer/nosniff headers.

## Recent Changes

- 2026-10-21: OFF-1B ES HTTPS/Mapping is **operator CLI**, not API. `python tools/sraf_airgap_off1b_es_https_mapping.py [--no-network] [--verify-credentials]` reads effective runtime settings from repository root and emits redacted fixed-schema `PARTIAL_ONLY_NOT_ACCEPTANCE` status, never raw ES credentials, user/realm, Mapping values or target URLs. Default at most 3 independent TLS-validated read-only GETs and does not attempt a bad password; opted-in credential challenge adds one GET and has audit/lockout risks.
- 2026-10-21: Protected `/_security/_authenticate` HTTP 401 => `auth=FAIL/es_auth_rejected` (exit 1); 403 => `auth=NOT_VERIFIED/es_auth_access_denied` (exit 2); 404 => incomplete endpoint; 429/5xx/redirect/other unexpected => `auth=NOT_VERIFIED/es_auth_http_unexpected` (exit 2). Principal 200 must attest configured enabled Basic realm user but default auth remains unverified because proxies can inject credentials.
- 2026-10-21: Opt-in deliberately invalid Basic password GET HTTP 401 => `credential_control=PASS/auth=PASS`. HTTP 200 with matching enabled Basic realm principal despite wrong password => `credential_control=FAIL/auth=FAIL/es_credential_control_not_rejected`. Other status, 403/429/5xx, 404/redirect or unattested HTTP 200 => `credential_control=INCOMPLETE/auth=NOT_VERIFIED/es_credential_control_unverified`, exit 2; Mapping GET is skipped. Later independent TLS identity failure forces `tls_validation=FAIL`/exit 1.
- 2026-10-21: ES Mapping JSON top-level non-object or invalid nested `properties`/`fields` dictionaries => `mapping_probe=FAIL/es_mapping_response_invalid` exit 1; zero/multi-target dictionary => `SKIP/es_mapping_target_ambiguous`. Reuse existing `mapping_compatibility` on structurally valid mappings. No writes, FULL_LIVE or index alias wildcard support.
- 2026-10-20: OFF-1B API /healthz observation remains separate anonymous loopback CLI, not a new HTTP API endpoint; OFF-1B configured TCP checks only reachability. OFF-0 19-check JSON contract/schema validation never asserts private live dependency health.
- 2026-10-12: Product P2.1 PR #288 proposes authenticated Task/Run read pagination, side-effect-free manual JSON/multipart previews and consistent Task/Schedule reads, with preparse/decoded CSV JSON XLSX limits, 8KiB task metadata predecode limit and true missing Import Profile 422 normalization. Its routes and responses require current PR review and authorized SQL Server E2E before declaring released.
- 2026-10-08: Durable Product P1.5 PATCH is either in-place name/enabled CAS (revision increments once) or immutable Schedule proposal draft (no activation/revision increase); mixed modes rejected. P1.5A activates exact superuser-authorized proposal; P1.6 low-level ownership fences protect Product-owned Schedule/source mutations. P1.7 input replacement uses Snapshot CAS separately.
- 2026-09-18: Runtime provenance and authenticated evidence keep Requirement SQL registry privileged/deployment-local, reject untrusted release-managed runtime input/module shadowing, and confine published DOCX artifact by root, format and checksum; signed browser responses use no-store/no-referrer/nosniff.

## Archived History

- `.codex/archive/api_contract.md-20261021-165000.md` — exact full pre-compaction API contract (36,169 characters), including Product P1–P2.1 reviews, E2E/provenance semantics, ES credential-error classifications and earlier HTTP routes; verified identical before rewrite.
- Earlier archived API/version details remain available through this archive's referenced history.

## Compaction Record

- 2026-10-21: Archived then condensed >20 dated API/work blocks per AGENTS.md without changing the implementation. Current route support, status contracts, safe input bounds and auth/SQL ownership requirements remain above. Live deployment is not verified by Hosted checks; do not Merge PR #295 without explicit authorization.

## 2026-10-24 OFF-1 Operator CLI Contract (Current)
- OFF-1B ES Mapping/index selector/search probes and OFF-1D matrix are operator CLI surfaces only, not new authenticated HTTP API routes. Diagnostics are bounded/redacted, default offline, partial-only and never FULL_LIVE. WARN_ONLY ES peer SAN carries credential/identity risk and cannot be treated as identity-verified PASS.
- OFF-1D `sraf_airgap_off1d_readiness_matrix_v1` outputs fixed component rows, statuses/reasons/dependencies, `feature_acceptance=NOT_TESTED`, `overall=INCOMPLETE|ISSUES_FOUND`; exit 1 on observed FAIL, exit 2 on incomplete including partial PASS. Default no network.
- `--probe-network --probe-llm-inventory` gates single localhost Ollama inventory GET. `--probe-llm-inference` adds a third explicit opt-in plus verified actual server PID and OLLAMA_NO_CLOUD=1 before bounded generation.
- `--probe-network --probe-sql-read` gates separate dedicated ODBC18 private-address strict TLS constant SELECT. Adding `--probe-worker-lease` gates one schema-constrained Handoff SQL lease snapshot; adding `--probe-lease-renewal` gates two extra bounded SQL snapshots, separated by fixed 15s, comparing same fencing generation and increasing heartbeat marker. Distinct `HANDOFF-RENEWAL` row depends on `SQL-READ` and `HANDOFF-LEASE`; never reports lease owner/token/timestamp or job progress.
- Independent `--probe-worker-identities` is local-only `/proc` Schedule/Handoff identity evidence and requires no network; none of these CLI observations promotes API Report Job/DOCX/Worker throughput or physical network-isolation acceptance.

## Archived History — 2026-10-24
- `.codex/archive/api_contract.md-20261024-180500.md` — byte/Git-SHA verified full original 14,199-character active API contract before compaction. Earlier schema/route history remains under `.codex/archive/api_contract.md-20261021-165000.md`.

## Compaction Record — 2026-10-24
- Preserved all original 2026-10-22 through OFF-1J CLI status details and Product API history in full archive before condensing; no claim of live deployment or actual SQL Server.

## 2026-10-24 OFF-1K optional CLI owner-correlation flag

- `--probe-handoff-owner` requires `--probe-network --probe-sql-read --probe-worker-lease --probe-lease-renewal --probe-worker-identities` and prior `WORKERS` and `HANDOFF-RENEWAL` PASS, so the user's opt-in includes OFF-1J 15-second double SQL heartbeat read. Adds `HANDOFF-OWNER` (depends on WORKERS/HANDOFF-RENEWAL). Uses explicit local process birth env owner ID and a single byte-exact parameterized SQL owner equality predicate. Default is NOT_TESTED/no extra SQL or environ read, positive means identity-only snapshot, feature_acceptance remains NOT_TESTED, no new HTTP route or FULL_LIVE.

## 2026-10-25 OFF-1L optional operator CLI contract

- --probe-schedule-claim requires --probe-network --probe-sql-read --probe-worker-identities, valid SRAF_OFF1L_SCHEDULE_ID (sch_ + 32 lowercase hex), and SQL-READ/WORKERS PASS. SCHEDULE-CLAIM row depends on SQL-READ and WORKERS, reporting NOT_TESTED/SKIP or a strictly grown actor-labelled scheduled-run count. Counts/ID never printed, no new HTTP route, feature_acceptance remains NOT_TESTED.

## 2026-10-25 OFF-1M additional Schedule-link CLI flag

- `--probe-schedule-link` requires `--probe-network --probe-sql-read --probe-worker-identities --probe-schedule-claim` and prior SCHEDULE-CLAIM PASS. Adds `SCHEDULE-LINK` row with dependencies SQL-READ and SCHEDULE-CLAIM. Only SQL-computed 3-flag linkage of enabled/approved active schedule, latest actor-labelled scheduled run and later next-run timestamp can PASS; all missing/malformed/no-link statuses SKIP. It does not emit IDs/timestamps or expose new HTTP APIs and never upgrades `feature_acceptance=NOT_TESTED`.

## 2026-10-25 OFF-1N extra Handoff-ack CLI contract

- `--probe-handoff-ack` requires `--probe-network --probe-sql-read --probe-worker-identities --probe-schedule-claim --probe-schedule-link` and an actual previous `SCHEDULE-LINK: PASS`. New `HANDOFF-ACK` row depends on SQL-READ/SCHEDULE-LINK and may PASS only if both SQL-computed acknowledgment predicates are 1; otherwise NOT_TESTED/SKIP. No new HTTP endpoint or job start; no remote job identifiers/data returned, `feature_acceptance=NOT_TESTED`, FULL_LIVE not implied.

## 2026-10-25 OFF-1O additional Report checkpoint CLI

- `--probe-report-checkpoint` adds `REPORT-CHECKPOINT` row and requires existing six OFF-1N flags `--probe-network --probe-sql-read --probe-worker-identities --probe-schedule-claim --probe-schedule-link --probe-handoff-ack` plus prior `HANDOFF-ACK: PASS`. The SQL returns only two predicates about the latest actor-labelled run's persisted Handoff/reconciled time and one same item's Report Job completed/artifact reconcile metadata. No IDs, counts, digest, paths, credentials or native SQL errors appear in JSON; no new HTTP route or artifact read. `feature_acceptance=NOT_TESTED` and incomplete overall remain.

## 2026-10-25 OFF-1P optional operator DOCX integrity CLI

- `--probe-docx-bytes` requires seven preceding `--probe-network --probe-sql-read --probe-worker-identities --probe-schedule-claim --probe-schedule-link --probe-handoff-ack --probe-report-checkpoint` flags, real `REPORT-CHECKPOINT: PASS`, canonical SRAF_OFF1L_SCHEDULE_ID and absolute operator SRAF_OFF1P_ARTIFACT_ROOT. Adds `DOCX-BYTES` row depending on SQL-READ/REPORT-CHECKPOINT. One extra SQL read followed by a bounded nofollow local DOCX checksum/ZIP validation. Only digest/ZIP corruption yields FAIL; other inconclusive reads SKIP. No new HTTP route, no leak of file path/digest, no full acceptance.

## 2026-10-27 OFF-1Q operator-only report-live CLI

- New `--probe-report-live` after the previous 8 explicit flags and prior `DOCX-BYTES: PASS`. Operator also sets `SRAF_OFF1Q_REPORT_API_PORT` (decimal 1..65535 on 127.0.0.1) and `SRAF_OFF1Q_REPORT_JOB_READ_TOKEN` (owner-scoped REPORT_JOB_READ). No caller-supplied URL/hostname allowed. One SQL SELECT obtains same-selected-item report_v1 submission and remote job ID in process, one GET only with no redirects/proxy, 8KiB maximum JSON, requires matching job_id + metadata submission_id/workflow_id + status=completed. Adds `REPORT-LIVE` (depends on SQL-READ/DOCX-BYTES); no new HTTP API, no Word download or job POST; JSON omits identifiers/credentials. Overall remains partial INCOMPLETE; feature_acceptance NOT_TESTED.

## 2026-10-27 OFF-1R tenth optional operator CLI flag

- `--probe-report-chain` requires the prior nine OFF-1Q flags, real prior `REPORT-LIVE: PASS`, canonical schedule ID, operator root/port/read-only Report Job token and OFF-1G restricted SQL credentials. Adds a `REPORT-CHAIN` matrix row that depends on SQL-READ, DOCX-BYTES and REPORT-LIVE. This check privately selects 7 immutable-looking SQL reference fields and checks one local DOCX SHA256/ZIP plus same job/submission authenticated GET and rechecks SQL reference. JSON emits only reviewed fixed reason code/status/boolean, never schedule/batch/item/job IDs, path, digest, credential or API body. No new HTTP route, no create/download; overall remains partial, feature_acceptance=NOT_TESTED.
