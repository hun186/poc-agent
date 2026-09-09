# SRA Requirement Schedule Runtime Automation — Design Specification v1

**Repository:** `hun186/poc-agent`
**Inspected baseline:** `b8bcd779815337bb386a97fc457a5f49663fb2b6` (PR #225 merge)
**Classification:** Phase 1C runtime automation completion delta
**Status:** design for review; implementation has not started

## 1. Authority and purpose

This design specializes and completes only the missing runtime driver for the already-implemented `ScheduleStore.claim_due()` boundary. It does **not** supersede Phase 1C-A Design v5, Job Task Orchestration Boundary Design v1, or the corrected Phase 1C-B Plan/architecture. Current source wins stale path assumptions.

Historical Phase 1C v2 established the need for due claiming but combined claim, Phase 1A handoff, and reconciliation. The later orchestration boundary correctly separated execution into the framework-neutral Phase 1C-B Handoff Coordinator. Current source implements `handoff-worker` but has no automatic caller of `claim_due()`. This design completes that one missing process without reviving the superseded coupling.

## 2. Runtime architecture

```text
                    SQL Server
                        |
             +----------+----------+
             |                     |
             v                     v
     schedule-worker         handoff-worker
             |                     |
       claim_due()            reconcile
             |                 prepare
             |                 submit
             v                     |
   scheduled Batch Run             v
             +------------> Report Job API
                                   |
                                   v
                           existing ReportJobWorker
                                   |
                                   v
                            Agent / ES / DOCX
```

These are two independent, externally supervised OS processes. They communicate only indirectly through SQL-authoritative Batch Run and Run Item state. No in-process signal is necessary in v1; bounded polling provides eventual progress.

### 2.1 `schedule-worker` owns only

1. load server-owned Requirement SQL configuration;
2. construct and initialize/validate `ScheduleStore`;
3. obtain a timezone-aware UTC current time;
4. invoke the existing public `ScheduleStore.claim_due(now_utc=..., actor=...)` boundary;
5. wait interruptibly for a bounded positive poll interval; and
6. repeat until graceful stop.

It may support `--once` as a deterministic operator/test surface. One-shot mode performs startup validation and exactly one `claim_due()` call, then exits according to the safe outcome. It does not drain all due schedules in one invocation.

### 2.2 `handoff-worker` remains unchanged

The current Phase 1C-B coordinator continues to reconcile, prepare, and submit. This design neither renames it nor changes its lease, fencing, submission, reconciliation, artifact, checkpoint, or closure contracts.

## 3. Startup and configuration

- Configuration is server-owned environment plus the existing Requirement SQL registry. Reuse `REQUIREMENT_SQL_REGISTRY_FILE`, `REQUIREMENT_CONTROL_DB_CONNECTION`, `REQUIREMENT_SCHEDULE_DB_SCHEMA`, and `REQUIREMENT_DB_SCHEMA`; do not create a parallel registry.
- Add only narrowly named runtime settings such as a bounded positive poll interval and a non-secret audit actor identity. Defaults must be safe and documented. Invalid, non-finite, zero, negative, or unreasonably large intervals fail before polling.
- Construct `ScheduleStore` through a small source-consistent factory and call `initialize()` before the first claim. Invalid configuration, inaccessible registry, or schema/catalog mismatch is fatal and fails closed with a stable safe error and nonzero exit.
- Initialization remains the store's schema validation/migration boundary. The worker adds no DDL and makes no assumptions about schema shape.

## 4. Due processing and time

Each iteration gets `datetime.now(timezone.utc)` (optionally injected as a clock for tests) and calls only:

```python
ScheduleStore.claim_due(now_utc=now_utc, actor=actor)
```

The worker must not duplicate or reinterpret recurrence parsing, `coalesce_latest`, scheduled occurrence identity, schedule locks, snapshot binding/materialization, selection policy, checkpoint evidence, audit mutation, or `next_run_at` advancement. Those remain atomic store responsibilities.

All worker-generated times are aware UTC. Naive caller datetimes are forbidden. This preserves PR #224's aware-UTC boundary; it does not change SQL Server time authority inside handoff leases/deadlines.

## 5. Polling, fairness, and shutdown

`claim_due()` currently claims at most one due occurrence, selecting the oldest persisted due time and then schedule ID. The worker therefore performs one claim per iteration. After a successful claim it may immediately begin the next bounded iteration (or use the configured wait consistently); when no schedule is due it waits for the poll interval. Either implementation must avoid an unbounded inner drain and must check stop state between claims.

Continuous execution eventually processes additional due schedules. Store locking, coalescing, atomic advancement, and unique scheduled-occurrence identity make concurrent workers/restarts safe against duplicate occurrence materialization. Throughput is intentionally bounded; v1 does not redesign `claim_due()`.

Waiting uses `stop_event.wait(poll_interval)`, not `time.sleep()` or a busy loop, so shutdown interrupts the wait. The CLI maps SIGTERM and KeyboardInterrupt to the stop event and exits after the current store call completes. No unsafe forced cancellation of an in-flight SQL transaction is introduced.

## 6. Error model and operator evidence

| Class | Examples | Required behavior |
|---|---|---|
| Startup fatal | missing/invalid registry or env, invalid interval/actor, failed store initialization, unrecognized schema | Fail closed before polling; nonzero exit; stable safe category only |
| Safe transient runtime/persistence | a post-start claim raises the store's safe `persistence_error` | Record a bounded safe operator event, wait interruptibly, and retry on a later iteration; no busy retry and no lifecycle fabrication |
| Programming/invariant failure | unexpected exception or invalid worker dependency result | Fail closed so external supervision can alert/restart; do not turn arbitrary failures into success |
| Graceful stop | stop event, SIGTERM, KeyboardInterrupt | Stop polling cleanly; expose no traceback or secret |

Operator-facing output/logging must never include raw ODBC/SQL exceptions, connection strings, credentials, headers, or tracebacks. Follow existing safe-error categories. A transient claim failure does not imply a failed Batch Run because no second lifecycle authority exists. `claim_due()` and materialization remain authoritative for all domain and audit mutations; the worker invents no schedule/run audit events.

## 7. Process supervision and CLI

The conceptual public CLI is:

```text
python -m requirement_scheduler schedule-worker
python -m requirement_scheduler schedule-worker --once
python -m requirement_scheduler handoff-worker
```

The existing `handoff-worker` behavior and spelling are compatibility contracts. Do not restore a generic historical `worker` command that combines scheduling and execution.

Production runs `schedule-worker` under Linux/systemd, a container orchestrator, or an equivalent external supervisor with restart/backoff, server-owned environment, separate logs, and graceful termination. FastAPI lifespan must not spawn it. Operations documentation should show both processes as separately deployable and independently observable, without embedding secrets.

## 8. Hard boundaries

The implementation must introduce:

- no new database schema, table, column, index, or migration;
- no `ScheduleStore.claim_due()` semantic redesign unless implementation-time source proves a blocker and a new design review approves it;
- no recurrence, coalescing, occurrence identity, materialization, policy, or checkpoint redesign;
- no Phase 1A `BatchSchedulerService` embedding or Batch Scheduler SQLite access;
- no `ReportJobStore`, `ReportJobWorker`, Agent, Elasticsearch, or Word renderer imports/access;
- no HTTP call, artifact publication, handoff, or reconciliation from `schedule-worker`;
- no FastAPI background scheduling thread;
- no distributed queue, Redis, Kafka, Celery, or equivalent;
- no JT-1 Task/Attempt tables or runtime work;
- no LangGraph work;
- no automatic failed Report Job retry; and
- no new cancellation engine.

## 9. Verification and acceptance

Repository tests must prove the worker delegates rather than recreates domain logic: zero/one/multiple due behavior, advancement via the store, disabled schedule behavior, restart/concurrency uniqueness, interruptible stop, fail-closed startup, CLI compatibility, and prohibited dependencies/I/O. Recurrence algorithms remain covered at the store/recurrence layer and are not duplicated in worker tests.

The supplied operator evidence establishes **Single-item Requirement → Report Job → Agent/Elasticsearch → DOCX live Golden Path: PASS**, after PR #223 (`202`/native status), PR #224 (aware UTC SQL clock), and PR #225 (`READPAST`) corrections. It does not test automatic due claiming. Runtime deployment acceptance requires enabling a schedule, allowing `next_run_at` to become due, observing exactly one scheduled Batch Run without a manual trigger, then observing the unchanged handoff worker complete it. Broader migration/failover/failure/race acceptance remains separately pending.

## 10. Self-review conclusion

This design has one lifecycle dependency (`ScheduleStore.claim_due()`), one external process responsibility, and no new persistence or execution authority. It preserves both current workers' separation and is ready for Design + Plan Review. Implementation is not authorized by this document alone.
