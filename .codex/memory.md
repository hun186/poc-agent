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


## 2026-10-19 OFF-1A PR #292 — exact-head progression

- OFF-1A five narrow read-only probes (sys-disk, odbc-library, api-health, es-transport, llm-inventory) preserve anonymous GET to numeric loopback, strict 3-second total monotonic deadline, bounded HTTP payload and fail-closed raw status/header/chunk/trailer parser. OFF-0 is schema-only. PARTIAL_ONLY_NOT_ACCEPTANCE must never be promoted to full live SQL Server/ES/LLM/Workers/DOCX acceptance.
- Full earlier review rounds, historical remediation and CI records are archived verbatim in `.codex/archive/memory.md-20261019-134500.md`. Pre-fix head `39af7be7584a93587596d1ed0a4e2452ee98e61e` had Hosted Actions run 39200232813 success (811 passed in 257.72s; OFF-0 19 PASS; Vercel Success). Codex exact-head reviewed at 2026-10-19 04:50 UTC and found two new P2s.
- RFC 8470 §5.1 forbids `Early-Data` in response trailers; RFC 9209 §2 permits `Proxy-Status` trailer only with matching intermediary member in corresponding response header. Added explicit Early-Data rejection, conditionally permitted member-matched Proxy-Status, retained other proxy-prefix bans. Expanded real loopback TCP regressions across API/ES/Ollama/OpenAI. New exact-head Hosted CI and Codex review pending.
- PR #292 remains OPEN, never merge without explicit user command. Formal offline deployment acceptance, ES mapping_incompatible blocker and OFF-1B+ are separate gates.

## Compaction Record — 2026-10-19

- Archived pre-compaction active memory verbatim at `.codex/archive/memory.md-20261019-134500.md` (>40KB / multiple dated sections), retained current summary, contracts, previous archives and outstanding obligations. No historical progress is discarded or falsely restated.

- 2026-10-19 PR #292 Codex exact-head 816a0297ed review completed after 863 passed (run 39206507074). Two new P2: malformed Proxy-Status parameter suffix (e.g. '; =broken') falsely accepted; legal RFC 8941 sf-token characters (e.g. '+') falsely rejected. Replaced prefix-only parsing with full RFC 8941 Item/Parameter matcher (all token tchar, key/bare item grammar and decoded Base64 validation). Added live TCP four-path valid/invalid regression matrix; new exact-head Hosted CI and Codex review pending. No full SRAF airgap deployment acceptance or merge authorization.

- 2026-10-19 PR #292 Codex exact-head aa8ed6f3df review completed at 2026-10-19T07:25:47Z (previous Hosted run 39211543915: 1003 PASS, OFF-0 19 schema-only PASS). New P2s: parser accepted known Proxy-Status fields using wrong types (e.g. received-status quoted string or error boolean) and incorrectly normalized illegal initial HTAB around RFC 8941 List items. Followup patch validates RFC 9209 and 9532 registered field types including next-protocol as Token OR Byte Sequence, and preserves RFC 8941 legal OWS around commas while rejecting HTAB at list start/end. Raw header guard rejects leading Tab before http.client strips it; strict trailer decoder no longer strips original field data. Four-endpoint live loopback regression vectors added. New exact-head Hosted CI and Codex re-review required; no merged/live acceptance claim.

- 2026-10-19 PR #292 Codex reviewed exact head bdb2148e01 at 08:11 UTC, found P1: valid Proxy-Status trailers all false-FAIL because the strict parser receives the raw trailer CRLF in its RFC 8941 fullmatch. Hosted Actions 39219555536 confirmed 148 FAIL, 979 PASS (not a PASS). Repair slices the already verified final CRLF off the wire line before parsing only the field value; preserve the actual leading/trailing content for OWS rules and reject bad raw line endings. Four-endpoint real TCP regression added. New exact-head Hosted CI / Codex review required, no merge or offline FULL_LIVE claim.


## 2026-10-19 OFF-1B configured preflight (proposed, NOT MERGED)

- Linux deployment evidence supplied by operator: effective .env.local uses private-IP HTTPS ES port 9001, HTTP SRA API port 9002 and HTTP LLM port 18080; API /healthz PASS, API/Workers processes share launcher, schedule/handoff runtime logs empty. API startup markers all present without observed ERROR/TRACEBACK, but earlier readiness timeout cause unproven and ~89-second API-to-worker gap requires investigation.
- New proposed OFF-1B first slice: tools/sraf_airgap_off1b_auto.py invokes real config.bootstrap.bootstrap_env() to select effective runtime env (OS > .env.local > .env.profile > .env), suppresses path-bearing bootstrap output, and attempts only bounded numeric RFC1918/loopback TCP connects. Config/TCP observations are explicitly PARTIAL_ONLY_NOT_ACCEPTANCE: NOT a verified ES service/TLS/auth, LLM inventory/inference, SQL, Worker, or air-gap acceptance. Never expose endpoint host, model, credentials or raw errors.
- Independent tests/workflow/docs are included on feat/sraf-airgap-off1b-runtime-config-preflight. Require Hosted CI and exact-head Codex review plus explicit user merge authorization before release packaging or deployed execution. PR #292 is already merged; do not reopen it.

- 2026-10-19 PR #293 first Codex exact-head review on 2008069288 found three P2 endpoint-parity issues: TOPIC_LLM_URL is a query_terms feature flag, not the actual network target; PUBLIC_API_BASE may be a reverse proxy, while the shell launcher binds PORT (default 9002); MODEL_BASE_URL supports /api/chat and /api/generate paths. Corrected the same branch and added regression tests. Exact-new-head Hosted CI and Codex re-review are required; no merge authorized, no Linux release acceptance claimed.

- 2026-10-19 PR #293 second Codex reviewed exact head b04b1479 and found two more P2s: runtime permits trailing slashes on /api/chat/ and /api/generate/ while preflight rejected them, and architecture memory incorrectly described Topic LLM feature flag as a separate TCP target. The same Hosted CI #39277783676 FAILED with a preflight Python IndentationError at line 191, so its tests did not run. Patched indentation, allowed runtime-normalized LLM suffixes, corrected architecture, and extended tests; a new exact-head Hosted CI and Codex review are mandatory. PR remains unmerged.

- 2026-10-20 PR #293 third Codex exact-head review completed at 28e98a233c with one new P2: unconditional URL trailing-slash normalization accepted forbidden ES_URL paths such as // and could open a TCP connection. Updated OFF-1B to normalize path only for the real LLM client, retain strict ES bare-origin policy, and added negative ES double/triple slash/no-network regressions. Exact-new-head Hosted CI and Codex review still required; no merge or FULL_LIVE claim.

- 2026-10-20 PR #293 fourth Codex review completed on head 45c03b3389 with one new P2: runtime LLMClient accepts prefixed MODEL_BASE_URL paths like /ollama and /ollama/api/chat but first OFF-1B preflight rejected them. Implemented bounded safe path-segment acceptance only for main LLM endpoints (no path transmitted, no URL/host printed), with regression tests for prefixed paths and strict ES no-prefix rejection. Exact-new-head Hosted CI and Codex review required; PR not merged.

- 2026-10-20 PR #293 fifth Codex exact-head review completed for cf84d5a3c3 (Hosted run 39296228558: 366 PASS, OFF-0 19 schema-only PASS), identified two P2: urlsplit drops empty ?/# delimiter evidence so malformed MODEL_BASE_URL could produce false TCP PASS, and post-rstrip path length test accepted >512 raw trailing slash paths. Corrected with raw delimiter rejection and before-trimming path bound; adversarial tests added. New exact-head Hosted CI and Codex review required before merge.

## 2026-10-20 OFF-1B next slice — configured API HTTP (in review, not merged)

- PR #293 was squash-merged into main at fb206f6f7e7ad21c355755cdd0f84d128237e53b after exact-head Codex 0 findings, Hosted 387 PASS, and all 9 review threads resolved. This does not establish live deployment acceptance.
- Operator prefers deferring Linux deployment updates until a useful OFF-1B milestone (API health + ES HTTPS/mapping + LLM inventory) is ready, rather than separately deploying the TCP-only slice.
- New branch feat/sraf-airgap-off1b-configured-api-health adds tools/sraf_airgap_off1b_api_http.py. It reuses the real OFF-1B env bootstrap and OFF-1A strict anonymous 127.0.0.1 GET /healthz engine, using shell PORT rather than PUBLIC_API_BASE, and reports only PARTIAL_ONLY_NOT_ACCEPTANCE. Unit and real-loopback regression tests plus Hosted CI workflow path were added; do not claim CI/review success until exact-head results return, no merge without explicit authorization.

## 2026-10-20 OFF-1B ES HTTPS/Mapping review slice

- PR #293 (configured TCP) and PR #294 (configured API HTTP) both merged with completed zero-Finding exact-head Codex and green Hosted CI. Deployment update intentionally deferred until API+ES+LLM diagnostic set provides real value.
- New branch feat/sraf-airgap-off1b-es-https-mapping adds tools/sraf_airgap_off1b_es_https_mapping.py. Operator-only configuration from real bootstrap; literal private numeric IPv4 HTTPS ES_URL, Basic credentials and one ES_INDEX, trusted existing agent/certs/http_ca.crt; TLS certificate chain AND numeric IP hostname verification required even though runtime ES client has ssl_assert_hostname=False. GET / identity and GET /{index}/_mapping only with bounded total asyncio deadline, bytes, redacted structured results; original mapping_compatibility reused, no queries/writes or FULL_LIVE promotion. Tests, CI and docs included; Hosted CI/Codex and live operator verification pending. The known live mapping_incompatible blocker remains unresolved without live evidence. No user authorization to merge this new PR.
