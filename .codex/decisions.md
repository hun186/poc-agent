# Architecture and Engineering Decisions

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
