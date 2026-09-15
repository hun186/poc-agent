# SRA Self-Bootstrapping Live-Acceptance Package — Command Review v1.4

## Review control

- Repository: `hun186/poc-agent`
- Hosted branch: `main`
- Hosted baseline supplied and locally matched: `548b08a4fb0ee719ed15dba91260db7ce0612201` (PR #243 merge)
- Hosted PR #243 head supplied: `90c4df44fc24375fae77228a55e0ac99877ce58b`
- Hosted refresh attempt: blocked by the environment's HTTP 403 CONNECT proxy; no newer hosted SHA is claimed excluded.
- Previous runbook baseline: `d21ce42c4abd740a50cb7d4d076bb04253cd2dca`
- Reviewed runtime baseline: `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`
- Input/output versions: v1.3 → v1.4
- Scope: documentation and project memory only; runtime code changed: **NO**.

Static command review is not live deployment acceptance. SD-1 through SD-7 were
not executed and remain **PENDING**.

## Source evidence and dispositions

### CLR4-001 — BLOCKER — CONFIRMED; FIXED

`run_sra_api.sh` defines `PORT="${PORT:-9002}"`, while v1.3 queried only TCP port
9002 before invoking the launcher. v1.4 derives the preflight port from the same
contract, rejects non-decimal and out-of-range values with
`SD_3_PRECHECK=FAIL reason=invalid_runtime_port`, and checks the selected port.

The v1.3 `lsof` handling could not safely treat every status 1 as proof of no
match because status 1 can also represent an authority/tool error. v1.4 instead
performs a bounded, exact Linux `/proc/net/tcp` and `/proc/net/tcp6` LISTEN-state
query. A matching listener blocks without signalling or modifying its owner.
Missing, unreadable, malformed, timed-out, or otherwise failed authority returns
`SD_3_PRECHECK=FAIL reason=listener_authority`. Every negative branch returns
before `./run_sra_api.sh`.

### CLR4-002 — MAJOR — CONFIRMED; FIXED

The configuration defaults include a 45-second lease duration, a 10-second
`heartbeat_interval`, and a 2-second polling interval. The current coordinator
does not implement an independent fixed heartbeat loop: after acquisition it
renews when `run_once()` begins, so elapsed workload/cycle time and polling affect
the renewal interval.

v1.4 removes the inaccurate fixed-renewal claim. It retains the greater-than-40-
second check solely as an operational execution budget derived from the explicit
10-second launcher shutdown, 20-second observation, 5-second OpenAPI, and
5-second SQL connection bounds. Insufficient margin remains BLOCKED before
restart mutation. This budget is expressly separate from renewal semantics.
Authoritative PASS still requires both `after_generation > before_generation`
and `after_sql_now < before_expires_at`; the temporal proof is unchanged.

### Package/overlay identity clarification

SD-1 is unchanged. Package/overlay mode remains BLOCKED unless an authoritative,
release-produced, tamper-evident manifest binds deployed bytes to the reviewed
runtime identity. No package builder or runtime implementation is included.

### Additional findings

No CLR4-003 or later finding was identified in the narrowly reviewed command
paths.

## Static validation

Static validation extracted all Bash fences for `bash -n`, compiled every Python
heredoc, checked failure propagation and forbidden patterns, and exercised the
SD-3 port authority through isolated synthetic `/proc` fixtures. Cases covered
default port 9002 free, overridden port 9010 occupied while 9002 is free, invalid
PORT, authority failure, and proof that no negative path reaches a fake launcher.

The SD-6 predicate tests cover generation increase before old expiry (accept),
generation increase at/after old expiry (reject), and insufficient operational
margin (BLOCKED). A static wording assertion rejects the superseded fixed
10-second-renewal sentence. These tests neither start SRA nor contact SQL.

## Live boundary

- SD-1 through SD-7 executed: **NO**
- Private SQL live acceptance: **NO**
- SRA lifecycle changed: **NO**
- Credential mutation: **NO**
- Golden Path replayed: **NO**
- Agent/ES/LLM/DOCX: **NO**

## Decision

`COMMAND-LEVEL REVIEW v1.4 = PASS`

`SD-1 THROUGH SD-7 LIVE EXECUTION = PENDING`
