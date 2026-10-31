# SRAF Project Handoff

## Current Focus

- **2026-10-31 active branch `feat/sraf-off1-output-dir-override-20261031`** adds only an operator-selected `SRAF_OFF1_OUTPUT_DIR` absolute single-line output path for one-command Bash diagnose while keeping project-local default. The existing Python 0700/UID/no-follow pinned dirfd remains the sole authority; no fallback, permission bypass, network operation or credential usage. Exact-head Hosted CI and formal Codex Review pending.
- **PR #344 MERGED** squash `decd3f233a8195e8c547a01480e4364a28170ba0`: OFF-4 exact fixed reason-triple Chinese remediation, no native errors. Hosted CI/19 OFF-0 and formal Codex CLEAN. Old overlapping PRs #315/#318 closed as superseded after verifying current stricter implementations.
- **PR #343 MERGED** squash `d3b0c27e83ad577fde2de4f7911b607893269b46`: E2E Linux operator client-only deadline, Hosted 1745 +429 and 19 OFF-0, Codex CLEAN; historical #322 closed superseded.
- **PR #342 MERGED** squash `a8b10ada280c379d2c7e18160d31f8fea5f78c1c`: OFF-4 Chinese TXT, 0600 pinned output. **PR #341 MERGED** squash `4dd2ba427a3c1b355351b1c256d894d3404a2d8f`: SQL optional constant SELECT. **PR #340 MERGED** squash `6631806f5ac37e57a536a05ef730ad6867c95b3c`: ES strict mapping opt-in; all partial only.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Validate the selected private-output-path override on exact-head Hosted regression + OFF-0 19 and formal Codex Review; correct blocking Findings and conditional auto-merge if safe. Historical PRs #315/#318 already closed superseded; merged #336–344 remain part of main.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
