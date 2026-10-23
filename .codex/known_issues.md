# Known Issues

## Current Summary

- Formal Requirement deployment acceptance is not complete. Repository tests and documentation review are not substitutes for authorized live SQL Server, Elasticsearch, external LLM, Agent, Schedule/Handoff, artifact, and DOCX verification.
- Live Requirement acceptance is specifically blocked by the unresolved Elasticsearch `mapping_incompatible` capability/mapping condition. Correct the live mapping issue and rerun authorized capability plus end-to-end acceptance before claiming deployment PASS.
- Unified launcher/deployment Gates SD-1 through SD-7 and real safe-restart/takeover behavior still require operator verification in the deployed SRA container.
- The execution environment may block direct Git/package-index network access through proxy/DNS restrictions. Hosted GitHub connector operations can still be available independently; installed requirements have allowed repository work when package downloads were unavailable.
- Browser/Playwright runtime is unavailable here; UI work can use static DOM/JavaScript/API tests but still requires browser-capable acceptance.
- Private Requirement SQL Server and SRA/Elasticsearch deployment credentials/configuration are not available in this repository environment.
- Direct `pytest` may omit the repository root from `sys.path` in this container; `python -m pytest` is the verified invocation style.
- Excel-to-SQL may emit `datetime.utcnow` deprecation warnings and FastAPI/Starlette TestClient compatibility warnings.

## Open Issues

### Requirement deployment acceptance

- Resolve live Elasticsearch `mapping_incompatible`, then rerun mapping/capability verification and the real Requirement → Schedule/Handoff → Report Job → Agent/LLM/Elasticsearch → DOCX flow.
- Run fresh/migrated SQL schema/catalog validation, rollback/failure injection, fencing/failover, concurrency/races, HA, credential rotation, and production content-quality acceptance in an authorized environment.
- The previously observed single-item and three-item technical Golden Paths do not close these broader matrices and must not be restated as fresh acceptance.

### Launcher and deployment lifecycle

- Run `./run_sra_api.sh` in the actual SRA container against the existing listener and verify the intended API process receives TERM, port 9002 is released, API/Schedule/Handoff replacements start, SQL lease authority remains correct, and no unrelated process is signaled.
- Manifest-enabled package/overlay trust-chain tooling exists, but live SD-1 through SD-7 evidence remains pending; do not retroactively bless an old deployment tree.

### Retrieval exclusion boundary

- Report instructions can keep an excluded term out of core-term selection, but downstream synonym expansion still lacks a structured exclusion contract. Contextual disambiguation is mitigation, not a hard guarantee.

### Runtime/provenance observation limits

- Python cannot safely inventory every dynamically loaded module in separate Schedule/Handoff worker processes without additional IPC/instrumentation. Current provenance positively binds managed runtime files and worker entry identities; stronger per-process loaded-module attestation requires separate design.
- Deployment-local Requirement SQL registry remains privileged configuration and is intentionally outside release-provenance contents/hash disclosure.

### Verification environment caveats

- Historical combined full-suite runs exposed order-dependent/pre-existing failures and launcher timing sensitivity while focused required suites passed. These records are preserved in archive; do not reinterpret them as a current full-suite PASS or current production defect without re-running on the relevant head.
- Remote/live operator execution requires valid ignored/process configuration for deployment URL, model, and authorized superuser session credentials. Do not substitute a Service Key where a user-session authority is required.
- Signed URLs remain bearer capabilities until expiry; service-key persistence and local Report Job SQLite/artifacts are not multi-machine HA.

### OFF-0 / OFF-1B air-gap diagnostic limitations

- OFF-0 consists of static 19-check contract/schema validation, not an executed FULL_LIVE deployment probe. OFF-1A loopback and OFF-1B operator preflights are individually bounded PARTIAL_ONLY_NOT_ACCEPTANCE observations; neither guarantees SQL/ES/LLM/Workers/DOCX health or physical network isolation.
- The API /healthz-only probe cannot attest launcher PID, worker state or SQL leases; separate operator observation reported an approximately 89-second API-to-worker startup gap near the 90-second readiness threshold, not yet independently explained.
- PR #295 OFF-1B ES HTTPS read-only Mapping CLI enforces private numeric IPv4 destinations, existing fixed CA, IP SAN TLS verification and redacted responses. The runtime ES client may disable hostname assertion; do not weaken the diagnostic's TLS identity policy to match it. No live deployment evidence yet proves ES Mapping compatible.
- Default ES probe makes no deliberately invalid login and keeps `auth=NOT_VERIFIED`; optional `--verify-credentials` may attempt one randomized wrong-password check, with failed-login audit/lockout risks. Only HTTP 401 confirms challenge rejection; verified matching enabled principal on wrong-password 200 demonstrates ineffective control, while other ambiguous responses remain incomplete. Actual code, runbook and API contract are authoritative.
- The previously blocked GitHub Actions runs did not start due to a PRIVATE-repository account billing/spending limit. The repository is now PUBLIC and new Actions jobs execute normally; do not present the historical NOT_EXECUTED failures as Python test failures or a current billing obstacle.
- Product API P2.1 PR #288 had substantial parser/size/concurrency guards; real SQL Server multi-connection, read/write and operator E2E acceptance remain independently required. Cross-Task execution/result deduplication is not implemented or approved; never share results across owners without explicit review.

## Recent Changes

- 2026-10-21: PR #295 thirteenth exact-head Codex review on `e587fcda9404bb18e6ac6a7753687629eac77944` identified a P1 memory-compaction rule breach: `.codex/known_issues.md` and `.codex/backlog.md` exceeded 40 KB. Full originals were archived byte-for-byte first and active summaries condensed according to AGENTS.md. This resolves the file-size aspect of the review; new exact-head verification/review is required.
- 2026-10-21: PR #295 on prior exact head `e587fcda9404bb18e6ac6a7753687629eac77944` had real Hosted Actions #39551740910 SUCCESS: 539 pytest PASS, OFF0_CONTRACT 19 schema-only PASS, and compile/dependencies/config-only PASS. All CI evidence is commit-specific history; query current PR HEAD + Actions + Codex for the live release gate.
- 2026-10-21: Earlier PR #295 fixes included TLS aggregation and failure exit classification, 401/403/429/5xx Basic authentication ambiguity, credential-control opt-in and 401-only negative challenge, malformed ES Mapping structures, request count and report redaction. Details retained in archive, tests and operator runbook.
- 2026-10-21: The PUBLIC repository change enabled real successful Hosted CI; historical no-step 404-log workflows were blocked before starting by billing/usage restrictions, not failed test cases.
- 2026-10-20: PR #293 configured TCP and PR #294 API HTTP slices are merged and Hosted-reviewed, but those results never establish private Linux ES/LLM/SQL/Worker acceptance.
- 2026-10-16: OFF-0 static contract disallows fabricated runtime PASS/FAIL/WARN evidence for unimplemented probes. Do not infer live service readiness from successful schema validation.
- 2026-10-12: Product P2.1 input-size safeguards and SQL read consistency were reviewed in PR #288 but separate authorized server and E2E acceptance remains required; older head-specific findings are historical.

## Archived History

- `.codex/archive/known_issues.md-20261021-165000.md` — exact full pre-compaction active known-issues content (45,639 characters), including all prior work records, open concerns, environment caveats, and every dated review/CI detail through the thirteenth review; contents verified identical before updating this active file.
- `.codex/archive/known_issues.md-20261006-153400.md` — preceding complete pre-compaction history.
- `.codex/archive/known_issues.md-20260910-070805.md` — older full history. Additional archive links and full original dated entries remain discoverable in preserved files.

## Compaction Record

- 2026-10-21: Triggered by >40 KB, substantial duplicated dated review history and outdated earlier-head statuses. Archive created and content re-read/compared before active rewrite. Kept all ongoing blockers, operator security caveats and release conditions in active summary. Active record is historical evidence; current HEAD/CI/review must be queried live. No Linux deployment or merge authorized.


- 2026-10-22 ES Docker container relocation: actual peer verified CA chain but presented 2 IP SAN, 2 DNS SAN, none matching the new ES_URL IP (OpenSSL verify code 64), so strict OFF-1B correctly failed before auth/mapping. PR #296 proposes explicit non-authoritative warning-only IP SAN mode, retaining CA verification but bearing serious Basic-credential exposure risk to a CA-signed impostor. Never default to bypass. Linux Mapping compatibility and full SRAF offline acceptance remain unverified until independently authenticated operator evidence.

- 2026-10-22 PR #296 warning-mode status transparency: a peer IP SAN mismatch may already be observed before Basic credentials are sent, and subsequent HTTP timeout/malformed response must not erase the observed mismatch or its credential-exposure risk. Original Codex P2 after `d741bef...` fixed by retaining mismatch in transport error and propagating identity_warning on root/auth/mapping. Quick default is lower identity assurance than strict and still sends Basic to a CA-signed unverified-IP peer; even air-gap networks are not intrinsically immune to misrouting/rogue authorized certificates. Formal acceptance must demand strict verified peer identity. Linux remains unverified.

- 2026-10-22 PR #296 final review P2: if initial CA-verified mismatched-IP SAN was observed, later transport failures on independent authentication or Mapping TLS connections could overwrite WARN with NOT_VERIFIED. `_later_tls_failure` now keeps WARN whenever prior `identity_warning` is true and evidence is merely incomplete; an explicit later CA/certificate identity error remains FAIL. Added four regression combinations. No real Linux acceptance asserted.

- 2026-10-22 OFF-1B production observation: ES Mapping GET answers 200 + Transfer-Encoding: chunked, no Content-Length, identity encoding. Old manual HTTP parser demanded Content-Length and classified Mapping as `es_https_transport_unavailable_ip_san_mismatch` before compatibility predicate. Not a Mapping-incompatible finding. PR #297 adds bounded chunked decoder/2MiB Mapping cap; pending Hosted CI/Code Review/real Linux run, all under PARTIAL_ONLY_NOT_ACCEPTANCE. Known Docker IP SAN mismatch still needs proper peer verification for formal LIVE acceptance.

- 2026-10-22 PR #297 reviewed framing boundary: HTTP Content-Encoding must be absent or a single identity token; arbitrary, compressed, duplicated or stacked response encodings may otherwise cause false Mapping success from mislabeled bytes. Now fail closed with sanitized transport classification; use normal Content-Length or bounded HTTP/1.1 chunked plus explicit no-decompression policy.

- 2026-10-22 PR #297 Codex P2: printable but malformed chunk extensions (e.g., `1;foo==bar`) could have been falsely accepted. Decoder now validates full extension grammar using OFF-1 `_CHUNK_HEAD`, and separately bounds chunk hex token to 8 digits and line to 256 bytes. Negative regression tests added; await Hosted CI and exact-head Codex, no Linux confirmation yet.


## 2026-10-22 Configured index discovery limits

- Runtime still has a hardcoded default development-index fallback when neither `ES_INDEX` nor canonical YAML `default_indexes` is configured. The configured-target discovery reports `runtime_default_fallback_not_attested` instead of inventing a production target.
- `config/indexes.yaml` currently contains legacy singular `default_index`, while `config.index_loader.load_index_mapping` recognizes plural `default_indexes`. New operator tool reports the ignored spelling; runtime config migration is a separately reviewed change.
- Mapping-only role checks do not demonstrate live RAG query success, multidimensional writer compatibility, historical-index retirement, Basic negative credential control or FULL_LIVE deployment acceptance. Distinguish these unfinished checks in operator reports; no automatic index removal or write probes.

## 2026-10-23 OFF-1B Codex review trust findings

- PR #298 Codex exact-head review on `1d8beaa5` found three open issues (P1 late Mapping SAN warning lost on fixture alias early exit; P2 identity-unverified 404/incompatible Mapping classified as definitive FAIL; P2 numeric YAML selector normalization mismatch). Fixes and regression tests are committed on the PR branch, but **latest Hosted CI and new formal review must independently verify them**. Neither static Mapping nor WARN_ONLY TLS can prove real Elasticsearch identity or FULL_LIVE readiness.
