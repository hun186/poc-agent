# Job Task Orchestration Boundary Discussion Notes

> **Classification:** Discussion Notes / Future Architecture / Non-authoritative
>
> **Status:** Implementation NOT STARTED
>
> **Authority:** Not an implementation plan; not yet `Job Task Orchestration Boundary Design v1`
>
> **Phase relationship:** Does not supersede Phase 1C Design v5; Phase 1C-B NOT STARTED
>
> **Required next step:** Must be reconciled against actual source before becoming formal Design authority

## Purpose and limits

These notes preserve the human-approved discussion after the Phase 1C-A v5 post-merge Implementation Review **PASS** at authoritative baseline `6a8b66b7d92ddfc9d9134c20f0e6235565df5e8a`. They retain decisions and conceptual examples for a future design review; they do not authorize implementation, freeze Python signatures, revise schema v2, or change Design v5, Plan v5, or the existing Phase 1C-B prompt.

Nothing here authorizes LangGraph integration, smolagents adapters, an orchestration port, workflow registries, Task/Attempt workers, or any other production change. Any statement below that differs from then-current source is a **Future design decision requiring reconciliation**, not a claim about implemented behavior.

## Current-source observations at preservation time

The limited source inspection needed to avoid treating future concepts as present behavior found:

- The current Report Job API exposes create/status/DOCX resources, backed by a local Report Job store and a FastAPI-process `ReportJobWorker` thread.
- The standalone Batch Scheduler drives Report Jobs through their HTTP API and maintains its own batch/task state.
- Phase 1C-A currently provides the Requirement Schedule control plane and materializes Batch Run/Run Item records, but it deliberately has no Phase 1C-B execution bridge.
- The existing Agent path uses smolagents in its data-agent/tool implementation. No LangGraph runtime integration was found.
- The future Task/Attempt model, engine-neutral port, static workflow registry, execution worker process, leases, canonical event stream, capability/runtime profiles, and normalized results described below do not exist as the formal Job Task architecture today.

Accordingly, all proposed boundaries in this note are **Future design decisions requiring reconciliation** against the actual source during the future Design v1 process.

## Preserved human-approved decisions

### Framework migration and routing authority

1. smolagents and LangGraph coexist and migrate gradually; there is no big-bang replacement.
2. The Job Task API remains framework-neutral and does not directly know or import smolagents or LangGraph.
3. Introduce a future engine-neutral Orchestration Port between the control plane and execution backends.
4. Workflow identities are versioned, for example `report_v1` and `report_v2`.
5. One workflow version maps to exactly one backend.
6. The caller cannot select the backend.
7. There is no automatic cross-backend fallback.
8. Use a repo-managed static Workflow Registry in v1; do not allow database-editable backend rebinding.
9. Do not add workflow aliases in v1; persist explicit resolved workflow IDs.
10. Adapters normalize output into a framework-neutral `ExecutionResult`.

### Asynchronous execution, ownership, and recovery

11. The formal Job Task execution contract is asynchronous.
12. The API creates and manages Tasks; an Execution Worker claims and executes work.
13. The first version uses DB-backed worker claim semantics rather than introducing Kafka or Redis without demonstrated need.
14. API Service and Execution Worker are separate processes.
15. smolagents and LangGraph adapters remain in-process with the Worker in v1; the architecture boundary does not have to be a network boundary.
16. Cancellation is cooperative and safe-point based; `cancel_requested != cancelled`.
17. Worker ownership uses a single active lease plus heartbeat.
18. Lease expiry means ownership loss, not execution failure and not retry authorization.
19. Reconciliation happens before any retry decision.

### Task, Attempt, state, and event identity

20. Task and Attempt are distinct identities.
21. A retry creates a new Attempt; terminal Attempts are immutable.
22. LangGraph checkpoint/resume remains within the same Attempt.
23. Task input is an immutable execution snapshot.
24. An Attempt stores the resolved workflow, backend, and runtime execution snapshot needed for reproducibility.
25. Artifacts are Attempt-scoped and immutable after finalization; a Task may point to `selected_result_attempt_id`.
26. The Job Task API uses a framework-neutral Attempt state machine.
27. An adapter translates framework-native states into canonical Job Task states.
28. Use an append-only, framework-neutral Execution Event stream.
29. The Execution Event Store and security Audit Outbox remain separate concerns.

### Capability, runtime, and contract authority

30. Every workflow version has a fixed server-side Capability Profile.
31. A backend consumes granted capabilities but cannot expand its own authority.
32. A client cannot request arbitrary tools or backend privileges.
33. Every workflow uses a repo-managed Runtime Profile for approved model/runtime policy.
34. A client cannot submit arbitrary model, backend, or framework runtime options as authority.
35. Workflow versions have typed and versioned input and output contracts.
36. Backend-specific GraphState, checkpoint configuration, smolagents kwargs, tool lists, and similar details do not enter the formal Job Task API.

### Secrets, failures, retries, and backend state

37. Secret values are resolved only by the Execution Worker at runtime through a controlled credential provider.
38. Secret values must not enter Task input, Attempt snapshots, events, audit payloads, artifacts, or framework-neutral results.
39. Adapters translate framework-specific exceptions into a framework-neutral safe Error Contract.
40. Retryability is descriptive evidence only; it never authorizes automatic retry.
41. The Job database must not become a mirror of LangGraph graph/checkpoint state.
42. A Job Task may store an opaque `external_execution_id`; it must not parse backend-specific semantics from it.
43. Same-backend resume/reconcile is allowed; silent backend switching is not.
44. Material changes to workflow semantics or security should create a new workflow/contract version rather than silently changing an existing workflow identity.

## Conceptual gradual migration example

This mapping is illustrative discussion material. It is not a registry definition and does not assert that these workflow IDs currently exist.

```text
report_v1        -> smolagents
rewrite_v1       -> smolagents
doc_followup_v1  -> smolagents

report_v2        -> langgraph
research_v1      -> langgraph
batch_report_v2  -> langgraph
```

## Conceptual future architecture

This diagram records the discussed separation of control-plane and execution responsibilities. It is not an implemented topology.

```text
Client / OpenWebUI / Scheduler
              |
              v
        Job Task API
              |
              v
        Task / Attempt DB
              |
       DB-backed claim
              |
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
Legacy/Smolagents   LangGraph
Adapter             Adapter
        |             |
        v             v
 Existing SRA       Graph workflows
```

## Conceptual future orchestration interface

The following operations preserve the semantic shape discussed for the future Orchestration Port only. They do **not** freeze exact Python signatures, types, sync/async syntax, error behavior, or module placement.

```text
start(request) -> ExecutionHandle
inspect(handle) -> ExecutionStatus
request_cancel(handle)
collect_result(handle) -> ExecutionResult
reconcile(handle) -> ReconciliationResult
```

## Matters that the formal Design v1 must reconcile

Before any of these notes become authoritative, the Design v1 process must compare them with actual source and explicitly resolve at least:

- coexistence with the current FastAPI-process Report Job worker, its SQLite state model, and its existing public API;
- the relationship among current Report Jobs, standalone Batch Scheduler tasks, Requirement Schedule Batch Runs/Run Items, and the proposed Job Task/Attempt identities;
- migration from current smolagents call paths without breaking established Agent, Report Job, scheduler, or artifact contracts;
- authoritative canonical states, lease/heartbeat transactions, safe points, reconciliation, retry authorization, and terminal immutability;
- exact ownership of the Workflow Registry, Capability Profiles, Runtime Profiles, typed contracts, credential resolution, event storage, and audit outbox boundaries;
- storage and retention rules for immutable snapshots, attempts, events, external execution IDs, and attempt-scoped artifacts;
- whether any Phase 1C-B scope should be replaced, split, or re-planned after the boundary is approved.

Until that reconciliation is reviewed and approved, each preserved proposal remains a **Future design decision requiring reconciliation**.

## Required future formal process

```text
Phase 1C-A PASS
        ↓
rebaseline actual main
        ↓
preserve/review discussion notes
        ↓
Job Task Orchestration Boundary Design v1
        ↓
human review/approval
        ↓
new/revised Phase 1C-B Implementation Plan
        ↓
new Codex execution prompt
        ↓
Phase 1C-B implementation
```

The repository's existing Phase 1C-B Prompt must **not** be executed directly before the future `Job Task Orchestration Boundary Design v1` and revised Gate-B Implementation Plan are reviewed and approved. A new Codex execution prompt is required after those gates.

## Preservation status

Job Task Orchestration Boundary discussion preserved for future Design v1.

Implementation NOT STARTED.

Phase 1C-B NOT STARTED.
