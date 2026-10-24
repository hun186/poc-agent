# SRAF OFF-1G — operator-authorized SQL Server constant SELECT

OFF-1G adds a narrow SQL Server connectivity/constant-read check to the OFF-1D readiness matrix. It is **not** a database permission audit, production Requirement SQL catalog validation, application transaction test, SQL schema check, credential-control exercise, SQL Server HA test or full deployment acceptance.

## How to run

On an authorized SRAF Linux deployment, use a **dedicated SQL Server principal independently restricted by the DBA to read-only permissions**. The tool cannot guarantee the principal is read-only; `ApplicationIntent=ReadOnly` is a routing hint, *not* a SQL permission boundary. Use a controlled account whose credentials are approved for operator testing. It may generate SQL Server login/audit records. Do not reuse SRAF privileged runtime SQL registry/service credentials.

Configure the five **operator-only** OS environment variables in the deployment shell, without storing secrets in Git or CLI arguments:

```bash
# Examples are illustrative only; use private numeric addresses from your site.
export SRAF_OFF1G_SQL_HOST=192.168.20.40
export SRAF_OFF1G_SQL_PORT=1433
export SRAF_OFF1G_SQL_DATABASE=sraf_reports
export SRAF_OFF1G_SQL_USER=sraf_probe_reader
# Inject SRAF_OFF1G_SQL_PASSWORD securely from your secret manager.
```

Run from the deployed repository root:

```bash
# Default: no SQL connection or credential lookup.
python tools/sraf_airgap_off1d_readiness_matrix.py

# Basic opt-in TCP/health does NOT connect to SQL.
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network

# Only this explicit two-flag choice enables one SQL constant SELECT.
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network --probe-sql-read
```

The SQL credential variables are used only when **both** flags are present, and are distinct from ordinary SRAF application SQL settings. No SQL URL, username, database name, password, SQLSTATE or ODBC exception text is emitted or logged by the probe. The SQL driver library prerequisite must have passed; actual `ODBC Driver 18 for SQL Server` installation is checked again by pyodbc. SQL parameters are strict: host must be a canonical numeric RFC1918/127.0.0.1 IPv4 address, port 1–65535, database and username bounded simple identifiers, and password bounded/escaped as an ODBC value. DNS, public IPs, Azure/SaaS hostnames, IPv6, arbitrary DSNs and additional connection string flags are not accepted. Unsupported valid credentials may result in SKIP rather than unsafe normalization.

The ODBC connection uses driver 18, `SERVER=tcp:<private-IP>,<port>`, `Encrypt=Yes`, `TrustServerCertificate=No`, SQL password authentication, `ApplicationIntent=ReadOnly` and no multi-subnet failover. The **server must present a trusted TLS certificate valid for the exact numeric IP address**, otherwise connection may not be established; do not enable `TrustServerCertificate=Yes` to bypass identity verification. Login timeout and query timeout are each configured to 3 seconds; driver/native OS behavior may extend actual latency and a timeout does not certify server-side cancellation.

After connecting, the tool issues exactly one literal `SELECT CAST(1 AS int)` and verifies precisely one integer result equal to 1. This reads **no SRAF business table**, retrieves no rows from Requirement/Report storage, calls no stored procedures and performs no writes. Cursor and connection handles are closed in all ordinary success/error paths. A PASS means an encrypted SQL connection and this fixed constant SQL roundtrip succeeded under the provided login, **not** that the login lacks write authority, or that any application table is readable. A login/driver/TLS/network error is redacted and may be SKIP (not verified); a malformed executed constant result is FAIL. Unrelated API/ES/LLM checks remain independent.

The `SQL-READ` row is `PARTIAL_ONLY_NOT_ACCEPTANCE`, with `feature_acceptance=NOT_TESTED` even on PASS, dependent on `SQL-ODBC`. `WORKERS`, `WORD`, `ES-MAPPING`, `ISOLATION` and end-to-end SQL/report acceptance remain **NOT_TESTED**. No FULL_LIVE/exit-zero claim. Hosted GitHub CI runs only deterministic fakes and has no connectivity to the private SQL instance. Full authorized Linux/SQL acceptance remains a later, separate gate.
