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

## 2026-10-24 OFF-1 Remaining Verification Gaps (Current)
- Live ES Mapping remains subject to actual deployment verification; historic `mapping_incompatible` and relocated private ES IP SAN mismatch were not cleared by CI. Strict certificate identity must not be replaced with warn-only diagnostic for acceptance.
- OFF-1B/1C read-only ES diagnostics, OFF-1E model-list, OFF-1F inference, OFF-1G SQL constant SELECT, OFF-1H Worker PID, OFF-1I SQL lease and OFF-1J heartbeat renewal are **separate partial evidence only**. CI mocks provide no private SQL or Ollama credentials and cannot certify live service health.
- OFF-1J advanced heartbeat only means some coordinator renewed one lease generation on the DB between two SELECTs. It does not bind to local Handoff PID or guarantee any dispatch/reconciliation progress. Custom `REQUIREMENT_HANDOFF_OWNER_ID` prevents naive PID owner guessing. A loaded or slow coordinator can cause fixed 15s observation to return inconclusive SKIP.
- Schedule Worker has no independent SQL heartbeat; `claim_due()` mutates scheduling state, so health cannot be proved by triggering it in a diagnostic. API Report Job Worker, Agent/LLM/Elasticsearch, DOCX, output integrity, isolation and SD-1–SD-7 remain pending real operator acceptance.
- ODBC login/query timeouts do not promise server-side cancellation or precise total wall deadline. The operator must use a DBA-restricted SQL principal, verified private IP SAN TLS, correct schema and explicitly authorized network/SQL/sampling flags.

## Archived History — 2026-10-24
- `.codex/archive/known_issues.md-20261024-180500.md` — entire 17,224-character active known-issues record, byte/Git SHA verified first; all dated OFF-1 and Product limitations traceable through it and `.codex/archive/known_issues.md-20261021-165000.md`.

## Compaction Record — 2026-10-24
- Active known issues retain unresolved production, service, security and acceptance gaps; older dated issue narratives are recoverable from complete full-content archive. No deployment action or FULL_LIVE claim.

## 2026-10-24 OFF-1K local owner evidence limits

- Process initial /proc environ may not contain `REQUIREMENT_HANDOFF_OWNER_ID` added by the existing post-exec bootstrap .env loader, even when runtime Coordinator has an explicit custom owner. Default `handoff-PID` cannot be trusted if dotenv overrides it, so OFF-1K conservatively SKIPs unless a unique valid owner was **already inherited at exec**. Reading >64KiB env or inaccessible PID namespace also SKIPs. Even exact SQL owner match under unchanged live PID is not proof the local process performed the previously observed heartbeat renewal or actually completed jobs. The diagnostic SQL principal must be separately DBA-restricted; Hosting mocks are not the operator's live deployment.

## 2026-10-24 P2.1 pending regression validation

- Oversized URL-encoded Preview `requirements_json` is rejected before Preview service runs but its status depends on the framework version: deployment host with Starlette 0.50 historically returned Product HTTP 422 `requirement_preview_input_invalid`; Hosted PR #289 run #40090472110 with FastAPI 0.162.0 / Starlette 1.9.0 returned framework HTTP 400. That failed run had 64 PASS / 1 FAIL and is **not** acceptance evidence. Test now checks safe bounded 400 or canonical safe 422, always no service call. Unpinned framework versions remain an API-status consistency consideration for clients; pin/normalization needs independent contract decision. Rerun exact-head `python -m pytest -q tests/test_requirement_product_api.py` and formal Review before Merge. OFF-1 Hosted checks cannot replace Product API coverage.


## 2026-10-24 OFF-1K main synchronization note

- PR #289 P2.1 URL-encoded Preview's 400/422 response split and dependency-version contract note were preserved during OFF-1K branch update; PR #289 is now merged into main, though strict HTTP response consistency remains an optional future decision. An earlier OFF-1K Codex CLEAN/CI is stale after this branch integration; run checks again on the exact new HEAD. No real Linux/SQL acceptance inferred.

## 2026-10-25 OFF-1L current limitations

- requirement_batch_runs.created_by is application-supplied and cannot identify which local Schedule PID created a run. A quiet schedule normally yields SKIP in the fixed 15-second window. DBA SELECT privileges, live SQL v4 schema, Report Job and DOCX acceptance cannot be established from Hosted mock ODBC tests.

## 2026-10-25 OFF-1M remaining attribution gap

- Actor-labelled run ledger and a currently coherent-looking active-version/latest-run/next-run SQL predicate are **not** authenticated local Schedule PID execution, atomic transaction proof, or exact attribution to OFF-1L's just-counted row. Normal SQL Server read committed isolation permits concurrent table changes; false inference must be prevented by partial-only language. Disabled/reconfigured/quiet schedules legitimately produce SKIP. Real Linux/SQL Server deployment, DBA SELECT privileges, Handoff/Report Job/DOCX and physical airgap remain separate acceptance tasks.

## 2026-10-25 OFF-1N evidence limits

- A valid SQL `requirement_handoff_submissions` row and non-null remote_job_id/dispatched_at only prove recorded handoff acknowledgement; neither the remote HTTP service nor actual Report Job execution is independently checked. Cross-table SELECT is not a serializable history or unique binding to OFF-1L's newly counted run. Actual Handoff/Report Job process correlation, provider job completion, DOCX artifact integrity and private physical airgap acceptance remain pending.

## 2026-10-25 OFF-1O persisted checkpoint is NOT Report Job proof

- `remote_job_state=completed`, `artifact_sha256` and `artifact_reconciled_at` are SQL-stored data; OFF-1O does not authenticate the actual Report Job API status or recompute real DOCX bytes. The presence of one completed selected item cannot certify all items or whole-batch success. Concurrent SQL writes, non-serializable cross-table reads and application actor labels preclude definitive attribution to OFF-1L's specific new row or local PID. Live private SQL/remote API/DOCX and isolation acceptance pending.

## 2026-10-25 OFF-1P evidence limits and private host restrictions

- Real DOCX byte match with a database-recorded digest establishes local published file consistency only: the digest itself was persisted by application, not independent provenance or verified Report Job API status. One completed selected run item does not imply the whole batch succeeded. Operator root must exist, not be symlink and match frozen canonical path fingerprint; fd-relative Linux O_NOFOLLOW and 16MiB file, 64MiB zip-uncompressed limits deliberately SKIP larger/unsupported artifacts. Hosted unit tests use temporary local DOCX and mocked SQL; real SQL deployment/operator privileges, authenticated Report Job GET, Agent/LLM/ES execution, and physical isolation still pending.

## 2026-10-25 OFF-1P two Codex P2 corrections

- Earlier OFF-1P opened absolute root after SQL, allowing replacement of a parent symlink; fixed by pre-pinning every root path component with O_NOFOLLOW and carrying the FD over the SQL query. ZIP `zlib.error` on a digest-matching corrupt DEFLATE stream now returns FAIL, not SKIP; both reproduced in regression tests. Still no real operator Linux/SQL/DOCX acceptance. Root path whose ancestors are symlinks is conservatively rejected; runtime mutable storage mount/device trust and authenticated remote job response remain independent tasks.

## 2026-10-27 OFF-1Q remote status evidence limits

- Only same-host loopback 127.0.0.1 HTTP is permitted; remote/private IPv4 HTTPS status probes not supported in OFF-1Q because validated service identity/TLS and SSRF constraints need independent review. REPORT_JOB_READ token must belong to principal authorized for Handoff-created job; normal owner restrictions can yield 404 SKIP. GET may emit server audit records. The SQL-observed selected item can change between OFF-1P DOCX byte verification and OFF-1Q SQL + HTTP GET; these independent PASS observations do not prove same immutable item or batch, trusted listening PID, Agent/LLM/ES computation or physical isolation.

## 2026-10-27 OFF-1Q bounded loopback HTTP framing decisions

- Earlier OFF-1Q used Requests stream timeout, which is inactivity-only; trickling listener could delay indefinitely. Replaced with fixed IPv4 socket request and 3s absolute monotonic deadline on connect, send, headers and body reads. Diagnostic deliberately rejects chunked or compressed responses, missing or duplicate Content-Length, headers >4KiB, JSON >8KiB or HTTP redirects: legitimate alternate proxies/servers may produce SKIP rather than PASS. Do not disable these limits for convenience or send credentials to unverified network hosts. Local 127.0.0.1 does not cryptographically attest API listener PID/owner; real operator auth and airgap pending.

## 2026-10-27 OFF-1Q SQL alias binding regression

- Codex review identified SQL Server projection scoping bug `SELECT h.submission_id` outside the `OUTER APPLY` body: alias h only exists within APPLY. Fixed to the outer derived column `i.submission_id`. Fake ODBC executes no SQL parser, so this test checks static projection syntax; live SQL Server execution still operator-pending.

## 2026-10-27 OFF-1R sequential chain and runtime validation limitations

- The new REPORT-CHAIN SQL selection binds the same selected item across its local DOCX and remote Job observations, and a second SQL tuple comparison detects some drift. It is **not an atomic cross-system transaction**; ABA selection changes and post-sample changes cannot be excluded, nor does it attest a trusted listener/PID, real job execution provenance, Agent/ES/LLM, full batch or isolation. Root descriptor stays pinned but trusted mount/device remains an operator concern. Hosted fake ODBC cannot prove SQL Server parse/permission; actual SQL syntax/column existence and read-only principal require real private deployment test. API GET may produce audit logs even though operator probe sends no writes.

## 2026-10-27 OFF-1R SQL migration column owner correction

- The first OFF-1R query draft incorrectly referenced `h.remote_job_id` and `h.dispatched_at` on `requirement_handoff_submissions`. The authoritative `requirement_scheduler.migrations.REQUIRED_COLUMNS` places both on `requirement_batch_run_items`. Replaced with `i.remote_job_id IS NOT NULL` and `i.dispatched_at IS NOT NULL`; Handoff is linked through `h.run_item_id=i.run_item_id` and workflow. Added migration-column/alias parity test, since mocked ODBC tests never parse SQL Server column references. Live SQL Server syntax still requires operator validation.

## 2026-10-27 OFF-1S service listener identity and residual races

- Process identity record is launcher-managed but same-UID writable, not digitally signed. A same-UID malicious process may forge it and imitate expected command line/socket fd; no cryptographic server authentication. Rechecking PID/start/socket after TCP connect and before writing bearer reduces but cannot eliminate the race between verification and send. Listener on 0.0.0.0 is not evidence of firewall/isolation. Fail closed when API uses different uvicorn command/title or nonshared proc/network namespace or when IPv6 listener may shadow IPv4, PID/fd access denied, or socket ambiguous. Operator-hosted test must check actual deployed Uvicorn title and launcher identity; Hosted pytest mocks cannot attest live runtime or private network.

## 2026-10-27 OFF-1S PR #316 shared listener ownership and process argv

- 2 formal P2 on exact head 29e923e: pip-installed uvicorn may have a seven-argument Python-shebang /proc cmdline or sra_api/main.py may apply setproctitle; earlier strict six-arg matcher incorrectly SKIPPED legitimate API. A unique socket inode still can be held by multiple processes; unrecorded socket acceptor can receive bearer even if one known PID owns the inode. Remediation adds exact launch/title alternatives and bounded, conservative global /proc/*/fd exclusivity, with synthetic regression tests. If process visibility is restricted, return SKIP instead of a false identity PASS; PID namespaces and same-UID spoofing still prevent cryptographic/race-free claims. Await exact-head Hosted CI and Codex review, no production attestation.


## 2026-10-28 OFF-1S procfs hidepid visibility P2

- A process-list scan cannot claim listener socket exclusivity when procfs `hidepid` silently omits other PIDs. OFF-1S now requires a bounded, unambiguous, unfiltered /proc mountinfo confirmation both before and after the global fd scan, refusing restricted/unknown hidepid, subset or nonstandard root mounts to SKIP. This conservative guard may SKIP on protected installations. PID namespace visibility, root/admin hostile tampering, mount-change races and same-UID impersonation remain beyond this noncryptographic operator diagnostic; actual private runtime acceptance is not established by Hosted CI.
