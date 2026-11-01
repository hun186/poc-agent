# SRAF Project Handoff

## Current Focus

- **2026-11-01 active operator E2E expired-canonical fail-fast candidate:** after #352 merged squash `cc9aa4ad8036dbd08a72441e91bd998d9ccf69a5` exact-head OFF-1/OFF-2 Hosted + Codex clean, current canonical XLSX bytes match old #270 and have now-expired October 2026 `DeadlineDT`. Add local SHA+deadline guard before any API request/authenticated preflight/Requirement import, fixed redacted INPUT_VALIDATION failure, synthetic no-socket regressions, operator instructions. Does NOT repair workbook or permit FULL_LIVE. New corrected golden workbook+SHA/provenance requires separate reviewed PR. Hosted/Review pending.


- **2026-11-01 current candidate OFF-2 explicit operator release policy:** based on main `96ba862351a086117e789f378e6c88b64060510d` after #350 and #351 successfully merged, add three operator shell files to explicit `managed_files` and six OFF-1/OFF-2 helper modules to `release_tool_files`, with checkout-local PASS_PARTIAL regression and existing Git review-policy identity tests in Hosted OFF-2 workflow. Does not generate/re-sign any manifest, package files, wheelhouse or modify deployment. Exact-head CI and formal Codex Review pending; no merge before gates. Old #270 still blocked by a P1 on expired canonical fixture dates.
- **#350 MERGED** squash `1150440fee4b3e4fbb30d908b1bab4a340ff9628`; Hosted OFF-1 476/OFF-2 322 PASS and formal Codex CLEAN. **#351 MERGED** squash `96ba862351a086117e789f378e6c88b64060510d`; exact-head Hosted OFF-1/OFF-2 SUCCESS and formal Codex CLEAN. Both partial-only, not OFF-3 airgap/FULL_LIVE.


- **2026-11-01 active OFF-3 release-policy route candidate**: after #350 squash `1150440fee4b3e4fbb30d908b1bab4a340ff9628` (Hosted 476+322 Python, Codex exact-head complete/no findings), add an explicit `release-policy` CLI dispatch to the existing read-only OFF-2 local policy audit, no implicit trust pin, credentialed probes or mutation. Hosted exact-head CI and Codex Review pending. Does not close the policy inventory gap or fulfill airgap/restore acceptance.


- **2026-11-01 active OFF-2 policy-gap audit candidate**: after confirmed #349 squash merge `8c1ee30a3e243426fc10e2322082c993ca3d3158`, add a zero-network, no-write local check for *explicit* release policy selection of nine minimum OFF-1/OFF-2/OFF-3 entrypoints. Existing manifest-policy selection is presently incomplete; tool reports count-only `INCOMPLETE`, never signs a new manifest or implies package coverage. Hosted CI and formal latest-head Codex review pending. Full wheelhouse, signed bundle, real offline acceptance and OFF-5 restore remain NOT TESTED.


- **2026-10-31 active branch feat/sraf-off3-unified-safe-dispatch-20261031:** first OFF-3 thin, conservative root Shell dispatcher for quick, diagnose, no-network and release-files, reusing existing OFF-1 hub/Bash and OFF-2 pin verifier. Unknown options and acceptance/upgrade/restore explicitly rejected; no new privileged probes, SQL/ES/LLM/Job, system mutation or insecure fallback. Exact-head Hosted and formal Codex Review pending. This is **OFF-3 partial read-only routing**, NOT FULL_LIVE or airgap acceptance.
- **PR #348 MERGED**, squash f39c32fd5caa0f0724e5c17ab94f73ac1b9701ba; OFF-2 standalone one-command Bash trusted-pin check, Hosted OFF-2 322 Python + OFF-1 445 Python and 19 OFF-0 each SUCCESS, exact-head Codex CLEAN.
- **PR #347 MERGED**, squash 304f031ebf13a26cbb6db12a41d9bbc548127ab6; existing Manifest-listed bytes checked under out-of-band SHA-256 pin with nofollow bounded dirfd. Hosted OFF-2 310 and OFF-1 445 Python, OFF-0 19 PASS, Codex CLEAN after P1 fix. Release completeness/signature/wheelhouse still NOT TESTED.
- **PR #346 MERGED**, squash 4ef831aa52b8964b4e41636ef1b41c97ebd6c3d2; root Bash no-network, while #345/#344 added safe output override and cause-specific Chinese reports.

## Recent Outcomes

- #319 removed active E2E LLM/ES preflight from normal API startup (not simply increasing timeouts). #333-335 added real DataAgent timing, durable Report Job progress, and browser UI; all are merged into main.
- Default quick mode is non-mutating with no LLM request. Diagnose mode includes configured TCP probes; no-network mode remains partial. Live-report must be explicit, strictly verify OFF-1S listener before credentials, create one real Job without blind POST retry, then poll and verify Word.
- Evidence writes use verified private Linux dirfd and cannot follow symlinked/replaced parent paths, and must not reveal credentials, job IDs, payload or internal hosts.

## Open Handoffs

- Validate OFF-3 safe dispatcher latest-head Hosted/19 OFF-0 and formal Codex review; conditional merge only if CLEAN. OFF-2 listed bytes and one-command wrapper #347/#348 already merged, but signed bundle/wheelhouse, real OFF-3 Acceptance and OFF-5 restore are not complete.
- Historical PR #315/#318/#322 closed superseded. #344–346 and #336–343 merged with exact-head gates.

- Private Linux/offline real E2E, strict ES TLS/IP SAN and Mapping, SQL source/schema, live Ollama/Agent timing, Word artifact and browser visual acceptance, Worker handoff, OFF-2-5 airgap/restore remain NOT TESTED by Hosted CI.
- Follow AGENTS.md and active .codex/memory.md, architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md; consult .codex/archive only for historical investigation.
