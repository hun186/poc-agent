# Backlog

## Current Summary

### Release gates for PR #328 (not yet merged)

- Revalidate exact current GitHub PR HEAD, Hosted Python focused/Report Job Worker/startup tests, cross-process Linux epoch regressions and **19 OFF-0 schema-only checks** after documentation compaction; complete formal Codex review on that exact HEAD. Resolve P1 memory-compaction finding with archive identity proof, reply in existing review Thread, and re-review until no actionable Findings/Threads. **Merge only upon a separate explicit user request.**
- Cross-process plan fencing remains **same Linux host, UID, canonical repo, shared lock mount/tempdir**. Explicitly validate the actual deployment's API Worker/container topology, UID, project path and mount namespace before relying on it. New plan admissions must fail closed after another Worker's new generation; do not claim a durable or distributed shared Plan.

### Real deployment acceptance (all NOT TESTED by Hosted synthetic CI)

- Obtain separately authorized read-only Linux baseline evidence before any mutating test: `tools/sraf_runtime_baseline_readonly.py --project-root "$PWD" --api-port 9002`, verified launcher process/socket identity, `/healthz`, Schedule/Handoff Worker identity under idle versus controlled Ollama contention. Never restart services or trigger production jobs as incidental diagnostics.
- Independently verify real Ollama/LiteLLM/smolagents/ES client timeout behavior, retries and non-cancelable SDK calls under controlled busy workload. Cooperative 540s deadline and `RUNNING_OVERDUE` cannot hard-stop a blocked SDK. Observe actual report >300s stage accounting, field-selector fallback quality and endpoint saturation.
- Operator-approved strict Elasticsearch HTTPS TLS/CA/IP SAN/Mapping/index selector and exact dedicated fixture read/create-only repair; ensure no overlap with production indexes, no unsafe alias wildcard, no silent source drift or out-of-band write. WARN-only Docker IP-SAN is **not** release acceptance.
- Independently verify SQL Server schema v4 migration/rollback, service-privilege least privilege, Product Task CAS/idempotency, Schedule/Handoff claim/renewal/ownership/failover and real Report Job artifact DOCX root/SHA/ZIP. OFF-1G/1I/1K–R are partial independently read-only evidence, not atomic end-to-end confirmation.
- Complete authorized Requirement→Schedule/Handoff→Report Job→real Agent/LLM/Elasticsearch→DOCX E2E, OFF-2 packaging, OFF-3/4 release reporting, OFF-5 recovery and physical airgap acceptance. Keep SQL/ES mutations, schedule triggers and production model calls opt-in and isolated.

### Product/other deferred work

- Preserve Product schema v4 and immutable Requirement SQL authority, canonical cross-resource request idempotency, superuser-owned provisioning and version activation, low-level ownership fences, Snapshot CAS, draft activation, Task/Run owner isolation. Reverify historical PR #288 P2.1 against current GitHub rather than trusting old status; P2.2/UI/production HTTP/security acceptance remain separate.
- Job Task JT-1, Workflow Registry, LangGraph integration are NOT STARTED absent new evidence. Future capabilities include durable cross-host E2E Plan lease/attestation and expiry, HA/job retention/cancel/retry/webhooks, audit filtering, authorization hardening, SQL/ES lineage, and signed per-worker code provenance.
- Document risks: no hard SDK cancellation, no atomic ES fixture rollback or cross-system SQL/HTTP/file transaction, no cross-host Plan sharing, possible already-admitted E2E Job completion after later drift, external writer TOCTOU, independent containers/UIDs not covered, same-UID local hostile actors not isolated by private file.

## Recent Changes

- 2026-10-30: #324 cooperative E2E budget; #325 safe ES fixture and Linux same-host lock; #326 staged Plan publication; #327 local revalidation and pinned in-flight Plan, merged at main `7a0bd1c901016e7869efeeb101642e4c1438c691`. These Hosted CI/review successes are not real Linux acceptance.
- 2026-10-30: #328 adds same-host opaque generation rotation and stale E2E plan refusal. Initial Hosted CI #40990112694 SUCCESS (1,533 Python tests and 19 OFF-0 schema checks) on code/docs HEAD `03c526eb1df0217d7ecfb2e5e6115515c8d982fd`, but Codex **P1 documentation compaction finding** requires fresh final-head evidence. No Merge.
- Earlier OFF-1 slices #295–314 and Product reviews are preserved in complete archives; old review/CI status entries are historical.

## Archived History

- `.codex/archive/backlog.md-20261030-101300.md` — full 21,142-character pre-compaction active backlog, exact matching Git blob SHA `829147a7e4bb496be98a999efd02281a67ffed45`, independently re-fetched before rewrite.
- `.codex/archive/backlog.md-20261024-170825.md` and `.codex/archive/backlog.md-20261021-165000.md` — prior complete Product/airgap/workflow history.
- 2026-10-30 compaction per `AGENTS.md` after >20 work records: historical details remain retrievable, but active file lists only current unresolved gates.


- 2026-10-30 OFF-1U passive Linux load/topology gate: validate final Hosted CI+OFF-0/legacy Worker tests and formal Codex CLEAN before separate explicit user Merge. Then *only on operator's real Linux host* run read-only baseline `tools/sraf_runtime_baseline_readonly.py --no-network` and new `tools/sraf_linux_load_topology_readonly.py --samples 3 --interval 5` at idle and during already-running approved busy workload; collect sanitized PARTIAL_ONLY output. Verify actual multi-worker TMPDIR/UID/root/mount topology independently; never infer lock sharing from one PID. Ollama/LiteLLM/ES timeouts, dedicated fixture create-only writes, SQL/Handoff/Report Job/DOCX and FULL_LIVE remain independently permission-gated future tests.


- 2026-10-30 OFF-1V release gates: check exact PR HEAD Hosted focused+Worker+startup Python and OFF-0 19 schema tests, complete formal Codex Review CLEAN and 0 P1/P2/threads before independent user-authorized Merge. After deployment, operator may manually capture OFF-1U idle and naturally busy snapshots with identical sample counts/intervals into user-controlled files and run OFF-1V offline; compare means/maxima as partial, not certified host/process identity. Future separate authorized real Linux multi-worker lock identity, busy Ollama/ES SDK timeout, ES create-only fixture recovery and SQL/Agent/DOCX acceptance are still NOT_TESTED.


- 2026-10-30 OFF-1V follow-up: ensure full Hosted CI on post-Codex-P2 HEAD, verify direct `python tools/sraf_linux_load_compare_offline.py --help` with PYTHONPATH absent and sanitized `10**400`/deep JSON rejection, reply to/resolve both inline review Threads and request a NEW formal final-head Codex Review. No Merge until CLEAN and explicit user instruction.

- 2026-10-30 OFF-1U actual Linux blocker: two runs returned zero samples because strict OFF-1S global exclusive-owner scan hit FD_LIMIT on both attempts, though the six preliminary listener/PID checks PASS. For PR #330 run final-head Hosted CI on new OFF-1U local nonexclusive PID/socket sampling proof and OFF-1V old/new schema comparison, obtain fresh formal Codex Review CLEAN with zero unresolved threads, and require separate user Merge authorization. After deployment, operator should repeat two safe OFF-1U normal/busy runs; socket exclusivity, cross-worker lock/mount identity, Ollama/ES SDK timeouts and FULL_LIVE remain NOT_TESTED.

- 2026-10-30 OFF-1W next-gate: run exact final-head Hosted Python + 19 OFF-0 and formal Codex Review CLEAN before a separately authorized Merge. After deployed, operator can run passive OFF-1W at naturally idle and already approved busy Ollama load, recognizing current PID-namespace coverage only. Still NOT TESTED: actual API-to-Ollama request latency, GPU/VRAM/queue, model identity and concurrent worker authenticity, ES/SQL/Report Job/DOCX live full E2E or physical airgap. Do not reuse OFF-1V to parse OFF-1W.

- 2026-10-30 LLM contention diagnostics next gate: Hosted final-head Python focused and existing E2E/startup/OFF-0 19 schema-only, formal Codex Review CLEAN and zero unresolved threads before separately authorized Merge. After deployment review naturally occurring idle/busy [llm_call] stage-level sanitized warning/info log lines without triggering extra inferencing. Separate later work (NOT TESTED) is smolagents LiteLLMModel timing and lossless error classification, user-visible per-Job stage updates, true queue vs first-token latency, provider cancellation/timeout and real Ollama server-side queue/GPU evidence. Do not assert root cause.

- 2026-10-30 DataAgent observation branch gates: latest-head GitHub Hosted focused + legacy Worker + startup/report tests and OFF-0 19 schema-only must pass; then complete formal Codex Review CLEAN, resolve all P1/P2 threads, require separate user approval to merge. Need separate operator-authorized validation of actual busy Ollama DataAgent request latencies, smolagents method binding compatibility in deployed version and end-user report phase progression; no new GPU/queue/root-cause claim. Future hard SDK cancellation/cross-worker status remains deferred. PR #322 E2E operator client timeout patch remains open, not merged.

- 2026-10-30 Report progress release gate: run Hosted Python test suite including v0/v1->v2 atomic migration/rollback and existing Report Job Worker, owner auth, E2E/19 OFF-0 schema checks; require exact-head Codex Review CLEAN/0 unresolved P1/P2, user Merge separately. Then authorized Linux deployment migration and real job/status inspection. Next separate increment: authenticated visual Job progress panel or UI polling, and finer Agent substage reporting with explicit context propagation; avoid false user-facing Ollama/GPU queue labels, and no hard provider cancellation yet.

- 2026-10-30 PR #334 remaining gates after addressing 2 initial Codex P2: exact HEAD Hosted including concurrent Report Job v2 initialization acceptance, targeted v1/v0 rollback and full E2E Worker tests, 19 OFF-0 schema-only; fresh completed formal Codex review clean and zero unresolved threads; reply/resolve both old Findings on validated correction and **no merge without user authorization**.

- 2026-10-30 browser progress follow-up pending gates: run exact-head Hosted Node JS flow + Python static route/owner/Worker + OFF-0 19 schema checks, fix any failures; complete formal final-head Codex Review CLEAN with zero P1/P2/unresolved threads, and require separate user permission before Merge. On deployed private Linux, separately verify actual browser auth/scope, real slow Ollama/ES phase, DOCX download, invalid token handling and visual mobile layout. Cannot claim live acceptance from synthetic Node VM.

- 2026-10-30 PR #335 Codex P1 memory-compaction remediation: preserve `.codex/known_issues.md` pre-rewrite bytes at archive/known_issues.md-20261030-162500.md with identical Git blob d588197f83574c207230caa23f7efd787342e488, replace active summary (32 lines, 3 dated record blocks, detailed open risks intact), record archive in memory; then rerun exact-HEAD Hosted CI and new formal Review, reply/resolve the original P1 only after validation. No Merge.

- 2026-10-30 PR #335 P2 follow-up: ensure browser authenticated Word download uses server-returned sanitized Content-Disposition filename/UTF-8 filename*, not the synthesized `report-<job_id>.docx` when name is available. Reject unsafe values with a safe fallback, test ASCII, UTF-8, malformed/absent/path input with synthetic Node VM. Run exact-head hosted Python/Node/OFF-0; resolve P2 after reply and request fresh Codex CLEAN. Separate permission required for Merge; real browser/Linux untested.

- 2026-10-30 airgap one-click next gates: newly added Report Job-focused one-command deployed CLI must pass full Hosted Python tests and OFF-0 19 checks, then formal Codex CLEAN before separate merge. Real Linux OFF-1S listener proof may fail under global FD_LIMIT and will fail closed before credentials; actual live Report Job, browser visual screenshot, model/ES/SQL/Worker acceptance and unified OFF-2–5 full release/restore suite remain NOT TESTED. Future one-click hub must link independent OFF-1P/Q/SQL/Handoff and offline release provenance without falsely treating TCP/HTTP health as FULL_LIVE.

- 2026-10-30 PR #336 first formal review on 3741ab91 completed with two P2 (unsafe output parent symlinks/error-path JSON, and diagnose TCP FAIL/SKIP omitted from exit). Follow-up pinned dirfd/output validation and diagnose exit plus regressions are committed. Next: verify **new exact HEAD** Hosted CI including OFF-0 19 checks, reply and resolve original Findings only after validation, obtain fresh completed formal Codex Review, no Merge without explicit user authorization. Private Linux operator execution and OFF-2–5 are NOT TESTED.
