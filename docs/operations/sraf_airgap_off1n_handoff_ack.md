# OFF-1N — Persisted Handoff submission acknowledgement (SQL only)

This opt-in operator diagnostic extends OFF-1L and OFF-1M. It checks the most recent actor-labelled scheduled run for **persisted Handoff acknowledgement**: the run has at least one selected item, non-null Handoff start and handed-off times, and an item with an SQL submission row (`workflow_id=report_v1`), non-null `remote_job_id` and `dispatched_at`. Only the two computed SQL predicates leave the database.

## Invocation

Run from the **deployed project root**, using the dedicated, DBA-restricted OFF-1G SQL diagnostic account. It needs SELECT on `requirement_schedules`, `requirement_schedule_versions`, `requirement_batch_runs`, `requirement_batch_run_items` and `requirement_handoff_submissions`, actual ODBC Driver 18, verified numeric RFC1918 IP and strict CA + IP-SAN TLS. Give one already-known canonical Schedule ID; **do not enumerate** production records:

```bash
export SRAF_OFF1L_SCHEDULE_ID='sch_<32-lowercase-hex-digits>'
# Only when Schedule tables really use a non-default schema:
export SRAF_OFF1I_SQL_SCHEMA='tenant_sched'
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-identities \
  --probe-schedule-claim --probe-schedule-link --probe-handoff-ack
```

**All six explicit flags** must be passed; prior `SQL-READ`, `WORKERS`, `SCHEDULE-CLAIM` and `SCHEDULE-LINK` have to return genuine PASS first. This includes OFF-1L's 15-second two-query ledger observation. If any prerequisite fails or flags are absent, `HANDOFF-ACK` returns SKIP/NOT_TESTED, and **does not connect** for its additional SQL query. The final probe uses one bounded, parameterized, read-only `SELECT TOP (2)` over the selected Schedule ID; no production schedule/job state is altered. `ApplicationIntent=ReadOnly` is NOT a security boundary, only DBA rights are.

### Interpretation

`HANDOFF-ACK: PASS` / `ack_persisted_submission_observed` means the SQL state contains both an acknowledged batch handoff timestamp and at least one selected item with a persistent Report Job submission record and remote job ID for that *currently latest scheduled run*. It does **not** contact or authenticate the remote Report Job endpoint. It cannot prove that the local Schedule/Handoff PID authored these records, the remote job is running/successful, any Agent/LLM/ES execution occurred, that Word output exists or is valid, or that the network is physically isolated. Also, the query is not a serializable multi-table transaction, and the latest run could differ from the run observed by OFF-1L 15 seconds earlier. A failed/quiet/disabled/reconfigured run may legitimately SKIP.

No run IDs, remote job IDs, submission identifiers, raw SQL, credentials, Requirement contents, counts, times or artifacts are serialized into matrix output. SQL failures and malformed rows are redacted. The matrix **always stays `feature_acceptance=NOT_TESTED` / overall `INCOMPLETE` unless independent FAIL**, never FULL_LIVE. Github Hosted CI uses simulated ODBC/procfs—not a substitute for separately approved operator testing on private Linux/SQL Server.
