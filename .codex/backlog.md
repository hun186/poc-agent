# Backlog

## Current Summary

### OFF-1I PR #305 — immediate review and deployment gates

- Complete mandatory AGENTS.md memory compaction: full original `.codex/memory.md` and `.codex/backlog.md` were archived before overwrite at `.codex/archive/{memory,backlog}.md-20261024-170825.md` and byte-for-byte verified. Keep these archive references in active memory.
- Run and inspect exact-current-HEAD Hosted OFF-1I/legacy E2E pytest and 19 OFF-0 schema contract checks after memory edits. Reply to initial Codex P1 memory-compaction finding, resolve thread after real preservation/condensation evidence and submit a fresh formal review. Correct any new findings, do not Merge without explicit user command.
- OFF-1I Handoff Coordinator lease diagnostic is a **single DB snapshot only**: default-off `--probe-network --probe-sql-read --probe-worker-lease` with a genuine OFF-1G SQL-READ PASS, readonly separate DBA-limited diagnostic SQL principal, numeric private IPv4/ODBC Driver18/strict SAN. Query only server-computed flags from known `sra_schedule.requirement_handoff_coordinator_leases`, never owner/token or job data. Active snapshot does NOT prove local Worker ownership or renewal/progress. No private Linux/SQL Server acceptance yet.
- After approved merge, obtain authorized private Linux evidence and identify any real SQL certificate/DB schema/permission issue without downgrading to an unsafe TLS or privileged account.

### Live acceptance still pending

- Real deployment acceptance remains INCOMPLETE. Verify ES index selector/Mapping against actual protected service; past `mapping_incompatible` and relocated Docker IP SAN mismatch were not cleared by Hosted CI. CA-verified but IP-identity-unknown WARN is not strict TLS identity evidence.
- Run authorized SQL Server schema v4/migrations, rollback/failure injection, fencing/failover, concurrent actors, HA and service privilege checks on controlled environment. OFF-1G fixed SELECT and OFF-1I one lease snapshot do not replace these tests.
- Independently prove Schedule Worker claim/progress (the current schema has no independent scheduler heartbeat), Handoff *local owner* association and repeated heartbeat/lease changes, API Report Job Worker, real Agent/LLM/ES execution, and signed/valid Word artifact SHA256. Do not trigger production schedules or mutate leases as diagnostics.
- Run full Requirement → Schedule/Handoff → Report Job → Agent/LLM/Elasticsearch → DOCX E2E and OFF-2 release packaging, OFF-3/4 operator reporting, OFF-5 recovery/true physical airgap validation after separate approvals. No report of FULL_LIVE from partial checks.
- Complete launcher deployment and durable output-root migration gates SD-1–SD-7, with per-host evidence and no speculation.

### Product implementation and security backlog

- Requirement Product follows Design/Plan v1, Phase 1B Import / Phase 1C Schedule/Handoff / Report Job, and existing SRA Editor Auth/RBAC; no parallel execution, queue, identity or report storage.
- Preserve immutable Requirement Version/Snapshot, Product Task provisioning/active/disabled, durable request idempotency with cross-resource canonical hash, superuser-only create/activation, draft CAS/owner fencing, controlled Schedule enablement and accurate request projection. Product P1.0–P1.6 historically merged via #283–286; verify current GitHub state of P1.7, P2.1 PR #288 and later work independently before calling merged/complete.
- P2.2, Product HTTP mutation and service-key scopes, Task Center UI/browser E2E, cross-Task result sharing and privacy/ACL/provenance require separate work and approvals.
- Job Task JT-1 and LangGraph integration remain NOT STARTED absent later exact-source evidence. Other future work: Report Job retention/metrics/cancel-retry-webhook, HA/exactly-once, stronger auth throttling/MFA/CSP/CSRF, audit filtering, import diagnostics and SQL/ES lineage.
- Future Worker loaded-code attestation requires reviewed IPC; sanitized SQL-registry proof must not reveal runtime secrets or introduce unsafe hash overrides.

## Recent Changes

- 2026-10-24: OFF-1H PR #304 merged with canonical fd-bound no-follow Worker identity verification, NUL-argv matching, and legacy E2E regression; its successes are point-in-time process checks only.
- 2026-10-24: OFF-1G PR #303 merged with TLS-verified operator SQL fixed constant SELECT; production SQL permissions unverified.
- 2026-10-24: OFF-1F PR #302 merged after cloud-forwarding P1 remedy; LLM local server verifies `OLLAMA_NO_CLOUD=1` by listener PID, but still no actual private Linux acceptance.
- 2026-10-24: OFF-1I PR #305 initial exact-head #40080725404 Hosted pytest 1,079 + two legacy E2E PASS, OFF-0 19 PASS; formal Codex first round identified memory compaction P1, now being corrected. Current exact HEAD requires new checks.
- 2026-10-24: active memory file compaction preserves all earlier OFF-1B/ES PR #295–301, Product and audit review chronology in byte-identical full archives, so older PR status statements in archived logs should not be mistaken for current Hosted GitHub state.
- 2026-10-21: previous mandatory memory compaction archived all six project records; see links in `.codex/memory.md`.

## Archived History

- `.codex/archive/backlog.md-20261024-170825.md` — verified full 20,489-character pre-compaction backlog containing all historic dated blocks and pending tasks before OFF-1I P1.
- `.codex/archive/memory.md-20261024-170825.md` — corresponding verified full 38,469-character pre-compaction project memory.
- `.codex/archive/backlog.md-20261021-165000.md` — prior full history; older 2026-10-06 and 2026-09-18 archives reachable through its references.
- Consult archives only for relevant history, not for every regular current task.

## Compaction Record

- 2026-10-24: original full files **created in .codex/archive and re-fetched with identical bytes and Git blob SHA** before any active memory rewrite. This active backlog now lists only current unresolved actions and durable design constraints; stale chronological review details remain recoverable. After these documentation commits, require exact-HEAD Hosted CI, formal Codex CLEAN and explicit merge authorization.

## 2026-10-24 OFF-1J pending acceptance gates

- Test exact PR head in GitHub Actions, inspect actual Hosted job log and 19 OFF-0 contracts; request formal Codex Review and address all findings. No GitHub Merge absent user authorization.
- Authorized private Linux SQL + worker operator run still needed. Next independently design local Handoff PID-to-custom-owner association, progress beyond heartbeats, Schedule Worker independent claim cycle evidence, API Report Job Worker and Word outputs. Never use a valid DB heartbeat to claim production job execution or FULL_LIVE.

## 2026-10-24 OFF-1K release gates

- Verify Hosted OFF-1K regression/legacy Worker E2E/19 OFF-0 schema checks on exact current HEAD; request formal Codex Review and resolve findings, then only Merge on explicit user instruction.
- Later collect operator-authorized Linux/sql instance evidence; assess deployments whose owner comes from dotenv after process launch or uses default `handoff-PID`, with a separately reviewed agent attestation mechanism if needed. Confirm lease renewal owner/generation atomicity and actual successful handoff, Schedule due claim, Report Job Worker, Word and physical isolation independently. Never promote this snapshot to FULL_LIVE.

## 2026-10-25 OFF-1L release gates

- Verify exact-head OFF-1L/legacy OFF-1B Hosted focused tests, 2 Worker E2E, 19 OFF-0 contract checks. Perform formal Codex Review and address findings before any explicit-user-authorized merge.
- Real private Linux SQL Server operator credentials, schema correctness and actual Schedule Worker -> claim process attribution remain pending. Actor-labelled SQL row creation is not a securely authenticated local PID. Handoff submission/reconciliation, Report Job completion, DOCX and isolation require separate evidence.

## 2026-10-25 OFF-1M release gates

- Run Hosted exact-head focused OFF-1M, OFF-1L and legacy tests, 2 Worker E2E, 19 OFF-0 schema contract checks; then request formal Codex and correct all actionable findings. Merge only on explicit user instruction.
- Future verified local Schedule PID→SQL authenticated claim and Handoff/Report Job/artifact evidence require separate safe design. OFF-1M only associates *current* active config to latest actor-labelled run; normal SQL Server isolation and a mutable actor label cannot prove atomicity or PID attribution. Private Linux SQL evidence, real E2E, DOCX and physical isolation untested.

## 2026-10-25 OFF-1N acceptance and review gates

- Run Hosted exact-head focused OFF-1N regressions, legacy E2E and OFF-0 19 contract checks; require formal Codex CLEAN and resolved P1/P2 before explicit-user-authorized merge. Live private SQL Server, privileges, TLS/SAN and physical airgap are **not** covered by mocked Hosted CI.
- OFF-1N persisted Handoff SQL acknowledgement does not attest an authenticated remote Report Job response or success. Need separate real API Report Job execution proof, actual Agent/ES/LLM and Word SHA256 checks, Schedule/Handoff PID attribution, failure/retry and isolation acceptance; never promote database snapshot to FULL_LIVE.

## 2026-10-25 OFF-1O pending gates

- Verify exact-head Hosted focused tests, Worker E2E and OFF-0 contract; formal Codex Review and all findings resolved before separate user-authorized merge.
- Future real operator E2E: authenticated read-only Report Job GET for the **same** persisted remote job identity under least privilege; independently validate remote completed status, download/publish DOCX, recompute actual file hash against SQL with secure output-root confinement, trace Agent/LLM/ES, tie schedule/handoff PID safely and demonstrate physical isolation. OFF-1O's SQL checkpoint is NOT remote or file proof.

## 2026-10-25 OFF-1P release gates and next real-live proof

- Exact-HEAD Hosted OFF-1P focused unit, legacy Worker E2E, OFF-0 19 schema checks; formal Codex Review CLEAN and resolved P1/P2 before separate user-authorized merge. Obtain approved Linux deployment operator run with real SQL SELECT-only principal, certificate IP SAN and output root proof. CI mocks SQL Server; no production DOCX verification yet.
- For actual Report Job proof, build separately reviewed authenticated read-only GET of the **same, persisted remote job ID** and verify status / real artifacts with controlled credential handling and URL safety. OFF-1P proves only one local published DOCX's bytes vs SQL digest, not whether Report Job API actually ran or Agent/ES/LLM, full batch, physical isolation.

## 2026-10-27 OFF-1Q review and acceptance gates

- Require exact-head Hosted OFF-1Q focused pytest + legacy Worker E2E + OFF-0 19; formal Codex Review CLEAN on same HEAD, resolve all P1/P2; then Merge only on explicit separate user command. No real operator SQL/Report Job HTTP authorization supplied; do not declare live PASS.
- Next live/deployment work: operator-approved real loopback Report Job response under owner-scoped REPORT_JOB_READ principal and independently verified SRAF API listener identity/PID, matching the same immutable run_item in SQL and locally published DOCX in one stable observation; verify remote artifact provenance and Agent/LLM/ES traces; test physical isolation. OFF-1Q only correlates sequential API and SQL snapshots.

## 2026-10-27 OFF-1R Hosted review and live acceptance gates

- Run exact-HEAD Hosted OFF-1B focused pytest including OFF-1R new tests + legacy Worker E2E + 19 OFF-0 schema checks, then formally request Codex Review on exact HEAD and correct all actionable P1/P2, resolve review threads. Do not merge without an explicit separate user instruction. No valid live SQL/HTTP/airgap acceptance is available in Hosted tests.
- Future operator-approved real SQL Server execution/permission/TLS SAN and SRAF listener/owner/PID attestation, immutable report job-to-artifact provenance (signed/durable linkage) and real Agent/LLM/ES end-to-end plus network isolation validation remain pending. OFF-1R only correlates a sequential three-observation chain.

## 2026-10-27 OFF-1S CI/review and deployment verification

- Exact-head Hosted OFF-1B tests including OFF-1S, 2 Worker E2E and 19 OFF-0 checks; new formal Codex review, correct every P1/P2 and resolve threads before separately authorized Merge. Operator must validate real launcher api_pid/start/euid/cwd, exact uvicorn command/process-title behaviour, /proc/net/tcp and FD visibility, and private SQL/Report Job live responses. Stronger authenticated local IPC (peer credentials / mTLS), signed artifact provenance, full Agent/LLM/ES and physical network isolation remain separate future gates.


## 2026-10-29 OFF-1S PR #316 review follow-up

- New P2 on exact old HEAD `5469b644bf4936468397876299681bc01fcef89f`:
  non-leader thread with unshared FD table could hold listener unseen by
  leader-only global scans. Thread-task enumeration and synthetic/real Linux
  regressions committed; require **new exact-HEAD** Hosted focused pytest,
  two Worker E2E and 19 OFF-0 checks, reply in the original P2 thread, and
  complete formal Codex review on the FINAL docs/code HEAD. Do not merge
  until separate user instruction.
- Require operator-authorized real private Linux listener/SQL/Report Job
  evidence; hosted simulated proof is never physical-airgap acceptance.

## 2026-10-29 OFF-1T next gates

- Require final-head Hosted focused CI, 2 legacy Worker E2E, 19 OFF-0 contract checks and formal completed Codex Review; fix new actionable findings and request separate user approval before Merge.
- Determine whether PR #315 is fully superseded once standalone CLI is reviewed. Keep both existing features' safety guards intact until then. Actual private Linux SRAF operator evidence and full air-gap acceptance remain pending.


## 2026-10-29 SRAF high-load reliability release gates

- Validate exact latest PR #319 HEAD with hosted focused/legacy E2E tests and OFF-0 contracts; complete fresh formal `@codex review` and fix any actionable P1/P2 findings before seeking explicit user merge authorization.
- Request operator-authorized Linux preflight/acceptance separately from normal /healthz and API listener. Observe startup phases, SQL/ES/Worker identity and authentic model/Word execution under controlled busy-Ollama conditions, without reinitializing live DB/leases as an incidental diagnostic.
- Investigate Data Agent LiteLLMModel.generate timeout/total deadline, real report-generation >300s stage accounting and selector retry/timeout endpoint. Confirm real evidence quality and fallback trace/UI semantics with representative cases.

## 2026-10-29 PR #319 current review gates

- Confirm latest Hosted workflow success on exact new HEAD; request a new formal Codex review and resolve three existing P2 threads only after fixes are independently checked. Re-review any further P1/P2. Explicit user approval is required before Merge.
- Follow-up: total monotonic deadline/async status for potentially prolonged Operator E2E preflight, including LiteLLMModel.generate; response timeout alone is not an absolute wall-clock guarantee. Capture safely redacted operator Linux evidence of API readiness, real Report Jobs/DOCX and field-selector fallback under competing model load.

## 2026-10-29 Post-#319 Linux operator baseline and remaining live gates

- Validate new composed read-only baseline on actual deployed Linux **without restarting services**: `python tools/sraf_runtime_baseline_readonly.py --project-root "$PWD" --api-port 9002`. Record redacted JSON at idle and under controlled Ollama contention; `--no-network` skips even anonymous GET. Comparing samples cannot establish root cause of an old 90s startup stall.
- Before merge of this new PR: exact-head Hosted focused/Worker E2E/OFF-0 tests, formal Codex Review CLEAN on final HEAD, resolve all P1/P2, explicit separate user merge command. Preserve OFF-1T and OFF-1B independent diagnostics; do not declare private Linux E2E accepted.
- Independently address E2E deferred-preflight **absolute** monotonic deadline or asynchronous preparation, and Data Agent LiteLLMModel.generate timeout. Current 600s HTTP inactivity timeout is not a strict wall clock limit. Verify real Linux SQL/ES and DOCX with separate operator approval; no automatic high-load test on active service.

## 2026-10-29 E2E Data Agent bounded-probe follow-ups

- Validate actual LiteLLM/smolagents version and Ollama under busy-model load before claiming the E2E-only 30s request timeout reliably ends a stuck network call; Hosted fake timeout tests only prove parameter forwarding and fail-closed classification. Complete exact-HEAD Hosted CI and formal Codex Review; no merge without explicit command.
- Still design authenticated operator preflight as bounded **whole-operation monotonic deadline** or async status/polling with cancellation/fixture consistency, rather than conflating Requests' 600s per-read timeout with full lifetime. Diagnose heavy report >300s and Field Selector metadata using redacted Linux traces after separately authorized deployment.

- 2026-10-30 E2E follow-up: after process-local preflight in-flight guard/status, design server-side monotonic total deadline with stage budget propagation, bounded ES/provider calls, truthful `RUNNING_OVERDUE`/terminal `TIMEOUT` semantics, immutable-plan/fixture ownership and safe multi-process polling. Linux live/high-load operator acceptance and real SQL/ES/LLM/DOCX checks remain pending. Do not merge this branch or #322 without separate authorization.
