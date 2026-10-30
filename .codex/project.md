# SRAF Project Handoff

## Current Focus

- **2026-10-31 Draft PR #340 (branch `feat/sraf-off1-es-strict-optin-20261031`)** extends the existing OFF-1 one-click hub with separately selected `--probe-es-tls-mapping` (also an exact allowlisted Shell flag). Normal `quick` and `diagnose` continue without authenticated ES requests. Opt-in reuses canonical OFF-1B strict HTTPS `_observe`: fixed local CA, private numeric IPv4, CA+IP SAN mandatory, limited GET root/protected principal/mapping; no incorrect-password challenge or search/query/write. Redacted fixed-status JSON; strict TLS and mapping partial observations without independently confirmed Basic authentication keep an INCOMPLETE top-level exit 2; detected TLS/mapping FAIL yields exit 1. Full ES manual gate remains NOT_TESTED. Run latest-head Hosted + formal Codex, no merge without explicit separate user approval.
- **PR #339 is MERGED** (2026-10-31 02:28 Asia/Taipei) squash `b758c2ef944ed6bedd1e63c3654291d18d30a785`; final HEAD `9f8a5858`, 75 Python tests and 19 OFF-0 PASS, formal Codex CLEAN. OFF-1H passive Worker identities advisory only, without SQL/Handoff E2E.
- PR #338 merged `97f8b81a426a4c98777dd7668dc0143dbf6c0196`; root Bash launcher project-local secure evidence dir. PR #337 merged `e44ae58ddf64f94938a368ceb4726bd3d3f8a658`; unified default-read-only hub. PR #336 merged existing strictly authorized one-live-Job CLI.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Complete PR #340 exact-head Hosted CI (canonical OFF-1B ES TLS/Mapping and focused shell/hub regression, OFF-0 19), formal Codex Review, resolve any P1/P2 and obtain separate explicit user Merge authorization. #336–339 are already merged.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
