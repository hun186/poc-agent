# OFF-1Q — operator-only same-item authenticated Report Job status

OFF-1Q is an **independent partial** observation, after OFF-1P's successful real DOCX bytes/digest verification. It selects the latest actor-labelled scheduled batch for one operator-known Schedule ID, selects one already completed report_v1 item using OFF-1P's ordering, and makes **one authenticated read-only GET** against the corresponding live Report Job status. It does not create jobs, download Word artifacts, inspect prompts or Agent/LLM/ES, prove local API PID identity, or certify the physical airgap.

## Controlled invocation on authorized Linux deployment

Use an operator credential scoped to **REPORT_JOB_READ only** (not create/admin/download), that can read the existing Handoff-created job (owner-scoped auth may require the same service principal). Use existing OFF-1G separately DBA restricted SQL credentials, strict IP-SAN/TLS to private SQL Server, and canonical Schedule ID. The HTTP endpoint is deliberately restricted to exact **127.0.0.1** (same local host and namespace): no operator URL, DNS, off-host proxy, redirect, retries, or TLS downgrade of a remote service.

\`\`\`sh
export SRAF_OFF1L_SCHEDULE_ID='sch_<32 lowercase hex digits>'
export SRAF_OFF1P_ARTIFACT_ROOT='/the/existing/published/output/root'
export SRAF_OFF1Q_REPORT_API_PORT='8000'  # locally bound authenticated SRAF API
export SRAF_OFF1Q_REPORT_JOB_READ_TOKEN='<read-scope-token>'
# Existing OFF-1G SRAF_OFF1G_SQL_* credentials + optional SRAF_OFF1I_SQL_SCHEMA
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-identities \
  --probe-schedule-claim --probe-schedule-link \
  --probe-handoff-ack --probe-report-checkpoint \
  --probe-docx-bytes --probe-report-live
\`\`\`

The **ninth** explicit \`--probe-report-live\` flag and the other eight flags are required; all preceding SQL/worker/Schedule/Report and DOCX-BYTES checks must have actually PASSED. Unless all nine flags are present, the CLI does not even read the API port/token environment variables. When the previous DOCX-BYTES check is not PASS, OFF-1Q does not touch SQL or HTTP.

The SQL query is fixed, parameterized and bounded \`SELECT TOP (2)\`, copying OFF-1P's latest batch and selected item order, joining that same item to a \`report_v1\` Handoff submission. Only \`rpt_<32 lowercase hex>\` and \`rhsub_<48 lowercase hex>\` are accepted. These values stay within the process, never printed. Then HTTP GET uses a fixed \`http://127.0.0.1:<validated numeric port>/v1/report/jobs/<validated id>\`, bearer authentication, 2s connect/3s read timeout, proxy and netrc disabled, redirects disabled, no retries, at most 8 KiB response. It parses only the required shape: same \`job_id\`, \`metadata.submission_id\`, \`metadata.workflow_id=report_v1\` and \`status=completed\`. Missing authorization, non-200 or unrecognized responses cannot PASS; explicit inconsistent job/submission IDs or terminal failure returns FAIL.

A PASS indicates **one independently queried local API status for a SQL-selected job** at the instant of the GET, plus earlier independently sampled DOCX evidence. It is NOT atomic identity binding to the specific previously checked DOCX file: the latest batch/item may change between separate SQL observations. It is not Agent/LLM/ES provenance, does not establish trusted local listener/PID identity, whole-batch success or physical isolation. Report Job API GET may create ordinary audit records and therefore is *HTTP GET only, not necessarily zero server-side log/audit writes*. Never run against production without local operator authorization. The matrix retains \`feature_acceptance=NOT_TESTED\`, \`overall=INCOMPLETE\` unless failures are observed.

Hosted CI uses mocked SQL responses and HTTP sessions: it does NOT connect to a real private SQL Server or contact an authenticated live Report Job in an airgapped host.

## Codex review remediation — absolute deadline (2026-10-27)

The first formal Codex Review found a P2: HTTP streaming with an inactivity-only timeout could be delayed indefinitely by a listener sending one byte every few seconds. OFF-1Q now uses a direct numeric IPv4 socket connection to the exact localhost API with **one absolute three-second monotonic deadline across connect, send, HTTP response headers and all JSON content reads**. For deterministic bounded transport it intentionally accepts only HTTP/1.0 or HTTP/1.1 with explicit unique Content-Length, 200 status, uncompressed application/json and <=4 KiB headers / <=8 KiB body. HTTP redirects, chunked transfer encoding, content compression, unknown-length replies and slow trickle are rejected (safe SKIP). Unlike Requests, the transport cannot load a proxy or .netrc configuration or resolve a hostname. This remains an operator-only partial observation; it is not process/PID identity or full Job/Word/Agent acceptance.

## Codex SQL Server OUTER APPLY P2 (2026-10-27)

Second formal Codex Review found an invalid alias in the outer SQL projection: `h` only exists within the nested APPLY subquery. OFF-1Q now reads `i.submission_id` from the APPLY-derived outer alias, with an explicit SQL text regression. Hosted fake ODBC tests cannot replace a live SQL Server parse/execution smoke test; that remains an operator acceptance task.
