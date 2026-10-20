# SRAF OFF-1B — Runtime-configured TCP preflight (first incremental slice)

This is an **operator convenience and bounded diagnostic**, not OFF-1B completion,
not ES/LLM/SQL acceptance, and not the OFF-3 unified runner. It directly addresses
the deployed Linux environment where the API, ES and LLM ports differ from examples
in OFF-1A documentation.

## One-command use

From the actual deployed repository root:

    python tools/sraf_airgap_off1b_auto.py

No manual IP/port/model argument is needed. The tool calls the existing
config.bootstrap.bootstrap_env() in a separate Python process,
using the exact runtime precedence:
OS environment > .env.local > .env.{APP_ENV} > .env.
The code does **not** import FastAPI, initialize SQL schemas, start workers, run
Agent inference or call any E2E fixture.

Alternative bounded commands:

    python tools/sraf_airgap_off1b_auto.py --check es
    python tools/sraf_airgap_off1b_auto.py --check llm
    python tools/sraf_airgap_off1b_auto.py --no-network

Services are selected from:
- API launcher listener: shell PORT (default 9002), numeric 127.0.0.1; PUBLIC_API_BASE may reference a separate reverse proxy and is not used to identify the listener. Note: this CLI observes its own launching shell PORT; a separately started running launcher may have used another PORT, so PID/listener attestation is still needed.
- Elasticsearch: ES_URL
- Main LLM: MODEL_BASE_URL (whether MODEL_ID is set is reported as boolean)
- Topic LLM: TOPIC_LLM_URL is only an enablement flag in the current query_terms path. It is never used for a TCP target. The actual client uses MODEL_BASE_URL / MODEL_ID; the explicit --check topic-llm reports only the enabled boolean and exit 2 (SKIP).

The default --check all probes API, ES and the actual LLM client only; it does NOT probe the topic feature flag. LLM base URL may be the origin, /api/chat or /api/generate, or a reverse-proxy prefix such as /ollama or /gateway/v1/ollama/api/chat (including trailing slashes). This matches the existing LLMClient suffix/appending behavior. The diagnostic never transmits or prints these URL paths. LLM path syntax is bounded to ordinary simple segments (no dot navigation, percent-escapes, doubled interior slash, userinfo, query or fragment). ES still requires an exact bare origin (empty path or a single slash): LLM normalization never applies to ES.

An endpoint with its hostname explicitly written as a numeric IPv4 address in
127/8 or RFC1918 10/8, 172.16/12, 192.168/16 may receive one TCP connection
with a two-second timeout. DNS hostnames, public addresses, link-local addresses
and IPv6 are categorically **not probed** by this first slice. No arbitrary URL
or override argument is supported. No DNS resolution, proxy, HTTP GET, TLS
handshake, redirect, credentials, SQL, writes, or model calls occur.

The tool never prints hostname, full URL, URL path, env-file path, user/password,
header, token, connection string, exception, or model name. JSON contains only
bounded configuration classification, the scheme and numeric port, and a separate
TCP observation. A URL containing embedded credentials, unexpected path/query,
fragments, or control whitespace is INVALID and no connection is attempted.

## Interpretation and exit codes

- configuration=RESOLVED means the selected runtime value is syntactically
  accepted, **not** that the service is functioning.
- tcp_probe=PASS and reason configured_tcp_connected mean only one TCP connect
  to the configured numeric private/loopback IP and port succeeded. The listener
  could still be another service. No application identity, auth, TLS certificate,
  Elasticsearch index/mapping, model presence/inference, SQL database, or Worker
  behavior has been verified.
- tcp_probe=FAIL means the bounded TCP attempt could not connect; it alone does
  not diagnose the reason (e.g. firewall vs no listener).
- tcp_probe=SKIP means no network attempt occurred (missing/invalid config,
  DNS/public/non-IPv4 outside scope, or --no-network).
- Exit 0: every selected **TCP-only** observation passed.
- Exit 1: at least one selected configuration invalid or TCP connect failed.
- Exit 2: selected observations are incomplete/skipped or preflight could not
  safely run.

All JSON carries mode=PARTIAL_ONLY_NOT_ACCEPTANCE and
schema=sraf_airgap_off1b_configured_tcp_preflight_v1. Do not map exit zero to
OFF-0 parent PASS, OFF-1B completion, or deployment FULL_LIVE.

## Next reviewed OFF-1B slices

1. Configured endpoint allowlist / actual bind identity, server TLS CA validation,
   bounded read-only HTTPS GET and safe credential interface for authenticated ES
   cluster/alias/mapping diagnostics, including mapping_incompatible.
2. Configured LLM backend discovery and bounded authenticated inventory/metadata
   checks for remote or local service; model names must not be logged.
3. Approved SQL read-only account / ODBC driver / schema diagnostics and worker
   readiness/heartbeat; Acceptance-only model inference and task processing.
4. Offline report provenance, dependencies and classification integrated only with
   a separately reviewed OFF-3 trustworthy runner.

The deployed operator may run this first-slice tool after the PR is reviewed,
CI passes, and its bytes are included in a verified deployment package. It must
not be interpreted as already deployed simply because GitHub contains the code.

## Codex exact-head remediation (2026-10-19)

- TOPIC_LLM_URL is a truthy feature flag, not an independent LLM endpoint. No network connection to its contents; --check topic-llm is classification-only SKIP.
- Launcher uses shell PORT (default 9002) and listens on all interfaces; test the numeric loopback bind target rather than PUBLIC_API_BASE, which may be a reverse proxy. The CLI process cannot prove the running supervisor used the same external shell environment.
- Accept the runtime LLMClient's /api/chat and /api/generate suffixes for MODEL_BASE_URL; validate host/port only, never expose the path.
- These corrections do not elevate a TCP connect to runtime PID attestation or live service verification.

## 2026-10-20 Codex follow-up — prefixed LLM paths

- Real LLMClient accepts a configurable /ollama or /gateway/ollama path prefix and appends /api/chat when needed. OFF-1B now derives the TCP-only host and port from these paths without treating the LLM path itself as an HTTP probe target.
- Continue refusing malformed URLs, nonnumeric hostnames, public or link-local destinations, credentials inside the URL, and query/fragment data. Reject dot-segment and interior doubled slash ambiguity to keep the preflight diagnosis bounded. These restrictions do not modify LLMClient behavior.
- ES_URL continues to accept only a bare origin and must never inherit LLM path-prefix rules. Passing this preflight still does not verify LLM or ES identity, TLS/authentication, inventory, or inference.

## 2026-10-20 fifth Codex review — raw URL validation

- URL delimiters '?' and '#' are prohibited outright, even when empty. urlsplit() converts empty query/fragment delimiters into empty strings, but actual LLMClient URL concatenation could otherwise turn /api/chat into query/fragment text. These malformed configs are classified INVALID without network activity.
- The 512-character raw MODEL_BASE_URL path bound is checked before trailing-slash normalization; an overlong path with hundreds of trailing slash characters must never be accepted. A path exactly 512 characters long remains valid if its normalized segments are safe. Negative and boundary regressions assert no unexpected TCP or secret output.

## 2026-10-20 second incremental slice — configured API HTTP health

The separate `tools/sraf_airgap_off1b_api_http.py` CLI extends the configured
TCP-only convenience without changing the first slice's API or widening network
scope. This is the first step toward a single, useful deployment diagnostics stage,
not a reason to redeploy immediately.

From the real deployed repository root, after this branch is reviewed, merged,
and deployed in a subsequent verified package:

    python tools/sraf_airgap_off1b_api_http.py --no-network
    python tools/sraf_airgap_off1b_api_http.py

The script reuses **the exact existing OFF-1B configuration bootstrap** and the
**reviewed OFF-1A strict bounded HTTP engine**. It observes only an anonymous
`GET /healthz` on numeric `127.0.0.1` at the launcher's shell `PORT` (default
9002), with OFF-1A's total 3-second monotonic deadline and 64-KiB body limit.
No host override, proxy, DNS lookup, redirects, auth, background work, SQL,
index queries, LLM model call, application import or Worker operation is added.
`PUBLIC_API_BASE` may be an external reverse proxy and is deliberately not
used to claim the API listener identity.

The output is one JSON document with schema
`sraf_airgap_off1b_configured_api_http_v1` and
`mode=PARTIAL_ONLY_NOT_ACCEPTANCE`. The result distinguishes configuration,
`http_probe` PASS/FAIL/SKIP, safe numeric HTTP status, and explicit
`service_identity=NOT_TESTED`, `worker_readiness=NOT_TESTED`,
`feature_acceptance=NOT_TESTED`. A HTTP 200 is **only /healthz reachable**;
it is not proof that the listening process belongs to SRA API or that other
services/Workers and end-to-end Report Jobs work. No host, URL, token, exception,
model ID or env-file path appears in JSON. CLI exits 0 for HTTP status 200, 1
for HTTP/config FAIL, and 2 for SKIP or incomplete.

The operator's diagnostic shell can have a different PORT environment from the
already-running launcher. Runtime supervisor PID/listener identity and actual
bind attestation still require a separately reviewed, read-only observation.
Do not treat this first HTTP slice as a replacement for authenticated ES HTTPS
Mapping, LLM inventory, SQL Server, worker heartbeat, or offline E2E evidence.

Deployment recommendation: bundle API HTTP, ES verified HTTPS/Mappings, and LLM
model inventory into the next useful OFF-1B deployment diagnostics milestone;
do not roll the Linux environment solely to try this incremental script.

## 2026-10-20 ES HTTPS / Mapping diagnostic slice (PR under review)

A separate standalone operator command now provides a safe, small Elasticsearch
identity and Mapping diagnosis. This is not a full SRAF acceptance check and
must not be run in the Linux production environment until the PR passes review,
is explicitly merged and packaged in a verified deployment.

    python tools/sraf_airgap_off1b_es_https_mapping.py --no-network
    python tools/sraf_airgap_off1b_es_https_mapping.py

    # EXPLICIT OPT-IN: makes exactly one intentionally invalid-password
    # authentication request, which can be audited or count toward lockout:
    python tools/sraf_airgap_off1b_es_https_mapping.py --verify-credentials

Configuration is derived exclusively from the existing dotenv bootstrap:
`ES_URL` (literal numeric RFC1918/loopback IPv4 **HTTPS origin only**),
`ES_USERNAME` + `ES_PASSWORD` (existing runtime Basic credentials), one
literal `ES_INDEX` or alias and the fixed repository
`agent/certs/http_ca.crt` trusted CA location. No manual destination, model,
certificate path, index or credentials are accepted on the command line.
Missing/unsafe settings are SKIP or INVALID, never silently probed.
Production Elasticsearch runtime currently disables TLS hostname matching;
**the diagnostic intentionally does not**. Both certificate chain and the
numeric IP's certificate identity must validate before sending Basic credentials.
If the deployment certificate is only valid for a DNS name, the result is
TLS identity failure, *not* an invitation to disable verification.

The default command opens at most three separate HTTPS connections to the
already allowlisted host:port: (1) ES identity GET / using configured Basic
credentials; (2) protected GET /_security/_authenticate identifying the
enabled Basic realm principal; and (3) GET /{literal-index}/_mapping.
A matching principal alone does not prove that the configured password caused
authentication when a reverse proxy may overwrite the Authorization header.
Thus the default `auth=NOT_VERIFIED` and exit code 2 cannot claim credential
verification even when a non-mutating Mapping probe passes.

Only if the operator EXPLICITLY opts in with `--verify-credentials` does
the command send a fourth GET to /_security/_authenticate using the same
username and a fresh, deliberately incorrect, non-disclosed password. It
must return HTTP 401 specifically; HTTP 403 may be a proxy authorization
denial without actually checking the password. Otherwise authentication
is FAIL/unverified and the Mapping GET is skipped. A verified positive principal and this negative
control are both required for `auth=PASS` and exit 0. A failed login
may generate an audit event, contribute toward security lockout thresholds
or trigger an alert; DO NOT select this option without operational approval.
No negative login test occurs with the default invocation or --no-network.
Each request has a
3-second total monotonic asyncio deadline, bounded header/body sizes and
fail-closed handling of unsupported framing. No redirects, DNS lookups,
HTTP proxy, model inference, SQL operation, index writes, bulk fetch,
search/query, HEAD or non-GET requests. All remote response content and raw
exception messages stay out of the report.

Mapping comparisons reuse `agent.external_capabilities.mapping_compatibility`,
the same predicate used for Requirement acceptance. A verified incompatible
mapping reports `mapping_incompatible`; 404 reports `es_index_missing`;
401/403 reports access denied; more than one resolved index/alias entry is
SKIP as ambiguous. Mapping PASS does **not** establish query correctness,
production selector provenance or FULL_LIVE.

Output: `schema=sraf_airgap_off1b_es_https_mapping_v1`,
`mode=PARTIAL_ONLY_NOT_ACCEPTANCE`, separate `https_probe` and
`mapping_probe` states, and fixed redacted reason codes. Never emit the
index/alias, host/IP, full URL, private certificate path, credential, cluster
name, mapping fields, model name or raw exception. Exit 0 requires valid
HTTPS identity + protected credential challenge + mapping all PASS;
exit 1 for evidence-supported FAIL, 2 for SKIP/incomplete/unverified auth.
Three independent TLS handshakes (four with credential challenge) are
aggregated; if any later handshake fails, the overall TLS result is no
longer PASS. A later certificate verification failure explicitly reports
tls_validation=FAIL, including on the Mapping GET.

Limitations requiring later work: (a) this early bounded probe requires a
single literal ES_INDEX and a server certificate identifying the numeric IP,
while some deployments use multiple index selectors or hostname-only certs;
(b) it intentionally rejects chunked responses and responses above its fixed
body bound rather than risk a false PASS; (c) mapping compatibility alone does
not resolve the known live `mapping_incompatible` deployment blocker without
actual operator-run evidence. A later independently reviewed extension may
support multiple approved selectors, trusted remote hostname pinning, verified
aliases and richer transport framing, without weakening TLS or sending data.

### 2026-10-20 Codex P2 authentication correction

- First exact-head review identified that anonymous root/mapping HTTP 200 could be mistaken for authenticated credentials. A protected Elasticsearch Security API GET /_security/_authenticate is now required between root identity and Mapping checks. auth=PASS requires exact username, enabled principal, authentication_type=realm and a nonempty realm type. Wrong identity, malformed response or access denial fail closed, and missing Security API remains incomplete. Mapping is not attempted when the protected principal is unverified.
A verified principal without operator-authorized bad-password control
can still permit a *partial, explicitly unauthenticated* read-only Mapping
diagnosis, but cannot produce `auth=PASS` or exit 0.
All original TLS verification, private-IP target scope and redaction constraints remain.

### 2026-10-20 second Codex P2 remediation

- A protected /_security/_authenticate HTTP 200 with matching principal can
  still be served by an intermediary replacing the supplied Authorization.
  Do **not** report auth=PASS from that evidence alone. Safe default reports
  auth=NOT_VERIFIED and does not trigger a failed-login audit; optional
  --verify-credentials performs an explicitly authorized one-time invalid
  password challenge, requires HTTP 401 (not proxy-supplied 403), then allows authenticated Mapping.
- TLS is an aggregate of every independent HTTPS connection, not just the
  first root request. Later authentication/control/Mapping TLS failures downgrade
  the overall certificate identity state and prevent any final PASS claim.
- These are local program/test changes only; no Linux deployment proof has been
  collected, no SRAF parent FULL_LIVE or OFF-3 approval, and PR is unmerged.

- More conservative boundary: HTTP 403 from the deliberately invalid password check is not proof the password failed authentication; it might be a proxy's ACL. Only HTTP 401 is accepted as a negative control. The failed-login audit/lockout caveat remains, and the default does not send a control.

### 2026-10-20 third Codex review — certificate failure exit status

- An independently confirmed later TLS certificate identity failure is a true
  observed FAIL, not an incomplete SKIP. The CLI now returns exit code 1
  whenever aggregate `tls_validation=FAIL`, even if `https_probe=PASS`
  and `auth=NOT_VERIFIED` with `mapping_probe=SKIP`. Added CLI regression tests
  for late failures on protected authentication, explicitly opted-in invalid
  credential challenge and mapping requests. Non-TLS transport uncertainty
  stays distinguishable from proved certificate validation failures.
