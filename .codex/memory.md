# Project Memory — SRAF (active, compacted 2026-11-11)

## Current Summary

- **Source of truth:** use latest Hosted `hun186/poc-agent` main/PR HEAD and exact-head Hosted CI, Codex review receipts, unresolved threads and branch protection; do not trust historical “pending” entries as current. Follow `AGENTS.md`, archive-first compaction, no mock success.
- **Production boundaries:** real FastAPI Agent/LLM, Elasticsearch, SQL Server Requirement Set/Version/Snapshot, versioned Schedule/Handoff lease workers, owner-scoped SQLite Report Job phases/RBAC/audit, and DOCX. Product v4, owner fencing, CAS and idempotency remain authoritative; don't create a second queue or silent API changes.
- **Safe diagnostics:** L0 passive and L1 /healthz/TCP can be `PASS_PARTIAL`, never FULL_LIVE. OFF-1S exclusive socket proof precedes bearer. Private L2 SQL/ES/model and L3 report/E2E require separate explicit operator authorization; no routine writes/restarts or secret/raw Evidence logs. Cooperative E2E timeouts are not hard provider cancellation.
- **Packaging:** OFF-2 local runtime/externally pinned Wheel checks are partial, not a signed transitive lock, real ODBC import, isolated installation, physical airgap, upgrade/rollback or OFF-5 recovery. `requirements.txt` direct `>=` remain unpinned.
- **Deployment:** the private Linux instance uses a **one-way Windows Robocopy/7z incremental overlay**, not a Git worktree. Never prescribe Linux `git fetch`/`pull`/`worktree`. Deleting a GitHub file doesn't remove deployed historical files.

## Recent Verified Outcomes / Open Work

- **2026-11-11 PR #395 MERGED:** authoritative nested Event+Timeline date precision, Evidence-local event IDs, bounded date-candidate refill and report completeness warnings; merged into `main` as `6896a8b2e96ec8d177636d5c9ac52cf874e577d4`. PR #394 CLOSED without merge. Real private `news_test` temporal, actual report/LLM/DOCX acceptance remain NOT_TESTED; Issue #393 remains open.
- **2026-11-11 PR #396 OPEN (NOT MERGED):** operator-only CA-verified IP SAN mismatch warning mode, strict override and redacted diagnostic; latest known HEAD `5cab77ebb4c9f3a20643fe53cee05923112014bd`; Hosted 5/5 SUCCESS and formal code review completed clean. Independent `security_review` was not recorded as completed; credential-to-IP-unverified-peer exception is security-sensitive and **requires explicit high-risk merge authorization** and assessed security gate. No private re-run asserted.
- **2026-11-11 PR #400 OPEN (NOT MERGED):** Issue #398 bounded substring Editor search (automatic literal underscore tokens only), mapping-aware nested queries, typed multifields, `rawInfo.title` and UI warning display; dedicated Python3.10/3.11 synthetic CI. Original PR HEAD `cddbba6` CI six workflows SUCCESS, but formal Codex found memory-compaction/API-contract/multifield P1/P2. Work in progress: archive-first compaction, API contract update, multifield fix and nested parent fix; **new HEAD CI/formal re-review PENDING**, no real ES performance or deployment acceptance.
- **2026-11-09 operator diagnostics:** canonical `1_完整診斷驗收_SRAF.sh` L0/L1 operator reports remain PARTIAL_ONLY; historical root `0_` shortcut retired on GitHub may persist under incremental Linux overlay. Private L1 reports showed API /healthz 200, Worker sometimes 2/2, ES/LLM TCP reachable; L2/L3 E2E NOT TESTED.
- **2026-11-08 OFF packaging/worker changes:** #368/#369 stdlib-only passive import isolation, #371 one-click quick diagnostic, #373 advanced launchers moved to `scripts/diagnostics/` all verified merged. Custom scripts/cron may need path migration; no signing or private FULL_LIVE acceptance.

## Open Handoffs (priority)

1. **#396:** keep the security-sensitive SAN trust-policy exception unmerged until formal security assessment and explicit high-risk merge approval. Do not weaken production client/TLS/CA identity.
2. **#400:** check latest SHA, all required Hosted Python3.10/3.11/Operator/Product/OFF-1/2 checks, formal Codex findings/threads, mapping multifield handling, nested parent clauses and performance risks before any Merge Gate. Real read-only `news_test` index/keyword availability, large-index latency and `search.allow_expensive_queries` support are NOT TESTED.
3. **#393/#397/#399:** private Event/Timeline date acceptance, Evidence Trace and adaptive bounded refill/token budgets remain P0/P1 separate work, never silently recover date-invalid citations. **#398** remains open for realistic index acceptance/performance.
4. **#290:** native ODBC/TLS, SQL/ES identity, Worker/Handoff, real model, Report Job/DOCX, independent Wheelhouse lock/signature and disconnected install/recovery still require authorized operator evidence.

## Archived History

Complete pre-compaction active content is preserved **verbatim** and independently verified by identical Git blob SHA:
- `.codex/archive/memory.md-20261111-200000.md` — `2acd75fccbe58fffdc5c50cec81ed2a116a9e195`.
- `.codex/archive/known_issues.md-20261111-200000.md` — `9778341e6f36db0381ae83cd4fec476513ae34a7`.
- `.codex/archive/decisions.md-20261111-200000.md` — `723b3602d143d5df5d15f773d23e43dbdebb6db2`.
- `.codex/archive/architecture.md-20261111-200000.md` — `f4637f782b33c39c410eff822fd1bc6a44d6c80b`.
- `.codex/archive/api_contract.md-20261111-200000.md` — `3ca0b353bac76615fa2aaa336b7c5d2e0ab3c313`.
Prior compaction archives remain intact. Exact old PR/test sequence and historical decisions are in the archives, not proof of current PR gates.
