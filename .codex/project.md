# SRAF Project Handoff

## Current Focus

- **2026-10-31 active branch `feat/sraf-off2-one-command-verify-20261031`:** Linux one-command `run_sraf_airgap_off2_verify.sh` for the existing OFF-2 listed-byte verifier, requiring an operator-provided independently trusted manifest digest via `SRAF_OFF2_TRUSTED_MANIFEST_SHA256`. No extra args, missing/invalid pin or Python fails closed, no self-hash fallback, writes, network or package mutations. Hosted exact-head and formal Codex Review pending. This is PARTIAL_ONLY, not signed release or full airgap acceptance.
- **PR #347 MERGED**, squash `304f031ebf13a26cbb6db12a41d9bbc548127ab6`. Existing provenance listed-file SHA-256 verifier with nofollow dirfd and bounded reads. Hosted OFF-2 310 tests, OFF-1 445 tests and 19 OFF-0 each PASS, formal latest-head Codex CLEAN after direct-script root-import P1 fix. Original review thread resolved.
- **PR #346 MERGED**, squash `4ef831aa52b8964b4e41636ef1b41c97ebd6c3d2`, Shell --no-network; PR #345 secure alternate output dir and PR #344 Chinese reason-safe report already merged.
## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Validate the OFF-2 one-command Bash wrapper latest-head Hosted and formal Codex review, conditional merge if gates hold. #347 manifest-listed hash verifier already merged and is not the completed OFF-2 signed bundle/wheelhouse, OFF-3/4 disconnected acceptance or OFF-5 restore.
- Historical PR #315/#318/#322 closed superseded. #344–346 and #336–343 merged with exact-head gates.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
