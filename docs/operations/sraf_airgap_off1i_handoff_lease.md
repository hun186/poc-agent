# OFF-1I — Handoff SQL coordinator lease snapshot (partial evidence only)

This OFF-1I slice addresses **one** verifiable gap: the Handoff Coordinator's authoritative SQL lease row. It does not modify the SQL Server, scan arbitrary tables, acquire/renew/release a lease, create a Schedule run, process jobs or make report artifacts.

The code was checked against the actual `requirement_scheduler.store.ScheduleStore.acquire_lease/renew_lease`, `requirement_scheduler.migrations` and `requirement_scheduler.lease.CONTROL_DOMAIN`. The SQL table is `[sra_schedule].[requirement_handoff_coordinator_leases]` by default, with a one-row-per-control-domain primary key, owner ID, secret token, generation, heartbeat and expiration. SQL Server's own clock is used rather than relying on the operator host's clock.

## Running on an authorized deployed Linux host

Use the **same dedicated DBA-limited diagnostic SQL principal** as OFF-1G, with a specific SELECT grant on the Handoff lease table, not the privileged SRAF runtime identity. Supply `SRAF_OFF1G_SQL_HOST`, `SRAF_OFF1G_SQL_PORT`, `SRAF_OFF1G_SQL_DATABASE`, `SRAF_OFF1G_SQL_USER` and `SRAF_OFF1G_SQL_PASSWORD` through operator-controlled OS environment, not through CLI arguments or source files. SQL host must be canonical numeric RFC1918/127.0.0.1 IPv4, using ODBC Driver 18 with Encrypt=Yes and TrustServerCertificate=No; server certificate must validate against the numeric IP.

```bash
# Local/default: NO SQL query or network activity.
python tools/sraf_airgap_off1d_readiness_matrix.py

# Explicit 3-flag, opt-in only. Performs the existing OFF-1G fixed
# SELECT CAST(1 AS int), then at most one OFF-1I lease snapshot SELECT.
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-lease
```

When the production SRAF Schedule DB schema is not `sra_schedule`, optionally supply `SRAF_OFF1I_SQL_SCHEMA` (one simple bounded unquoted SQL identifier; no brackets, semicolons, dots or expressions). Its value is not inspected unless all three flags are supplied. Missing/invalid configuration fails closed before executing the lease query. The probe never reads SRAF's protected runtime SQL registry.

The only OFF-1I query is a parameterized `SELECT TOP (2)` restricted by the fixed logical `requirement-report-v1` control domain. It returns **three SQL-computed integer predicates**, never the owner ID, token, generation, timestamps, raw SQL exceptions, host or database. The predicates require valid owner/token/generation shape, an unexpired lease, and heartbeat not in the future and no more than 120 seconds old relative to SQL Server's own clock. For a missing/expired/stale row, the probe reports SKIP; a contradictory duplicate or invalid predicate returns FAIL. Positive evidence is `HANDOFF-LEASE: PASS/lease_active_snapshot_observed` for an **instantaneous database lease observation only**.

It does **not** prove the local Handoff PID owns this lease, that the worker will renew it, that it is making progress, that jobs were claimed or reconciled, or that any particular scheduler cycle happened. Another node's lease could be active. It does **not** inspect Schedule Worker heartbeat (no equivalent independent Schedule heartbeat exists in the current schema) or API Report Job worker. If no Coordinator is currently active, SKIP is not an outage determination.

The matrix remains `PARTIAL_ONLY_NOT_ACCEPTANCE`, with `feature_acceptance=NOT_TESTED` even for a positive SQL lease row. The independent `WORKERS` process-identity check is not promoted. Word, physical isolation and true durable scheduling/lease ownership acceptance are separate. All Hosted tests use fake pyodbc; no real SQL Server was contacted, no private Linux deployment accepted, and no production DB mutation was performed.

## Resource limits and security tradeoffs

Two separate SQL logins are initiated by the 3-flag operator action: OFF-1G's fixed constant SELECT, followed only if it passes by this one fixed lease SELECT. Each connection sets 3-second login and query timeout; Python driver / kernel delays might exceed that and timeout cannot guarantee server-side cancellation. Query and connection handles are closed. The diagnostic login still needs DBA-enforced SELECT-only rights; `ApplicationIntent=ReadOnly` is a connection routing hint, **not** a permission boundary.
