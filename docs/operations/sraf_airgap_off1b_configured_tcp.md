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
- API: PUBLIC_API_BASE
- Elasticsearch: ES_URL
- Main LLM: MODEL_BASE_URL (whether MODEL_ID is set is reported as boolean)
- Topic LLM: TOPIC_LLM_URL (whether TOPIC_LLM_MODEL is set is boolean)

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
