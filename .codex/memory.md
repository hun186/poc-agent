# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval is in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Requirement import authority is SQL Server with immutable Requirement Version/Snapshot history. Requirement recurrence/execution authority is the separately versioned `sra_schedule` schema. Report Jobs own real Agent/LLM/Elasticsearch execution and DOCX production.
- Requirement scheduling uses external Schedule/Handoff workers; Report Job execution remains downstream. Product orchestration must compose those authorities rather than create a second scheduler, queue, worker, auth store, or execution path.
- Formal live Requirement deployment acceptance remains blocked by the unresolved Elasticsearch `mapping_incompatible` condition. Repository review/checks do not clear that live blocker.
- Requirement Product Design/Plan v1 is the active implementation roadmap. P1.0 schema v4, P1.0A authority identities, P1.1 presenters/identities, P1.2 preview, P1.3 one-time create, and P1.4 recurring create are merged through PR #283 at `main@2c22df0bf7fa9a973f374849ebd0de82f2ca6946`.
- P1.5 Task updates / Schedule draft proposals are implemented on `feat/requirement-product-task-updates-p1-5` and require exact-head Hosted review/check evidence before merge. P1.5A draft activation, P1.6 low-level ownership fences, P1.7 input replacement, Product HTTP routes, and UI remain pending.

## Requirement Product — Current Contract

- Product v1 integrates into the existing SRA management shell/Auth/RBAC. There is no second login or separate execution subsystem.
- Product Task lifecycle is `provisioning|active|disabled`. One-time Tasks remain active after provisioning; recurring Task state mirrors Schedule enablement: active/true and disabled/false.
- Product create is superuser-only. Preview remains side-effect free. Product presenters suppress Report Job native states/IDs, credentials, absolute paths, E2E markers, and trigger-request internals.
- Durable Product mutations use `requirement_product_requests` with principal + operation + idempotency key + canonical request hash. Cross-resource identities are included in hashes so one key cannot replay another Task/version.
- P1.3 one-time create preallocates cross-authority IDs, commits Requirement import/Snapshot and Schedule authorities, then atomically materializes the initial manual Run while making the Product Task visible. One-time selection semantics are anchored to the durable request `created_at`; audit/materialization timestamps use actual finalization time.
- P1.4 recurring create approves the initial Schedule Version while keeping recurrence disabled during provisioning. Its finalizer atomically enables the Schedule, computes the first due through existing Phase 1C recurrence logic, marks the Task active, and marks the request succeeded. It does not create an initial manual Run.
- Scheduled occurrence selection is evaluated at canonical `scheduled_for`, not later worker claim time. Runs with `selected_count == 0` terminalize to `completed` in the materialization transaction so empty Runs cannot remain stranded.
- P1.5 classifies Task PATCH semantics before durable reservation:
  - in-place mode: `name` and/or recurring `enabled`;
  - schedule-proposal mode: `timezone`, `recurrence`, `run_policy`, and/or `model`;
  - mixed modes are rejected before any request reservation.
- P1.5 reservation locks the Product Task, rejects provisioning, persists `base_task_revision`, and preallocates `schedule_version_id` only for schedule proposals.
- P1.5 in-place finalization locks request/Task/Schedule, enforces revision CAS, allows name changes for normal Product operators, requires superuser for recurring enable/disable, atomically mirrors recurring Task/Schedule state, increments Task revision exactly once, stores `result_task_revision`, audit metadata, bounded result, and request success.
- A same-state `enabled=true|false` in-place PATCH does not recompute or shift `next_run_at`; only a real disabled→enabled transition calculates a fresh due. One-time Tasks do not support enabled-state transitions in v1.
- P1.5 schedule-proposal updates create exactly one immutable request-owned draft and never approve/activate it, change active Schedule Version, change `next_run_at`, change enabled state, or increment Product Task revision. Successful proposal requests keep `result_task_revision=NULL`.
- Schedule-proposal retry first recovers the exact preallocated draft identity if it already exists; it does not rebuild the draft from a newer active config after a crash. Draft activation remains a separate P1.5A superuser-only operation using the proposal's persisted `base_task_revision` CAS anchor.
- P1.6 transactional low-level Product ownership fences and P1.7 input-replacement snapshot CAS remain planned, not yet implemented.

## Recent Changes

- 2026-10-08: Implemented P1.5 internal Task update orchestration and Schedule-store persistence: durable `task_update` reservation, in-place CAS finalizer, immutable draft proposal completion, exact-draft recovery, active-config reader, and focused replay/RBAC/stale-CAS tests.
- 2026-10-08: P1.5 prevalidation rejects mixed update modes, invalid timezone, and unauthorized recurring toggle before durable reservation. Same-key hashes bind Task + mode + normalized patch.
- 2026-10-08: PR #283 merged P1.4 recurring Product create/finalization at `main@2c22df0bf7fa9a973f374849ebd0de82f2ca6946`.
- 2026-10-08: Schedule materialization now terminalizes zero-selection Runs inside the same transaction via existing terminal recomputation.
- 2026-10-07: Scheduled Run selection semantics were bound to `scheduled_for`; worker claim time remains operational/audit time.
- 2026-10-07: P1.4 separated durable reservation time from recurring release time and added first-occurrence selectability protection.
- 2026-10-07: PR #282 merged P1.3 one-time Product create saga; exact-ID recovery, durable eligibility time, and selection-vs-audit time separation were established.
- 2026-10-07: PR #281 merged side-effect-free Product preview; P1.1 presenters and P1.0/P1.0A authority/schema work were merged immediately before it.
- 2026-10-06: Product Design/Plan v1 and Schedule schema v4 implementation established revision CAS, durable request identities, provisioning visibility, and cross-authority preallocation as the Product control-plane foundation.

## Verification and Acceptance

- Direct Git transport from the execution environment remains unavailable because `github.com` DNS resolution fails. No local pytest PASS is claimed for current Product branches.
- Available repository evidence is Hosted source inspection, focused test additions, exact-head Codex review, and Hosted checks such as Vercel.
- Formal production acceptance still requires authorized SQL Server / Elasticsearch / worker / Report Job / Agent / LLM / DOCX execution after the live `mapping_incompatible` blocker is fixed.

## Archived History

- `.codex/archive/memory.md-20261008-113100.md` — full active memory immediately before the 2026-10-08 P1.5 compaction.
- `.codex/archive/memory.md-20261006-143100.md` — prior Product/design implementation history before the earlier compaction.
- `.codex/archive/memory.md-20260915-170533.md` — earlier project history.

## Compaction Record

- 2026-10-08: Compacted `.codex/memory.md` after the active file exceeded the AGENTS.md >20 date/work-block trigger. The pre-compaction text was archived intact; unresolved live acceptance, Product implementation status, current architecture/contracts, pending gates, and verification limitations remain active above.


- 2026-10-08 P1.5 merged in PR #284 at `main@ad5dde9133e9e93eb4e8ffdd162d55debbaff3f1`.
- 2026-10-08 P1.5A Product draft activation is implemented on `feat/requirement-product-draft-activation-p1-5a`: superuser-only durable `task_version_activate` reservation, exact proposal-origin proof, originating `base_task_revision` CAS, atomic Schedule approval + Product Task revision increment + bounded request success, stale-draft retirement, and low-level Schedule approval 409 precheck for Product-owned Schedules.
- P1.5A reuses the shared locked Schedule approval helper so Product activation and low-level Schedule approval retain one recurrence/active-version transition rule. Product HTTP Task routes remain deferred to P2.
- The low-level Product-owned approval rejection added in P1.5A is intentionally an interim read/precheck. P1.6 remains required to move Product ownership checks and low-level mutation into one SQL transaction and close TOCTOU races.


- 2026-10-08 P1.5A review correction: successful Product draft activation now enqueues Product-level `requirement.task.updated` audit evidence in the same SQL transaction as exact draft approval, Product Task revision increment, bounded result, and activation-request success. The event carries only bounded `task_id`, `revision`, and `operation=task_version_activate` payload plus Schedule/version identity.
- 2026-10-08 P1.5A review correction: activation reservation now acquires Product Task, target Schedule Version, then the immutable successful proposal-origin request, matching the finalizer's relative lock order and preventing concurrent different-key activation deadlocks; focused regression asserts the ordering.
- 2026-10-11 P1.5A review correction: `complete_product_task_update_proposal()` now locks the Product Task before its originating request, so a still-finishing proposal cannot deadlock with activation reservation's Task-first ordering. Regression asserts Task → proposal request → draft Version ordering.
- 2026-10-11 P1.5A review correction: low-level `approve_version()` now resolves immutable version identity without an update lock, then delegates mutation locking to `_approve_version_locked()` so approval preserves Schedule → Version ordering shared with `set_enabled()`; focused regression asserts the identity lookup is unlocked and the helper lock order.

- 2026-10-11: PR #285 merged P1.5A Product draft activation to authoritative `main@69a873fd94be8dd34a808d59375b7e9f2f7522d1`.
- 2026-10-11 P1.6 current slice: public low-level Schedule mutations (rename, enable/disable, version create/approve, manual Run) and Requirement-source mutations (PATCH/import) now use same-transaction Product ownership fences. Ownership is proven by either the steady-state Product Task or any durable `task_create` reservation for the preallocated identity, including the provisioning gap. Product internal create/update/finalizer paths continue to use their reviewed unfenced authority methods so the Product does not block its own orchestration.
- P1.6 reuses the already-merged/catalog-validated schema-v4 indexes `IX_requirement_product_request_schedule` and `IX_requirement_product_request_source`; no new schema version is introduced. Exact-head Hosted review/check evidence remains required before merge.

## 2026-10-12 Requirement Product P1.6 → P1.7 handoff

- PR #286 P1.6 transactional low-level Schedule/source ownership fences merged to `main@30071cb3b7b732b2875a35c6929b430693029905` after clean Codex exact-head review and successful Hosted Vercel.
- P1.7 work is scoped to internal Product input replacement: lifecycle-checked reservation with immutable `base_snapshot_id`, preallocated import/snapshot IDs, Phase 1B locked snapshot CAS, delayed committed replay before normalization, and bounded Product ledger finalization.
- No Product HTTP routes or P1.7 deployment/live SQL Server acceptance are claimed; local pytest remains unavailable without direct Git transport. Retain P1.6 ownership fences and do not merge the P1.7 PR until explicit authorization.

## 2026-10-12 P2.1 Product API first HTTP slice

- Authoritative P1.7 merged PR #287 at `main@1ebb44986acf5c901861728fa61ee0b897bb904c`. P2.1 begins on `feat/requirement-product-api-read-preview-p2-1`, PR #288, with read-only Product Task/Run HTTP routes and operator-only side-effect-free multipart/direct-JSON preview.
- Product service is initialized only with both Requirement Import and Schedule authorities, reuses existing `current_user` and `require_db_operator`, and projects finalized Product Task/Run identities from ScheduleStore/P1 presenters. No mutation, Run trigger, new auth store, worker, Report Job, or artifact route is introduced.
- P2.1 PR #288 first exact-head `5483b66d0334286d9bd1f8d657bc49721553998c` requested `@codex review`, but GitHub Codex bot responded review usage limit exceeded; no clean review or pytest/real SQL PASS is claimed. Do not merge without user approval and completed current-head review gate.
- Original v1 has no cross-Task identical/similar-Requirement execution sharing. User asked about this potential optimization; defer to a separate explicit security/provenance/semantic design.

## 2026-10-12 P2.1 Codex findings remediation

- Codex Review for PR #288 exact head `3cf17b81310d4c3dbb8b19d66e63cca860526c9f` completed with 1 P1 + 5 P2 findings. Corrective changes remain on the existing Product P2.1 branch.
- Added pre-multipart-body ASGI cap, HTTP-only normalization/ZIP/preview bounds, independent Run Item paging, atomic Task/Schedule read projections and safe 500 for backend invariant failures. Internal P1 Product create/replacement semantics remain separate from public preview-only caps.
- Added focused regression source tests; no actual local pytest or two-connection SQL Server PASS is asserted because direct Git transport cannot resolve github.com in the execution environment. New exact-head Codex review and Hosted checks are the next gates; no merge authorization has been given.

## 2026-10-12 P2.1 second Codex review

- PR #288 exact head `41415706013da58356002840c2348924a84c518a` Codex completed with three P2 findings and no new P1. Addressed the parser 400/test mismatch, JOIN read-consistency with SQL Server `HOLDLOCK` for both Task/Schedule, and unexpected presenter `KeyError` masking as 500. Added focused regression tests for known 404 vs unexpected KeyError and lock hints. All verification remains source-based until new exact-head Hosted review/CI and runtime pytest/live SQL acceptance.

## 2026-10-12 P2.1 third Codex review

- PR #288 third exact-head Codex review `9fa8890` completed with three P2 issues. Added XLSX preview total cell/value-byte caps, one-query Product Run history pages (no per-Run round trips) and removed the deferred Artifacts HTTP relation. Test coverage and API/architecture documentation updated. No merge authorized, exact-head review/CI and live SQL Server verification pending.

## 2026-10-12 P2.1 fourth Codex review

- Codex completed on `45318fd8ad124ae94758799c9dc2ab40bf6d27e8` with two P2 findings: malformed XLSX classified as 500 and pre-parser 413 without browser CORS headers. Fixed input decoding error normalization and middleware order, added tests and documentation on PR #288 original branch. New-head Codex review/hosted checks and true pytest/live SQL Server acceptance are separate gates; no merge instruction given.

## 2026-10-12 P2.1 fifth Codex review

- Exact-head Codex review at `6dbcf20d163b565a4f3cf8ee34c3ece11872f1d3` completed with one P2 malformed-XLSX TypeError error classification finding. Added an XLSX decoding-boundary `TypeError` normalization to stable `source_format_invalid` and regression using an invalid `sheetId` attribute in an otherwise valid XLSX archive. Do not treat any prior review or CI result as passing the new head; runtime pytest and real SQL Server tests are pending. PR #288 remains open, no merge authorized.

## 2026-10-12 P2.1 sixth Codex review

- PR #288 sixth Codex review for `1102b368ebd38d1856f8d84b42a5f36eb1df9534` finished with one P2 CSV matrix amplification issue. Fix caps width (128), total cell count (50,000) and decoded bytes (8 MiB) in preview-only CSV. Same guard added to preview-only JSON for consistent format isolation; internal no-limit P1 reads unaffected. Regressions and API contract updated. Await new exact-head review and actual pytest/SQL Server tests; do not merge without explicit user instruction.

## 2026-10-12 P2.1 seventh Codex review

- Codex review at exact head `b9d4bd3a5e2859c44af78bd31ce6d76b14002b73` found one P2 JSON preview pre-decode amplification bug. Added preview-only incremental array parsing of at most one 1 MiB row at a time, respecting escaped strings and nested values, with 5,000-row and 50,000-cell caps. The P1 internal JSON reader remains unchanged. Added regression tests for a very large compact array, malformed syntax, and normal nested objects. The branch is still open, exact-head review/CI and runtime pytest/SQL Server acceptance are not claimed.

## 2026-10-12 P2.1 eighth Codex review

- Exact-head `e4642084a73c48fc42a5021c66a91e593b182415` review found two P2 issues in incremental JSON preview: UTF-8 byte accounting (previously Unicode characters) and invalid array separators accepted. Adjusted the scanner to enforce 1 MiB original UTF-8 bytes before each row parse and reject top-level delimiters other than comma/closing square bracket. Added multilingual/invalid-JSON regressions. Keep P2.1 on original PR #288, no merge until explicitly authorized and exact-head verification.

## 2026-10-12 P2.1 ninth Codex review

- Exact-head Codex review `d72444b64961e023fff148f856531db73f380f35` found one P2 JSON preview invalid Unicode surrogate gap. Fixed isolated-surrogate `UnicodeEncodeError` to HTTP 422 `source_format_invalid` at the JSON reader's untrusted-value byte accounting boundary, without weakening general persistence/presenter errors. Added parameterized invalid keys/values and valid surrogate-pair regression. PR #288 remains open; fresh exact-head review and executable pytest/SQL Server acceptance are necessary.

## 2026-10-12 P2.1 tenth Codex review

- Exact-head `dd2f296645eb3a3989418210a71a10c4379d9e77` Codex review completed with a P2 on malformed XLSX XML when optional lxml parsing is enabled. A specific reader-level catch now normalizes XMLSyntaxError to 422 source_format_invalid and does not require lxml to be installed. Added regression mutating [Content_Types].xml in a real ZIP workbook to trigger lxml; no hosted runtime pytest PASS evidence claimed. PR #288 remains Open; do not merge without explicit user instruction.

## 2026-10-12 P2.1 eleventh Codex review

- Exact-head `4fe28edafd438854d70e99bb416ad4deb4909cb6` Codex review found P1 prohibited try/except import of optional lxml and P2 nested JSON memory amplification before decoding. Fixed via importlib module lookup following AGENTS.md, and a 5k/row plus 100k/preview preparse JSON structural-token cap on the existing incremental HTTP reader, before one-row object construction. Added adversarial and positive regressions; no full pytest or live SQL Server acceptance claimed. PR #288 stays open, no merge authorization.

## 2026-10-12 P2.1 twelfth Codex review

- PR #288 review at exact head `a9449c61b347a1509951f5034639d948e7a3c38d` finished with P1 JSON scanner comma-regression, P2 `requirements_json` direct-form predecode memory amplification. Both repaired on original PR branch: top-level commas now end each JSON fragment before counting nested tokens; direct JSON uses existing bounded HTTP reader to materialize rows before preview service's canonical serialization. Added multirow reader/API, nested form amplification and invalid syntax tests. Await fresh exact-head review / full runtime pytest / real SQL Server acceptance; do not merge without user's explicit instruction.

## 2026-10-12 P2.1 thirteenth Codex review

- The 13th Codex review of PR #288 (`fc1e8eac0906999fc2085808bc00fae63d2d2298`) found three P2 issues. HTTP preview task form metadata now has 4 KiB predecode budget, valid two-field boundary retained. XLSX ZipFile opens only after a bounded raw central-directory EOCD/member-count preflight, with ZIP64/multidisk large variants refused and forged EOCD count cross-checked. Empty XLSX headers now yield 422 source-format validation. Regression tests added; exact-head Codex re-review, full pytest and real SQL Server acceptance remain unverified. No merge.

## 2026-10-13 P2.1 fourteenth Codex review

- Exact-head review `5ff11c6789bcae908274cf41544f10f5780aa97f` reported one P2 metadata encoding compatibility bug: `json.dumps` default ASCII escaping can generate more than 4 KiB from two otherwise Pydantic-valid Unicode fields. Increased preview-only `task` JSON predecode budget to 8 KiB, tested 128 + 240 non-BMP characters serialized with default escapes, and kept oversized nested task form rejection. Maintain original PR #288, no merge until explicitly instructed; real pytest and SQL Server tests remain unverified.

## 2026-10-13 P2.1 fifteenth Codex review

- The 15th Codex review of PR #288 on exact head `b3f3e73116410ad335e1b05a70e587be5e799e91` reported one P2 in CSV preview: width check only after csv.reader created million-column field arrays. Fixed through preview-only pre-scan of CSV logical records before csv.reader, respecting quotes, escaped quotes, CRLF and quoted newlines, rejecting >128 columns before allocating decoded field lists. Added adversarial/positive regressions, retained unrestricted internal Phase 1B import. Same PR branch, no merge; exact-head review and actual pytest/live SQL Server still pending.

## 2026-10-13 P2.1 sixteenth Codex review

- PR #288 exact-head Codex review `f372756a184979593d44803a5e6b21deaf51ee50` found a P2 malformed XLSX no-active-worksheet case. Reader now checks resolved sheet for None before touching max_column/header, closes workbook and reports 422 source_format_invalid. Added realistic ZIP workbook.xml-without-sheets regression; local isolated openpyxl confirmed workbook.active is None. Full repository pytest, hosted authoritative CI and real SQL acceptance are unverified. Maintain original PR; no merge without authorization.

## 2026-10-13 P2.1 seventeenth Codex review

- Exact-head `7b064f56bfb065539c78449b2e352b9cf4c79d0a` review found user-supplied nonexistent profile IDs produced `KeyError("profile_version_not_found")` and incorrectly became HTTP 500. Narrow normalization at Product preview service's known profile lookup now yields HTTP 422 `requirement_preview_profile_invalid`, preserving unknown backend KeyError as masked 500. Unit/API regressions added, full pytest and real SQL Server acceptance not yet verified. PR #288 open and unmerged.

## 2026-10-15 SRAF air-gap OFF-0 inventory handoff

- Issue #290 tracks an independent sealed-network release/acceptance program alongside Product P2.2. OFF-0 inventory and acceptance-mode contract are proposed on `feat/sraf-airgap-off0-inventory-contract`: `docs/operations/sraf_airgap_off0.md`, `docs/operations/sraf_airgap_off0_checks.v1.json`, a pure-stdlib registry validator, and focused contract safety tests. This is design/schema validation ONLY, not a runtime offline-check launcher, dependency probe, or air-gapped acceptance PASS.
- Reuse existing provenance, operator E2E, runtime-evidence, ES mapping/LLM probes and existing P2.1 API smoke evidence with strict mode/side-effect separation. Quick/Diagnose must not execute `run_sra_api.sh`, DB `initialize()`/migration, `prepare_requirement_elasticsearch()` fixture writes, or automatic login; authorized Acceptance is a separate gated mutation mode.
- Focused P2.1 user evidence is 13/13 live smoke and three approved XLSX preview rows; actual Product-owned Task/Run fixture and cross-reader RBAC acceptance remain missing, and PR #289's URL-encoded 400/422 test-only fix is still a separate pending PR. Do not merge OFF-0 automatically.

- 2026-10-15 OFF-0 PR #291 initial exact-head Codex review of `a20b84e` completed with three P2 findings: missing enforceable report redaction, missing PKG-01 precondition on worker-evidence API, and malformed unhashable registry list fields causing unbounded traceback. Branch now adds a fail-closed report policy, a safe-record constructor accepting only reviewed message strings and bounded allowlisted evidence, the missing worker-provenance dependency, and malformed-type regressions. Added a separate GitHub Actions OFF-0 focused-test workflow for developer-hosted testing; this does NOT run inside the target air-gapped environment. Exact-head re-review and green hosted tests remain required, and there is NO merge authorization.

- 2026-10-15 OFF-0 PR #291 second exact-head Codex review (`42689fb4`) completed with three additional findings (P1: GitHub Actions installed only pytest without `requirements.txt`; P2: unchecked report-emitted title/remediation/error_code strings; P2: oversized JSON integer could produce a traceback). The PR branch now installs project requirements before pytest, checks bounded report text/structured code/component and rejects obvious credentials/URLs/paths/tracebacks, and isolates JSON decode exceptions from `ContractError` with a stable CLI failure. Focused tests added, pending new exact-head CI/Codex re-review. This remains OFF-0 contract-only, not the air-gap executable system; no merge authorized.

- 2026-10-15 PR #291 third exact-head Codex review at `fb6afd2` completed with 3 P2: underscored credential/unicode/path bypass in report strings, json.loads RecursionError escaping bounded parser error, and stat-only unlimited nonregular/device read. The existing OFF-0 branch was updated with vetted pinned report title/remediation allowlist, Unicode category restrictions, expanded credential/path guards, nonblocking O_NOFOLLOW open with fstat regular-file requirement and hard 256KiB+1 bounded read, dedicated RecursionError mapping, and focused subprocess/malicious-input regressions. Hosted exact-head CI plus fresh Codex review still required; no merge authorization.

- 2026-10-16 OFF-0 PR #291 fourth Codex review at exact head `93c355b5` completed with three P2 findings: Python-version-dependent deeply nested JSON test, FAIL/SKIP report-code confusion, and successful contract validation on incomplete check inventory. Same OFF-0 PR branch now adds bounded JSON structural-depth scanning before json.loads (ignoring braces within strings), report-specific FAIL code vs allowlisted SKIP reason semantics, and required exact 19-ID approved inventory; focused tests cover valid/invalid cases. Exact-head CI and Codex re-review still required; no merge authorization. This does not execute actual offline SQL/ES/LLM checks.

- 2026-10-16 OFF-0 PR #291 fifth exact-head Codex review of `a679533b` completed: one P2 that `readiness=planned` checks could claim FAIL/WARN without an implementation. Remediated in the same branch: planned checks now can only create `SKIP(check_not_implemented)` reports (PASS retains `report_unimplemented_pass` refusal), with parameterized negative and allowed-result tests. Exact-head hosted CI and follow-up Codex review are required before merge; this is static contract work only, and no merge authorization was granted.

- 2026-10-16 OFF-0 PR #291 sixth exact-head Codex review of `fe5cc68e` reported one P2: mutating `SYS-01.readiness` from `planned` to `existing_component` bypassed the planned-result SKIP invariant. Added in-code `APPROVED_CHECK_READINESS` binding for all 19 check IDs, fail-closed `contract_check_readiness_unapproved`, and positive/negative CLI and record-builder regressions. Hosted CI and new Codex exact-head review remain required. Do not merge without explicit user authorization.

- 2026-10-16 OFF-0 PR #291 seventh Codex review on `23166cc3` completed with 2 P2s: mutable `minimum_mode/effect/depends_on` could authorize write-producing E2E in Quick, and mutable `error_code` could misattribute API errors to ES Mapping. Existing OFF-0 branch now pins all 19 checks' execution semantics and error codes (plus component) to reviewed in-code `APPROVED_CHECK_SEMANTICS`, with regression tests for unsafe promotions and wrong failure attribution. Current-head CI/Codex re-review are required; this is contract-only, no real offline probe or production mutation, and no merge authorization.

- 2026-10-16 OFF-0 PR #291 eighth Codex review on `6f7b987a` identified one P2: `make_report_record(..., "PASS")` can succeed with no evidence for existing-component checks. Given OFF-0 has **no reviewed execution-bound real probe**, the constructor now categorically rejects single-check PASS with `report_pass_probe_not_implemented` (planned entries retain `report_unimplemented_pass`). Added adversarial regressions for missing/empty/forged-looking allowed evidence. `OFF0_CONTRACT=PASS` remains schema validation only, not operational health. Hosted exact-head CI and next Codex review pending; no merge authorization.

- 2026-10-16 OFF-0 PR #291 ninth exact-head Codex review at `781e214e` found one P2: make_report_record could emit unexecuted FAIL/WARN, despite already blocking proofless PASS. This branch now guards all runtime PASS/FAIL/WARN in the contract-only stage, with explicit stable `report_outcome_probe_not_implemented` error and regressions across reusable checks, empty and fabricated-looking evidence. Existing SKIP and report-output validation remain available. Follow up with current-head CI and new Codex review; no merge permission.

- 2026-10-16 OFF-0 PR #291 tenth Codex review at `ccf6dd5f` found one P2: even SKIP could emit caller-supplied allowlisted but fictitious evidence such as FULL_LIVE/HTTP 200. Fix: require empty `evidence` on OFF-0 SKIP via `report_skip_evidence_untrusted`, with parameterized negative tests for planned/existing checks and positive tests for None/empty; prior report construction positive test updated to no evidence. OFF-0 remains contract-only; latest-head CI and re-review must be checked before any merge (no authorization).

- 2026-10-16 PR #291 eleventh Codex review of `2dec55a7` found one P2: global SKIP reasons allow false precondition explanations for API-01 and other checks despite OFF-0 not executing dependencies, auth, or mode. Contract-only record builder now accepts only SKIP(check_not_implemented) with empty evidence for all checks, and rejects other globally recognized reasons with `report_skip_reason_unverified`. Code and negative/positive tests committed. `check_not_implemented` denotes OFF-0 probe, not upstream SRAF component. Latest-head CI and fresh review pending; no merge authorization.

- 2026-10-16 OFF-0 PR #291 twelfth exact-head Codex review of `0aadda10` identified 2 P2: a no-probe SKIP could fake a nonzero `duration_ms`, and it could emit operational failure remediation even though no probe executed. Updated OFF-0 report constructor to require zero duration and emit `remediation=None` on contract-only SKIPs, preserving failure copy in reviewed registry for future real probes; regression tests check all checks, positive zero and invalid/nonzero values. Exact-head CI and re-review pending. No merge authorization.

- 2026-10-16 OFF-0 PR #291 thirteenth Codex Review of exact head `a47e0f4d` completed with one P2: static `report_policy.remediation_source=inventory_check_remediation` contradicted actual SKIP remediation=null. Updated registry and validator to `verified_fail_warn_inventory_remediation_else_null`; added policy integrity tests plus CLI check refusing old policy and asserting all 19 SKIPs have null remediation. The policy does not authorize OFF-0 live PASS/FAIL/WARN. Hosted current-head CI and fresh Codex review needed before merge; not authorized to merge.

## 2026-10-17 SRAF OFF-1A start (PR forthcoming)

- PR #291 OFF-0 was merged on 2026-10-16; Hosted final head 04d2e654, merger df8e987b, 295 focused tests pass. It is the contract/schema gate only.
- OFF-1A begins on separate branch feat/sraf-airgap-off1-readonly-probes: standalone read-only and **partial-only** probes for disk/CPU observation, native ODBC library discovery, anonymous loopback GET /healthz, ES HTTP identity, and local Ollama/OpenAI-compatible model inventory. All network calls GET via http.client to fixed 127.0.0.1 only, with timeout and response cap, and no credentials/writes. CLI requires explicit check; diagnose-only probes are mode-fenced. Output mode PARTIAL_ONLY_NOT_ACCEPTANCE prevents claiming parent check/full-live acceptance. No modification to OFF-0 make_report_record.
- Security regressions include real local HTTPServer, redirects, auth-boundary, fake HTTP 200, oversized/malformed responses, mode selection, evidence redaction, and original OFF-0 boundary. Hosted PR CI and Codex review are still pending; no deployment-host SQL/ES/LLM live proof and no merge authorization.

- 2026-10-17 OFF-1A PR #292 first Codex review of head eb479618 completed with one **P1**: socket inactivity timeout 3s did not bound a slow-dripping header/body response. Fixed via a monotonic absolute deadline shared by connect/send/header/body reads in _DeadlineSocket (used by http.client SocketIO), returning stable non-secret transport classification on expiration. Added real ThreadingHTTPServer slow-drip headers/body regressions and deterministic per-operation deadline tests; documentation updated. Await hosted exact-head CI and fresh Codex review. PR not merge-authorized; OFF-0 contract unchanged.

- 2026-10-17 OFF-1A exact-head GitHub Actions run 38992439458 failed new slow-drip tests: 2 failed, 331 passed. Root cause confirmed from Python standard-library implementation: HTTPConnection.__init__ creates instance attribute _create_connection=socket.create_connection, shadowing the subclass method that was supposed to create _DeadlineSocket. Fixed by rebinding _create_connection to self._bounded_create_connection after super().__init__; new test asserts a real _DeadlineSocket gets installed. Not yet hosted-verified; next CI and fresh Codex review required. Never count earlier CI PASS as valid for newer head.

- 2026-10-17 OFF-1A PR #292 second Codex review at 37523ad1: P1 on ODBC helper calls with indefinite runtime. Switched native-library discovery to a finite static list of local Unix candidate files, no process spawning, and marked non-POSIX as SKIP. Added narrow-scope tests and docs; full driver compatibility stays OFF-1B. Latest CI and follow-up Codex review pending; PR must remain unmerged.

- 2026-10-17 OFF-1A third Codex review of head a10408e8 found two P2: HTTP Content-Length may exceed received body but http.client.read(amt) can silently accept valid partial JSON; blank ES cluster_name/version.number could satisfy string type checks. Fixed by preserving declared length before bounded read and rejecting premature EOF, and requiring nonblank ES identity strings. Tests cover truncated valid ES/Ollama/OpenAI JSON and empty/whitespace identity. Await exact-head Actions and fresh review.

- 2026-10-17 OFF-1A PR #292 fourth exact-head Codex Review at 8d18d965 completed with one P2: http.client converts malformed declared Content-Length to None, allowing a fake ES/model JSON PASS as if header absent. Added strict raw parsed Content-Length validation: only one ASCII-decimal header, optional HTTP whitespace, rejects invalid/negative/duplicate/transfer-encoding conflict, verifies declared length before accepting body. Added parameterized live loopback ES/Ollama/OpenAI tests for malformed/duplicate/conflicting headers, plus valid-whitespace case. Pending exact-head Hosted Actions and fresh Codex review; no merge authorization.

- 2026-10-17 OFF-1A PR #292 fifth Codex review of head 1f6fc17e found P2 malformed raw HTTP framing lines (e.g. Content-Length : -1) silently discarded by Python header parser; get_all() cannot detect them and false PASS could result. Fixed _http_get to reject response.headers.defects before any HTTP identity acceptance. Added live raw-header HTTPServer tests for API health, ES root, Ollama tags and OpenAI model list, including malformed length, malformed transfer encoding, and bare header lines; kept valid close-delimited response acceptance. New current-head Hosted Actions and exact-head Codex review required. No merge authorization.

- 2026-10-17 OFF-1A PR #292 sixth exact-head Codex review at 0642280130 finished with a P2: reject-all Transfer-Encoding handling falsely failed valid standard HTTP/1.1 chunked responses without Content-Length. Reworked parser to allow one exact chunked coding, no Content-Length, and only when http.client marks response.chunked=True; reject duplicated/unsupported coding and mixed Content-Length + transfer encoding. Added actual local HTTPServer tests for valid chunked API/ES/Ollama/OpenAI responses, unsupported/ambiguous TE across all four, missing final chunk and uppercase CHUNKED. OFF-0 trust boundary and full-live acceptance remain unchanged. Exact-head Hosted Actions and fresh Codex review pending; no merge authorization.

- 2026-10-17 PR #292 seventh Codex review at 77347ed3 completed with two P2: CPython http.client chunk decoder does not verify the CRLF following each chunk payload and may accept EOF before the final trailer terminator; also accepted Transfer-Encoding: chunked in HTTP/1.0. OFF-1A now uses a custom tightly bounded decoder on response.fp with exact chunk-size line, per-chunk CRLF, valid 0-chunk/trailer terminator and bounded trailer/fragment count, subject to the existing 3s monotonic socket deadline; HTTP version 11 is mandatory for chunked. Added raw TCP tests across API/ES/Ollama/OpenAI for corrupt delimiter, incomplete trailer and HTTP/1.0, plus valid trailers and oversized body. No API/ES/LLM real deployment acceptance. Hosted exact-head CI and Codex review pending; PR unmerged.
