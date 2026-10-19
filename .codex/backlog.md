# Backlog

## Current Summary

### Live acceptance still pending

- Formal Requirement deployment acceptance remains incomplete. After merge and independent hosted-source review, run the Requirement automatic operator E2E only from an authorized deployment with valid `SRA_E2E_*` configuration; repository tests/docs do not prove a fresh live PASS.
- Resolve the live Elasticsearch `mapping_incompatible` blocker, then rerun authorized Elasticsearch capability/mapping acceptance plus the real Requirement → Schedule/Handoff → Report Job → Agent/LLM/Elasticsearch → DOCX path.
- Execute remaining authorized SQL Server acceptance for fresh/migrated schemas, rollback/failure injection, fencing/failover, concurrency/races, HA, and security rotation.
- Execute the complete Phase 0 Service-Key → real Elasticsearch/Agent/LLM → signed valid DOCX chain and post-pass credential rotation when an authorized environment is available.
- Execute pending unified-launcher deployment Gates SD-1 through SD-7, including durable output-root migration evidence. Do not replay or invent live evidence.

### Future architecture and product work

- Requirement Product API + Task Center Design/Plan v1 is approved (PR #277). P1.0 schema v4, P1.0A authority-supplied IDs, and P1.1 Product presenters/identities are merged through PR #280. P1.2 side-effect-free Product preview is merged in PR #281. P1.3 one-time create orchestration is the current slice; recurring create, routers, activation/run flows, UI, Product E2E, and browser E2E remain pending.
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

## Recent Changes

- 2026-10-06: Product implementation started after PR #277 merge. Current slice is P1.0 Schedule schema v4 only; all higher Product gates remain pending.
- 2026-10-05: PR #277 split schedule proposal from privileged activation and explicitly deferred durable Run retry ancestry from Product v1.
- 2026-10-02: PR #277 added Product revision CAS, transactional low-level ownership fencing, input replacement snapshot CAS, same-ID import recovery before preparation, provisioning lifecycle gating, and atomic create finalization.
- 2026-10-01: PR #277 established docs-only Product API + Task Center design, Schedule schema v4 Product metadata/idempotency, preallocated cross-authority IDs, and two-stage superuser/service-key Product E2E.
- 2026-09-23: Requirement E2E semantics/provenance corrections remained subject to authorized deployment re-acceptance; archived history contains the superseded hosted-access operational details.
- 2026-09-18: bounded runtime-input provenance and Harness v2 were implemented; live deployment re-acceptance remains separate work.

## Archived History

- `.codex/archive/backlog.md-20261006-153400.md` — complete active backlog immediately before this compaction, including all 21 dated PR #277 work-record entries and earlier pending acceptance items.
- `.codex/archive/backlog.md-20260918-000000.md` — earlier full pre-compaction backlog with historical gates and superseded status detail.
- Earlier archives referenced by those files remain under `.codex/archive/`.

## Compaction Record

- 2026-10-06: Compacted active `.codex/backlog.md` after it exceeded the AGENTS.md >20 work-record trigger. Full text was archived before rewrite; unresolved live-acceptance work, Product NOT STARTED status, future architecture items, security/UI/ingestion debt, and the Elasticsearch `mapping_incompatible` blocker remain active.

## 2026-10-08 Requirement Product implementation status

- P1.0 schema v4, P1.0A authority identities, P1.1 Product presenters/identities, P1.2 preview, P1.3 one-time create, and P1.4 recurring create/finalization are merged through PR #283 at `main@2c22df0bf7fa9a973f374849ebd0de82f2ca6946`.
- P1.5 Task updates / immutable Schedule draft proposals are merged through PR #284 at `main@ad5dde9133e9e93eb4e8ffdd162d55debbaff3f1`.
- P1.5A Product draft activation is implemented on `feat/requirement-product-draft-activation-p1-5a` and requires exact-head Hosted review/check evidence before merge.
- Keep P1.5A limited to superuser activation reservation/provenance/CAS, shared locked Schedule approval, stale exact-draft retirement, low-level approve interim 409 precheck, and focused tests.
- P1.6 atomic low-level ownership fences, P1.7 input replacement, Product HTTP router/UI, and later Product API gates remain pending.


- 2026-10-07 P1.3 exact-head review P1 profile-binding race was fixed on the same branch; exact-head Codex re-review/check evidence is required before merge.


- 2026-10-07 P1.3 second exact-head review findings (P1 recovery ordering, P2 zero-row run) were fixed on the same branch; exact-head re-review/check evidence remains required before merge.


- 2026-10-07 P1.3 third exact-head review findings (P1 preview normalization regression, P2 expired-only zero-select run) were fixed; exact-head re-review/check evidence remains required before merge.


- 2026-10-07 P1.3 fourth exact-head review findings (P1 exact preview normalization block, P1 durable eligibility time) were fixed; exact-head re-review/check evidence remains required before merge.


- 2026-10-07 P1.3 fifth exact-head review finding (P1 finalizer selection-time drift) was fixed; exact-head re-review/check evidence remains required before merge.


- 2026-10-07 P1.4 recurring create current slice: exact-head Hosted Codex review/check evidence is required before merge. After P1.4, continue with the next planned Product gate rather than folding P1.5/P1.6 into this PR.


- 2026-10-07 P1.4 exact-head review P1 audit-payload rollback was fixed on the same branch; exact-head Codex re-review/check evidence is required before merge.


- 2026-10-07 P1.4 second exact-head review findings (P2 stale recurrence-release clock, P2 first-occurrence zero-selection) were fixed; exact-head Codex re-review/check evidence remains required before merge.


- 2026-10-07 P1.4 third exact-head review finding (P2 delayed claim selection-time drift) was fixed by binding scheduled materialization to `scheduled_for`; exact-head re-review/check evidence remains required before merge.


- 2026-10-08 P1.4 fourth exact-head review finding (P2 coalesced occurrence can still select zero) was fixed by terminalizing all zero-selection runs during materialization; exact-head Codex re-review/check evidence remains required before merge.


- 2026-10-08 P1.5 current slice: exact-head Hosted Codex review/check evidence is required before merge. Do not fold P1.5A activation or P1.6 low-level ownership fencing into this PR.


- 2026-10-08 P1.5A current slice: exact-head Hosted Codex review/check evidence is required before merge. P1.6 must replace the low-level approve read/precheck with same-transaction Product ownership fencing and extend that fence to all planned Schedule/source mutations.


- 2026-10-08 P1.5A first exact-head Codex finding (P2 missing Product activation audit) was fixed by atomically enqueuing `requirement.task.updated` and adding focused store/outbox regressions; exact-head re-review/check evidence remains required before merge.

- 2026-10-11 P1.5A merged in PR #285 at `main@69a873fd94be8dd34a808d59375b7e9f2f7522d1`.
- 2026-10-11 P1.6 atomic low-level Product ownership fences are implemented on `feat/requirement-product-ownership-fences-p1-6`: five Schedule mutations and two Requirement-source mutations now use same-transaction ownership checks covering both provisioning reservations and steady Product Tasks. Exact-head Hosted Codex review/check evidence is required before merge.
- After P1.6, continue with P1.7 input replacement snapshot CAS; do not fold P1.7 or Product HTTP/UI work into this PR.

## 2026-10-12 Requirement Product implementation

- P1.6 low-level Product ownership fences merged as PR #286 (`30071cb3b7b732b2875a35c6929b430693029905`).
- P1.7 input-replacement base-snapshot CAS is implemented on `feat/requirement-product-input-replacement-p1-7`, pending exact-head Hosted Codex review, regression verification and explicit merge authorization.
- P2 Product Task HTTP router / Task Center, P2.3 run-trigger admission, and deployment SQL concurrency/real E2E acceptance remain later gates. Do not mix them into P1.7.

- 2026-10-12 P2.1 Product API read + preview in progress on `feat/requirement-product-api-read-preview-p2-1`. Adds finalized Task and Run projection endpoints and multipart/manual JSON preview, wired only when both existing authorities are enabled. Requires exact-head Hosted Codex review and acceptance before merge. P2 mutations/idempotency run admission, artifact, service-key scopes, GUI, and authorized live SQL/real E2E remain pending.
- Cross-Task identical/semantically-similar Requirement execution deduplication is NOT supported by v1 design or P2.1. Requires separate reviewed semantics of input identity, model/config/time window, ownership/ACL, execution freshness, sharing consent and audit lineage; do not silently reuse or cross-leak another Task's output.

- 2026-10-12 PR #288 Codex review could not execute because the code-review usage limit was reached. Review gate is blocked; do not merge solely on Vercel. After review capacity returns, request one current-head review and handle findings, then continue P2.2/P2.3 separate from Task Center UI.

- 2026-10-12 P2.1 PR #288 exact-head Codex review finally ran (1 P1, 5 P2). A bounded hardening slice is now implemented on the existing branch: request body cap before multipart spooling, preview size/row/result bounds, run item pagination, consistent joined Task/Schedule reads and corrected invariant HTTP errors. Pending: verify all six findings at new exact head, exact-head Hosted checks, and authorized local/live SQL + E2E acceptance. P2.2/P2.3 and cross-Task sharing remain deferred.

- 2026-10-12 P2.1 round-2 review (head `4141570`) found three P2 regressions; corrected form parser error expectation, joined Product read locks and unexpected KeyError mapping in the existing PR. Next gates: exact-head Codex review and checks; runtime pytest and authorized SQL Server read/write concurrency remain unverified. Keep P2.2 and cross-Task dedup outside current PR.

- 2026-10-12 P2.1 third Codex review found three P2 concerns (XLSX total-cell resource bound, Run-list N+1 SQL, broken deferred artifacts link). Code and regressions updated on PR #288; next gates: exact-head Codex and hosted checks, runtime pytest, SQL Server large-history and two-connection concurrency acceptance. P2.2/3 and cross-operator result sharing remain outside this PR.

- 2026-10-12 PR #288 round-four review: corrected two P2 findings (invalid XLSX parser errors and early-body-limit CORS headers), with regressions. Pending exact-head review, hosted checks and real runtime/SQL acceptance before proposing merge. Do not start P2.2 or cross-operator dedup as part of this review loop.

- 2026-10-12 fifth Codex review on PR #288 exact head `6dbcf20` found a P2 malformed-XLSX parser TypeError → 500 gap. Narrow reader-boundary normalization plus XML-attribute regression added. Re-review the new exact head and validate actual pytest/SQL Server before merge; P2.2 and cross-operator dedup stay deferred.

- 2026-10-12 P2.1 PR #288 sixth review found unbounded sparse-CSV decoded cells despite the row cap. Implemented HTTP-only CSV/JSON total-cell, width and decoded-value bounds with regression tests. Require new exact-head review, hosted checks and executable pytest/SQL Server acceptance. No P2.2 or cross-operator execution sharing in this review PR.

- 2026-10-12 P2.1 seventh review found JSON pre-decode amplification: whole-array `json.loads` before row checks. New HTTP-only JSON streaming element scanner with pre-element and post-decode bounds, plus regression coverage, is on original PR #288 branch. Require new exact-head review and runtime pytest/real SQL Server acceptance before merge; no P2.2 or cross-owner dedup in this PR.

- 2026-10-12 P2.1 eighth review: fix two P2 JSON scanner bugs (Unicode code points vs UTF-8 bytes; invalid closing-brace array separator). Changes and regressions on PR #288, new exact-head Codex review/CI and actual pytest/SQL Server acceptance still needed before suggesting merge.

- 2026-10-12 ninth P2.1 Codex round: isolate and classify invalid JSON Unicode surrogate escapes as source-format 422 at preview byte-accounting boundary; add nested/key/value regression and valid Unicode positive case. Re-review exact PR #288 head; actual pytest and real SQL Server acceptance still pending, no merge authorized.

- 2026-10-12 P2.1 PR #288 tenth review: normalize optional lxml XMLSyntaxError on malformed uploaded XLSX XML to 422, retaining stdlib parser support, with regression. Latest exact-head Codex/hosted CI and real runtime/SQL Server acceptance required before proposing merge; P2.2 and cross-owner dedup deferred.

- 2026-10-12 P2.1 PR #288 eleventh review: address P1 AGENTS.md import rule (remove guarded lxml import) and P2 preparse nested JSON memory budget with structural-token ceilings; commit tests/docs to same branch. New exact-head Codex review, hosted tests and real SQL Server acceptance remain required. Do not merge or expand into P2.2/cross-owner dedup.

- 2026-10-12 P2.1 PR #288 twelfth review P1/P2: restore valid multirow JSON parsing and make direct `requirements_json` form path enforce predecode row/structure caps, same as .json upload. Tests added. Request new exact-head Codex review, inspect hosted checks, and run executable pytest / true SQL Server two-connection acceptance before merge; P2.2/cross-operator features remain deferred.

- 2026-10-12 P2.1 PR #288 thirteenth review: fixed three P2 input guards (predecode task metadata 4 KiB, raw ZIP central directory 2,000-entry bound before ZipFile, blank XLSX header 422) and added tests. Preserve P1 internal import behavior, seek exact-head Codex approval and verified pytest/SQL Server tests before any merge. Deferred P2.2 and cross-owner duplicate scheduling unchanged.

- 2026-10-13 P2.1 PR #288 fourteenth review P2: increase `task` predecode bound from 4 KiB to 8 KiB to admit valid escaped non-BMP maximum fields, with adversarial nested-task and positive regression tests. Request new exact-head review and verify hosted pytest and real SQL Server acceptance; do not merge or expand scope.

- 2026-10-13 P2.1 PR #288 fifteenth Codex P2: pre-scan CSV logical records (including quoted commas and newlines) to reject >128 columns before csv.reader materializes millions of strings. Added tests for very wide header/data, normal quoted multiline input and internal Phase 1B parity. Request exact-head Codex review and authoritative pytest/SQL Server acceptance; no merge authorization.

- 2026-10-13 PR #288 sixteenth Codex review: fix no-active-worksheet XLSX P2, with real XLSX fixture and 422 input-code regression. Re-request Codex on exact new head. Full pytest/hosted CI and two-connection real SQL Server tests remain outstanding; do not merge without user's explicit authorization.

- 2026-10-13 PR #288 seventeenth review: map explicitly missing Import Profile version selection to 422 (not 500), with adversarial unknown KeyError still mapping to 500. Tests/docs committed on same PR. Request exact-head Codex review; full repository pytest, hosted authoritative CI and two-connection real SQL Server acceptance pending before merge. Do not merge without explicit user authorization.

## 2026-10-15 OFF-0 air-gap delivery line (Issue #290)

- Separate scoped OFF-0 PR: inventory reusable release/E2E/API/ES/LLM code, 19 check contracts and dependency graph, Quick/Diagnose/Acceptance read/write matrix, redaction/error report fields, and focused JSON contract validator/test. Review the branch and execute `python -m pytest -q tests/test_sraf_airgap_off0_contract.py` on a repository checkout before Merge; no user authorization to Merge this slice has been given.
- OFF-1: build actual safe, bounded SQL/ES/LLM/ODBC/disk/model read-only probes and error tests. OFF-2: independently reproducible full release bundle/wheelhouse/model/ODBC/index and safe incremental upgrades. OFF-3/4: unified offline runner and readable reports/manual. OFF-5: site isolation + FULL_LIVE and failure/recovery drills. P2.2 must not inherit any OFF-side work or be blocked by its future steps.

- 2026-10-15 OFF-0 PR #291 first Codex review completed with three P2 items; implemented isolated fix set and extended unit regressions. Added a path-filtered GitHub Actions workflow to run stdlib validator and focused pytest against PR changes in the development environment. Request fresh exact-head Codex review, verify CI; **do not merge without explicit user approval**. OFF-1 probe implementation stays separate from P2.2 and remains pending once OFF-0 safety contract is reviewed.

- 2026-10-15 OFF-0 PR #291 second Codex review (`42689fb4`) found P1 GitHub Actions missing project dependency setup, P2 report string redaction bypass, P2 oversize-number JSON parser traceback. Remediation and adversarial CLI/registry regressions added; require latest exact-head GitHub Actions tests and a new Codex review before any proposal to merge. Keep OFF-1 runtime probes and Product P2.2 separate. Vercel quota block does not imply Python test failure, but cannot be recorded as a successful Vercel gate.

- 2026-10-15 OFF-0 PR #291 third Codex round found 3 P2 redaction/deep JSON/device-boundary issues. In-branch remediation adds static allowlisted report copy, stricter Unicode/path/credential checks, bounded fd reads, RecursionError normalization, and adversarial regressions. Next: verify exact-head Github Actions and request Codex review, fix anything flagged, obtain explicit merge authorization only after review; OFF-1 probes and P2.2 remain separate.

- 2026-10-16 OFF-0 PR #291 fourth-round Codex review completed at head `93c355b5`, three P2 issues (cross-Python nesting behavior; contradictory FAIL/SKIP codes; incomplete check list passing validation). Fixes and new regression tests on the existing branch; require exact-head GH Actions PASS and fresh Codex review before any merge. Separate OFF-1 real dependency probes and Product P2.2 remain pending and independent.

- 2026-10-16 OFF-0 PR #291 fifth Codex review completed at `a679533b`: one P2 (planned checks could produce unexecuted FAIL/WARN). Added restrictive safe-record status rule and adversarial regressions, pending exact-head CI/Codex re-review. No merge authorized. OFF-1 and Product P2.2 remain independent future work.

- 2026-10-16 OFF-0 PR #291 sixth Codex round completed at `fe5cc68e`: one P2, readiness could be self-promoted in JSON. Fix enforces complete 19-ID in-code approved readiness and adds malformed/promotion regression tests. Await current-head GH Actions and Codex re-review; no Merge authorization. OFF-1 and Product P2.2 remain independent.

- 2026-10-16 OFF-0 PR #291 seventh Codex review on `23166cc3`: 2 P2 findings for execution gate/dependency JSON privilege escalation and fault-code rebinding. Added reviewed per-check execution/error/component authority and tests; exact-head GH Actions plus next Codex review pending. Do NOT merge without authorization. OFF-1 real probes and Product P2.2 remain separate.

- 2026-10-16 OFF-0 PR #291 eighth round Codex found one P2: runtime `PASS` records were allowed with empty/untrusted evidence. In this contract-only stage, reject all per-check PASS pending OFF-1 reviewed probes; regressions cover no evidence, empty evidence and plausible-but-forged evidence. Next: exact-head CI then Codex review; never merge without explicit authorization. This does not block independent P2.2 Product API progress.

- 2026-10-16 PR #291 ninth Codex review at `781e214e`: one P2 for proofless FAIL/WARN. Safe record constructor now blocks every unprobed runtime PASS/FAIL/WARN; tests exercise real-check IDs and fake evidence. Await exact-head GitHub Actions and Codex re-review. OFF-1 and P2.2 remain independent. No merge authorized.

- 2026-10-16 OFF-0 PR #291 tenth Codex review (`ccf6dd5f`) identified one P2 allowing fabricated evidence in SKIP despite no probes. Added fail-closed empty-evidence gate and regression coverage; pending exact-head GitHub Actions and Codex re-review. Do not merge without explicit user instruction. OFF-1 remains independent from P2.2.

- 2026-10-16 PR #291 eleventh Codex round at `2dec55a7` found one P2 allowing false SKIP reasons. Fix restricts all OFF-0 SKIPs to check_not_implemented, with no evidence, and adds negative cases for blocked_by_dependency/auth_session_unavailable/mode_not_enabled. Require current-head Actions success and fresh Codex review. Do not merge without user authorization; OFF-1 and P2.2 stay separate.

- 2026-10-16 OFF-0 PR #291 twelfth Codex round at `0aadda10` yielded 2 P2: fabricated duration and incorrect operational remediation for no-probe SKIP. Branch amended with zero-duration guard, null remediation and adversarial tests. Await hosted CI and exact-head next review; do not Merge without permission.

- 2026-10-16 OFF-0 PR #291 thirteenth Codex review at `a47e0f4d` identified policy/output contradiction about nullable SKIP remediation. Updated registry and validator to explicit status-conditional remediation sourcing with negative/CLI tests; exact-head hosted CI and Codex next review pending. No merge without permission. OFF-1 live probes and P2.2 remain separate.

## 2026-10-17 OFF-1 work started separately from Product P2.2

- OFF-1A branch feat/sraf-airgap-off1-readonly-probes adds first bounded localhost/host-only probe slices with tests, docs, and Actions. Hosted CI, Codex Review, and explicit user merge instruction still required.
- OFF-1B: approved read-only SQL connector with non-logging DSN handling and SQL permission/catalog, ES authenticated GET mapping/alias diagnostics (live mapping_incompatible blocker), vetted remote/internal TLS allowlist and LLM model/resource metadata, native ODBC SQL driver confirmation, wheelhouse/GPU/time/CA/disk target root, dependency-based fault attribution. No fake FULL_LIVE PASS.
- OFF-2 bundle, OFF-3 unified Runner, OFF-4 safety reports/runbook, OFF-5 real isolated air-gap dress rehearsal remain unimplemented, independent from Requirement Product API P2.2.

- 2026-10-17 PR #292 first Codex review produced P1 unbounded wall-clock duration under slow-drip HTTP response despite 3s inactivity timeouts. Added absolute deadline socket and adversarial live loopback regressions. Track exact new head Hosted CI, address any failures, re-request Codex review, do NOT merge without explicit user authorization.

- 2026-10-17 OFF-1A P1 first fix CI run 38992439458 FAILED (331 PASS/2 FAIL): actual slow-drip still exceeded 3s due to HTTPConnection's instance _create_connection shadowing. Fixed binding and regression in new branch head; await new hosted CI and Codex re-review. No merge permission.

- 2026-10-17 OFF-1A: second Codex review P1 about unbounded ODBC helper execution addressed by static finite Unix library candidate checks plus tests/docs. Hosted exact-head Actions and fresh Codex review still required before merge authorization. Expand real ODBC/SQL testing only with reviewed OFF-1B trust boundary.

- 2026-10-17 OFF-1A third Codex review of a10408e8 surfaced two P2 (Content-Length early EOF, empty ES identity). Added safeguards, negative real loopback tests, and docs; current-head GitHub Actions/Codex review and explicit merge authorization remain outstanding.

- 2026-10-17 OFF-1A fourth Codex P2: reject malformed Content-Length obscured by http.client. Added strict framing check and ES/LLM loopback regressions; hosted exact-head CI and further Codex review still pending. PR #292 must stay open until user explicitly authorizes merge.

- 2026-10-17 OFF-1A PR #292 fifth Codex P2 on discarded malformed HTTP headers fixed by rejecting response.headers.defects. Added real raw malformed framing GET tests across API/ES/Ollama/OpenAI. Exact latest-head GitHub Actions and Codex re-review pending. Do not merge before user approval.

- 2026-10-17 PR #292 sixth Codex review found P2 legitimate chunked transfer decoding rejected. Added safe chunked-only allowance and 26 parameterized regression cases for valid/invalid/truncated responses; exact-head CI and new review must finish before any merge. OFF-1B/full-airgap acceptance still future work.

- 2026-10-17 PR #292 seventh Codex review found 2 P2: malformed chunk CRLF or incomplete final trailers falsely accepted; HTTP/1.0 Transfer-Encoding chunked falsely accepted. Fix and adversarial raw HTTP regressions submitted; latest Hosted CI and exact-head Codex review outstanding. No merge authorization.

- 2026-10-17 PR #292 eighth Codex review found one P2 normalized response.version accepted HTTP/1.2/1.X in chunked reply. Raw status token now checked for exact HTTP/1.1, with 18 new parametrized and direct HTTP socket regressions. Run Hosted current-head CI and fresh Codex review; await explicit merge authorization.

- 2026-10-18 PR #292 ninth exact-head Codex review flagged one P2 bare-LF HTTP status/header false-PASS. Added strict CRLF raw-header guard and 21 new tested scenarios, docs updated. Must verify exact-head Hosted GitHub Actions and submit tenth Codex review; no merge without explicit user request.

- 2026-10-18 PR #292 tenth Codex review produced two P2: invalid raw headers including interim 100 bypass parser defects, and unsupported status tokens on nonchunked Content-Length responses. Fixed both with header raw-syntax and all-mode literal-version validation; expanded live TCP tests. Exact-head Actions and eleventh Codex review outstanding; no merge until explicit authorization.

- 2026-10-18 OFF-1A PR #292 Hosted run 39094410231 FAILED (526 pass, 1 obsolete expectation test fail). Updated test to expect immediate HTTP/1.2 rejection consistent with strict all-mode guard; new exact-head Hosted CI and fresh Codex review pending. No merge approval.

- 2026-10-18 OFF-1A followup review at old 53cd2655 reported P1 obsolete HTTP/1.2 regression test (already corrected on later head) and P2 NUL in raw reason phrase (patched using strict raw status regex plus live negative tests). Current head requires Hosted CI and Codex re-review; PR remains OPEN and unmerged.

- 2026-10-18 CI 39094831761 returned 552 PASS / 1 FAIL because direct invalid HTTP/1.2 test asserted stale exception reason. Updated test to assert http_status_line_invalid from earliest raw status-line syntax guard; new exact-head CI and re-review required, PR remains OPEN.

- 2026-10-18 d82fc99d Codex review P2 missing post-status separator fixed; tests for HTTP/1.1 200 (no SP) negative across 4 probes, interim 100 negative and 'HTTP/1.1 200 ' positive. Latest Hosted CI and Codex review outstanding.

- 2026-10-18 PR #292 current 0171184d Codex P2 on forbidden 100 Continue framing headers addressed with raw state tracking and 25 new parameterized TCP cases. Exact head Hosted Actions and fresh Codex review required before merge; offline FULL_LIVE acceptance still not implemented.

- 2026-10-18 PR #292 latest Codex review on 9129fff0 found P2 forbidden framing field names in chunk trailers. Fix and 44 live socket tests committed across four endpoint types; next exact-head Hosted CI and Codex review needed; do not merge without approval.

- 2026-10-18 PR #292 current Codex Review found 2 P2 on header-only chunk trailer fields and legal obs-text custom metadata. Code/docs/test fix committed; verify latest Hosted GitHub Actions and request fresh exact-head Codex review. No merge without user authorization.

- 2026-10-19 PR #292 OFF-1A trailer compatibility/control-field remediation submitted for exact-head review. Gate on new HEAD's Hosted Actions, OFF-0 schema-only, all focused tests, and no remaining new P1/P2; await explicit user merge command. OFF-1B live SQL/ES/LLM/Workers/DOCX remains independent.
