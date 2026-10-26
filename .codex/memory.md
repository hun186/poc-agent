# Project Memory — SRAF

## Current Summary

- SRAF is the core report writing system (FastAPI, Agent/LLM/Elasticsearch, Word); Requirement Product, scheduling and Handoff are added automation applications, not its sole identity. Use existing sra_api/, requirement_scheduler/, agent/, SQL Server, and existing authentication and report execution systems. No parallel schedulers or Report Jobs.
- Main GitHub hun186/poc-agent HEAD as checked 2026-10-27 is ff5ac56ec18a58c812deeca30381aea5b1151f70, from user-authorized OFF-1P PR #312 merge. OFF-1P two Codex P2 findings were corrected with tests; exact-head formal review CLEAN, zero unresolved threads; Hosted 1,259 focused + 2 Worker E2E + 19 OFF-0 PASS. No private Linux/SQL/DOCX/physical airgap live acceptance.
- CURRENT FOCUS OFF-1Q PR #313, branch feat/sraf-off1q-report-job-status. New opt-in REPORT-LIVE row requires nine flags and actual DOCX-BYTES PASS, uses fixed read-only SQL to select one completed report_v1 item's remote job/submission IDs, then one authenticated bounded GET against the localhost Report Job API; match returned job_id, metadata submission_id/workflow_id and status=completed. Never start jobs, download Word, print secrets/IDs or infer full live release acceptance. Same SQL item binding is not atomic with the earlier DOCX byte verification; the latest scheduled run may have moved.
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

- 2026-10-27 OFF-1Q PR #313: one authenticated Report Job GET correlated to persisted report_v1 SQL submission, ninth explicit operator flag, localhost only, body/auth/proxy/redirection restrictions. CODED; Hosted initial PASS but latest-head review/merge pending.
- 2026-10-27 mandatory active memory compaction: archived full original 27,635 characters first into .codex/archive/memory.md-20261027-004300.md at Git blob SHA 117c0ddfdc9c28cf3a3969f4474ad47f6cce9dc2; re-fetched and compared byte-for-byte before this rewrite.
- 2026-10-26 OFF-1P PR #312 merged as ff5ac56ec18a58c812deeca30381aea5b1151f70 after 2 Codex P2 fixes; 1,259 focused + 2 Worker E2E + 19 OFF-0; exact-head CLEAN. Local DOCX bytes/digest operator proof only, no production acceptance.
- 2026-10-25 OFF-1O #311 merged aeae06963a7b1412ae2e46172e93f8884e47ebe1: persisted Report completed artifact checkpoints only; OFF-1N #310 merged c0e37d04aa1e2326ef96fb113d1ac8e4eab0a6de: Handoff acknowledgment only.
- 2026-10-25 OFF-1M #309 and OFF-1L #308 merged Schedule-run linkage and actor-labelled claims (not PID process attribution). 2026-10-24 OFF-1K/J/I/H/G/F earlier partial probes merged, no real airgap acceptance.

## Archived History

- .codex/archive/memory.md-20261027-004300.md — byte-identical full original active Project Memory just before this OFF-1Q compaction, including all prior Hosted reviews, testing, Product contracts and OFF-1J through OFF-1P; archived and verified before rewrite. Git blob SHA 117c0ddfdc9c28cf3a3969f4474ad47f6cce9dc2.
- .codex/archive/memory.md-20261024-170825.md and .codex/archive/backlog.md-20261024-170825.md — previous full Product/airgap evolution, older historical 2026-10-21/10-06 archives linked within.
- Per AGENTS.md compaction (>20 dated work blocks) originals were archived first. Historic state cannot override current Hosted GitHub. This compaction revalidation remains subject to exact-head CI and formal review.
