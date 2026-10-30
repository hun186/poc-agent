# SRAF Project Handoff

## Current Focus

- **PR #338 (Draft, 2026-10-31)**: add root-level `run_sraf_airgap_off1_diagnose.sh` as a fixed-argument, read-only Linux Bash launcher for merged OFF-1 hub. Use SRAF's already installed Python, anchor cwd to script location, output to `$HOME/sraf-acceptance-results`, preserve CLI exit code. No automatic model job, SQL/ES mutations, restarts or credential use. Local Bash syntax/argument/error-code tests PASS; Hosted CI and formal Codex review on exact PR HEAD still needed. Separate approval required to merge.
- **PR #337 is MERGED** (2026-10-31 00:43 Asia/Taipei), squash merge `e44ae58ddf64f94938a368ceb4726bd3d3f8a658`, exact-head Hosted SUCCESS 26 Python tests +19 OFF-0 schema checks, latest formal Codex CLEAN 0 findings, prior P1 import-path finding resolved. Use this vetted hub; do not create another diagnosis engine.
- PR #336 previously merged: one real Report Job acceptance flow opt-in, with strict OFF-1S attestation, installed application Python and pinned evidence output. Do not weaken or launch it implicitly.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Complete PR #338 exact-head Hosted CI including Bash launcher regression, OFF-0 19 schema-only and hub tests; formal Codex review with zero outstanding findings before separate explicit user approval to merge. #336 and #337 are already merged.


- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
