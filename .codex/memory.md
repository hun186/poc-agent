# Project Memory — SRAF

## Current Summary

- SRAF is the core report writing system (FastAPI, Agent/LLM/Elasticsearch, Word); Requirement Product, scheduling and Handoff are added automation applications, not its sole identity. Use existing sra_api/, requirement_scheduler/, agent/, SQL Server, and existing authentication and report execution systems. No parallel schedulers or Report Jobs.
- OFF-1Q is merged into main at 50f44c6b58fd3a2e9e12b98ed9a99a88f598e2c7; earlier OFF-1P main HEAD was ff5ac56ec18a58c812deeca30381aea5b1151f70, from user-authorized OFF-1P PR #312 merge. OFF-1P two Codex P2 findings were corrected with tests; exact-head formal review CLEAN, zero unresolved threads; Hosted 1,259 focused + 2 Worker E2E + 19 OFF-0 PASS. No private Linux/SQL/DOCX/physical airgap live acceptance.
- OFF-1Q PR #313 merged; its implemented behaviour: New opt-in REPORT-LIVE row requires nine flags and actual DOCX-BYTES PASS, uses fixed read-only SQL to select one completed report_v1 item's remote job/submission IDs, then one authenticated bounded GET against the localhost Report Job API; match returned job_id, metadata submission_id/workflow_id and status=completed. Never start jobs, download Word, print secrets/IDs or infer full live release acceptance. Same SQL item binding is not atomic with the earlier DOCX byte verification; the latest scheduled run may have moved.
- SQL diagnostic access requires separately DBA-enforced SELECT-only principal, ODBC18, numeric private IPv4, strict CA plus IP-SAN TLS. API GET permits only explicit 127.0.0.1 port with operator-provided owner-scoped REPORT_JOB_READ bearer token and no proxy, redirects or retries. Listener PID, Agent/LLM/ES, full-job provenance, immutable DOCX association and physical airgap remain unverified.
- Refer to .codex/architecture.md, api_contract.md, known_issues.md, decisions.md, backlog.md for current architecture, limitations and unresolved work. Archive references below retain full prior Product and operator review history; don't load full history routinely.

## Product Durable Contract

- Requirement Version/Snapshot immutable; SQL Server authoritative. Separately versioned sra_schedule schema controls recurring schedules, Handoff and coordinator leases; Report Job uses real Agent/LLM/ES/DOCX. Product Task statuses are provisioning/active/disabled and recurring enablement mirrors Schedule. Product create / draft activation requires superuser; Preview is side-effect free.
- Product durable request idempotency uses principal, operation, key and canonical payload hash incl. cross-resource identities. One-time Task create makes initial manual run anchored to durable request created_at. Recurring first enablement happens after provisioning without an initial manual run. Due claim uses canonical scheduled_for; zero selected run terminalizes completed.
- Product Task PATCH in-place changes name/recurring enabled; immutable draft proposals alter timezone/recurrence/run_policy/model, never activate in the same request. Mixed modes rejected; preallocated IDs, CAS revision fencing, idempotent draft recovery. Same-state enabled PATCH cannot shift next_run_at; only disabled-to-enabled recomputes.
- Preview oversized form response 400 vs safe 422 may differ by FastAPI/Starlette; see known_issues. Check Hosted GitHub before claiming later Product phases or PRs complete.

## Verification and Acceptance

- NEVER call mock Hosted CI, 19 OFF-0 schema-only checks, sampled SQL, PID checks or HTTP result FULL_LIVE. Release acceptance stays NOT_TESTED until independently proven.
- Before Merge: check latest exact PR HEAD, successful Hosted CI, completed formal Codex CLEAN on SAME HEAD and zero unresolved P1/P2/review threads; require separate user's explicit merge command.
- OFF-1Q first verified Hosted Actions #40360967667 (https://github.com/hun186/poc-agent/actions/runs/40360967667) at code/docs SHA 4fa50cb962344954d05c674bfab1e5aee2c0b50c: 1,289 focused pytest PASS, 2 legacy Worker E2E PASS and OFF-0 19 schema-only PASS. Tests mock ODBC and HTTP; no live private SQL, Report Job or physical isolation. Subsequent archive and memory commits MUST be rechecked on the exact final HEAD.

## Recent Changes

- 2026-10-27 OFF-1Q PR #313: one authenticated Report Job GET correlated to persisted report_v1 SQL submission, ninth explicit operator flag, localhost only, body/auth/proxy/redirection restrictions. MERGED after two P2 corrections and exact-head clean review; live private deployment acceptance pending.
- 2026-10-27 mandatory active memory compaction: archived full original 27,635 characters first into .codex/archive/memory.md-20261027-004300.md at Git blob SHA 117c0ddfdc9c28cf3a3969f4474ad47f6cce9dc2; re-fetched and compared byte-for-byte before this rewrite.
- 2026-10-26 OFF-1P PR #312 merged as ff5ac56ec18a58c812deeca30381aea5b1151f70 after 2 Codex P2 fixes; 1,259 focused + 2 Worker E2E + 19 OFF-0; exact-head CLEAN. Local DOCX bytes/digest operator proof only, no production acceptance.
- 2026-10-25 OFF-1O #311 merged aeae06963a7b1412ae2e46172e93f8884e47ebe1: persisted Report completed artifact checkpoints only; OFF-1N #310 merged c0e37d04aa1e2326ef96fb113d1ac8e4eab0a6de: Handoff acknowledgment only.
- 2026-10-25 OFF-1M #309 and OFF-1L #308 merged Schedule-run linkage and actor-labelled claims (not PID process attribution). 2026-10-24 OFF-1K/J/I/H/G/F earlier partial probes merged, no real airgap acceptance.

## Archived History

- .codex/archive/memory.md-20261027-004300.md — byte-identical full original active Project Memory just before this OFF-1Q compaction, including all prior Hosted reviews, testing, Product contracts and OFF-1J through OFF-1P; archived and verified before rewrite. Git blob SHA 117c0ddfdc9c28cf3a3969f4474ad47f6cce9dc2.
- .codex/archive/memory.md-20261024-170825.md and .codex/archive/backlog.md-20261024-170825.md — previous full Product/airgap evolution, older historical 2026-10-21/10-06 archives linked within.
- Per AGENTS.md compaction (>20 dated work blocks) originals were archived first. Historic state cannot override current Hosted GitHub. This compaction revalidation remains subject to exact-head CI and formal review.

## 2026-10-27 OFF-1Q Codex P2 absolute HTTP deadline remediation

- Initial formal Codex Review on code/docs HEAD 4fa50cb962344954d05c674bfab1e5aee2c0b50c identified one P2: a trickle-fed HTTP body could evade Requests' per-read timeout and block indefinitely. OFF-1Q replaced streamed Requests GET with one fixed AF_INET numeric 127.0.0.1 socket GET. Connection, send, bounded headers and bounded full-body reads share a 3s monotonic absolute deadline with per-recv remaining timeout; strict HTTP/1.0-1.1 200, exactly one Content-Length, max 8KiB JSON, no chunked/compressed or unsafe redirects. Fake fd-level slow-header and slow-body regressions were added. Actions #40362535218 at e6ae4957f1e9b66c1a2081ba01ec7402266df355 SUCCESS: 1,292 focused pytest + 2 Worker E2E + OFF-0 19 schema-only PASS. This documentation update requires new exact-head Hosted CI and fresh formal Codex review, then explicit user authorization for merge. No actual private Linux SQL or Report Job acceptance claimed.

## 2026-10-27 OFF-1Q second formal Codex P2 — SQL APPLY projection fix

- Formal latest-head Codex Review on `cc8322cba6f8a67125f2a39ed96e580f43adf986` found P2: outer SQL SELECT referenced inner APPLY-only h.submission_id, which is not visible in SQL Server; mocked ODBC did not bind SQL. Fixed projection to `i.submission_id`, the derived APPLY column in outer scope. Added exact SQL projection regression assertion to fake ODBC test. Both earlier 3-second absolute HTTP deadline P2 and this SQL alias P2 require exact new-head CI and fresh formal Codex review; do not Merge before new CLEAN or operator-approved real SQL/HTTP acceptance.

## 2026-10-27 OFF-1R same-item correlation — active work

- OFF-1Q PR #313 was user-authorized merged to main at `50f44c6b58fd3a2e9e12b98ed9a99a88f598e2c7` after 2 formal P2 corrections, exact-head Codex CLEAN and Hosted 1,292 focused pytest + 2 Worker E2E + 19 OFF-0 schema checks PASS; **no** live SQL/Report Job/DOCX/airgap attestation.
- New branch `feat/sraf-off1r-same-item-chain` adds opt-in `REPORT-CHAIN` after all 10 flags and actual `REPORT-LIVE: PASS`. A **single** in-process seven-column SQL SELECT binds latest scheduled batch, one completed report_v1 run item, DOCX path/hash/root fingerprint and linked remote job/submission. Uses pinned root fd for local file and one authenticated bounded 127.0.0.1 GET with those saved exact same job/submission IDs, then compares a re-read of all seven SQL fields; a mismatch SKIPs rather than declaring a stale combined success. Neither this nor OFF-1P/Q can prove an atomic SQL/HTTP/filesystem transaction, remote process identity, full Agent/LLM/ES execution or physical airgap. Tests/CI/docs and exact-head Codex review to be confirmed separately.

## 2026-10-27 OFF-1R Hosted and first formal Codex evidence

- PR #314 initial code/docs HEAD 6eabeb842fbc7668995c55b1505604c5bb680033 received formal Codex P2 on nonexistent h.remote_job_id / h.dispatched_at in the Handoff SQL table. On latest tested HEAD 448f0650a91ed4027860fa3c880571b815dab38a, changed query to valid Run Item columns i.remote_job_id / i.dispatched_at and added a migration-authoritative REQUIRED_COLUMNS alias check (with the inner h.submission_id to outer i.submission_id APPLY projection represented explicitly). Hosted [#40437841634](https://github.com/hun186/poc-agent/actions/runs/40437841634) completed SUCCESS: **1,328 focused pytest PASS**, **2 Worker identity E2E PASS**, and **19 OFF-0 schema-only contract PASS**. The SQL itself has not executed on real private SQL Server; operator live gate remains. This memory update changes HEAD: require another exact-head Hosted SUCCESS, explicit inline P2 resolution, and fresh formal Codex Review before any separate user-approved Merge.

## 2026-10-27 OFF-1S API listener identity — current PR work

- OFF-1R PR #314 merged with explicit user approval to main `f5dce5434419fe20e0dac28ec9fa55fee991c7ef`; exact-head Codex CLEAN with 0 unresolved threads and Hosted 1,328 focused + 2 Worker E2E + 19 OFF-0 schema-only PASS; no real private SQL/API/DOCX/airgap acceptance.
- OFF-1S `feat/sraf-off1s-api-listener-identity`: add default-off eleventh `--probe-api-listener`, checking run_sra_api.sh's exact `.run_sra_api_api.identity`, Linux PID start tick, EUID/cwd/exact uvicorn argv, /proc/net/tcp bound listener inode and fd owner. When operator requests it, Report Job bearer calls are blocked unless the attestation passes; reverify listener on the already connected socket before transmitting credentials and again after response. Alternate process/namespace/IPv6 listener/ambiguous inode FAIL CLOSED to SKIP. This is only process corroboration, not cryptographic server identity or zero-TOCTOU, and does not prove network isolation or live end-to-end evidence. Tests, Hosted CI and formal review pending exact HEAD; do not Merge absent separate user command.

## 2026-10-27 OFF-1S first Hosted CI and negative fixture corrections

- OFF-1S PR #316 code/tests/docs HEAD `483266b2d9f21154fbee8bd1995ec4b72e48f383`: Hosted Actions [#40497730636](https://github.com/hun186/poc-agent/actions/runs/40497730636) completed SUCCESS: **1,338 focused pytest PASS**, **2 Worker E2E PASS** and **19 OFF-0 schema-only contract PASS**. Two earlier Hosted red builds were caused by incorrect synthetic `uvicorn --host 0.0.0.0` NUL delimiter encoding and misordered synthetic Linux proc Uid field; both fixtures were corrected without relaxing actual UID/PID/argv checks. Formal Codex review had not yet completed on current HEAD at evidence capture; this documentation commit changes HEAD and requires new exact-head Hosted CI plus fresh completed Codex review before separately authorized Merge. No real API process / private SQL / physical-airgap acceptance was exercised.

## 2026-10-27 OFF-1S PR #316 two exact-head Codex P2 corrections (pending Hosted verification)

- Codex completed formal review on 29e923e23b58b2951a240c083350a0851fb5b2d0 with two P2: actual Python-shebang Uvicorn (7 args) and setproctitle runtime process title were rejected by a strict six-argument matcher; unique listening inode and one matching API PID fd did not exclude a fork-shared/socket-passed listener whose other PID could receive bearer credentials. Both threads require corrections and re-review.
- New code matches launcher console-script shebang and exact repository SRA-API runtime title under existing UID, pinned root, PID start tick and socket checks. It also requires exclusive visible /proc process fd ownership of the listening inode; shared, unreadable or scan-capped process tables fail closed to SKIP. Added negative and positive regression tests plus operator limitations. The broad global scan may SKIP on insufficient /proc visibility and is not cryptographic/process-atomic proof. HOSTED CI, exact-head formal Codex re-review and operator live acceptance have NOT YET been verified for this new commit; no merge authorized.

## 2026-10-27 OFF-1S PR #316 real procfs regression and Hosted evidence

- First fix HEAD e9890970dce942aeb118e4170ad59e6554b102b0 Hosted run #40531392216 succeeded: 1,341 focused pytest PASS, 2 Worker E2E PASS, 19 OFF-0 schema-only checks PASS (mock/synthetic and CI-host only; not production acceptance).
- Added separate real Linux /proc process regression that launches an actual temporary Python-shebang executable named uvicorn with the exact launcher arguments, checks real PID/start/EUID/cwd/cmdline matching and wrong-port rejection, plus hardened shared-owner matrix regression assertion. This new HEAD requires its own Hosted run, formal Codex exact-head re-review, and separate explicit merge authorization.

## 2026-10-27 OFF-1S exact verified Hosted P2 regression (before final documentation SHA)

- Final functional regression commit `663f6e3e1afa500c5b9d8cf72dbb146286ed0d17`: hosted [run #40531972972](https://github.com/hun186/poc-agent/actions/runs/40531972972) completed SUCCESS with **1,342 focused pytest**, **2 Worker E2E**, **19 OFF-0 schema-only contracts**. Includes an actually launched Linux Python-shebang process and /proc identity assertion, synthetic shared socket and unreadable-fd rejection, and pre-send bearer fail-closed checks. Earlier first correction `e9890970dce942aeb118e4170ad59e6554b102b0` also had hosted run #40531392216 success (1,341 focused + 2 E2E + 19 schema-only). Both formal Codex P2 discussions answered; this subsequent documentation-only update changes HEAD and requires fresh exact-head CI and formal review. Production SQL/API/airgap acceptance remains untested; no merge authorization.


## 2026-10-28 OFF-1S PR #316 third Codex P2 remediation (pending exact-head review)

- Fresh formal Codex review of `5ff30b713801d0b293ab3bb41620f6ce74125cfe` returned one new P2: Linux procfs `hidepid=2/4` may omit non-owned PID directories entirely, so an apparently complete `/proc/*/fd` scan could falsely pass exclusive listener ownership, exposing bearer credentials to an unlisted process. Earlier two P2 Threads had already been answered and resolved; latest prior Hosted #40532441760 SUCCESS (1,342 focused tests + 2 Worker identity E2E + OFF-0 19 schema-only).
- Added a fail-closed bounded `/proc/self/mountinfo` visibility check before and after descriptor enumeration. Only a single ordinary procfs mount with absent/`hidepid=0` and no filtered subset qualifies; `hidepid=1/2/4`, unknown hidepid values, partial mountinfo or unexpected bind-root mounts SKIP. Added negative hidepid/omitted-owner and mount-change regressions, updated runbook. This is still only same-PID-namespace partial evidence, not a full trusted peer or airgap attestation. New HEAD requires Hosted CI success, formal exact-head Codex review and separate explicit merge approval.

## 2026-10-28 OFF-1S PR #316 procfs submount P2 remediation

- Latest exact-HEAD Codex review on `53b0390cb6aaeaee48e1cd656a29c69336c4558c` identified P2: procfs descendant mounts (e.g. tmpfs over `/proc/<other-pid>/fd`) can conceal a shared socket co-owner even with normal top-level hidepid=0; one old P2 review thread remained unresolved. Corrected the bounded `/proc/self/mountinfo` check to reject mounts masking numeric PID subtrees and /proc/self, /proc/thread-self or /proc/net, with ambiguous path escapes fail-closed, while allowing unrelated normal auxiliary /proc mounts. Added synthetic masked co-owner and negative proc mount regression; operator doc updated. **Do not claim validated** until exact new SHA Hosted tests and formal Codex Review complete, and do not merge without explicit user instruction. No private deployment/physical airgap acceptance.
