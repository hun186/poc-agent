# OFF-1M — Schedule active-version and latest actor-labelled run linkage

OFF-1M builds on OFF-1L's separately observed **SQL scheduled-run ledger growth**. It adds one bounded, non-mutating SQL Server query that asks whether, *at the time of observation*, a chosen Schedule has an enabled + approved active version, its **latest actor-labelled scheduled** batch run is associated with that active version, and `next_run_at` is strictly after that latest run's `scheduled_for`. SQL Server calculates three 0/1 predicates; no run IDs, schedule IDs, timestamps, configuration, secrets, or data rows are exposed.

## Operator-only opt-in

From a deployed Linux repo root with a separately DBA-restricted OFF-1G diagnostic SQL login, numeric private IPv4 endpoint, ODBC Driver 18, strict TLS CA+numeric IP SAN identity, and the actual Schedule ID:

```bash
export SRAF_OFF1L_SCHEDULE_ID='sch_<32-lowercase-hex-digits>'
# Optional only for non-default existing Schedule schema:
export SRAF_OFF1I_SQL_SCHEMA='tenant_sched'
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-identities \
  --probe-schedule-claim --probe-schedule-link
```

All **five explicit flags** are required. The existing SQL-READ and WORKERS checks must succeed. The OFF-1L SCHEDULE-CLAIM row must also be PASS (the first two SQL count reads 15 seconds apart), **before** OFF-1M sends its additional one parameterized read-only SELECT. Otherwise SCHEDULE-LINK is NOT_TESTED or SKIP without that query. No SQL permission escalation, process start, job claim or schedule modification is performed. No additional sleep is introduced beyond OFF-1L.

**PASS** means only three SQL-computed current linkage predicates were observed for one Schedule at one point: enabled/approved active version; latest scheduled Worker-actor-labelled run's version matches active version; and a non-null persisted next-run time strictly follows that record's scheduled time. Any missing, ambiguous, malformed, unapproved, version-changed, no next-run or SQL failure yields **SKIP/inconclusive**. A newly reconfigured/disabled Schedule may legitimately SKIP.

**Critical limitations:** `created_by='requirement-schedule-worker'` is an application-supplied actor label, not authenticated process identity. A current read of related tables under normal SQL Server isolation is not a proof of atomic multi-table snapshot or the *particular* run added in the preceding 15-second window. The check cannot prove the observed local Schedule PID performed the SQL write or that Handoff, Report Job, Agent/LLM/ES, DOCX, or physical network isolation succeeded. `feature_acceptance=NOT_TESTED`, `overall=INCOMPLETE` are not upgraded by either PASS. Query access must be separately restricted by DBA (ApplicationIntent=ReadOnly is not security); ODBC timeout is not server-side cancellation. Never seed a production job solely to make the test green. Hosted CI uses fake ODBC only.
