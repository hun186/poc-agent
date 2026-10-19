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
