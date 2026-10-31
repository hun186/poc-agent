# SRAF Project Handoff

## Current Focus

- **2026-10-31 current branch `fix/sraf-operator-e2e-deadline-rebased-20261031`** ports only the reviewed operator E2E Linux 600s elapsed-time SIGALRM client guard and four synthetic tests from old open PR #322 onto the newest main. This avoids overwriting newer main `.codex`/workflow/runbook histories. In Linux main-thread only, refuse existing alarm owners and worker-thread requests before sending bearer; restore handler/timer, preserve exact redacted HarnessFailure categories; no server cancellation or production timeout changes. New current-head Hosted CI and formal Codex review pending. Historical PR #322 is **not** merged and should be marked superseded only after replacement succeeds.
- **PR #342 MERGED** squash `a8b10ada280c379d2c7e18160d31f8fea5f78c1c`, final HEAD `4ffbcb3fe2`. OFF-4 redacted Chinese TXT companion and private dirfd evidence; Hosted 429 Python plus OFF-0 19 PASS and formal Codex CLEAN. Optional Vercel preview failed solely from free deployment-count quota, not a required code test.
- **PR #341 MERGED** squash `4dd2ba427a3c1b355351b1c256d894d3404a2d8f`, final HEAD `554eb7239803`; dedicated optional SQL-01 constant SELECT only, full schema/permissions NOT_TESTED.
- **PR #340 MERGED** squash `6631806f5ac37e57a536a05ef730ad6867c95b3c`; optional strict ES CA/IP SAN and mapping remain partial. Earlier PR #336–339 merged.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Complete rebased Linux operator client wait guard exact-HEAD Hosted CI (including E2E harness v2 and 19 OFF-0), formal Codex Review and remaining threads; do not merge the old #322 branch wholesale or overwrite recent .codex state. PR #336–342 already merged.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
