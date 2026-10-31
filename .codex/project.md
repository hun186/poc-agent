# SRAF Project Handoff

## Current Focus

- **2026-10-31 current branch `feat/sraf-off1-shell-no-network-20261031`:** allow explicitly selected root Bash `--no-network` only, forwarding to the existing OFF-1 Python `--suite diagnose --no-network` implementation. Refuse duplicates and combined SQL/ES credentialed flags before executing Python. Preserve existing Bash allowlist, default diagnose, secured project-root or optional private path, 8 manual NOT_TESTED gates and normal INCOMPLETE/exit 2 when connectivity rows are SKIP. Hosted exact-head CI/formal Codex pending; zero socket network probing is not physical airgap acceptance.
- **PR #345 MERGED** squash `3534c495c937a9016f07f9d5e41952645c9a558d`, latest PR HEAD `b0a357cf887ed2dce99a324edffe487d0c2a4c93`: optional shell `SRAF_OFF1_OUTPUT_DIR` absolute single-line trusted-path override; Python nofollow dirfd remains authoritative. Hosted 438 Python +19 OFF-0 PASS and formal Codex CLEAN after fixing initial P2.
- **PR #344 MERGED** squash `decd3f233a8195e8c547a01480e4364a28170ba0`: known fixed reason-triples -> Chinese guidance, no native text; CI/Code Review CLEAN.
- **PR #343 MERGED** squash `d3b0c27e83ad577fde2de4f7911b607893269b46`: Linux E2E operator 600s client-only deadline; no server cancellation, 1745+429 Python and OFF-0 CI PASS.
- **PR #342 MERGED** squash `a8b10ada280c379d2c7e18160d31f8fea5f78c1c`: private Chinese TXT, and #341/#340 merged partial opt-in SQL and ES.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Validate the one-click --no-network flag exact-head Hosted test (root Shell + canonical hub / OFF-0 19) and formal Codex Review, repair P1/P2 and only then conditional auto-merge. Historical #315/#318 and #322 are superseded/closed; PR #336–345 already merged.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
