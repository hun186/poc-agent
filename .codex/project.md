# SRAF Project Handoff

## Current Focus

- **2026-10-30 PR #337 DRAFT** follows PR #336 (CLEAN, squash merged into main at 10e5dc480008): operator-only OFF-1 unified one-command hub. Compose pre-existing host disk/ODBC, Report Job UI/health/listener, optional private TCP diagnose, separately opt-in strictly attested real Report Job. All SQL/ES TLS, Handoff, full Agent, browser, packaging, restore, physical-airgap gates stay NOT_TESTED. Fresh exact-head Hosted and formal Codex review needed before separate user merge approval.


- 2026-10-30 current PR #336 (`feat/sraf-airgap-report-jobs-oneclick-20261030`) delivers an operator-only, stdlib Linux one-command Report Job/UI readiness checker plus explicitly authorized real Agent/LLM/DOCX acceptance. It complements SRAF core reporting; do not add a second queue or authority.
- First formal Codex Review HEAD 3741ab91: two P2 output-path and diagnose-exit findings corrected; latest previous CI 28b2e435 SUCCESS (1717 Python/19 OFF-0/Node). Second formal Codex Review HEAD 28b2e435 **COMPLETED with three new P2**: deployed app Python dependency contract incorrectly claimed stdlib-only, HTTP budget expiry after listener guard still allowed POST, corrupt DOCX zlib.error escaped. Corrected docs to explicitly require preinstalled application Python (no online pip), fail before expired send, catch damaged DEFLATE ZIP, and added regression tests. Recheck exact new HEAD Hosted+new formal Codex. DO NOT merge without separate explicit user authorization.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Review PR #337 final HEAD in Hosted CI (including hub tests, Report Job regressions, 19 OFF-0), request formal Codex re-review, address issues, and do NOT merge without explicit permission. PR #336 is already merged.


- Validate exact latest PR HEAD Hosted CI, reply/resolve three second-round P2 threads only with verified evidence and request fresh formal review; two first-round threads already resolved. PR stays draft/unmerged pending user authorization.
- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
