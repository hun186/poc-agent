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
