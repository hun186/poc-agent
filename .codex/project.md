# SRAF Project Handoff

## Current Focus

- **2026-10-31 current branch `feat/sraf-off4-cause-guidance-20261031`**: additive, pure TXT report enhancement; only an exact code-reviewed `(check,status,reason)` triple selects fixed Chinese remediation, and raw reasons/payloads never appear. Unknown/untrusted values fall back to generic advice. No added network/SQL/ES/LLM/Job calls, no full release Gate upgrade. Hosted exact-head CI and formal Codex Review pending; do not confuse synthetic tests with real Linux/airgap acceptance.
- **PR #343 MERGED**, squash `d3b0c27e83ad577fde2de4f7911b607893269b46`. Rebased Linux E2E 600-second client wait guard and tests; Hosted OFF-1B 1,745 Python + OFF-1 hub 429 PASS, OFF-0 19 checks, exact-head Codex CLEAN. The historical overlapping PR #322 is closed as superseded; **client timeout still does not cancel server-side E2E**.
- **PR #342 MERGED** squash `a8b10ada280c379d2c7e18160d31f8fea5f78c1c`; OFF-4 private Chinese TXT companion, Hosted 429 Python and OFF-0 19 PASS, formal Codex CLEAN. Vercel Preview was quota-limited, not a required CI.
- **PR #341 MERGED** squash `4dd2ba427a3c1b355351b1c256d894d3404a2d8f`, SQL opt-in constant SELECT only; full SQL schema and permissions NOT_TESTED.
- **PR #340 MERGED** squash `6631806f5ac37e57a536a05ef730ad6867c95b3c`, optional strict ES mapping partial; earlier #336–339 merged.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Validate the current OFF-4 cause-guidance branch with exact-head Hosted tests + OFF-0 19 and formal Codex Review; resolve P1/P2 before conditional Merge. Merged #336–343 remain part of main. Historical PR #318/#315 need current code-overlap analysis rather than blind merges.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
