# SRAF Project Handoff

## Current Focus

- **2026-10-31 OFF-4 incremental branch `feat/sraf-off4-redacted-text-report-20261031`** adds a Chinese human-readable TXT companion to one-command OFF-1 JSON diagnostics. The renderer accepts only closed, static check/status names and static remediation text; it never interpolates native errors, endpoints, credentials, raw reason codes or payloads. Both files are mode 0600 through the existing pinned no-follow private dirfd; a TXT write failure returns INCOMPLETE (exit 2) rather than forging report success. Default probe behavior is unchanged. Current Hosted CI, formal latest-head Codex Review and merge are pending.
- **PR #341 MERGED** 2026-10-31 squash `4dd2ba427a3c1b355351b1c256d894d3404a2d8f`, final HEAD `554eb7239803`: 424 Python tests and 19 OFF-0 PASS, exact-head formal Codex CLEAN, resolved earlier P2. Optional dedicated ODBC18 SQL constant SELECT is available with `--probe-sql-read`, but SQL v4/schema/source/permissions and private Linux remain NOT_TESTED.
- **PR #340 MERGED** squash `6631806f5ac37e57a536a05ef730ad6867c95b3c`, final HEAD `a5b5807b`: strict ES opt-in remains partial, no default authenticated ES. Earlier PR #336–339 merged.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Complete OFF-4 TXT regression Hosted CI and formal Codex Review on its exact latest HEAD; correct valid findings and merge only once all current gates pass. PR #336–341 already merged.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
