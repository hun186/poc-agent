# OFF-1K — Local Handoff Worker inherited owner ↔ SQL lease snapshot

OFF-1K is a **read-only, operator-gated** partial evidence step. It addresses a narrow question: does the currently verified **local** Handoff Worker process carry an explicit owner identity in its *initial process environment* which matches the owner ID of the active Handoff SQL Server coordinator lease? It does not prove job processing, output, schedule progress, or exclusive authority.

## Why not infer owner from PID?

The actual `requirement_scheduler.cli.build_coordinator_from_env()` sets `owner_id = os.getenv("REQUIREMENT_HANDOFF_OWNER_ID") or f"handoff-{os.getpid()}"`. But the launcher's Python `-c` entrypoint calls `config.bootstrap.bootstrap_env()` **after exec**; that bootstrap may load an owner value from `.env`, `.env.<APP_ENV>` or `.env.local`. Linux `/proc/<pid>/environ` generally reflects the initial exec environment, not subsequent process `setenv` changes. The bootstrap deliberately **does not overwrite existing OS environment entries**.

Consequently OFF-1K accepts an explicit, unique, printable ASCII `REQUIREMENT_HANDOFF_OWNER_ID` value already inherited by the verified Handoff process at exec. It does **not** guess `handoff-<pid>`, use the operator's shell environment, read dotenv/private SQL registries, follow symlinks to arbitrary PIDs, or trust a manually supplied expected owner ID. Missing, late-dotenv-only, duplicate, inaccessible or untrusted values are **SKIP**, not false PASS. To achieve useful positive OFF-1K evidence, the deployment launcher must **already** have injected a stable OS-level owner ID before starting the Handoff Worker. Do not change production launcher settings solely to get a green check without a separate operational review.

## Explicit operator invocation

From the **deployed repository root**, with the separately provisioned restricted diagnostic SQL account (OFF-1G credentials `SRAF_OFF1G_SQL_HOST/PORT/DATABASE/USER/PASSWORD`), numeric private IPv4, ODBC Driver 18 with strict CA + numeric IP-SAN TLS and DBA-granted SELECT on the actual `[sra_schedule].[requirement_handoff_coordinator_leases]` table:

```bash
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-lease \
  --probe-lease-renewal --probe-worker-identities --probe-handoff-owner
```

The **sixth opt-in flag** adds exactly one fixed parameterized SQL Server `SELECT TOP (2)` after earlier SQL-READ, HANDOFF-LEASE, HANDOFF-RENEWAL and WORKERS observations pass. This command also **authorizes the OFF-1J 15-second two-sample SQL heartbeat observation** and prerequisite bounded probes; it is NOT an offline command with zero network effects.

The local scope uses only the hardcoded `.run_sra_api_handoff.identity` in the project root, the existing canonical `verify_worker_identity` (PID start tick, effective UID, cwd, exact worker command), and at most 65,537 bytes of `/proc/<verified PID>/environ`, with an EOF check and strict NUL-framed parsing. It intentionally rejects a process environment larger than 64KiB rather than risking an unbounded memory/secrets read. The OS owner ID must be printable, <=128 bytes, and unique. The worker is verified again (including PID start and initial owner value) after SQL returns, reducing PID reuse and process/owner drift false positives.

The SQL server is asked only to compute three integer flags: byte-exact `NVARCHAR(128)` owner comparison via `CONVERT(varbinary(256), ...)` (avoids case-insensitive collation false matches), lease unexpired, and heartbeat recent by **SQL Server UTC clock**. It returns no owner ID, token, PID, process environment, connection information, timestamps or raw SQL errors. Any unavailable/ambiguous/mismatched/stale row or process identity change is `SKIP`; only matching positive flags with stable local identity produce `HANDOFF-OWNER: PASS`. Neither the numeric SQL sample nor initial owner value is printed. Privileges are enforced by DBA SELECT grants; `ApplicationIntent=ReadOnly` is not an access-control boundary.

**Evidence limit:** A matching local inherited Owner ID plus active DB owner is a point-in-time correlation, not proof that this PID actively renewed the earlier generation, that it has current live SQL credentials, or that any useful Handoff tasks were submitted/reconciled. Even `HANDOFF-RENEWAL: PASS` and `HANDOFF-OWNER: PASS` are separate snapshots and cannot be composed into formal job completion. `feature_acceptance` always remains `NOT_TESTED`; OFF-0/FULL_LIVE cannot be derived. Schedule Worker has no independent heartbeat; API Report Job, Word artifacts and physical network isolation require separate reviewed probes.

The Github Hosted CI uses fake ODBC/procfs evidence to test bounds, opt-ins, PID changes, SQL predicate safety and output redaction. It **does not** contact your private SQL Server or perform Linux deployment acceptance.
