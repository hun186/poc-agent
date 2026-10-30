# Project Memory — SRAF

## Current Summary

- **SRAF is the core report system.** Production FastAPI/Agent/LLM/Elasticsearch/SQL Server/Word/DOCX remain real and authoritative, with optional Product Task/Requirement v4 Version/Snapshot, Schedule/Handoff, owner-scoped Report Job Worker and RBAC. Do not introduce mock success, a second auth authority, schedule queue or report engine.
- **Ordinary startup is not operator E2E**: merged PR #319 separated heavy LLM/ES E2E probes from normal API lifespan; no production SDK timeout enlargement is implied. Operator-triggered verified preflight uses a cooperative budget, immutable per-process E2E Plans and same-host/UID locks/opaque generation fences, not distributed atomic cross-host authorization or hard SDK cancellation. Already-admitted pinned Jobs may complete after later revalidation.
- **Trust/evidence**: Strict OFF-1S API listener proof scans exclusive /proc socket ownership before sending Bearer/login credentials; FD_LIMIT/procfs restrictions fail closed. OFF-1U weaker local PID/socket numeric proof is anonymous only, never sufficient for credentials. No exposed secrets, hosts, PID, Job IDs, private SQL registries, native exception text or payloads in operator JSON.
- **Linux observations are partial**: OFF-1U low-load vs busy (3 samples each) showed API RSS ~202.5 MiB/70 threads vs 199.3 MiB/70 threads, but did NOT establish GPU/Ollama/ES root cause; Ollama may be in a separate container. Strict ES TLS CA+IP SAN and mapping, private SQL schema/permissions, actual Worker lease/Handoff, authorized real Agent/LLM/DOCX, browser interaction and OFF-2–5 airgap/restore are NOT TESTED by Hosted CI.

## Current Focus — Draft PR #340 (explicit strict ES identity/mapping)

- Branch `feat/sraf-off1-es-strict-optin-20261031` adds an **explicit opt-in**, `--probe-es-tls-mapping`, with optional exact argument in root Bash launcher. Ordinary `quick` and `diagnose` never request authenticated ES HTTPS. Selecting the flag requires `--suite diagnose`, excludes no-network and live-report. Existing OFF-1B `_observe` uses strict CA+numeric-IP SAN and bounded read-only GET of root, protected principal and selected index mapping; no DNS, relaxed TLS, password-negative challenge, search or writes. Evidence is only fixed redacted enums, no host/selector/CA/secret/HTTP body.
- **Trust boundary**: verifying a principal from one protected GET does not independently prove the supplied Basic password was honored (proxy substitution possible). This intentionally skips invalid-password challenge and cannot return an overall credential-attested PASS; even TLS/Mapping PASS is reported as INCOMPLETE (exit 2), while identity/mapping failure yields FAIL (exit 1). Eight manual gates including `es_tls_ca_san_mapping` remain NOT_TESTED; actual Linux HTTPS/IP SAN and configuration have not been tested.
- Added focused projection, shell allowlist and hub flag regression; integrated canonical OFF-1B HTTPS/mapping tests and 19 OFF-0 in Hosted workflow. New final-head CI and formal Codex review required, then separate user permission for merge.

## Recent Outcomes

- PR #339 OFF-1H passive Worker advisory identity merged with user authorization to main squash `b758c2ef944ed6bedd1e63c3654291d18d30a785`, final HEAD `9f8a5858`, Hosted #41100220011 SUCCESS (75 Python + 19 OFF-0), formal Codex CLEAN/no threads. It did not certify real Schedule/Handoff E2E.

- PR #336 (one-command operator Report Job/UI acceptance) squash merged `10e5dc4800085e02aaad58c260d038b5dfdd9a79`: bounded loopback health/UI, strict OFF-1S before opt-in real single Report Job and DOCX; installed application Python required, no extra offline pip.
- PR #337 (read-only-by-default OFF-1 unified hub) squash merged `e44ae58ddf64f94938a368ceb4726bd3d3f8a658`: host disk/ODBC, HTTP/UI/listener, optional private TCP diagnose, separately opt-in real Job; private O_NOFOLLOW dirfd evidence, eight full gates NOT_TESTED; exact-head Hosted/Code Review CLEAN.
- PR #338 (root `run_sraf_airgap_off1_diagnose.sh` Bash wrapper) user-approved squash merged `97f8b81a426a4c98777dd7668dc0143dbf6c0196`; final HEAD `6795fbfd` Hosted #41097544331 SUCCESS (29 Python +19 OFF-0), formal Codex CLEAN. Shell auto-selects project root and saves evidence in `$PROJECT_ROOT/sraf-acceptance-results/` (already gitignored), propagates Python exit status, and never adds `--live-report`.
- Earlier #333–335 merged DataAgent LLM timing, durable Report Job stage tracking, and authenticated browser Report Job progress panel. Real browser/private Linux validation is still a separate acceptance step.

## Open Handoffs

- PR #340 final HEAD Hosted strict ES + shell/hub tests, 19 OFF-0 and formal Codex review with no outstanding P1/P2; no merge without separate permission. No claim of real private ES identity/credentials in Hosted sandbox.
- Independently verify configured ES CA/IP SAN/Mapping and endpoint scope; previous IP-SAN mismatch under warn-only may be lower assurance; private SQL Server v4 schema, source, ODBC18, least-privilege SELECT, Worker namespace and Schedule/Handoff claim/lease/renewal/reconciliation, actual LLM/Agent/DOCX and UI/mobile, package/offline upgrade/restore OFF-2–5. No automatic production mutation, schedule claim or model inference during diagnostic-only actions.
- Preserve deployment output dirfd constraints. A group-writable SRAF ancestor can cause `output_ancestor_writable` rather than a successful JSON file; never bypass no-follow/private directory validation to force PASS.
- Reuse `.codex/architecture.md`, `api_contract.md`, `known_issues.md`, `decisions.md`, `backlog.md` as needed. Never silently promote mocked/fixture/Hosted OFF-0 evidence to full live acceptance.

## Archived History

- `.codex/archive/memory.md-20261030-173339.md` — **entire byte-identical pre-compaction active memory** (19,412 characters, Git blob SHA `fb77ea1fe7d4794204aa351520b14ac11f63e2c8`), independently re-fetched and SHA verified before this rewrite. Contains all 20 accumulated dated records and PR #336–338/Codex detailed progress; use only when historically necessary.
- `.codex/archive/memory.md-20261030-123000.md` (prior full-compaction record) and `.codex/archive/memory.md-20261029-203755.md` remain preserved for earlier research.
- 2026-10-31 compaction performed per AGENTS.md as a new dated record would cross the 20-work-record threshold. Verified archive first; this summary retains active contracts, latest successes, and all distinct unresolved gates. Revalidate Hosted after rewriting.
