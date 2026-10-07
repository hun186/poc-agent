# Architecture and Engineering Decisions

## Current Summary

### Runtime and execution boundaries

- Keep runtime API code in `sra_api/` with `api/` as compatibility namespace. Preserve established Auth/RBAC, signed-capability, audit, and owner-isolation boundaries.
- Keep Phase 1A Batch Scheduler separate from Requirement Scheduler and keep Report Job Worker ownership in API lifespan.
- Keep Requirement import authority in SQL Server with immutable Requirement Version/Snapshot history and exact catalog validation.
- Keep Requirement recurrence/execution control in separately versioned `sra_schedule`, driven by external Schedule/Handoff workers rather than FastAPI background loops.
- Keep HTTP/filesystem effects outside SQL authority transactions. SQL lifecycle state/fencing/audit mutations commit atomically; JSONL/audit projections are not transaction authority.
- Preserve production Report Job execution through real Agent/LLM/Elasticsearch. Verified E2E semantic mocks are job-scoped test authority only and must never leak to ordinary production jobs.
- Job Task JT-1, generic Task/Attempt/Event infrastructure, Workflow Registry, and LangGraph integration remain future work and are NOT STARTED.

### Deployment and provenance

- Requirement SQL registry selection is deployment-local privileged authority and is excluded from release-provenance evidence; do not expose registry bytes, digest, resolved path, credentials, or query text.
- Runtime provenance uses explicit shared bounded selectors. Generated artifacts and deployment-local mutable/secrets state do not become release authority merely by directory location.
- Functional verification may make only reviewed runtime byte drift advisory; security/discovery/module-shadow/worker/artifact integrity checks remain fail closed. Release verification remains the strict default.
- Operator E2E is a stimulus/observer of deployed public APIs/workers, not a second executor. Live acceptance claims require actual authorized deployment evidence.

### Requirement Product API + Task Center

- The first implementation slice is intentionally limited to Schedule schema v4 Product control-plane persistence and exact migration/catalog validation; Product service/router/create saga/UI remain separate later PRs.
- Integrate Requirement automation into the existing SRA operations console. Reuse existing navigation, Auth/RBAC, audit, service-key system, Requirement Import, Schedule/Handoff, Report Job, and artifact authorities; do not build parallel infrastructure.
- Persist Product Task identity/kind/state and Product idempotency in Schedule schema v4 using only `requirement_product_tasks` and `requirement_product_requests` in v1.
- New Product Task/source provisioning remains superuser-only. Service-key automation is limited to already provisioned Tasks.
- Preallocate cross-authority Product saga IDs before authority commit. Requirement import and Schedule Version authorities accept optional caller-supplied IDs with same-ID/same-semantics recovery.
- Product-owned low-level Schedule/source HTTP mutation is fenced transactionally; reads remain available and non-Product mutation remains backward compatible.
- Hide/inhibit Product Tasks while `provisioning`. Release one-time initial Run or recurring enablement only inside the atomic Product create finalizer that also publishes Task visibility and create success.
- Input replacement persists `base_snapshot_id` and uses locked CAS. Same-ID committed import recovery occurs before `_prepare()`.
- Schedule-affecting Product PATCH creates a draft only. A separate superuser-only `task_version_activate` operation approves/activates the exact draft. Low-level Product-owned approval stays fenced.
- Product Task revision represents active semantic state: successful in-place metadata/state PATCH and successful activation each increment once; draft-only proposal and input replacement do not.
- Reject mixed in-place + schedule-proposal PATCH before durable reservation with `requirement_task_patch_mixed_modes`.
- Recurring Product `product_state` mirrors Schedule enablement atomically: active/true and disabled/false. One-time Tasks remain active in v1.
- First manual `run_trigger` admission serializes with recurring disable on the Product Task lock. Disable affects new admissions only.
- For an existing same principal/operation/idempotency key, compare canonical hash and dispatch every persisted ledger state before lifecycle checks: recoverable states resume, success replays success, terminal failure replays the same safe terminal result.
- Canonical Product request hashes bind operation + every path/target resource identity + semantic payload/input digest. Task-scoped operations include `task_id`; draft activation includes `task_id + schedule_version_id`; empty-body Run trigger still hashes `task_id`. Reusing one key on another resource yields `requirement_idempotency_conflict`.
- Product v1 does not persist retry parent/child ancestry; “Run again” creates an independent Run.

## Recent Decisions

### 2026-10-06 Preserve quoted literals during SQL catalog normalization

- Catalog normalization may remove SQL Server-owned brackets/parentheses/spacing and normalize unquoted syntax only; it must never rewrite characters inside quoted SQL literals.
- Hash/fingerprint CHECK patterns therefore retain the exact `[^0-9a-f]` character class so structural drift cannot be normalized into equivalence.


### 2026-10-06 Implement Product schema v4 as the first isolated slice

- Start implementation with P1.0 only: Schedule schema v4, Product Task/request catalog descriptors, transactional v3→v4 migration/fresh bootstrap, and focused persistence tests.
- Do not introduce Product router, UI, create saga, activation, input replacement, or Run trigger in this slice; later gates build on the reviewed persistence authority.
- Keep `requirement_product_requests` reservation refs intentionally non-FK while `requirement_product_tasks.schedule_id/source_id` are real FKs to existing Schedule/Requirement authorities.
- Persist Product Task `revision` and request-ledger `base_task_revision` / `result_task_revision` as SQL Server BIGINT, matching the approved monotonic revision authority before schema v4 is released.


### 2026-10-06 Canonical idempotency hash binds target resources

- Ledger namespace remains principal + operation + idempotency key, so `request_sha256` must distinguish the target resource.
- Cross-Task or cross-Version reuse of the same key cannot replay an earlier resource even when request bodies are identical or empty.

### 2026-10-06 Persisted run-trigger state precedes lifecycle admission

- Current disabled/provisioning state is a rule for truly new `run_trigger` admission only.
- Existing same-key requests are resolved by request hash and persisted ledger state first. `failed_recoverable` remains resumable after disable; `failed_terminal` remains the same terminal result.

### 2026-10-06 Serialize manual Run admission with recurring disable

- The Product Task lock is the serialization point between first `run_trigger` reservation and recurring enable/disable.
- Disable-first rejects without a request row; trigger-first creates one durable admitted request. Later disable does not revoke it.

### 2026-10-06 Product state/revision rules

- `product_state=disabled` is reachable only for recurring Tasks and atomically mirrors Schedule `enabled=false`; re-enable mirrors active/true.
- Draft proposal creation does not change Product Task revision or `result_task_revision`. In-place Product mutations and successful activation each advance revision exactly once.
- Mixed in-place + schedule-proposal PATCH is rejected instead of defining a coupled two-phase transaction in v1.

### 2026-10-05 Separate Schedule proposal from activation

- `db_operator` may propose immutable Schedule drafts but cannot activate them. Superuser activation is a distinct idempotent Product operation using the proposal's original `base_task_revision` CAS anchor.
- Durable retry ancestry is outside Product v1.

### 2026-10-02 Product concurrency and recovery

- Product ownership fencing is transactional with low-level writes and recognizes task-create reservations before the Product Task row exists.
- Input replacement uses `base_snapshot_id` CAS; committed same-ID import replay must be recovered before preparation/diagnostics.
- Product create finalization is the atomic execution-release and visibility boundary.

### 2026-09-30 E2E isolation

- Verified E2E authority is carried on per-Agent tool instances and re-opened in worker threads; no process-global fallback may make mocks visible to production jobs.

### 2026-09-23 Verification/provenance

- Keep release verification strict by default. Functional verification does not bypass runtime discovery, active-module, worker identity, or artifact integrity.
- Port semantic-input corrections without weakening deployment capability/worker/artifact architecture.

## Archived History

- `.codex/archive/decisions.md-20261006-143100.md` — full active decision history immediately before this compaction, including all dated Product-review decisions through 2026-10-06.
- `.codex/archive/decisions.md-20260907-120000.md` — earlier complete pre-compaction history through PR #214.
- `.codex/archive/decisions.md-20260813-000000.md` — earlier retained decision history.
- Historical details not repeated here remain authoritative for traceability only when not superseded by the current summary.


### 2026-10-07 One-time Product create uses persisted preallocation + atomic release

- Reserve every cross-authority identity in `requirement_product_requests` before creating Source/Import/Snapshot/Schedule/Task/Version rows.
- Exact-ID Source and Schedule creation must replay only when semantics match; unique-key or same-ID drift is never treated as success.
- The one-time initial Batch Run is created only inside the Product finalizer, using the existing locked Schedule materializer and a stable request-derived manual trigger. Product visibility (`active`) and request success commit in that same transaction.
- The selected preview profile must still be the active approved profile at create time so Requirement commit cannot silently normalize under a different profile version.


### 2026-10-07 Product preview profile identity must be transactionally bound at import

- A Product create pre-check of the active Requirement profile is insufficient because another superuser can activate a different profile version before the import transaction begins.
- Product create therefore passes the previewed `profile_version_id + profile_sha256` into Requirement Import authority. Preparation uses that exact version; a new import locks/validates the active profile binding inside the mutation transaction; terminal exact-ID replay verifies persisted import/snapshot profile identity without requiring the profile to remain currently active after success.


### 2026-10-07 Product create recovery precedes current-active profile admission

- Historical exact-ID import recovery is authoritative once the persisted import/snapshot is bound to the expected profile identity. A later profile activation change must not prevent recovery/finalization of that already-committed Product request.
- Therefore Product orchestration must not independently reject the current active profile before calling Requirement Import recovery. The Requirement Import transaction enforces active-profile equality only for a genuinely new write.
- One-time Product create requires at least one accepted Requirement row. Empty direct JSON/header-only uploads fail terminal before durable domain objects or an initial Batch Run are created.


### 2026-10-07 Product create selection time is part of durable request semantics

- One-time Product create eligibility must not drift across retries. The selection/expiry evaluation time is the Product request's persisted `created_at`, established when the idempotency reservation is first committed.
- Retries may occur after Requirement rows expire; if those rows were eligible at the original request time, recovery/finalization continues using that same evaluation instant rather than converting the request to terminal failure.


### 2026-10-07 Product one-time finalization separates selection time from audit time

- `_materialize_locked()` accepts an optional semantic `selection_time`; existing scheduler/manual paths default it to `now_utc`.
- Product one-time finalization passes the reserved Product request `created_at` as `selection_time` so retries select the same rows as the original request.
- Audit/materialization timestamps continue using current `now_utc`; only eligibility evaluation and item `evaluated_at` use the durable selection instant.


### 2026-10-07 Recurring Product create releases only recurrence, not an initial Run

- Reuse the existing Phase 1C recurrence calculation and scheduler worker rather than copying scheduler logic into Product service.
- The recurring finalizer computes `next_run_at` with `next_occurrence()` and enables the Schedule in the same transaction that makes the Product Task visible and marks the owning request succeeded.
- Do not create a manual/initial Batch Run for recurring Product create. The scheduler remains the sole authority for scheduled occurrence materialization.
- Persist the first computed due time in bounded request result metadata so same-key replay returns original create evidence even after the scheduler advances the live Schedule.


### 2026-10-07 Recurring create uses separate reservation and release clocks

- Product request `created_at` remains the durable semantic time for preview/replay identity; it is not the authority for recurrence release after potentially long provisioning.
- Immediately before recurring finalization, the service obtains a fresh UTC release time. The finalizer computes `next_run_at` from that release time using existing Phase 1C recurrence logic.
- The exact first due is also the authoritative first-run expiry gate. The finalizer must prove the committed snapshot contains at least one row with no expiry or `expires_at > initial_next_run_at` before it can enable recurrence.
- If no row can participate in the first occurrence, the create request is terminalized while Schedule remains disabled and Product Task remains provisioning; no zero-selected scheduled Run is released.


### 2026-10-07 Scheduled Requirement selection is evaluated at scheduled_for

- For scheduled runs, `scheduled_for` is the semantic selection/evaluation time. Worker claim time is operational/audit time only.
- Delayed scheduler claims therefore do not change expiry-based membership for the occurrence being materialized.
- This reuses the existing materializer's explicit `selection_time` mechanism; manual/Product one-time paths retain their own reviewed selection-time semantics.
