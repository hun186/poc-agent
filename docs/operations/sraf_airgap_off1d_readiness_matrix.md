# SRAF OFF-1D — dependency-aware operator readiness matrix

This incremental operator-only command **does not approve the deployment**. It
combines existing reviewed, bounded probes with a fixed dependency inventory
without pretending that unimplemented SQL/Agent/worker/report checks passed.

## Usage (from the deployed checkout root)

```bash
# Default: local filesystem/ODBC-library checks + selected-config classification.
# No sockets, DNS, HTTP, authentication, SQL, LLM or subprocesses.
python tools/sraf_airgap_off1d_readiness_matrix.py

# Explicit bounded network opt-in:
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network
```

The option only connects once to each configured, **numeric private/loopback
IPv4** API, ES and LLM service, using the existing OFF-1B two-second TCP probe.
When the API TCP check passes, it also performs one anonymous, loopback-only
`GET /healthz` using the audited OFF-1A bounded HTTP parser. The API target is
the launcher's bind port, not `PUBLIC_API_BASE`. It never scans hosts,
resolves DNS, follows redirects, sends credentials or calls an LLM. A failure
for one independently configured service does **not** stop other TCP checks.

The default still runs the existing local disk-space check and fixed-path
ODBC library file-discovery probe; observing an ODBC library **does not**
demonstrate SQL Server driver compatibility or database access. These checks
do not run remote SQL queries or mutate any database.

## Reading the matrix

The report uses `schema=sraf_airgap_off1d_readiness_matrix_v1`,
`mode=PARTIAL_ONLY_NOT_ACCEPTANCE`, and fixed redacted `results` with check
identifier, component, limited aspect, evidence status and dependency check
identifiers. It never includes environment values, hosts, ports, URLs, file
paths, credentials, index names, model names or remote response bodies.

The checks with actual possible evidence are `HOST-DISK`, `SQL-ODBC`,
`API-TCP`, `API-HEALTH`, `ES-TCP` and `LLM-TCP`.
`API-HEALTH` is skipped when `API-TCP` fails. The failure does not suppress
independent ES and LLM checks. TCP PASS merely means *a socket accepted*;
HTTP 200 on `/healthz` says nothing about process identity or workers.

The following remain explicitly **NOT_TESTED**, even if prerequisites pass:
`SQL-READ` (real authorized SQL read), `ES-MAPPING` (independent strict
authenticated ES Mapping — available via the separate OFF-1B CLI, not run
here), `LLM-INVENTORY`, `LLM-INFERENCE`, `WORKERS` (actual launcher/process
and SQL lease identities), `WORD` (real output artifact), and `ISOLATION`
(physical offline network isolation). Their `depends_on` entries are
**ordering hints, not claimed validation or blocking authority**.

A genuine failed executed check or invalid configuration produces
`overall=ISSUES_FOUND` and exit **1**. Otherwise `overall=INCOMPLETE` and
exit **2**, even if all observed checks are PASS: no exit 0/FULL_LIVE is
possible. The fixed `feature_acceptance` for every row and the report is
`NOT_TESTED`. The map is for triage, not OFF-0 promotion or release approval.

### Separate next actions

After operator-authorized deployment, collect real Linux evidence through the
separate OFF-1B Elasticsearch Mapping/strict identity checks and relevant
authorized SQL, LLM, worker and Word acceptance slices. The known Docker
Elasticsearch IP SAN mismatch cannot be treated as strict verified identity;
do not use reduced-assurance Basic credentials as proof of FULL_LIVE.

CI exercises deterministic, mocked network boundaries and config-only smoke
checks. It cannot attest a running private network, SQL Server, ES or LLM
service. No production deployment is performed by this PR.

## Codex P2 remediation: reliable failure severity (2026-10-24)

A nested API health provider cannot report PASS on its own: the readiness
matrix requires configuration RESOLVED, an actual integer HTTP status **200**,
the matching `healthz_http_200` reason, `GET` and `/healthz`. A
contradictory HTTP 503 is recorded as FAIL rather than a positive health
attestation. An invalid nested configuration is FAIL. Other malformed
PASS-looking results are downgraded to non-authoritative SKIP.

When an executed lower-level probe explicitly says FAIL but supplies an unknown
reason, the reason is sanitized to `unexpected_probe_result` **without**
downgrading FAIL to SKIP. Exit 1 still indicates ISSUES_FOUND. A malformed
`APP_ENV` profile rejected by the real configuration bootstrap is reported
as `runtime_profile_invalid`, `overall=ISSUES_FOUND`, and exit 1; it is not
treated as routine incomplete acceptance. Unrelated dotenv/runtime-loader
errors are redacted and remain exit 2. No raw environment value is printed.

These behaviors are validated by deterministic Hosted tests and still do not
certify private Linux readiness, SQL, ES, LLM, workers, Word or FULL_LIVE.

## 2026-10-24 TCP scope review follow-up

The matrix re-parses the configured endpoint before it accepts a nested TCP success. The reported service, configuration key, scheme, integer port, and host scope must match that resolved configuration. The API is restricted to loopback IPv4; ES and LLM are restricted to loopback or RFC1918 IPv4. Contradictory success claims are downgraded to SKIP, and API health is not called if API TCP was not credibly verified. These are socket-level diagnostics, never identity or application acceptance.
