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


- 2026-10-22 PR #296 adds an explicit operator CLI-only --warn-only-ip-san diagnostic. The default strict CA + numeric IP SAN identity requirement is unchanged. The opt-in keeps CERT_REQUIRED trusted CA chain, private numeric IP destination and bounded GETs but allows missing IP SAN only as identity_warning=true / tls_validation=WARN. On a peer identity mismatch, a compatible or incompatible mapping observation becomes non-authoritative mapping_probe=WARN with *_identity_unverified reason; exit 2 always indicates incomplete. The configured Basic credentials are still sent to a CA-signed but IP-identity-unverified peer, posing a real impersonation/secret exposure risk, so warning mode cannot combine with --verify-credentials. No official TLS PASS, FULL_LIVE or production ES client change.

- 2026-10-22 PR #296 CLI revised: no flag => default Quick/Diagnose WARN IP SAN policy; --strict-ip-san => strict CA + IP SAN; --verify-credentials => strict by implication; --warn-only-ip-san remains compatibility alias to default Quick and must not coexist with either strict/verify. Quick requires CA chain validation and private numeric IPv4, returns tls_validation=WARN + mapping_probe=WARN + exit 2 on mismatched SAN, records identity_warning even if HTTP response transport later fails (`es_https_transport_unavailable_ip_san_mismatch`). Quick still transmits the configured Basic credential after CA-only verification; user must not construe identity or Mapping as FULL_LIVE acceptance.

- 2026-10-22 PR #297 standalone OFF-1B ES HTTPS operator CLI reads HTTP/1.1 `Transfer-Encoding: chunked` in addition to a single Content-Length. Reject CL+TE conflict, duplicate/stacked unsupported codings, oversized/truncated chunks/invalid CRLF/trailers with sanitized error classification. Size limit is 2 MiB decoded for Mapping GET, 64KiB root/auth; 3-second total deadline. Existing reason/TLS identity trust boundaries unchanged; the previously reported es_https_transport_unavailable_ip_san_mismatch from unsupported framing does not prove mapping_incompatible.

- 2026-10-22 PR #297 reviewed transport contract: on either supported body framing mode, `Content-Encoding` absent or exactly one case-insensitive `identity` value; reject gzip/br/deflate, stacked or repeated fields without decompressing. Auth/TLS SAN warning, fixed origin and Mapping acceptance semantics unchanged.


## 2026-10-22 OFF-1B ES configured index operator CLI (not HTTP API)

- `python tools/sraf_airgap_off1b_es_index_discovery.py [--no-network] [--strict-ip-san] [--show-index-names]` emits `sraf_airgap_off1b_es_index_discovery_v1`, always `mode=PARTIAL_ONLY_NOT_ACCEPTANCE` and `feature_acceptance=NOT_TESTED`. Results have stable `ES-IDX-XX` check IDs, source types, `ACTIVE_REQUIRED|ACTIVE_OPTIONAL|E2E_FIXTURE` classifications, selector resolution, per-profile static Mapping statuses, separate multidimensional observation, and explicit `query_probe=NOT_TESTED`.
- No configured index names appear unless explicit operator `--show-index-names`; never use that option in shared logs. No API route, cluster enumeration, documents, SQL/LLM probes or writes. Exit 1 denotes observed critical failure, exit 2 an incomplete/partial result; never return code 0 as FULL_LIVE acceptance.

## 2026-10-23 OFF-1C optional operator search CLI contract (proposed)

- `python tools/sraf_airgap_off1b_es_index_discovery.py --check-readonly-search --strict-ip-san` adds at most one literal selected-index Elasticsearch read-only `GET /{index}/_search?size=0&track_total_hits=false&terminate_after=1&timeout=1s&allow_partial_search_results=false` after the existing mandatory root, protected-principal and Mapping probes. Without `--strict-ip-san` the extra option blocks all requests and marks `readonly_search_requires_strict_ip_san`.
- For each existing per-selector result the new `query_reason` provides a redacted fixed reason; `query_probe` remains NOT_TESTED by default. Only a compatible first ACTIVE_REQUIRED selector may be assessed as PASS/FAIL/NOT_VERIFIED, subject to TLS and role checks. `mode=PARTIAL_ONLY_NOT_ACCEPTANCE` and `feature_acceptance=NOT_TESTED` are unchanged. Query FAIL returns exit 1; incomplete evidence returns exit 2. No document snippets, document counts, URLs or ES response bodies are returned.

## 2026-10-24 OFF-1D local CLI output (proposal, not an API route)

- `python tools/sraf_airgap_off1d_readiness_matrix.py [--probe-network]` returns JSON schema `sraf_airgap_off1d_readiness_matrix_v1`, mode `PARTIAL_ONLY_NOT_ACCEPTANCE`, overall `INCOMPLETE` or `ISSUES_FOUND`, `counts`, and fixed `results` rows of `id/component/aspect/status/reason/executed/depends_on/feature_acceptance`. No network by default, and no secrets/hosts/ports/body in response. Exit 1 denotes an observed failure; exit 2 denotes incomplete, including positive bounded probes. No exit 0 / FULL_LIVE.

## 2026-10-24 OFF-1E operator CLI additive flag

- `python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network --probe-llm-inventory` adds a single optional anonymous localhost Ollama /api/tags inventory observation, bounded by the existing OFF-1A client. LLM-INVENTORY may carry evidence-backed PASS/FAIL/SKIP with a fixed redacted reason. Its default remains NOT_TESTED. The matrix has no new HTTP API route and never promotes LLM-INFERENCE, SQL, ES, workers, Word or FULL_LIVE; CLI exit stays 1 on observed failure, 2 on incompleteness.

## 2026-10-24 OFF-1F CLI-only generation proposal

- `--probe-llm-inference` is optional and requires `--probe-network --probe-llm-inventory`. For local HTTP Ollama and positive inventory only, one bounded `POST /api/generate` returns an `LLM-INFERENCE` operator row with fixed reason, status and dependencies. It does not expose model name, prompt, response or credentials, does not create HTTP API routes, and never promotes FULL_LIVE or changes the matrix's exit policy.
