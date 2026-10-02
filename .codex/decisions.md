# Architecture and Engineering Decisions

## 2026-09-22 Heartbeat Handoff authority without weakening fencing

- Use a short-lived, joined heartbeat thread around each production Handoff authoritative-work cycle so blocking remote I/O can coexist with SQL lease renewal. Do not lengthen the lease, renew inside `_prove_lease`, or treat expiration as valid.
- Synchronize the current `LeaseProof`, preserve owner/token/fencing-generation identity across renewal, and recheck authority between coordinator stages. Store-level `_prove_lease` remains the final race-safe boundary for mutations occurring inside a stage.
- Classify only exact `RuntimeError("lease_lost")` and `RuntimeError("lease_unavailable")` as recoverable coordination states. They clear in-memory authority and retry after the bounded poll interval; programming, schema, semantic, and other invariant failures continue to terminate visibly.
- When work and heartbeat both fail, select any non-recoverable error before any recoverable lease condition; use work-before-heartbeat ordering within the same severity. At stop-aware stage boundaries, finish the already-started call but do not begin prepare or submit after shutdown is requested.
- Do not use the process `stop_event` to terminate lease renewal. Continue heartbeats until current authoritative work reaches `_run_with_heartbeat()` cleanup; use `heartbeat_stop` as the sole normal heartbeat termination signal so graceful shutdown cannot expire authority underneath an in-flight call.

## 2026-09-20 Deployment-owned Requirement registry classification

- Requirement SQL registry selection is deployment-local authority. Generic/offline package verification must not infer it from the caller's environment; only deployment-side source evidence supplies the selected repository member for fail-closed manifest rejection.
- Do not serialize the selected registry identity into provenance or runtime evidence. Cross-host acceptance remains bound by the canonical provenance fingerprint and the authenticated deployment determination.

## 2026-09-20 Requirement SQL registry remains deployment authority

- Keep `requirement_sql_registry_path()` as the single selector used by API, Schedule Worker, Handoff Worker, and deployment bootstrap, but exclude the selected registry from release-provenance membership and evidence.
- Derive only a transient normalized repository-relative member for provenance policy. Exclude exactly that selected member during generation and reject it at shared package verification before byte hashing; do not publish the resolved absolute selection or blanket-exclude similarly named/non-selected configuration.
- The ignored/default or externally selected registry is privileged deployment-local configuration. Named reviewed queries and least-privilege database permissions remain its security boundary; do not publish its bytes, digest, resolved path, credentials, connection details, or query text.
- Preserve an explicit empty `MANUAL_SYNONYMS_DIR` as the historical opt-out. Only absence selects `config/synonyms`; non-empty values resolve normally.

## 2026-09-16 Generated artifacts cannot acquire runtime provenance authority by directory location

- Select the broad runtime-containing roots, then apply the shared `is_generated_non_runtime_path()` exclusion before hashing or accepting a manifest path. Do not weaken byte validation for selected runtime paths and do not special-case individual report filenames.
- Keep canonical harness profile/input assets selected. They are operator fixture authority rather than generated output, and removing them would silently weaken reproducibility and the XLSX's independent digest check.

## 2026-09-15 Thin automatic E2E observer

- Keep the Requirement E2E harness as a stimulus/observer rather than a second executor. Automatic scheduling is proven only by a new durable `scheduled` Batch tied to the invocation's version, occurrence, and Snapshot; manual Run and worker/coordinator invocation are prohibited.
- Reuse exact dedicated Profile/Source/Schedule shells but create unique Import Run, Snapshot, Schedule Version, Batch, Run Items, jobs, and evidence each invocation. Unknown drift or ambiguity fails closed, and cleanup only disables the exact schedule through its normal API.

## Current Summary

- Keep runtime API code in `sra_api/` with `api/` as compatibility namespace; preserve established authentication, RBAC, signed capability, and owner-isolation boundaries.
- Keep Phase 1A Batch Scheduler a standalone SQLite-backed HTTP client of Report Jobs. Do not embed its store/service lifecycle in Requirement Scheduler.
- Keep Requirement import authority in SQL Server with immutable RequirementVersion/Snapshot history and exact catalog validation.
- Keep Phase 1C recurrence and execution control in separately versioned `sra_schedule`, driven by an external one-active-worker process rather than FastAPI lifespan.
- SQL lifecycle mutation and audit authority commit atomically through the schedule SQL outbox. JSONL is a bounded, at-least-once projection with stable event identity/time, not an exactly-once transaction participant.
- Phase 1C-B stays behind immutable, framework-neutral `report_v1` contracts. The server-owned output-root fingerprint binds once during Prepare; callers never provide root authority.
- Every Gate-B business mutation proves SQL Server database time plus exact owner/token/fencing generation in the same transaction. HTTP and filesystem activity never occurs inside these transactions.
- Submission ID, isolated session, semantic manifest, and idempotency key are deterministic and immutable. Ambiguous transport replays the same business submission; it never authorizes automatic retry or a second execution.
- Artifact publication is contained, DOCX-validated, digest-proven, relative-path-only, and restart-reconcilable. Changed roots and conflicting existing files fail closed.
- Successful item closure is separate from checkpoint advancement: lower versions and equal immutable versions may complete with checkpoint no-op; equal version numbers with different immutable RequirementVersion IDs fail closed. Counters are recomputed from selected item states.
- Job Task JT-1, Task/Attempt/Event Store, Workflow Registry infrastructure, and LangGraph integration are future gates and remain NOT STARTED. Requirement Scheduler must not import smolagents internals, ReportJobStore, or ReportJobWorker.

## Recent Changes

### 2026-09-10 Unified SRA runtime launcher

- Keep one operator command, `./run_sra_api.sh`, as a narrow foreground supervisor rather than changing API, scheduler, handoff, or Report Job ownership. It starts the three external roles; the API lifespan remains the sole Report Job Worker owner.
- Use `flock` for duplicate-launch exclusion, direct child PIDs with process-substitution log consumers, bounded TERM-then-KILL shutdown, and `/proc` command/cwd evidence before acting on a port-9002 owner. Unverified listeners always fail closed without a signal.
- Bootstrap `.env` inside each worker's inline Python entrypoint before importing and calling the existing Requirement CLI, avoiding a scheduler-module convenience change.

### 2026-09-09 Separate scheduled materialization runtime

- Complete automatic scheduled materialization with a narrow external `schedule-worker` that delegates one occurrence at a time to existing `ScheduleStore.claim_due()` and polls interruptibly. Keep the implemented `handoff-worker` independent; SQL Batch Run / Run Item state is their only communication boundary.
- Do not revive Phase 1C v2's combined scheduling/execution worker, embed the Phase 1A controller, add a FastAPI scheduling thread, or introduce a queue/schema. Store recurrence, locking, materialization, occurrence identity, audit, and advancement semantics remain authoritative.

### 2026-09-09 Requirement Handoff queue locking

- Prepare scans candidate `requirement_batch_run_items` with `UPDLOCK,READPAST,READCOMMITTEDLOCK`: update locks preserve claim intent, `READPAST` skips rows locked by another consumer, and `READCOMMITTEDLOCK` explicitly selects locking READ COMMITTED behavior, including compatibility with databases where `READ_COMMITTED_SNAPSHOT` is enabled. Do not combine the candidate's `READPAST` with `HOLDLOCK`/SERIALIZABLE.
- The joined `requirement_batch_runs` row continues to use `UPDLOCK,HOLDLOCK`; it does not use `READPAST` and still protects run identity/state through the existing Prepare transaction.

### 2026-09-09 Requirement Handoff SQL clock type boundary

- Requirement Handoff retains SQL Server as its lease and deadline time authority, but reads that clock through `TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')` so pyodbc applies the existing `datetimeoffset` converter and returns an aware UTC Python datetime consistent with persisted lease/deadline values.
- A single private store helper validates the result as aware UTC and fails closed on malformed or unexpected driver values. Do not substitute host/caller time, use server-local `SYSDATETIMEOFFSET()`, scatter `tzinfo` replacement, or globally reinterpret unrelated `datetime2` results.

### 2026-09-08 Narrow SQL Server CHECK-expression equivalence

- SQL Server-owned catalog formatting may normalize the proven unquoted equivalence `NOT <identifier> LIKE` to `<identifier> NOT LIKE` before exact CHECK comparison. Quoted string segments are excluded from this rewrite, and predicate columns, literals, operators, length, NULL semantics, constraint identity, and ownership remain exact. This is not a general SQL parser or permission to weaken catalog validation.

### 2026-09-08 DB-API-neutral catalog row comparison

- Canonical catalog validation normalizes each sequence-like DB-API result row into a plain Python tuple before exact expected-evidence comparison. This changes only container semantics: cardinality, scalar values, ordering, ownership, names, kinds, columns, referenced objects, and ordinals remain exact, with no driver-specific row-type dependency.

### 2026-09-08 Requirement SQL configuration alignment

- Keep the operational registries separate but share one neutral SQL Server ODBC driver resolver. Requirement direct inner keys are canonical; explicitly configured legacy `*_env` sources remain authoritative and fail closed when absent.

### 2026-09-07 Acceptance-driven persistence correction

- Only SQL Server duplicate-key errors (`SQLSTATE 23000` with native `2601` or `2627`) may enter immutable submission winner reconciliation. Arbitrary insert/database failures propagate and roll back the Prepare transaction.
- `ExecutionManifest` is an explicit `ScheduleStore` dependency because durable submission replay and ACK reconstruct the stored neutral contract.
- These are minimal implementation corrections; Design v1 and Plan v1.1 remain valid.

### 2026-09-07 Phase 1C-B bridge decisions

- Preserve PR #213 neutral contracts and implement lifecycle authority in `ScheduleStore` transactions without adding a shadow Task/Attempt store.
- Bind the server-owned root once in Prepare, keep remote/filesystem effects out of SQL, and expose only neutral Requirement Schedule management evidence.

### 2026-09-05 Phase 1C-A schema/audit decisions

- Canonical schema v2 (later evolved explicitly to v3 for Gate B) uses complete source-faithful catalog classification, explicit migrations, same-schedule composite integrity, and a transactional SQL outbox.
- Marker rows and DB-API rows are interpreted by cardinality/indexed scalar evidence without pyodbc-specific branches; SQL Server-owned expression formatting is narrowly normalized.

### 2026-09-04 Scheduling control-plane decisions

- Use immutable monotonic schedule versions, structured recurrence, `coalesce_latest`, pause semantics, RequirementVersion-number checkpoint chronology, and schedule-scoped manual trigger identity.
- Materialized runs bind exact approved schedule versions and active Requirement snapshots. Schedule changes affect future recurrence, not already materialized work.

### 2026-09-04 Phase 1A boundary

- Use deterministic task idempotency, the existing Report Job HTTP API, and confined atomic DOCX publication. Do not add recurrence, queues, server UI, or server-internal imports to Phase 1A.

### 2026-09-03 and earlier security/data decisions

- Direct principals and signed browser capabilities share one resolver; a supplied invalid Authorization header is authoritative. Signing-secret startup failures fail closed without revealing secret values.
- User-requested time scope is authoritative over background event dates. Retrieval/reference text and structured output contracts remain explicit and auditable.

## Archived History

- `.codex/archive/decisions.md-20260907-120000.md` — complete pre-compaction decision history through PR #214.
- `.codex/archive/decisions.md-20260813-000000.md` — earlier decision history retained for traceability.

## 2026-09-10 Validate rewritten SRA titles without weakening fail-closed takeover

- PR #230 assumed original uvicorn argv remained in `/proc/<pid>/cmdline`. The API import-time `setproctitle` call intentionally replaces that argv, so the launcher now recognizes the exact source-derived title (including same-namespace `os.getpid()` and `socket.gethostname()`) rather than a generic `SRA-API` substring.
- Listener PID, cwd, effective UID, configured port, exact title fields, and process start time are independent required evidence. A launcher-owned atomic identity record adds durable PID/start-time/port evidence for newly launched API children but cannot authorize signaling without current listener and `/proc` validation.

## 2026-09-10 Deployment bootstrap and orphan recovery

- Keep the Bash supervisor and generic environment loader narrowly scoped; use an in-process Python bootstrap rather than CLI/HTTP key capture or `.env.local` generation.
- Missing raw canonical credentials, corrupt/mismatched state, ambiguous recovery identity, and unverified live worker records fail closed. Rotation is exceptional, retains the canonical principal name, and never prints the raw key.
- Generated state is data, never shell code. Import only the fixed Handoff whitelist and require exact owner/mode/version evidence.

## 2026-09-10 Deployment bootstrap review correction

- Treat the Python bootstrap result as the sole effective state-path authority because it runs after project dotenv loading; expose only a fixed machine-readable path record, never raw generated values.
- Factor SQL registry validation from connection opening and reuse the same connection-string semantics during preflight. Also reuse signed-resource startup validation before destructive takeover.
- Keep ordinary startup strictly non-destructive on canonical-key ambiguity. Exceptional repair creates the replacement first, atomically replaces protected raw state, then revokes the old key; pre-replace failure attempts replacement rollback, while a recognizable post-replace interruption is completed only by a later explicit repair.

## 2026-09-10 Repair identity and commit-boundary decision

- Do not use `_write_state()` return as the credential commit boundary because `os.replace()` precedes directory fsync. Re-read the protected state after errors and retain both keys whenever the visible version cannot be proven old.
- Persist an owner-only old/new ID journal before state replacement. Only that journal authorizes interrupted-repair old-key revocation; creator and scope similarity alone are insufficient evidence.
- Permit state-absent repair only for one exact-scope canonical orphan owned by first-run `deployment-bootstrap`, using create-new → journal → persist-state → revoke-orphan ordering.

## 2026-09-10 Journal before replacement creation

- Preselect a cryptographically random Service Key ID and allow `ServiceKeyStore.create` to accept that validated, collision-checked ID. Persist journal v2 before creation so a store commit followed by a lost response never produces an unattributable second key.
- Encode transaction origin explicitly rather than inferring it from `created_by`. Only `first_run_orphan_recovery` with `old_state_present=false` permits journal recovery while state is absent; ordinary rotation continues to fail closed on missing state.

## 2026-09-10 Serialize deployment credential transactions above the key store

- Retain ServiceKeyStore's per-operation lock for generic callers, and add a distinct deployment-state transaction lock around complete bootstrap/repair operations. The outer lock is required because journal, state, and multiple key-store operations form one recovery transaction.
- Treat ServiceKeyStore parent-directory fsync as part of successful mutation, not optional hardening. Repair may durably delete its journal only after old-key revocation returns from that complete durability boundary.

## 2026-09-10 Restart through verified supervisor ownership

- Preserve supervisor ownership: restart sends SIGTERM only to a fully verified launcher and does not introduce a second child-kill path. Launcher timeout fails closed; existing verified child cleanup and orphan recovery policies remain unchanged.
- Keep runtime flock evidence non-truncating and place durable launcher identity in a separate atomic owner-mode-0600 record. Serialize simultaneous takeover attempts with a second flock and reject targeting a launcher newer than the contender.
- Convert Handoff SIGTERM/SIGINT into its existing stop-event contract rather than changing SQL lease, TTL, fencing, or ownership semantics.

## 2026-09-15 Externally anchored SD-1 package identity

- Use a deterministic Git-anchored manifest plus an out-of-band SHA-256 retained in the release record. A host-created commit marker cannot bind deployed bytes, and a manifest stored only beside those bytes is self-attestation; historical local `.git` is therefore never package authority.
- Include the verifier as a hashed `release_tool` entry and require the runbook's standard-library bootstrap to authenticate the manifest and verifier before project code runs. Package verification is read-only and fail closed.
- Asymmetric signing is deferred rather than prohibited. v1 addresses the present deployment gap with an independently retained digest and reviewed release environment without adding dependencies or changing SRA runtime behavior.

## 2026-09-15 Dual-baseline SD-1 authority decision

- Candidate source policy is never comparison authority. Exact policy Git blob and mode must equal `reviewed_manifest_commit`; runtime equality continues to use fixed baseline `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`.
- Release tools require their own reviewed baseline and the authoritative CLI additionally compares its running builder bytes to the source Git blob. This is source integrity inside the trusted release environment, not a defense against total release-host compromise.
- No managed-root extra is benign: `__pycache__` and bytecode are rejected rather than deleted. Every path component is opened no-follow, and Git executable intent is verified without requiring exact POSIX permission values.

## 2026-09-15 Separate cleanup ownership from durable E2E identities

- Schedule cleanup state must not double as Batch lookup identity. Continue disabling the Schedule immediately after recurrence advancement is proven, clear cleanup ownership, and use the Schedule identity persisted on the observed Batch for all terminal polling.
- Import ambiguous-write recovery defines “new” against every durable pre-commit Snapshot ID in the exact Source/Requirement Set context, not only previously active Snapshot IDs; historical same-content imports therefore cannot win recovery.
- After configuration succeeds, resolved `config.output_dir` is invocation authority. CLI `--output-dir` retains explicit precedence, and a separate fallback exists only to preserve evidence when configuration cannot be built.

## 2026-09-16 Harness v2 shared orchestration and remote trust boundary

- Keep one functional Harness and isolate only deployment evidence behind local/remote providers; duplicated state-machine implementations were rejected.
- Remote acceptance trusts deployment-generated Git/worker/root-fingerprint evidence plus independently downloaded artifact bytes. Operator and deployment sources must both bind to the externally reviewed runtime SHA.
- Reuse Report Job download authorization and add only a bounded superuser read-only evidence route; no new artifact store, Service Key scope, DB schema, or worker-control surface.

## 2026-09-16 Durable Handoff publication is remote artifact authority

- Supersede the earlier choice to reuse Report Job `/word` for remote acceptance: that upstream copy cannot prove the separate Handoff publication still exists and matches durable reconciliation state.
- Use immutable Batch/Run Item identity to read existing durable metadata server-side, validate it under the configured Handoff root, and return only verified bytes. Reject client filesystem authority and keep the route GET-only/superuser-only rather than widening Service Key scopes.
- Retain independent operator-side DOCX and SHA verification so Remote PASS proves both authoritative server publication and receipt of identical bytes.

## 2026-09-16 Active runtime evidence over directory cleanliness

- Accept reviewed-equivalent documentation descendants and non-runtime/generated dirt; fail closed for runtime-relevant committed or dirty paths.
- For robocopy overlays, compare every provenance-managed runtime byte to externally reconstructed reviewed Git bytes and reject active unexpected/shadow modules. Do not require deleted-file history or reject inactive residue solely for existing.

## 2026-09-16 Explicit shared root-file runtime provenance

- Use one importable policy (`shared.runtime_provenance`) rather than duplicated generator/operator/deployment selectors. This prevents reviewed-map reconstruction from drifting from package generation or deployment path validation.
- Include only root files with demonstrated runtime effect: `python_compat.py`, `telemetry.py`, `app.py`, `run_sra_api.sh`, and `requirements.txt`. Do not blanket-select repository-root content; notably, the empty root `__init__.py` and README/TODO documentation are excluded.
- Hash the launcher as an authoritative runtime input without pretending it is a loaded Python module. Keep `unexpected_active_runtime_module` fail-closed: an active root module must both belong to the explicit policy/provenance and match externally reviewed bytes.

## 2026-09-16 Namespace-authoritative module provenance and byte-exact packaging

- Determine loaded project code from Python import identity, not coincidental filesystem tokens: exact managed package top-level namespaces plus exact module names derived only from explicit root `.py` files are authoritative.
- Preserve fail-closed shadow detection after namespace qualification. Do not classify `thirdparty.api.*` or `vendor.telemetry` as project code, regardless of path segments or basenames.
- Keep deployment verification byte-exact. Prevent predictable Windows robocopy failures at package creation by comparing working-tree bytes to reviewed Git blobs and refusing manifest emission on any difference; do not normalize line endings or rewrite checkout content.

## 2026-09-18 Separate reviewed source equivalence from package identity

- Accept only exact Git-blob bytes or, for an explicit text-extension allowlist, candidate bytes equal to replacement of every reviewed LF with CRLF when the reviewed blob contains no CR. Do not decode or normalize whitespace, BOM, Unicode, final newlines, shell scripts, Office files, images, archives, or unknown formats.
- Record SHA-256 of actual package bytes in schema v2. Deployment never normalizes. Canonical validated provenance JSON, not reviewed Git SHA alone, is the cross-host release identity.
- Keep `SRA_E2E_EXPECTED_RUNTIME_SHA` only as a deprecated additional assertion; provenance is primary and disagreement fails closed.

## 2026-09-18 Bounded discovered-input provenance authority

- Enforce `actually discovered/selected release-managed runtime inputs ⊆ schema-v2 provenance`, not filesystem equality under runtime roots.
- Use one side-effect-free policy in `shared.runtime_provenance` for runtime loaders, generation, Linux evidence, and offline operator verification. Closed-directory discovery exactly follows direct-child, case-insensitive `.json` synonym membership; selector resolution preserves index precedence and covers the Requirement SQL registry and Editor form config.
- Existing selected paths outside the project root have no implicit authority and fail as `unexpected_runtime_input`. Dotenv, secrets, auth/session stores, SQLite, generated outputs, import sources, and operator-managed task configuration remain separate mutable/deployment authority.
- Preserve incremental deployments: unrelated and ignored residue remains accepted; inactive Python remains a bounded warning, while imported project modules absent from provenance remain blocked by the existing active-module rule.

## 2026-09-22 Freeze explicit E2E external backend policy

- Keep ordinary production backend behavior unchanged unless the explicit Requirement E2E external-mode variable is present. Resolve both dependencies before workbook mutation and never change the plan after a runtime failure.
- Reuse the existing ES client seam and separate the Requirement semantic fixture index from the generic Vercel preview fixture. Mock only external model/search boundaries; keep production query, evidence, Agent, Schedule, Handoff, Report Job, DOCX, reconciliation, and terminal-state paths real.

## 2026-09-23 External capability corrective decisions

- Never configure an already-running deployment by mutating the operator harness environment. Freeze capability state in the ReportJobWorker-owning process and expose only safe authenticated evidence.
- Keep full live mapping authority in `indices.get_mapping()`, the czjLLM subtree contract separate, and validate only retrieval-required live fields/multifields plus the configured reference-text path.
- A semantic mock must reject unsupported DSL and discriminate business topics; returning every fixture is not an acceptable fallback.

## 2026-09-23 Deterministic LLM contracts fail closed

- Treat deterministic E2E output as a faithful external-boundary contract, not input for downstream repair. Raw structured responses must independently satisfy each production prompt.
- Explicitly model every current SRA_REPORT direct-LLM stage and raise `unsupported_e2e_llm_contract` for unknown prompts. Keep ordinary `LLMClient` behavior unchanged and retain an isolated test-only singleton reset.

## 2026-09-23 Separate functional verification from release attestation

- Preserve `release` as the backward-compatible strict default. Functional verification is not a provenance bypass: it attempts full verification and makes only `active_runtime_source_mismatch` advisory.
- Keep discovery and active-module security fences independent from byte hashing so a stale hash cannot conceal an unexpected selected input or module shadow. Functional success always reports deployment acceptance as not established.

## 2026-09-23 Port only PR #270 semantic-input contract

- Preserve PR #271 capability, verification, worker, and artifact architecture. Reconcile only the real workbook bytes, production import-profile selection, exact Snapshot prompt guard, v2 fixture identity, and semantic regression coverage.
- Never log full Requirement content. Compare in memory and expose only `prompt_content_mismatch` at `REQUIREMENT_ITEMS` when durable content differs.

## 2026-09-30 Keep E2E mock authority job-scoped across tool threads

- Do not use a process-global or thread-global fallback flag to make semantic mocks visible to `smolagents` worker threads; concurrent production jobs must never be able to observe E2E mock authority.
- Carry only a boolean verified-E2E execution marker on the per-Agent ES Tool instances created inside the Report Job's acceptance scope. Each decorated `Tool.forward()` re-opens the ContextVar scope inside whatever worker thread actually executes it.
- Normal canonical Handoff provenance alone is not test provenance. Only the reserved E2E marker plus persisted canonical Handoff provenance activates the verified E2E job scope; ordinary scheduled production jobs remain real-only.
## 2026-10-01 Treat E2E external-mode CLI as an optional assertion

- Deployment runtime evidence is authoritative for the already-running E2E external capability mode. Do not impose a separate CLI default that can disagree with a correctly configured deployment.
- Omitting `--external-mode` means “use the authenticated deployed mode”; explicitly supplying the option means “assert that the deployment is in this mode.” Explicit disagreement remains fail closed.
- This is an operator UX change only. It does not let the harness reconfigure API/workers and does not alter production Report Job dependency selection or E2E mock isolation.

## 2026-10-01 Integrate Requirement automation into the existing SRA operations console

- Treat Requirement automation as another module of the existing SRA management product, not a standalone administration site. Reuse current navigation, Auth/RBAC, audit, and visual shell.
- Place the planned Requirement Task Center under the existing 匯入管理 domain alongside Excel→SQL tooling, while preserving ES 資料庫 and 系統/帳號管理 as existing peer domains.
- Build a stable Product API façade for external automation and UI use, but keep Phase 1B Requirement Import and Phase 1C Schedule/Handoff as the underlying authorities. Do not duplicate their persistence or execution engines.
- Keep Product E2E distinct from Operator acceptance E2E: the former proves an external client/user workflow from runtime-supplied input; the latter remains deployment/technical acceptance.

## 2026-10-01 Persist Product Task kind and idempotency in Schedule schema v4

- Product Task identity is distinct from Schedule identity. Persist `execution_kind=once|recurring` and task/source/schedule binding in `requirement_product_tasks`; never infer one-time versus disabled-recurring from Schedule `enabled`.
- Persist Product mutation idempotency in `requirement_product_requests` using principal + operation + key + canonical request hash and safe durable progress/result references. Treat multi-authority Product mutations as a resumable saga, not as blind retries.
- Preserve existing Phase 1B activation RBAC: only superuser may provision/activate a new Product Task/source in v1. Service-key automation requires a pre-provisioned active task.

## 2026-10-01 Product saga ordering and delegated automation identity

- Create Schedule before inserting `requirement_product_tasks`; persist safe saga references after each successful cross-authority step so non-null FKs are always satisfied and replay can resume.
- For Product request idempotency, human principals use canonical account identity; service principals use immutable `credential_id/key_id`. Never use the service-key display name/subject as an idempotency namespace.
- Treat all Product Task PATCH mutations as durable `task_update` operations requiring `Idempotency-Key`, including schedule-changing updates that create immutable Schedule Versions.
- Formal Product automation acceptance is split: superuser provisioning first, then least-privilege service-key operations on the active pre-provisioned task. Service keys do not provision/activate sources/tasks in v1.

## 2026-10-01 Preallocate cross-authority Product saga IDs before commit

- For Product operations spanning Requirement and Schedule authorities, durable identity must be known before an authority can commit. Preallocate/persist import_run_id + snapshot_id before Requirement commit and schedule_version_id before Schedule version creation.
- Extend existing authorities backward-compatibly with optional caller-supplied IDs and same-ID/same-semantics replay. Omitted IDs preserve existing low-level behavior.
- Product request reserved identity columns are non-FK by design so reservation precedes target creation; Product resume checks exact ownership/config semantics and fails closed on mismatch.
- Reuse the existing manual trigger_request_id uniqueness for Run materialization instead of introducing Product batch_run_id injection.

## 2026-10-02 Use Task revision CAS and atomic ledger finalization for mutable PATCH

- Add monotonic `revision` to `requirement_product_tasks`; reserve `base_task_revision` for every `task_update` request.
- Finalize Product Task rename/state/schedule activation and Product request success in one Schedule SQL transaction. Persist bounded `safe_result_json` and result revision for exact replay.
- A stale unfinished request whose base revision no longer matches fails closed with `requirement_task_conflict` and does not reapply old state. This prevents old idempotency-key retries from overwriting newer successful updates.

## 2026-10-02 Make Product-owned low-level Schedule/source surfaces read-only

- Once linked by requirement_product_tasks, a Schedule cannot be mutated through retained low-level HTTP PATCH/version/approve/manual-run endpoints; return 409 requirement_product_owned_schedule. A task-owned Requirement source cannot be PATCHed/imported through low-level HTTP; return 409 requirement_product_owned_source.
- Reads remain available and non-Product low-level mutation semantics remain unchanged.
- Enforce ownership at the public router/service boundary so internal Product orchestration can still use the underlying reviewed stores. This keeps Product Task revision/CAS authoritative across API surfaces.

## 2026-10-02 Make ownership fencing transactional and input replacement snapshot-CAS

- Treat task_create request-ledger source_id/schedule_id reservations as Product ownership claims before requirement_product_tasks exists. Low-level mutation authority must check those claims and steady-state Product ownership in the same DB transaction as each write; router pre-checks are insufficient.
- Add base_snapshot_id to input_replace request state. Requirement commit checks expected_base_snapshot_id under the locked requirement_sets row only when the preallocated import/snapshot identity does not already exist. A stale uncommitted replacement fails requirement_input_conflict rather than rolling active input backward.

## 2026-10-02 Same-ID committed import recovery precedes _prepare

- Product-layer request_sha256 proves semantic replay identity; server-owned import_run_id/snapshot_id prove persisted authority identity/linkage.
- RequirementImportService.commit performs persisted-result recovery before any fresh source acquisition or classification. Only absent persisted identity may enter _prepare and then base_snapshot_id CAS/commit.
- Required race test order: A commits S1, B commits S2, A delayed retry returns A/S1 result with no stale diagnostics/failed import and leaves S2 active.

## 2026-10-02 Separate committed-import recovery from preparation

- Use a narrow read-only store recovery helper at RequirementImportService.commit entry. Do not place same-ID replay detection only inside commit_candidate because _prepare may already classify an older replay as stale after a newer replacement.

## 2026-10-02 Hide and lock Product Tasks while provisioning

- Add provisioning to Product Task lifecycle. Partial task rows are durable recovery anchors but are not user-operable resources.
- All normal Product read/mutation/service-key surfaces gate provisioning before request reservation; only the original task_create request can resume.
- Final visibility is atomic with create success: verify required Schedule/version/run evidence, transition provisioning→active, persist create result, and mark task_create succeeded in one Schedule transaction.

