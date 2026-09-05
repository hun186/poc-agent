# Job Task Orchestration Boundary — Design Specification v1

**Repository:** `hun186/poc-agent`  
**Authoritative source branch inspected:** `main`  
**Inspected hosted baseline:** `249038dea5c7932d39c6220c000fccc3955e9df2` (PR #209 merge)  
**Design status:** Formal architecture specification; implementation NOT STARTED  
**Phase status:** Phase 1C-A repository gate PASS; Phase 1C-B NOT STARTED  
**Supersedes as architecture authority:** `docs/superpowers/notes/2026-09-05-job-task-orchestration-boundary-discussion-notes.md`  
**Does not supersede:** Phase 1C-A Design v5 / Plan v5 / Prompt A history or its canonical schema-v2 acceptance evidence

> This specification formalizes the human-approved Job Task Orchestration Boundary decisions after reconciling them with actual source at the baseline above. Source wins stale documentation. It does not authorize implementation. The existing Phase 1C-B execution prompt is stale and MUST NOT be executed; a new Gate-B Plan and Codex execution contract must be written only after this Design v1 is reviewed and approved.

## 1. Problem statement

The repository already has multiple execution-related surfaces, but they are not one execution authority:

- the persisted Report Job API owns legacy asynchronous report execution;
- the standalone Batch Scheduler owns its own batch/task controller state and calls Report Job over HTTP;
- Phase 1C-A Requirement Scheduler owns recurrence, versioned schedule policy, immutable materialization, selection checkpoints, and SQL audit authority, but deliberately stops at `handoff_pending`;
- the Agent implementation contains smolagents-specific code below the public API boundary;
- no LangGraph production integration, Task/Attempt execution platform, workflow registry, engine-neutral adapter layer, or general execution-event store currently exists.

The architecture must finish the current Requirement → schedule → batch → report capability without coupling the Requirement Scheduler or future Job Task API to smolagents, while preserving a clean path to introduce LangGraph one workflow version at a time later.

The selected strategy is progressive migration through an explicit engine-neutral boundary, not a mid-project rewrite.

## 2. Source reconciliation at baseline `249038d`

### 2.1 Runtime package and legacy Report Job

Runtime API code lives in `sra_api/`; top-level `api/` is the compatibility namespace. The current Report Job surface exposes create/status/DOCX resources. `ReportJobStore` is SQLite single-machine persistence with owner-scoped idempotency and states `queued`, `running`, `completed`, `failed`, and `interrupted`. `ReportJobWorker` is a daemon thread started by FastAPI lifespan, claims queued jobs, calls `execute_agent_turn()`, builds DOCX, writes a temp file, validates it, atomically renames it, then records completion. Startup converts stale `running` jobs to `interrupted`.

Consequences:

- current Report Job is a legacy execution authority, not the future Job Task Worker;
- `interrupted` is ambiguous execution truth and cannot be treated as ordinary failure/retry authorization;
- Report Job has no authoritative cancel API;
- current SQLite/local-artifact worker must not be renamed or represented as the target Task/Attempt architecture.

### 2.2 Existing turn execution is not a pure framework-neutral port

`sra_api/services/turn_execution.py` directly calls `agent.agent.answer_with_routing()`. It reads mutable session history, memory, prior structured output, citation/reuse state, and saves structured snapshots as a compatibility side effect.

Consequences:

- an originating conversational session is not a reproducible job execution contract;
- scheduled execution must use an isolated deterministic legacy session namespace;
- a future Legacy SRA Adapter may wrap this seam initially, but the formal Job Task contract cannot expose mutable chat-session semantics as execution authority.

### 2.3 Standalone Batch Scheduler is a sibling control plane

`batch_scheduler/` is a standalone SQLite-backed controller. It calls `/v1/report/jobs`, polls remote status, downloads DOCX, and publishes artifacts under its own output root. It already contains useful transport and safe publication code, but its service/store together form a complete batch controller.

The current Batch Scheduler also expects remote `pending|running` while the Report Job store actually emits `queued|running`, demonstrating why backend-native state strings must be hidden behind an anti-corruption layer.

Consequences:

- Phase 1C-B MUST NOT nest `BatchSchedulerService` or its SQLite state beneath Requirement Scheduler, because that would create Requirement Run → Batch Scheduler Task → Report Job as three competing lifecycle authorities;
- Phase 1C-B may reuse or refactor narrow transport/output helpers when source-compatible, but standalone Phase 1A behavior must remain intact;
- the prior Gate-B assumption that Requirement Scheduler must delegate execution authority to Phase 1A is superseded where it conflicts with this source-reconciled boundary.

### 2.4 Requirement Scheduler Gate A is already the correct control-plane boundary

`requirement_scheduler/` uses SQL Server authority. Materialization binds exact `schedule_version_id`, `snapshot_id`, `requirement_version_id`, monotonic `requirement_version_number`, external Phase 1A identities, selection reasons, expiry evidence, and checkpoint history. Selected items stop at `execution_state='handoff_pending'`. Gate-B evidence columns already exist for remote job state, handoff/dispatched/completed timestamps, artifact reference, counters, and output-root fingerprint.

Canonical schema version 2 is exact-validated: unexpected tables, columns, keys, indexes, or foreign keys fail closed.

Consequences:

- Gate A remains unchanged and Design v5 stays authoritative for canonical v2;
- Phase 1C-B may not silently add persistent objects while leaving `schema_version=2`;
- the approved durable handoff identity/fingerprint and coordinator lease requirements require an explicit subsequent schema evolution if they need new persistent structures. This Design authorizes Gate-B to introduce canonical schema v3 as a forward migration from accepted v2; exact DDL, descriptors, rollback, and tests belong in the new Gate-B Plan. Historical Design v5 is not edited.

### 2.5 smolagents is an internal Agent implementation detail

`agent/data_agent/builder.py` imports and constructs smolagents `CodeAgent`, `LiteLLMModel`, and tools directly. No LangGraph integration exists in the current source.

Consequences:

- Job Task API, Requirement Scheduler, and Phase 1C-B MUST NOT import smolagents or LangGraph;
- the earliest safe legacy adapter wraps established SRA workflow behavior above the smolagents implementation rather than exposing framework objects.

## 3. Selected migration architecture

Rejected approaches:

1. **Job Task API directly calls smolagents and is replaced later.** Rejected because it makes framework details part of the public/control contract.
2. **Immediate independent LangGraph microservice.** Rejected because it duplicates execution authority before the current scheduled-report path is complete.
3. **Transitional fake Task/Attempt layer that merely wraps legacy Report Job.** Rejected because it would create a second lifecycle database without actually owning execution.

Selected approach:

```text
Client / OpenWebUI / Requirement Scheduler
                    |
                    v
              Job Task API                 (future JT-1)
                    |
                    v
              Task / Attempt DB
                    |
             DB-backed claim
                    v
             Execution Worker
                    |
                    v
          Static Workflow Registry
                    |
                    v
           Orchestration Port
              /           \
             v             v
    Legacy SRA Adapter   LangGraph Adapter
             |             |
             v             v
       Existing SRA      Graph workflows
```

Phase 1C-B intentionally stops earlier:

```text
Requirement Scheduler
        |
        v
Requirement Handoff Coordinator
        |
        v
Execution Submission Boundary
        |
        v
Legacy ReportJob Gateway
        |
        v
existing /v1/report/jobs
        |
        v
existing ReportJobWorker
        |
        v
Existing SRA / smolagents internals
```

When JT-1 later becomes authoritative, Requirement Scheduler replaces only the gateway target:

```text
Legacy ReportJob Gateway  ->  Job Task Gateway
```

The Requirement materialization and handoff semantics remain stable.

## 4. Migration gates and scope freeze

### Gate OB-1 — this Design v1

Defines target Job Task architecture and the Phase 1C-B compatibility contract. Documentation only.

### Gate 1C-B — Requirement execution compatibility bridge

Implements only:

- external Requirement Handoff Coordinator;
- framework-neutral execution submission boundary;
- Legacy ReportJob Gateway;
- durable submission identity/fingerprint;
- one-active coordinator ownership with fencing;
- second expiry check;
- status translation/reconciliation;
- safe artifact publication/reconciliation;
- monotonic checkpoint closure;
- transactional Gate-B audit evidence;
- service-principal ownership and safe error handling.

It MUST NOT implement:

- Task or Attempt tables;
- general-purpose execution queue;
- general multi-worker Attempt claiming;
- Execution Event Store;
- LangGraph adapter or checkpoint database;
- production Workflow Registry / Capability Profile / Runtime Profile infrastructure;
- smolagents refactor;
- replacement of ReportJobWorker or ReportJobStore;
- automatic failed-execution retry;
- a new cancellation engine;
- a FastAPI scheduling thread.

### Gate JT-1 — real Job Task execution authority

After Phase 1C-B PASS, introduce Task/Attempt persistence, independent Execution Worker, static Workflow Registry, profiles, engine-neutral Orchestration Port, Legacy SRA Adapter, event stream, and neutral result/error contracts.

### Gate JT-2+ — gradual LangGraph adoption

Only after JT-1 is authoritative, introduce LangGraph per new versioned workflow. No big-bang migration.

## 5. Framework-neutral workflow authority

1. smolagents and LangGraph coexist during migration.
2. Job Task API and Requirement Scheduler are framework-neutral.
3. A future Orchestration Port separates control plane from engines.
4. Workflow identities are explicit and versioned, e.g. `report_v1`, `report_v2`.
5. One workflow version maps to exactly one backend.
6. Callers cannot choose a backend.
7. There is no automatic cross-backend fallback.
8. Workflow Registry v1 is repo-managed static configuration, not DB-editable rebinding.
9. Workflow aliases are out of scope for v1; persisted work uses explicit resolved workflow IDs.
10. Adapters normalize results into framework-neutral `ExecutionResult`.

Material semantic or security changes require a new workflow/contract version rather than silently changing an existing workflow identity.

Illustrative future mapping only:

```text
report_v1        -> Legacy SRA Adapter -> existing SRA/smolagents
rewrite_v1       -> Legacy SRA Adapter
report_v2        -> LangGraph Adapter -> LangGraph
research_v1      -> LangGraph Adapter
```

## 6. Future Job Task / Attempt authority

The formal future contract is asynchronous.

### 6.1 Task

A Task is one immutable semantic request. It owns:

- stable Task identity;
- workflow ID and typed contract version;
- immutable input snapshot;
- immutable explicitly captured workflow context;
- Task-creation idempotency key/fingerprint;
- selected successful result reference, if any.

Mutable conversational memory is not Task authority. An originating session may be retained only for correlation.

### 6.2 Attempt

Task and Attempt are distinct identities. Every execution try creates an Attempt; terminal Attempts are immutable. A new retry creates a new Attempt. LangGraph checkpoint/resume within the same backend remains within the same Attempt.

Each Attempt snapshots resolved workflow/backend/runtime information needed for reproducibility and owns an immutable execution-start token distinct from Task-creation idempotency.

Reconciliation of one existing Attempt reuses that Attempt token. A new Attempt gets a new token. Task idempotency keys MUST NOT be reused as backend execution identity across Attempts.

### 6.3 Worker ownership

API Service and Execution Worker are separate processes. Initial worker claim semantics are DB-backed; Kafka/Redis are not introduced without demonstrated need. One Attempt has one active lease plus heartbeat. Lease expiry is ownership loss only; it is not execution failure and does not authorize retry. Reconciliation precedes retry decisions.

### 6.4 Canonical execution states

Backends translate native states into a framework-neutral model. The design vocabulary is:

```text
pending
claimed
starting
running
cancel_requested
reconciling
recovery_required
completed
failed
cancelled
```

`recovery_required` is a fail-closed halted state requiring authoritative reconciliation/intervention; it is neither success nor automatic retry authorization.

Unknown backend states never map by guesswork to success, failure, pending, or retry.

## 7. Execution result, error, events, artifacts, and side effects

### 7.1 ExecutionResult

Conceptual neutral result:

```text
status
output
artifact_refs
citations
error_code
error_message
runtime_metadata
```

Backend-private traces remain backend diagnostics and do not become the public contract.

### 7.2 Error Contract

Conceptual neutral error:

```text
ExecutionError(
  error_code,
  category,
  retryability,
  safe_message,
  occurred_stage,
  diagnostics_ref
)
```

Retryability is descriptive evidence only. Control-plane policy separately authorizes transport retry, reconciliation, a new Attempt, or a new business run.

### 7.3 Execution Event Store vs security/domain audit

Future Attempts emit an append-only framework-neutral Execution Event stream. It is separate from the security/domain Audit Outbox. Heartbeats and backend node traces do not become security audit noise.

Each subsystem records only facts it authoritatively owns. Stable safe correlation IDs connect schedule → run → run item → submission → Task → Attempt → opaque external execution → artifact. No cross-system total ordering is assumed.

### 7.4 Artifacts and side effects

Artifacts are Attempt-scoped and immutable after finalization. Backends may produce staging artifacts but cannot directly overwrite Task-level official results. Task result selection is a separate controlled operation, e.g. `selected_result_attempt_id`.

Side-effecting operations must be idempotent, reconcilable, or explicitly ineligible for automatic retry. Backend success does not justify replaying uncontrolled external side effects.

## 8. Workflow Registry, capabilities, runtime, and secrets

Every workflow version has:

- a fixed repo-managed backend mapping;
- a server-side Capability Profile;
- a repo-managed Runtime Profile;
- typed/versioned input and output contracts.

Clients cannot request arbitrary backend/framework selection, tools, model authority, checkpoint settings, GraphState, smolagents kwargs, or runtime privileges.

Backend technical capability, workflow authorization, and caller authorization are separate gates.

Secrets are resolved by the Worker at runtime through a controlled credential provider. Secret values never enter Task input, Attempt snapshots, semantic fingerprints, events, audit payloads, artifacts, or neutral results.

The Job database does not mirror LangGraph graph/checkpoint state. A Job Task may keep an opaque `external_execution_id`, but neither control plane nor caller parses backend semantics from it. Same-backend resume/reconcile is allowed; silent backend switching is forbidden.

## 9. Phase 1C-B execution handoff contract

### 9.1 Handoff identity and immutable manifest

Every selected Run Item produces at most one logical Phase 1C-B submission identity. Before any remote call, the Coordinator resolves only exact materialized/versioned source identities and approved server-side policy into a canonical semantic handoff manifest.

Conceptual content:

```text
ExecutionHandoff
  submission_id
  workflow_id = report_v1
  source_identity:
    schedule_id
    schedule_version_id
    batch_run_id
    run_item_id
    snapshot_id
    requirement_id
    requirement_version_id
    requirement_version_number
  execution_input:
    resolved_prompt
    resolved_model
    output_contract
    logical_filename
  execution_policy:
    deadline_at
    isolated_execution_context
  semantic_fingerprint
```

The exact encoding is a Plan concern, but semantic input and operational metadata are separate domains. Worker ID, lease expiry, HTTP retry count, polling timestamps, and trace IDs do not enter the semantic fingerprint.

An already-materialized execution MUST NOT re-resolve mutable “latest” Requirement, Schedule, model, conversational memory, or backend configuration.

### 9.2 Canonical schema-v3 Gate-B evolution

Current schema v2 has no durable per-item submission fingerprint record and no durable coordinator lease/fencing record, while v2 exact validation rejects extra objects. Therefore Gate 1C-B SHALL introduce an explicit canonical schema-v3 migration before adding such state; it MUST NOT alter v2 objects while leaving marker 2.

At design level, v3 needs two new durable concepts:

- **Handoff Submission record:** one-to-one with a selected Run Item; stores stable submission identity, workflow identity, semantic fingerprint, isolated legacy execution context identity, creation timestamps, and only other minimal crash-recovery evidence not already owned by the Run/Run Item tables.
- **Handoff Coordinator Lease record:** singleton/per-control-domain ownership with owner identity, opaque lease token, monotonically increasing fencing generation, heartbeat, and expiry.

Existing Run/Run Item Gate-B fields remain the authority for remote job ID/state, artifact reference, counters, terminal evidence, and checkpoints; v3 MUST NOT duplicate them into a shadow Task/Attempt model.

The future Gate-B Plan must define exact names, columns, constraints, migration from canonical v2, fresh-v3 DDL, complete catalog validation, rollback injection, and accepted predecessor rules. Design v5 remains unchanged historical authority for v2.

### 9.3 Task creation identity and submission identity domains

Phase 1C-B has no Task/Attempt system yet. Its stable `submission_id` identifies one logical compatibility handoff and maps stably to the existing Report Job `Idempotency-Key`.

Future Task-creation idempotency and Attempt execution-start tokens remain separate domains. Phase 1C-B MUST NOT create fake Task/Attempt records merely to imitate the future architecture.

### 9.4 Isolated legacy session

Because legacy `execute_agent_turn()` consumes mutable session/memory state, scheduled handoff uses a deterministic isolated legacy session namespace derived from the stable submission identity. It MUST NOT reuse an interactive OpenWebUI/conversational session as semantic execution authority.

Transport replay of the same submission reproduces the same isolated legacy session identity. A new intentional business run receives a new submission identity and therefore a separate legacy session namespace.

### 9.5 Stable remote creation and crash consistency

Cross-system handoff is at-least-once transport with idempotent remote creation and reconciliation; it MUST NOT claim distributed exactly-once execution.

Required order:

```text
SQL transaction:
  verify item eligibility and lease/fencing
  second expiry check
  persist stable submission identity + semantic fingerprint + handoff intent
  enqueue matching safe audit evidence
COMMIT

remote POST /v1/report/jobs
  authenticated as scheduler service principal
  Idempotency-Key = stable submission identity mapping
  fixed allowlisted metadata/correlation

SQL transaction:
  re-verify lease/fencing
  CAS expected handoff state
  persist remote_job_id / dispatched evidence
  enqueue matching audit evidence
COMMIT
```

No SQL transaction or lock spans remote I/O.

If POST succeeds but the local remote-job acknowledgement is lost, restart/retry uses the same submission identity, manifest, fingerprint, session identity, and backend idempotency key. A 409 idempotency conflict or semantic fingerprint drift fails closed; it is never bypassed by generating a new key.

### 9.6 One-active Handoff Coordinator

Phase 1C-B runs a separate external **Requirement Handoff Coordinator**, not a FastAPI thread and not the future Execution Worker.

One coordinator is active per scheduler/control domain. Ownership uses a durable SQL-backed lease with opaque token and monotonically increasing fencing generation. A stale owner cannot perform authoritative mutations after lease loss.

Startup order:

```text
acquire lease
reconcile unfinished handoffs
only then process new materialized work
```

Lease loss revokes submission/reconciliation authority; it does not mark remote execution failed or authorize retry.

### 9.7 Second expiry check

Immediately before persisting first handoff intent, selected items receive the required second expiry/deadline eligibility check. If the item has expired before handoff, Gate-B records `expired_before_handoff` and does not call the remote API.

This check is based on immutable run-local policy, not current Schedule enablement or a newly activated Schedule Version.

### 9.8 Legacy ReportJob Gateway state translation

Backend-native strings never become Requirement Scheduler control contracts.

Required legacy mapping:

```text
ReportJob queued       -> pending
ReportJob running      -> running
ReportJob completed    -> completed
ReportJob failed       -> failed
ReportJob interrupted  -> recovery_required
unknown/contradictory  -> reconciling -> recovery_required if unresolved
```

The Coordinator never checks framework-native state strings outside the gateway translation boundary.

### 9.9 Failure taxonomy and retry authority

Canonical safe categories include, at minimum:

```text
transport_ambiguous
remote_unavailable
authentication_failed
authorization_failed
semantic_conflict
remote_execution_failed
deadline_exceeded
artifact_invalid
artifact_publication_failed
reconciliation_unknown
persistence_failed
internal_contract_violation
```

Phase 1C-B may automatically retry only bounded transient operations while preserving the same submission/remote execution:

- ambiguous/temporarily unavailable POST transport using the same idempotency identity;
- status polling;
- artifact download.

It MUST NOT automatically create a new remote execution after terminal remote failure, semantic conflict, credential/authorization failure, artifact failure, ambiguous backend truth, or a deadline event.

### 9.10 Deadline, timeout, lease expiry, and cancellation

These are separate concepts.

- Attempt deadline is future server-owned execution policy.
- dependency/HTTP timeout is a local operation limit;
- coordinator/worker lease expiry is ownership loss;
- cancellation is explicit control intent.

Reaching a deadline does not itself prove remote failure or authorize retry. The legacy Report Job API exposes no authoritative cancellation operation, so Phase 1C-B does not claim active cancellation capability. If a deadline is reached while legacy execution may still be alive, the item enters reconciliation and, if truth cannot be proven, `recovery_required`.

A future backend may expose cooperative cancel; `cancel_requested != cancelled`, and cancellation is terminal only after authoritative reconciliation proves the backend stopped.

### 9.11 Artifact destination authority and reconciliation

Artifact destination is server-owned policy. Each Gate-B Batch Run snapshots a canonical output-root fingerprint before handoff. Every later publication/reconciliation verifies the fingerprint; configuration drift fails closed and never silently redirects an existing run.

Persistent state/API expose only validated relative artifact references, never host absolute paths. Logical filename is presentation input, not storage authority.

Publication uses deterministic confined paths, temp write, flush/fsync, format validation, atomic finalization, and no blind overwrite. A published file present after a crash but lacking SQL completion evidence is reconciled against the expected deterministic identity and content digest; an ambiguous existing file is never deleted or overwritten automatically.

Remote `completed` alone is not Requirement success.

### 9.12 Successful completion and monotonic checkpoint

Requirement success requires:

```text
remote execution authoritatively completed
artifact downloaded
artifact validated
output-root fingerprint verified
artifact publication/reconciliation proven
run item terminal success + counters + checkpoint + audit committed atomically
```

Checkpoint advancement is monotonic by immutable Requirement Version number. An older or ambiguous completion never regresses or overwrites a newer successful checkpoint. Failed, cancelled, expired, deadline-ambiguous, artifact-invalid, or `recovery_required` items do not advance success checkpoint.

### 9.13 Manual trigger and re-run semantics

Manual trigger identity remains schedule-scoped and idempotent. Repeating the same manual trigger request returns the same materialized run. An intentional new “run now” action creates a new manual run with a new trigger identity and materializes against then-authoritative approved source state.

Existing runs are immutable and are never reset to pending for re-execution. Failed/ambiguous execution does not automatically create another run. Exact historical replay is a separate future privileged operation and is out of scope for Phase 1C-B.

Manual and scheduled occurrences remain independent identities.

### 9.14 Schedule changes are prospective, not retroactive

Schedule enablement/configuration changes affect future materialization only. Once a Run is materialized, its exact Schedule Version, Requirement Version identities, workflow semantics, and immutable execution policy remain bound.

Disabling a Schedule prevents future automatic scheduled materialization but does not implicitly cancel, invalidate, rewrite, or fail an already-materialized/dispatched Run. Run cancellation is a separate explicit operation and is not implemented in Phase 1C-B v1.

### 9.15 Business actor vs execution owner

Business actor identity and remote execution ownership are separate security domains.

- manual trigger user/system scheduler identity is preserved as business/audit actor;
- all legacy Report Jobs created by Phase 1C-B are owned by a dedicated server-managed service principal derived only from authenticated principal state;
- request payload/metadata cannot impersonate or select a remote owner;
- credential rotation may change secret material/credential ID but must preserve stable logical service-principal identity so old remote jobs remain reconcilable;
- credentials are runtime-resolved and excluded from manifests/fingerprints/audit/artifacts.

### 9.16 Audit responsibility and correlation

Requirement Scheduler domain/control mutations and their audit evidence remain transactionally coupled through the SQL audit outbox. Report Job security events remain owned by the Report Job security boundary. The Coordinator records only safe facts it authoritatively knows; a remote HTTP denial is recorded as a safe remote authorization category, not forged as a backend security event.

Action-specific positive allowlists apply to Gate-B audit payloads. Do not store prompts, credentials, raw HTTP bodies, absolute paths, SQL/ODBC errors, tracebacks, arbitrary metadata, LangGraph state, or backend-private traces.

Safe correlation includes schedule, schedule version, batch run, run item, submission, workflow, and opaque remote execution identities.

## 10. Capability truth

Backend capabilities are explicit server-side contracts. They are not inferred from client payload, method existence, framework detection, or optimistic probing.

A control operation is allowed only when all required gates agree:

```text
caller authorization
AND workflow/capability policy
AND backend technical capability
```

Legacy ReportJob Gateway capabilities for Phase 1C-B:

```text
submit              supported
inspect             supported
download artifact   supported
idempotent replay   supported through ReportJob create semantics
reconcile            limited
active cancel        unsupported
resume/checkpoint    unsupported
```

Unsupported or unknown capabilities fail closed.

## 11. Future Orchestration Port

Conceptual interface only; exact signatures and async model are intentionally deferred to JT-1 Plan/source review:

```text
start(request) -> ExecutionHandle
inspect(handle) -> ExecutionStatus
request_cancel(handle)
collect_result(handle) -> ExecutionResult
reconcile(handle) -> ReconciliationResult
```

Adapters translate backend-native exceptions and states into neutral contracts. They may consume server-granted capabilities but cannot expand authority.

## 12. LangGraph migration rules

LangGraph enters only after JT-1 is authoritative.

- one existing workflow version is never silently rebound from legacy to LangGraph;
- introduce a new workflow version such as `report_v2`;
- LangGraph checkpoint/resume stays within one Attempt;
- Task/Attempt DB stores only neutral execution evidence, not GraphState/checkpoint internals;
- no automatic fallback from LangGraph to legacy backend;
- the Legacy SRA Adapter remains available for workflows not yet migrated.

This ordering intentionally lets the current scheduled-report feature finish before framework migration work begins.

## 13. Required Gate-B Plan tests and acceptance evidence

The revised Phase 1C-B Plan must use strict TDD against actual source and include, at minimum:

1. canonical schema-v2 → v3 migration, fresh-v3 initialization, exact catalog validation, marker-last semantics, and rollback at every migration boundary;
2. one-to-one durable submission intent, stable fingerprint, and deterministic isolated legacy session identity;
3. second expiry check before any remote call;
4. POST-success/local-ack-loss replay returning the same remote job;
5. idempotency conflict and semantic drift fail closed;
6. lease acquisition, heartbeat, expiry, successor takeover, and stale-owner fencing;
7. startup reconciliation before new submissions;
8. legacy state translation including `queued`, `interrupted`, and unknown values;
9. bounded same-submission transport/poll/download retries and no automatic failed-job rerun;
10. 401/403 stop-active-retry behavior and safe error output;
11. output-root fingerprint drift rejection;
12. deterministic safe relative artifact publication, invalid DOCX, pre-existing artifact crash reconciliation, digest mismatch, and no blind overwrite;
13. remote completed + artifact failure does not advance checkpoint;
14. monotonic version-number checkpoint anti-regression and atomic item/counter/checkpoint/audit closure;
15. manual trigger idempotency and intentional new-run semantics;
16. Schedule disable/version activation non-retroactivity for already-materialized runs;
17. dedicated service-principal owner isolation and credential rotation identity semantics;
18. Gate-B audit action allowlists and correlation with no secrets/prompts/raw errors/absolute paths;
19. explicit proof of no imports/dependencies on smolagents, LangGraph, Agent execution internals, ReportJobWorker internals, ReportJob SQLite, or Batch Scheduler SQLite;
20. explicit proof that no Task/Attempt/Event Store/general execution queue has been introduced.

Live SQL Server and private Report Job/Agent/DOCX acceptance remain **NOT EXECUTED** unless an explicitly authorized target/credential is supplied. Repository simulations and transport fakes are repository evidence, not deployment acceptance.

## 14. Design invariants / decision ledger #1–#62

The following numbered ledger is authoritative and preserves the approved discussion without requiring readers to reconstruct chat history.

1. smolagents + LangGraph coexist and migrate gradually.
2. Job Task API is framework-neutral.
3. Future engine-neutral Orchestration Port.
4. Versioned workflow identity.
5. One workflow version → exactly one backend.
6. Caller cannot select backend.
7. No automatic cross-backend fallback.
8. Repo-managed static Workflow Registry v1.
9. No workflow aliases v1.
10. Adapters normalize to `ExecutionResult`.
11. Job Task execution contract is asynchronous.
12. API manages Tasks; independent Worker executes.
13. Initial DB-backed claims; no Kafka/Redis without need.
14. API and Worker are separate processes.
15. Adapters are in Worker process v1; boundary need not be networked.
16. Cancellation cooperative; `cancel_requested != cancelled`.
17. Single active Attempt lease + heartbeat.
18. Lease expiry = ownership loss, not failure/retry authorization.
19. Reconcile before retry.
20. Task and Attempt identities are distinct.
21. Retry creates new Attempt; terminal Attempts immutable.
22. LangGraph resume/checkpoint stays in same Attempt.
23. Task semantic input is immutable.
24. Attempt snapshots resolved workflow/backend/runtime execution context.
25. Artifacts Attempt-scoped; Task may select a result Attempt.
26. Framework-neutral Attempt state machine.
27. Adapters translate backend-native states.
28. Append-only framework-neutral Execution Event stream.
29. Execution events and security/domain audit are separate.
30. Fixed server-side Capability Profile per workflow version.
31. Backend consumes but cannot expand granted authority.
32. Client cannot request arbitrary tools/backend privileges.
33. Repo-managed Runtime Profile per workflow.
34. Client cannot submit arbitrary model/backend/framework authority.
35. Typed/versioned workflow I/O contracts.
36. Backend-native GraphState/checkpoint/smolagents details stay out of formal API.
37. Secrets resolved by Worker runtime via controlled provider.
38. Secrets never enter snapshots/events/audit/artifacts/neutral results.
39. Adapter exceptions map to neutral safe Error Contract.
40. Retryability is descriptive only.
41. Job DB does not mirror LangGraph graph/checkpoint state.
42. `external_execution_id` is opaque.
43. Same-backend resume/reconcile allowed; silent backend switch forbidden.
44. Material semantic/security change creates new workflow/contract version.
45. Full target is defined now, but Phase 1C-B implements only framework-neutral submission + Legacy ReportJob Gateway; full Job Task authority is a later gate.
46. Task-creation idempotency and Attempt execution-start idempotency are separate domains.
47. Artifacts/side effects are Attempt-scoped; official result publication/selection is separately controlled; side effects must be idempotent, reconcilable, or non-auto-retryable.
48. Deadline, dependency timeout, and lease expiry are distinct; deadline triggers cancellation/reconciliation rather than proving failure.
49. Backend-native states are translated through an anti-corruption layer; ambiguous truth → reconciliation / `recovery_required`.
50. Conversational session state is not execution authority; job context is immutable/snapshotted; legacy scheduled execution uses isolated deterministic sessions.
51. Execution handoff is derived from exact materialized/versioned identities; same-submission replay must reproduce the same semantic fingerprint.
52. Remote handoff uses durable intent + stable idempotent replay; no distributed exactly-once claim and no new key to bypass conflict.
53. Phase 1C-B has one active external Handoff Coordinator with durable SQL lease/fencing; no DB transaction spans remote I/O; it is distinct from future Execution Worker.
54. Requirement success requires authoritative remote completion + artifact reconciliation; checkpoint advancement is monotonic and transactionally coupled to item/counter/audit success.
55. Manual trigger idempotency is schedule-scoped; intentional re-run creates a new immutable manual run; failed/ambiguous execution does not auto-rerun.
56. Artifact destination is server policy; output-root fingerprint is snapshotted/verified; only safe relative references persist; ambiguous existing output is reconciled, never blindly overwritten.
57. Business actor and remote execution owner are separate; legacy remote jobs use stable service-principal ownership with runtime-resolved credentials.
58. Control audit, execution events, and backend security audit are distinct evidence domains connected by safe correlation IDs.
59. Schedule/config changes are prospective; disabling a Schedule does not cancel or rewrite already-materialized execution.
60. Failure classification is separate from retry authority; Phase 1C-B only retries bounded transient operations within the same submission/remote execution.
61. Backend capabilities are explicit truth; legacy ReportJob Gateway has no active cancel capability and must not fabricate cancellation/failure.
62. Migration is gate-frozen: Phase 1C-B finishes the compatibility bridge only; JT-1 creates real Task/Attempt authority; LangGraph follows later per versioned workflow.

## 15. Supersession and next gate

This Design v1 makes the discussion note historical/non-authoritative and formally supersedes stale future Gate-B execution-routing assumptions where they conflict with this source-reconciled architecture. It does **not** rewrite Phase 1C-A Design v5 history or retroactively change the schema-v2 PASS evidence.

Before any implementation:

1. human/ChatGPT review this written Design v1;
2. if approved, write a fresh source-bound Phase 1C-B Implementation Plan against the then-current `main` baseline;
3. create a new Phase 1C-B Codex execution contract from Design v1 + the new Plan;
4. implement in a separate PR;
5. perform post-merge Implementation Review before starting JT-1.

Required current status:

```text
Job Task Orchestration Boundary Design v1 written for review.
Implementation NOT STARTED.
Phase 1C-B NOT STARTED.
Existing Phase 1C-B Prompt remains BLOCKED/STALE.
```
