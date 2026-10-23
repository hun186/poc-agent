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

A separate standalone operator command from merged PR #295 provides bounded
Elasticsearch identity and Mapping diagnosis. It is not full SRAF acceptance.
The proposed PR #296 changes the operator CLI default to warning-only
**diagnostic mode**, while preserving explicit --strict-ip-san for identity
verification. Do not deploy these new flags until review, explicit Merge
and a verified incremental release package.

    python tools/sraf_airgap_off1b_es_https_mapping.py --no-network
    python tools/sraf_airgap_off1b_es_https_mapping.py

    # Explicit strict server-IP identity diagnostic:
    python tools/sraf_airgap_off1b_es_https_mapping.py --strict-ip-san

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
Production Elasticsearch runtime currently disables TLS hostname matching.
The **new PR #296 default Quick/Diagnose mode** retains the trusted CA chain,
but reports a relocated numeric IP SAN mismatch as an explicit warning. The
operator's existing Basic username/password are still sent to this
CA-signed yet IP-identity-unverified endpoint; this is a concrete credential
interception risk even on a disconnected LAN. TLS identity and Mapping cannot
be certified PASS from this observation: warn and exit 2.
Use --strict-ip-san to require both CA chain and numeric IP SAN match before
sending credentials. --verify-credentials also implicitly selects strict
mode, and never combines with warning mode. The old --warn-only-ip-san flag
remains a compatibility alias for the new Quick default. No mode in this
standalone CLI constitutes FULL_LIVE acceptance.

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
(b) as of PR #297 it accepts bounded, single HTTP/1.1 chunked framing
or unambiguous Content-Length (2 MiB Mapping, 64 KiB root/auth), while refusing
unbounded/ambiguous responses; (c) mapping compatibility alone does
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

### 2026-10-20 fourth Codex review — 403 gateway-denial classification

- A 401 from the protected `/_security/_authenticate` endpoint is an observed credential rejection. HTTP 403 can be caused by a reverse proxy denying the protected path **without checking the supplied Basic credentials**. Accordingly protected-endpoint HTTP 403 now yields `auth=NOT_VERIFIED`, `reason=es_auth_access_denied` and incomplete exit code 2, not `es_auth_rejected` / exit 1. No negative password control or Mapping GET occurs after 403, including if `--verify-credentials` was requested. The JSON remains redacted and `PARTIAL_ONLY_NOT_ACCEPTANCE`.

### 2026-10-20 fifth Codex review — root-path 403 classification

- On the very first ES identity `GET /`, a 403 might be emitted by a gateway
  that never evaluates the Basic header, or by Elasticsearch after successfully
  authenticating a principal that lacks permissions. Treat it as
  `https_probe=FAIL`, `auth=NOT_VERIFIED`, `reason=es_root_access_denied` and
  exit code 1 (root identity could not be observed), **not** the incorrect
  `es_auth_rejected` finding. Retain HTTP 401 as the rejected-credentials
  classification. Neither root-denied outcome sends a subsequent authentication,
  negative-password control or Mapping request, even with --verify-credentials.
  The only visible output is fixed redacted JSON.

### 2026-10-21 sixth Codex review — nested Mapping container validation

- A syntactically valid JSON Mapping response can still contain non-object
  `mappings.properties`, a nested `properties`/`fields` array or a malformed
  field node. The application `mapping_compatibility()` assumes dict-based
  field structures; passing these values through could raise `AttributeError`
  rather than producing a redacted operator result. The standalone diagnostic
  now validates the shape of all traversed Mapping property/field containers
  using bounded iterative traversal (maximum 4096 field nodes), then calls
  the original application predicate unchanged for actual compatibility.
  Invalid containers or unexpected attribute lookup errors fail closed as
  `mapping_probe=FAIL`, `reason=es_mapping_response_invalid`, exit 1;
  raw response content, index names and exception details are not printed.
  Regression tests include root/nested arrays, scalar values, unrelated
  fields, CLI output and redaction; legitimate Mapping still uses existing
  compatibility behavior. This does not prove the deployed ES Mapping passes.

### 2026-10-21 seventh Codex and confirmed external Hosted CI blocker

- JSON Mapping responses with top-level arrays/scalars/null are structurally
  invalid, even when the array has zero or multiple entries. The OFF-1B ES
  diagnostic now classifies these as `FAIL/es_mapping_response_invalid`
  (CLI exit 1); only a Mapping dictionary with zero/multiple target keys
  retains `SKIP/es_mapping_target_ambiguous`. Added functional and CLI
  regression tests with no raw data leakage.
- Historical GitHub Actions UI annotation **confirmed** the job was not
  started before the repository visibility change due to payment or Actions
  spending limit (exact: "The job was not started because recent account
  payments have failed or your spending limit needs to be increased").
  The old fail-marked jobs with empty steps/404 log blobs were **NOT_EXECUTED**,
  not pytest failures. The Ubuntu 26 runner-image migration notice was
  informational, not the failed-job cause.
- **Current authoritative update, 2026-10-21:** the repository is now PUBLIC.
  After that switch, Hosted Actions rerun **#39533967611** on head
  `c0f663bcd5e69472e40060c3afc0eed675a6d3a6` SUCCEEDED (513 pytest PASS,
  19 OFF-0 schema-only contract checks PASS). The separate exact-head Hosted
  Actions **#39534484218** on head
  `b6f8c4181426084cf039baeb979d586b2aeeda38` also SUCCEEDED (513 pytest
  PASS in 2.01 seconds, 19 OFF-0 schema-only contract checks PASS).
  Both runs actually started and passed compile/install and config-only smoke.
  The prior "do not rerun due to billing" instruction is superseded; continue
  normal exact-head CI as the PR changes.
- Ninth-round Codex on `b6f8c4181426084cf039baeb979d586b2aeeda38`
  identified an outdated PRIVATE/billing status in `.codex/memory.md`; its
  active summary was corrected to PUBLIC, current real CI successes and
  historical billing block. Fresh exact-head Codex and CI after edits remain
  separate merge gates. No Linux runtime acceptance or merge.

### 2026-10-21 tenth Codex review — protected authentication transient errors

- On the protected `GET /_security/_authenticate` path, **only HTTP 401**
  proves rejected Basic credentials. HTTP 403 signals ambiguous ACL/gateway
  denial (`auth=NOT_VERIFIED`, `es_auth_access_denied`, exit 2). HTTP 404 is
  unavailable/incomplete. HTTP 429, 500, 502 and any other unexpected
  status likewise cannot prove a bad password: `auth=NOT_VERIFIED`,
  `reason=es_auth_http_unexpected`, exit 2. These failures do not initiate
  Mapping access or any deliberately invalid-password control, even when
  `--verify-credentials` was requested. Results never display response bodies,
  credentials or private destinations. An independent observed TLS FAIL still
  forces exit 1. CLI negative tests cover common transient status and gateway
  codes with and without explicit credential-control opt-in.

### 2026-10-21 eleventh Codex — deliberately invalid-password challenge outcomes

- The optional `--verify-credentials` sends a deliberately incorrect Basic
  password only after a verified positive principal. The negative check **PASS**
  requires HTTP 401, never 403. When a proxy/gateway or server responds with
  HTTP 403, 429, 5xx, redirects, 404, other unexpected codes, or HTTP 200
  without an attested matching principal, the diagnostic cannot prove whether
  the invalid password was examined. It now reports
  `credential_control=INCOMPLETE`, `auth=NOT_VERIFIED`,
  `reason=es_credential_control_unverified`, CLI exit 2, and never sends a
  Mapping GET. A control HTTP 200 containing the matching enabled Basic realm
  principal means even the deliberately invalid password was accepted or
  replaced, so it remains an evidence-supported FAIL (exit 1). A control HTTP
  401 with previous positive principal permits `auth=PASS` and Mapping GET.
  Control request count and failed-login audit/lockout warning remain unchanged;
  default mode never sends intentionally invalid credentials. Regression tests
  include 200 positive/unattested, 302, 403, 404, 408, 429, 500, 502 and 503
  with correct CLI return codes, request bounds and redaction.
- GitHub Actions #39543476662 on previously reviewed head
  `e63c4dbb5bd9c38d0aaba3f005228dae1ae3418a` actually succeeded with
  527 pytest PASS and 19 OFF-0 schema-only contract PASS, plus green compile,
  dependencies and config-only checks. This remains historical previous-head
  evidence until new exact-head CI runs; it is not Linux deployment acceptance.


### 2026-10-22 Docker IP relocation: optional IP SAN warning (PR #296)

The new **default is Quick/Diagnose WARN**, not strict server identity validation. Moving an ES Docker container to a new private IP can leave a CA-valid leaf certificate with the old IP SAN. The default allows the bounded read-only probe to continue while clearly warning. The legacy explicit alias remains supported:

    python tools/sraf_airgap_off1b_es_https_mapping.py --warn-only-ip-san
    echo "Exit code: $?"

In default Quick mode or when explicitly using the alias, CA chain validation remains CERT_REQUIRED, connections remain fixed to the existing numeric private IPv4 ES_URL with no proxy, DNS, redirect or writes. The TLS peer certificate SAN is inspected before sending Basic Authorization. Any IP SAN mismatch is reported as ip_san_policy=WARN_ONLY, identity_warning=true, tls_validation=WARN, and a compatible/incompatible mapping observation is demoted to mapping_probe=WARN with the *_identity_unverified reason. Exit 2 means INCOMPLETE; never claim TLS identity PASS, Mapping acceptance or FULL_LIVE. Genuine CA-chain/certificate errors, later TLS failure, and invalid/malformed responses are not automatically waived.

**Important risk:** Because the IP identity is not verified, **the default Quick diagnostic** still sends the configured Basic username/password to a CA-signed endpoint which may not be the intended Elasticsearch server. A CA-signed impersonator or wrongly routed Docker connection could capture the credentials. Use only after independently verifying the private network, Docker host, routing and certificate provenance. Prefer renewing the leaf certificate with current IP SAN or separately reviewing a stable verified TLS DNS name for production acceptance. This opt-down is intentionally limited to this standalone non-authoritative operator CLI. Do NOT use the Quick default to certify identity; run --strict-ip-san or --verify-credentials when the deployment needs strict TLS identity assurance.

The explicit --warn-only-ip-san flag cannot combine with --verify-credentials (which deliberately submits an invalid password). Calling --verify-credentials by itself implicitly turns on strict IP SAN checking. The normal invocation is warning-only Quick/Diagnose, and --no-network still performs no socket I/O. This script never updates Elasticsearch runtime TLS settings or Docker certs; operator-run real mapping_incompatible evidence and FULL_LIVE acceptance remain separate.


### 2026-10-22 OFF-1B Mapping HTTP chunked support (PR #297)

Live operator evidence after PR #296: Mapping `GET /{literal-index}/_mapping` returned **HTTP 200, `Transfer-Encoding: chunked`, no `Content-Length`, and identity encoding**. The existing diagnostic required a single `Content-Length` and therefore returned `es_https_transport_unavailable_ip_san_mismatch` before it could compare the Mapping. This does **not** demonstrate `mapping_incompatible`.

PR #297 adds bounded HTTP/1.1 single `Transfer-Encoding: chunked` parsing with strict CRLF, cumulative dechunked body limit, chunk count/line limits, bounded trailers, no stacked codings or ambiguous `Content-Length` + Transfer-Encoding framing. Mapping-specific decoded-body maximum is 2 MiB; root and protected auth remain at 64 KiB. A single 3-second absolute GET deadline, fixed private IPv4 origin, CA chain, optional IP SAN warning, header bounds, redaction, no redirects/proxies/DNS/writes and no compression remain intact.

After review and explicit merge, the operator can incrementally deploy only the updated `tools/sraf_airgap_off1b_es_https_mapping.py` plus referenced runtime unchanged and rerun `python tools/sraf_airgap_off1b_es_https_mapping.py`. On the Docker IP relocation, `tls_validation=WARN` and `identity_warning=true` still mean unverified peer identity; `mapping_probe=WARN` with `*_identity_unverified` reason means an observation only, never FULL_LIVE/feature acceptance. Header tests and hosted CI do NOT establish actual Mapping compatibility. Confirm the exact Linux command output separately.

PR #297 also enforces `Content-Encoding` to be absent or **a single `identity` value** for both fixed-length and chunked responses. Compressed, duplicate or stacked content encoding is rejected even if the returned bytes happen to look like JSON; the CLI does not decompress remote data or misreport a Mapping compatibility PASS. This matches the live operator observation `Content-Encoding: IDENTITY`.


PR #297 additionally verifies complete constrained chunk-extension token syntax using the existing OFF-1 chunk-head parser; merely printable but malformed extensions (for example, `;foo==bar`) are rejected, not silently treated as a valid Mapping response. The numeric chunk-size digits and total line/decoded-body bounds remain separate limits.



### 2026-10-22 configured Elasticsearch index discovery (separate, partial-only)

After updating the reviewed tools, run from the repository root:

```bash
python tools/sraf_airgap_off1b_es_index_discovery.py --no-network
python tools/sraf_airgap_off1b_es_index_discovery.py
# Optional: strict verified-IP SAN (recommended for secure identity checking)
python tools/sraf_airgap_off1b_es_index_discovery.py --strict-ip-san
```

The tool discovers literal selectors from the effective `ES_INDEX`, the actually selected `config/indexes.yaml` / `indexes.<APP_ENV>.yaml` or explicit `INDEXES_CONFIG(S)` overrides, and explicitly configured `REQUIREMENT_E2E_ES_INDEX`. Topic indices retain index_loader's additive-merge order, including numeric or boolean YAML topic keys when their values declare indexes. Explicit `INDEXES_CONFIG`, `INDEX_CONFIG` or `INDEXES_CONFIGS` can select deployment-managed YAML files **outside the checkout**, including absolute paths; the diagnostic reads only those selected files (max 8 files, 256 KiB each) and records `external_index_config_not_release_attested` without disclosing file paths. This is runtime-selector parity, **not** verification that external bytes belong to the reviewed release; external file provenance must be checked separately before formal acceptance. Implicit default configs remain repository-local, and an implicit repo path escaping through a symlink is not read. It never performs cluster-wide enumeration or wildcard expansion; only a bounded operator-selected list of up to 12 names is queried by read-only Mapping GET. It does not mutate indexes, query documents, run SQL, test LLM inference or prove production RAG behavior.

JSON distinguishes required runtime default, optional topics and explicit E2E fixture; it reports individual failures/warnings and continues other safe selector checks. If the runtime's configured **or built-in default** E2E fixture index name matches a production selector, discovery reports a redacted `e2e_production_selector_conflict` and `INVALID_CONFIG`, exits 1, and makes no Elasticsearch requests. A production alias resolving to that fixture is also a conflict. The implicit fixture is protected even when `REQUIREMENT_E2E_ES_INDEX` is unset, but it is not independently probed unless the operator explicitly selected an E2E fixture. This known local conflict is not affected by WARN_ONLY TLS identity policy. If a selected nonempty YAML root is not an object, or YAML syntax is malformed (including recursion-depth failures), the runtime cannot establish an effective index configuration: discovery marks `selector_discovery=INVALID_CONFIG`, clears all candidates, makes **zero Elasticsearch network requests**, and returns CLI exit 1. Empty/null/falsy YAML roots keep the loader's empty-mapping fallback. A YAML field such as `default_indexes: 123` or `indexes: 123`, and an unreadable or invalid-UTF-8 selected YAML, also stop discovery before Elasticsearch access. The report uses redacted `index_config_indexes_invalid` or `index_config_unavailable` notes. When a selected config is rejected by an operator safety limit, discovery likewise cannot safely reconstruct effective selectors; no network probe is attempted. Even an explicitly configured `ES_INDEX` is not probed while runtime YAML loading is invalid. These are fixed redacted reason codes, never user file paths or index names. A historical-looking name in active configuration is **not** automatically legacy. A legacy singular `default_index` is ignored by the current loader, and fallback development defaults are not attested production indexes. Mapping role checks are intentionally lighter than formal Requirement E2E; `query_probe=NOT_TESTED` and `feature_acceptance=NOT_TESTED` even when static Mapping PASS.

By default index names and internal selectors are redacted. An authorized operator may explicitly use `--show-index-names` **only** on secure local output, never in shared logs or public tickets. CA-signed peers with mismatching IP SAN remain WARN_ONLY and may still receive Basic credentials: do not use this mode without separately trusted routing and CA/certificate provenance. `--strict-ip-san` fails closed on SAN mismatch. Normal exit 2 means partial/incomplete; exit 1 means an evidence-backed failure. Neither exit code establishes FULL_LIVE acceptance. The existing single-index CLI remains supported without changes to its default behavior.
