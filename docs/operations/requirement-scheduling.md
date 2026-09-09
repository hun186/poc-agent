# Requirement scheduling control plane (Phase 1C-A)

Phase 1C-A provides the `sra_schedule` SQL Server control plane, structured `daily`, `weekly`, `monthly`, and elapsed-duration `interval` recurrence, and `coalesce_latest` for downtime while a schedule remains enabled. Disable is an intentional pause and clears `next_run_at`; re-enable starts strictly after server transaction UTC.

Set `REQUIREMENT_SCHEDULER_ENABLED=true`, `REQUIREMENT_CONTROL_DB_CONNECTION`, `REQUIREMENT_SCHEDULE_DB_SCHEMA` (default `sra_schedule`), `REQUIREMENT_DB_SCHEMA` (default `sra_requirement`), and the existing named SQL registry. Startup creates canonical schema v2 directly, validates existing v2 without DDL, and recognizes only the exact reviewed PR #200/#201 v1 catalogs for transactional migration. The marker changes to 2 last. The SQL principal needs read/reference access to Phase 1B and DDL/DML only in Phase 1C.

Authenticated readers may inspect schedules. `db_operator` creates disabled schedules, renames disabled metadata, and creates immutable draft versions. `superuser` approves/activates versions and enables/disables automation. Successful lifecycle mutations enqueue immutable evidence in the same SQL transaction; the bounded projector forwards it to the canonical JSONL audit sink at least once. Projection uses the outbox creation instant as `ts`, and both success and failure delivery updates compare-and-set only pending rows. Authorization denial continues to use the canonical direct audit path.

SQL and filesystem writes are not atomic, and JSONL delivery is not exactly once. A sink failure after SQL commit leaves the domain mutation and outbox row committed and pending; retries preserve the stable event ID and lifecycle timestamp.

The control plane and execution bridge run as two separate, externally supervised
processes. Do not use a FastAPI lifespan task or the obsolete generic `worker`
command:

```bash
python -m requirement_scheduler schedule-worker
python -m requirement_scheduler handoff-worker
```

`schedule-worker` only initializes and validates `ScheduleStore`, then calls its
existing due-claim boundary. It performs no HTTP, Report Job, Agent,
Elasticsearch, rendering, artifact, or handoff work. `handoff-worker` remains
the independently deployed execution-side coordinator. Run both under systemd,
a container orchestrator, or an equivalent supervisor with restart/backoff and
separate safe logs.

## Schedule worker configuration and behavior

`REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL` is the schedule worker's only new
setting. It defaults to `2.0` seconds and must be a finite float in the inclusive
range `0.1` through `300.0`. Invalid values fail startup before registry/store
construction. Do not substitute `REQUIREMENT_HANDOFF_POLL_INTERVAL`.

Claims always use the non-configurable system actor
`requirement-schedule-worker`. The normal worker claims at most one occurrence
per outer iteration. A successful claim may proceed to the next iteration;
no-due and safe `persistence_error` outcomes wait interruptibly for the poll
interval. Other invariant failures are fatal so the supervisor can alert and
restart. Logs expose only safe categories and must not contain SQL errors,
connection strings, credentials, headers, or tracebacks.

For a deterministic startup/operator diagnostic, run:

```bash
python -m requirement_scheduler schedule-worker --once
```

`--once` initializes the store, obtains one aware UTC time, performs exactly one
claim, and exits without waiting or retrying. No due item and one successful
claim both exit zero. Configuration, initialization, `persistence_error`, and
unexpected failures exit nonzero.

SIGTERM and KeyboardInterrupt set the schedule worker stop event. An in-flight
claim is allowed to finish its current SQL transaction; it is never
force-cancelled. All idle/retry waits use the interruptible stop event.

## Live acceptance gate

Live/deployment acceptance requires **separate authorization** and must not be
self-run as part of repository verification. The authorized sequence is:

```text
import >= 3 active Requirements
→ approved/enabled schedule
→ wait for next_run_at
→ schedule-worker automatically materializes ONE scheduled Batch Run
→ 3 selected Run Items
→ handoff-worker automatically submits them
→ 3 Report Jobs → 3 DOCX → automatic reconciliation
→ Batch completed; success_count = 3; failure_count = 0
```

Do not use a manual schedule trigger or manually invoke a coordinator
`run_once()` during that acceptance. Phase 1C live SQL Server acceptance remains
**NOT EXECUTED** in repository-only environments without explicit authorization.
