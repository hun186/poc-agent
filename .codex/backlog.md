# Backlog

## Current Summary

### Live acceptance still pending

- Formal Requirement deployment acceptance remains incomplete. After merge and independent hosted-source review, run the Requirement automatic operator E2E only from an authorized deployment with valid `SRA_E2E_*` configuration; repository tests/docs do not prove a fresh live PASS.
- Resolve the live Elasticsearch `mapping_incompatible` blocker, then rerun authorized Elasticsearch capability/mapping acceptance plus the real Requirement → Schedule/Handoff → Report Job → Agent/LLM/Elasticsearch → DOCX path.
- Execute remaining authorized SQL Server acceptance for fresh/migrated schemas, rollback/failure injection, fencing/failover, concurrency/races, HA, and security rotation.
- Execute the complete Phase 0 Service-Key → real Elasticsearch/Agent/LLM → signed valid DOCX chain and post-pass credential rotation when an authorized environment is available.
- Execute pending unified-launcher deployment Gates SD-1 through SD-7, including durable output-root migration evidence. Do not replay or invent live evidence.

### Future architecture and product work

- Requirement Product API + Task Center Design/Plan v1 was approved in PR #277; P1.0–P1.4 create and recurring slices merged through PR #283, P1.5 Task updates in PR #284, P1.5A draft activation in PR #285, and P1.6 ownership fences in PR #286 per project work records. P2.1 Task/Run read and preview is implemented on PR #288 review branch with extensive input-hardening fixes; do not presume merged or live-accepted without a fresh PR check. P2.2, Product HTTP remaining mutations, service-key scopes, UI/browser E2E, cross-Task sharing and the separate offline deployment acceptance remain further work.
- Product implementation must integrate with the existing SRA `/editor` management shell/Auth/RBAC, reuse Phase 1B Requirement Import + Phase 1C Schedule/Handoff + Report Job, and never expose Handoff credentials or raw artifact paths to browsers.
- Product v1 requires Schedule schema v4 Product Task/request control-plane tables, superuser-only provisioning/activation, durable idempotency/resource-bound canonical hashes, revision/CAS rules, transactional ownership fences, provisioning visibility gates, atomic Run admission vs disable, and reviewed Product E2E coverage.
- Job Task JT-1 and LangGraph integration remain NOT STARTED and require new reviewed designs/plans.
- Consider Report Job retention, metrics, cancel/retry/webhook, shared queue/object storage, and HA/exactly-once strategy.
- Continue structured retrieval/event-cluster improvements and reference-text backfill/content coverage work.
- Consider stronger per-process worker loaded-module attestation only through a separately reviewed IPC design.
- Consider stronger sanitized SQL-registry attestation only as separately reviewed future work; do not expose the private deployment registry or add a manual expected-hash variable.

### Security, UI, and ingestion debt

- Evaluate shared auth throttling, MFA/re-authentication, CSP/XSS hardening, HttpOnly/CSRF design, stronger registration controls, and reusable audit/reset/navigation components.
- Add browser E2E when Playwright/runtime is available and improve audit server-side filtering/export as volume grows.
- Replace remaining naive UTC datetimes; improve Excel import error exports/diagnostics; design SQL View support and SQL/ES lineage/delete reconciliation.

### OFF-1B / Elasticsearch and next independent milestones

- PR #295 read-only ES HTTPS/Mapping diagnostic is still OPEN on `feat/sraf-airgap-off1b-es-https-mapping`. Complete exact-head Hosted CI and a clean formal Codex Review with all threads resolved, then obtain explicit user Merge permission. Do not update the private Linux deployment before release package approval.
- PR #295 default probing is non-mutating, uses private numeric IPv4 and CA/IP-SAN TLS verification, verifies protected ES principal without assuming Basic header success, and remains `PARTIAL_ONLY_NOT_ACCEPTANCE`. The explicit `--verify-credentials` check sends an intentionally invalid password and may generate failed-login audit/lockout events; default is safer and leaves auth NOT_VERIFIED. Existing live ES `mapping_incompatible` still requires authorized operator-run evidence.
- Next after ES: separately reviewed LLM backend/model-inventory probe without inference, then combined ES/LLM/API diagnostic. Implement SQL Server/ODBC/catalog, worker, report job/DOCX, genuine isolated network, OFF-2 release bundle, OFF-3/4 runner/report, and OFF-5 recovery/airgap acceptance in independently reviewed phases; never infer FULL_LIVE from contract-only OFF-0.
- Product P2.1 on PR #288 requires careful current-HEAD review, hosted checks, authorized live SQL Server/HTTP/concurrency and E2E tests before Merge. P2.2 and UI remain separate. Cross-Task dedup/output sharing is NOT implemented and needs its own privacy/ACL/provenance design and user authorization.

## Recent Changes

- 2026-10-21: Thirteenth exact-head Codex for PR #295 on `e587fcda9404bb18e6ac6a7753687629eac77944` found one P1: two active `.codex` records exceeded 40 KB and must be archived/compacted during the same task. Stored full originals under `.codex/archive/` and condensed to actionable active summaries. Latest SHA/CI and Codex must be rechecked after these edits.
- 2026-10-21: Prior exact-head Hosted Actions #39551740910 on `e587fcda9404bb18e6ac6a7753687629eac77944` succeeded: 539 pytest PASS, OFF0_CONTRACT 19 schema-only PASS, green compile/dependencies/config. Such facts are historical per-SHA evidence, not continuously updated current CI status.
- 2026-10-21: Earlier PR #295 security/diagnostic reviews fixed false authentication claims (401/403/429/5xx), optional invalid-password control, TLS validation aggregation/exit semantics, malformed Mapping JSON and unsafe error disclosure; previous findings/CI are preserved in the archive.
- 2026-10-21: Repository is PUBLIC; prior Private-repository billing/spending-limit Actions jobs never started. New public Hosted CI executes and passes; do not confuse historical NOT_EXECUTED with code failures or active restrictions.
- 2026-10-20: Configured OFF-1B TCP and API HTTP slices merged as PRs #293/#294, but private Linux end-to-end readiness is not proven by hosted checks.
- 2026-10-16: OFF-0 schema/contract tooling uses 19 checks and cannot report evidence-backed runtime service PASS before reviewed real OFF-1 probes exist.
- 2026-10-12: Product P2.1 read/preview branch PR #288 has extensive adversarial JSON/CSV/XLSX/parser, pagination and SQL snapshot-read fixes; merging requires latest-head verified evidence, not an older review.

## Archived History

- `.codex/archive/backlog.md-20261021-165000.md` — exact full pre-compaction active backlog (40,879 characters), preserving old Product PRs, OFF-0/1 stages, dated Codex fixes, GitHub CI evidence and unresolved future tasks; archive bytes verified before active rewrite.
- `.codex/archive/backlog.md-20261006-153400.md` — previous pre-compaction full backlog.
- `.codex/archive/backlog.md-20260918-000000.md` — earlier full backlog. Prior archive chain/history still available by following archived references.

## Compaction Record

- 2026-10-21: Mandatory compaction triggered by >40KB and obsolete/repeated work blocks. All original content preserved in archive, actionable unresolved requirements remain above, and current PR/CI state must be fetched from Hosted GitHub rather than frozen into this file. No Merge or Linux deployment authorized.


- 2026-10-22 PR #296: verify the Docker ES new-IP warning-only diagnostic, including actual latest-head Hosted CI, formal Codex review, CA failure remains FAIL, IP SAN mismatch is WARN not verified TLS PASS, mapping non-authoritative WARN, no wrong-password challenge in reduced identity mode and no secret logging. After explicit merge/deploy approval, collect Linux operator observations, then independently fix certificate identity (new IP SAN or reviewed stable DNS name) before FULL_LIVE acceptance. PR is not merged, Docker config unchanged.

- 2026-10-22 PR #296: obtain fresh exact-head Hosted CI and formal Codex no-P1/P2 after shifting Quick CLI default to WARN, introducing --strict-ip-san, preserving legacy alias and repairing Codex P2 SAN warning lost on HTTP-response failures. Test real Linux after user-authorized merge; default warning is not FULL_LIVE and real Basic credentials still reach an identity-unverified CA-certified endpoint on old IP SAN, so do not promote to PASS. Independently design stable TLS DNS identity if portability and end-to-end verified acceptance are both required.

- 2026-10-22 PR #296 final gate before operator-authorized merge: check exact-head Hosted Actions PASS plus Codex completion on fix to previous SAN warning loss for a later auth/mapping connection failure. Distinguish old SAN observation WARN from genuine later certificate verification FAIL. After merge, user will pull and incrementally deploy manually; obtain actual private ES TLS/auth/Mapping partial evidence and do not mark FULL_LIVE based on Quick warning mode.

- 2026-10-22 PR #297: verify safely decoded HTTP/1.1 chunked ES Mapping responses with exact-head Hosted tests, Codex review, and operator deployment. Keep conflicting CL/TE, stacked codings, truncated bodies, oversize payloads, malformed CRLF and trailers rejected. Root/auth remain 64KiB, Mapping <=2MiB, 3s deadline. Re-run Linux CLI after explicit authorized Merge; `tls_validation=WARN` remains a non-authoritative result, not FULL_LIVE; separate true Mapping compatibility still pending.


## 2026-10-22 ES configured-index discovery review / remaining work

- Verify new `feat/sraf-off1b-es-index-discovery` HEAD with OFF-1B targeted pytest, Hosted CI exact-head and clean Codex review, then resolve findings. Do not merge without operator instruction; no Linux changes.
- After explicit deployment authorization, run `python tools/sraf_airgap_off1b_es_index_discovery.py` on real air-gapped host and reconcile actual configured indexes, aliases, and roles. Historic `satmeta` may be required as default until live call-chain evidence proves otherwise; do not label it retired from the name or mapping alone.
- Future independent slices: bounded operator-authorized read-only query capability, evidence-linked alias/selector verification, authorized E2E isolation, and dependency-aware orchestration of SQL/LLM/API/workers/Word checks with no false FULL_LIVE success.

## 2026-10-23 PR #298 remaining exact-head gates

- Validate remediation of Codex P1+2 P2 on current HEAD through Hosted OFF-1B pytest/OFF-0 contract and fresh Codex review receipt for precisely the reviewed SHA. Reply to the three new findings and resolve threads only after verifying fixes; repeat until CLEAN or report outstanding issues. Keep PR unmerged and obtain real Linux read-only diagnosis only after separate operator-authorized deployment; no production mutation or FULL_LIVE claim.

## 2026-10-23 PR #298 external YAML-path parity follow-up

- Complete Hosted CI tests and exact-head Codex review on the explicit external config-path compatibility fix. Once tests pass, reply to the new P2 Finding, resolve its thread, re-request formal Codex review on latest SHA, and do not Merge without operator authorization. Operator-only Mapping and external-file identification remain NOT_FULL_LIVE; externally managed file provenance must be independently attested.

## 2026-10-23 PR #298 selected YAML failure gate

- Verify current exact-head OFF-1B Hosted CI after fail-closed YAML-root changes; reply to Codex ninth P2 and resolve its review thread only after verification. Request new formal exact-head Codex Review, fix any outstanding P1/P2 before seeking explicit merge authorization. Keep static diagnosis `PARTIAL_ONLY_NOT_ACCEPTANCE`, no Linux/ES changes.

## 2026-10-23 OFF-1B PR #298 verification

- Check Hosted CI on the current exact PR HEAD for index type and YAML read-error fixes; review and resolve two newly raised Codex P2 comments after tests pass.
- Request formal Codex review on the latest commit, and continue findings remediation without merging. On-host production acceptance remains separately unverified.

## 2026-10-23 PR #298 latest review gate

- Verify exact HEAD after literal-fixture-collision and numeric-topic-key fixes with Hosted OFF-1B/ OFF-0 tests; reply to new P2 comments, review previous unresolved threads, and retry resolution when possible. Submit exact-head formal Codex review after CI. No merge without explicit authorization and no FULL_LIVE claim.

## 2026-10-23 PR #298 next review gates

- Check exact-head Hosted CI for default fixture protection and recursive YAML failure classification; answer and resolve two new P2 threads and submit formal Codex review of latest HEAD only after CI passes. Correct any further P1/P2 findings before authorized merge. The operator probe remains PARTIAL_ONLY_NOT_ACCEPTANCE with no change to air-gapped Linux deployment.

## 2026-10-23 PR #298 latest review gate — fixture naming

- Confirm latest exact-head Hosted CI for shared Runtime E2E fixture naming rule and operator fail-closed validation. Reply to the new P2 Finding, resolve its thread, and request formal exact-head Codex Review after CI passes. Fix further P1/P2 findings; no Merge or FULL_LIVE claims without explicit authorization and evidence.

## 2026-10-23 OFF-1C query diagnostic next gates

- Run exact-head Hosted CI and formal Codex review for the optional strict-TLS zero-hit search check before any merge. The current Docker Elasticsearch IP SAN mismatch prevents a trustworthy live query preflight until operator-managed certificate correction.
- SQL Server, LLM/Agent inference, workers, Word outputs, real RAG quality and full air-gap acceptance remain separate incomplete implementation and live-verification slices. The new query check does not prove them.

## 2026-10-23 PR #299 follow-up review gates

- Verify latest exact HEAD after two new Codex P2 fixes with OFF-1B focused pytest, OFF-0 19-check contract and no-network config-only checks. Reply to both Findings, resolve threads after evidence, re-request formal Codex review on latest HEAD and fix any subsequent findings. Do not merge without an explicit user request or imply production SSL/ES verification.

## 2026-10-24 OFF-1D next gates

- Verify latest exact-head CI for `feat/sraf-off1d-readiness-matrix` (OFF-1B focused tests, OFF-1D tests, OFF-0 19 schema checks and offline CLI). Fix any failures, request formal Codex review and resolve P1/P2 before seeking explicit merge permission.
- Only after independently authorized Linux deployment, run local OFF-1D matrix and interpret TCP/health/ODBC as partial. Implement later SQL Server authorized read-only proof, LLM model inventory/inference, worker/lease identities, Word DOCX artifact and physical air-gap isolation as separate evidence-producing slices. Never infer these from config/TCP or Hosted CI.

## 2026-10-24 PR #300 formal-review remediation gates

- Confirm exact HEAD Hosted CI for 3 new P2 fixes; reply to comments `4361687822`, `4361687833`, `4361687845`, resolve review threads after CI passes and submit fresh exact-head Codex Review. Do not merge without explicit instruction.
- Keep default no-network, bounded network optional, partial-only observation and honest NOT_TESTED labels for SQL read, ES Mapping, LLM, workers, Word and network isolation.

## 2026-10-24 PR #300 TCP scope review gate

- Confirm exact-head Hosted CI after the Codex fourth P2 fix validating reported TCP scope and endpoint invariants. Reply to Finding #4361787008, resolve its review thread only after tests, and issue a fresh formal @codex review for latest HEAD. Retain partial-only and no-network default. Do not merge until user explicitly authorizes.

## 2026-10-24 OFF-1E next gates

- Verify exact-head Hosted CI for new OFF-1E model inventory regressions and 19-check OFF-0 static contract. Request formal Codex code review after CI, correct any findings and resolve comment threads before seeking separate explicit merge authorization.
- A positive local Ollama model-list observation is not model inference or RAG quality. Unsupported remote/private HTTPS/Ollama proxy and OpenAI-compatible endpoints are SKIP, not positive coverage. Real private Linux LLM and full SQL/ES/Worker/Word isolation acceptance remain pending.
