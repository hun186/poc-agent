# SRAF Project Handoff

## Current Focus

- **2026-10-31 current Draft PR #341** (branch `feat/sraf-off1-sql-read-optin-20261031`): optional `--probe-sql-read` in existing OFF-1 one-click Bash/Hub reusing canonical OFF-1G fixed `SELECT CAST(1 AS int)` with ODBC 18 `Encrypt=Yes;TrustServerCertificate=No;ApplicationIntent=ReadOnly`. Require separate operator-supplied 5 `SRAF_OFF1G_SQL_*` variables, no production SQL Registry, no application table data, no schema inspection or mutation. Explicitly reject quick/no-network/live-report combinations. Redacted SQL-01 adapter can PASS fixed constant-only, SKIP missing identity/driver/transport and FAIL wrong response. Complete SQL v4/schema/source/permissions remains NOT_TESTED. Exact-head Hosted tests (including original OFF-1G), formal Codex clean and separate user authorization required before Merge.
- **PR #340 merged** 2026-10-31 10:53 Asia/Taipei squash `6631806f5ac37e57a536a05ef730ad6867c95b3c`, final HEAD `a5b5807b89ae`, 337 Python +19 OFF-0 PASS, formal Codex CLEAN, old P1 deferred import fixed. Opt-in strict ES CA/IP SAN/Mapping mode remains partial, no default authenticated ES requests.
- PR #339 merged `b758c2ef944ed6bedd1e63c3654291d18d30a785` passive Worker identities; PR #338 merged `97f8b81a426a4c98777dd7668dc0143dbf6c0196` root Bash launcher; PR #337 merged `e44ae58ddf64f94938a368ceb4726bd3d3f8a658` OFF-1 unified hub; PR #336 merged strictly authorized one-live-Job CLI.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Complete PR #341 exact-head Hosted CI (canonical OFF-1G SQL read, hub+shell focused tests, OFF-0 19), formal Codex Review and all threads, then await separate explicit user Merge authorization. #336–340 are already merged.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
