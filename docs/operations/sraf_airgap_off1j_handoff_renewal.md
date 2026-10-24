# SRAF OFF-1J — two SQL Handoff heartbeat samples (partial only)

OFF-1J is **one** additional, operator-authorized diagnostic: observe whether the
same DB Handoff coordinator lease generation has a strictly increasing
\`heartbeat_at\` across two separate SQL snapshots. It is not a local Worker
owner attestation, job-progress check, lease acquisition/release, or service
health acceptance.

## Authorized operator command

From the *running repository root* on the Linux deployment host, provide the
dedicated DBA-restricted diagnostic SQL identity already documented for
OFF-1G/OFF-1I. It must have explicit SELECT grants on the Handoff lease table,
and must not be the SRAF runtime privileged SQL account. The diagnostic driver
requires TLS with verified server IP SAN (ODBC Driver 18, Encrypt=Yes and
TrustServerCertificate=No), private numeric IPv4 and scoped schema
\`SRAF_OFF1I_SQL_SCHEMA\` (default \`sra_schedule\`).

Default invocation sends no SQL queries and causes no 15s wait:

\`\`\`bash
python tools/sraf_airgap_off1d_readiness_matrix.py
\`\`\`

**Only** four explicit options authorize the additional probe:

\`\`\`bash
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-lease \
  --probe-lease-renewal
\`\`\`

The operator authorizes all of: one OFF-1G constant SELECT, the OFF-1I
single lease snapshot, and **two additional** fixed lease snapshot SELECTs
with a 15-second wall-clock gap, each in a separate, closed ODBC connection.
The first sample is closed before sleeping. The second runs only after the
first is valid and 15s elapsed. Each SQL query uses login/query timeouts of
3 seconds; actual kernel/driver delays may exceed these bounds. No polling
loop, retries, unrestricted SQL, DDL/DML, or worker actions are allowed.

The SQL statements use the **SQL Server clock**, a fixed parameterized
\`control_domain=requirement-report-v1\`, and bounded \`SELECT TOP (2)\`.
Each snapshot internally reads only three SQL-side safety flags,
\`fencing_generation\`, and a server-derived numeric millisecond heartbeat
marker. No SQL owner ID, lease token, raw timestamp, database name, host,
credentials, table row body or native ODBC error are placed in the report.
No lease token or owner ID is fetched by the client.

PASS requires all of: the earlier OFF-1I snapshot PASS, both snapshots valid
and unexpired, both heartbeats <=120 seconds old by the SQL server clock,
**unchanged positive fencing generation**, and the second heartbeat marker
strictly greater than the first. Missing/expired/unchanged/change-of-
generation/SQL exception evidence returns an incomplete SKIP; no success is
claimed just because the lease exists. The \`HANDOFF-RENEWAL\` result is always
\`PARTIAL_ONLY_NOT_ACCEPTANCE\`, \`feature_acceptance=NOT_TESTED\`.

The coordinator may be another host's process, may be stuck doing useful work
while its heartbeat continues, or may be idle with a valid lease. The current
code supports a custom \`REQUIREMENT_HANDOFF_OWNER_ID\` override, so inferring
local ownership from \`handoff-<pid>\` naming alone would be unsafe.
OFF-1J does **not** prove local owner-to-process binding, actual dispatch,
reconciliation, Schedule Worker claim/progress (it has no independent SQL
heartbeat), API Report Job Worker, Word or physical network isolation.

All GitHub Hosted tests are deterministic pyodbc fakes; they do not constitute
authorized private Linux/SQL Server acceptance. Failed operator results
should be investigated without relaxing TLS verification or granting
unnecessarily privileged SQL credentials.
