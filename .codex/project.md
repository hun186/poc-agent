# SRAF Project Handoff

## Current Focus

- **2026-10-31 active branch `feat/sraf-off2-pinned-provenance-20261031`:** first OFF-2 listed runtime-file SHA-256 integrity verifier, pure offline/read-only. Requires an independently provided digest of the reviewed `REQUIREMENT_E2E_PROVENANCE.json`, validates its strict schema and only its explicitly listed runtime files using nofollow dirfds/bounded reads. PASS_PARTIAL means listed hashes match only, not a package/signature/wheelhouse/deployment/physical-airgap certificate. New Hosted 19 OFF-0 + focused unit tests and exact HEAD Codex Review pending, conditional auto-merge if all gates hold.
- **PR #346 MERGED**, squash `4ef831aa52b8964b4e41636ef1b41c97ebd6c3d2`, exact HEAD `e3fd5ca2615eef5772baf27a0011268285a8e801`: Shell --no-network, 445 Python/19 OFF-0 Hosted PASS, latest Codex CLEAN, all manual gates NOT_TESTED.
- **PR #345 MERGED**, squash `3534c495c937a9016f07f9d5e41952645c9a558d`: optional safe output-dir override, 438 Python/19 OFF-0, formal Codex CLEAN after a P2 fix.
- **PR #344 MERGED**, squash `decd3f233a8195e8c547a01480e4364a28170ba0`: OFF-4 reason-triple static Chinese remediation; Hosted and Codex CLEAN. #343 Linux operator preflight SIGALRM and #340–342 partial OFF-1 probes/TXT are also merged.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Validate current OFF-2 pinned manifest listed-byte verifier on exact HEAD Hosted / OFF-0 19, formal Codex Review and zero unresolved findings or review threads, then conditional auto-merge. This is *not* the finished OFF-2 bundle/signing/wheelhouse, OFF-3/4 airgap or OFF-5 restore.
- Historical PR #315/#318/#322 closed superseded. #344–346 and #336–343 merged with exact-head gates.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
