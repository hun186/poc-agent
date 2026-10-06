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
