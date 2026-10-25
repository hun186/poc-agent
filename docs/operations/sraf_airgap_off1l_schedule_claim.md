# OFF-1L — Read-only Schedule claim ledger observation

**Partial operator evidence, NOT Schedule Worker PID attestation.** Existing Schedule Worker calls the mutating SQL claim_due() and writes a requirement_batch_runs entry with application actor requirement-schedule-worker. OFF-1L deliberately does not call that method, change schedules or seed runs. It checks whether the committed scheduled-run count with that actor label increased for one explicitly chosen schedule in 15 seconds.

## Authorized operator invocation

From deployed repository root, with separate DBA-restricted SELECT principal using OFF-1G variables, numeric private IPv4, ODBC 18 and strict CA + IP-SAN identity:

```bash
export SRAF_OFF1L_SCHEDULE_ID='sch_<32-lowercase-hex-digits>'
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read \
  --probe-worker-identities --probe-schedule-claim
```

All four flags and genuine prior SQL-READ and WORKERS PASS are required. By default there are no schedule-ledger SQL reads or delays. Optional probe makes two independent bounded parameterized SELECT COUNT_BIG queries, 15 seconds apart, scoped to only this schedule, trigger_type='scheduled', created_by='requirement-schedule-worker'. Only strict count growth is SCHEDULE-CLAIM PASS; no increase is SKIP, not a false negative worker health verdict. A naturally quiet schedule will usually SKIP.

Real SQL SELECT privileges must be separately DBA-granted; ApplicationIntent=ReadOnly is not authorization. ODBC timeout does not guarantee immediate server cancellation. The check emits no raw SQL/ODBC errors, schedule ID, count, worker PID, Requirement contents or credentials.

**Interpretation:** created_by is an application-supplied actor, not a cryptographic proof of the local process or SQL session. Another caller can create a row with the same label. Neither process-attributed scheduling, Handoff, Report Job, Agent/LLM, DOCX nor physical offline isolation are proven. The matrix stays feature_acceptance=NOT_TESTED / overall=INCOMPLETE. Never force a production schedule to make this diagnostic PASS. Hosted CI uses fake ODBC and cannot replace actual private SQL/Linux operator acceptance.
