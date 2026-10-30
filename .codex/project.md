# SRAF Project Handoff

## Current Focus

- 2026-10-30 current PR #336 (`feat/sraf-airgap-report-jobs-oneclick-20261030`) delivers an operator-only, stdlib Linux one-command Report Job/UI readiness checker plus explicitly authorized real Agent/LLM/DOCX acceptance. It complements SRAF core reporting; do not add a second queue or authority.
- The first formal Codex Review at HEAD 3741ab91 completed with two P2 findings: unsafe symlink/output-directory redirection and diagnose TCP FAIL/SKIP ignored by top-level result. Follow-up fixes and tests were committed; new latest-head Hosted CI and formal review are still required. DO NOT merge without separate explicit user authorization.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Verify exact latest PR HEAD CI, reply/resolve both original P2 review threads based on verified corrections, and request new completed formal Codex Review. PR remains draft/unmerged pending user authorization.
- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
