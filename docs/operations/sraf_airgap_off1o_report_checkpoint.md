# OFF-1O — Read-only persisted Report Job completion checkpoint

**Partial SQL evidence only.** OFF-1O follows OFF-1N. It observes the latest application-actor-labelled scheduled batch run and requires its recorded Handoff/reconciliation timestamps and **one same selected item** with a joined `report_v1` Handoff submission, persistent remote job ID, dispatch and remote-completed timestamps, `remote_job_state=completed`, `execution_state=completed`, item completion timestamp, artifact reconciliation timestamp, nonempty recorded artifact relative path, and a 64-character lower-case hexadecimal SHA256 in SQL. These are **persisted database claims**, not independent proof of an actual Report Job HTTP result, physical DOCX file or independently recomputed file SHA256.

## Operator invocation

Use only an authorized deployed Linux operator, separately DBA-restricted OFF-1G diagnostic SQL SELECT principal, private numeric IPv4 endpoint, ODBC Driver 18 and strict CA-validated IP-SAN TLS. A known canonical Schedule ID is supplied, never enumerated:

```bash
export SRAF_OFF1L_SCHEDULE_ID='sch_<32-lowercase-hex-digits>'
# Optional when the existing installation uses a non-default Schedule schema:
export SRAF_OFF1I_SQL_SCHEMA='tenant_sched'
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-identities \
  --probe-schedule-claim --probe-schedule-link \
  --probe-handoff-ack --probe-report-checkpoint
```

**Seven independent flags** are required. The real upstream SQL-READ, WORKERS, SCHEDULE-CLAIM, SCHEDULE-LINK and HANDOFF-ACK checks must PASS. OFF-1L already includes two SQL counts separated by 15 seconds. Only after positive HANDOFF-ACK does OFF-1O issue **one additional** bounded, parameterized, read-only SQL SELECT, scoped to the known schedule ID. Without opt-in or valid upstream evidence, it produces NOT_TESTED/SKIP and does not query the Report checkpoint tables. The SQL principal still needs DBA-enforced SELECT permissions; `ApplicationIntent=ReadOnly` is not an authorization control.

A **PASS** means only two SQL-computed predicates matched at this read instant: the latest actor-labelled batch has Handoff/reconciliation timestamps, and *one same selected item* has a persisted Report completion and artifact-reconciliation checkpoint with a syntactically valid SHA256. One completed item does **not** mean all selected items or the entire batch succeeded. Failures, missing rows, interrupted work and naturally quiet/disabled/reconfigured schedules yield SKIP.

**No claims of live proof:** No authenticated GET to `/v1/report/jobs/{id}`, remote Agent/LLM/ES inspection, actual `GET /word`, local DOCX byte inspection, hash recomputation, trusted PID/job linkage or physical isolation are performed. Normal SQL isolation is not a serializable audit, and the latest batch may have changed after earlier 15-second sampling. Database columns can be application-supplied. No job IDs, file paths, hashes, schedule IDs, SQL-native errors or credentials leave SQL as JSON. The matrix stays `feature_acceptance=NOT_TESTED`, `overall=INCOMPLETE` (unless unrelated observed failures). Hosted CI uses mock ODBC, not real Linux/SQL/DOCX evidence. Never create production jobs to make these diagnostics pass.
