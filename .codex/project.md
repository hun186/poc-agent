# SRAF Project Handoff

## Current Focus

- **2026-10-31 current Draft PR #339** (branch `feat/sraf-off1h-worker-observation-hub-20261031`) incorporates existing OFF-1H local Schedule/Handoff Worker process identity verification into the operator-only OFF-1 `--suite diagnose` hub. No network, SQL, lease, authentication or Worker process control in the added OFF-1H probe. Emit advisory PASS/SKIP + redacted verified role count; preserve schedule_handoff_workers=NOT_TESTED for full E2E and preserve existing required HTTP/TCP exit logic. Test exact new HEAD Hosted, then formal Codex and separate user Merge.
- **PR #338 merged 2026-10-31 01:27 Asia/Taipei** into main squash `97f8b81a426a4c98777dd7668dc0143dbf6c0196`: root-level Bash one-click `run_sraf_airgap_off1_diagnose.sh` anchors output in repo `sraf-acceptance-results/`; final HEAD `6795fbfd`, Hosted #41097544331 SUCCESS 29 Python +19 OFF-0, formal Codex CLEAN/no unresolved findings. Do not recreate launcher or loosen existing output security.
- **PR #337 merged** at `e44ae58ddf64f94938a368ceb4726bd3d3f8a658`; unified OFF-1 hub and strict Report Job opt-in remain existing authority. PR #336 previously merged one real Report Job CLI.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Complete PR #339 exact-head Hosted CI (new OFF-1H + existing Hub/Bash/19 OFF-0), formal Codex Review, resolve actionable findings, and obtain separate explicit user Merge authorization. #336–338 are merged.


- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
