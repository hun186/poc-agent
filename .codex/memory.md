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
