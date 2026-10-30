# SRAF Project Handoff

## Current Focus

- **2026-10-30 PR #337 DRAFT** follows PR #336 (CLEAN, squash merged into main at 10e5dc480008): operator-only OFF-1 unified one-command hub. Compose pre-existing host disk/ODBC, Report Job UI/health/listener, optional private TCP diagnose, separately opt-in strictly attested real Report Job. All SQL/ES TLS, Handoff, full Agent, browser, packaging, restore, physical-airgap gates stay NOT_TESTED. Hosted #41052583678 passed 26 Python +19 OFF-0 on 9032056f; old P1 direct script import corrected and thread resolved. Fresh formal exact-head Codex review REQUESTED but FAILED due usage limit, NOT CLEAN. Separate user merge approval only after review gate.


- PR #336 is already merged, not an open handoff. Its existing operator Report Job CLI runs with the deployed application Python (including dotenv/pyodbc), not bare system stdlib. Five historical P2 findings were corrected, all review threads resolved and third formal Codex CLEAN on head a397e237; retain its secure one-job opt-in behavior and do not create a new queue.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Review PR #337 final HEAD in Hosted CI (including hub tests, Report Job regressions, 19 OFF-0), retry formal Codex re-review once account usage permits, address issues, and do NOT merge without explicit permission. PR #336 is already merged.


- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
