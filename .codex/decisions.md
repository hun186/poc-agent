# Architecture and Engineering Decisions — SRAF (active, compacted 2026-11-11)

## Current Summary

### Authoritative services and state
- Keep the existing real FastAPI `sra_api/` and `api/` compatibility, Agent/LLM, Elasticsearch, SQL Server, ReportJobStore SQLite, Handoff workers and DOCX; never use mocks as production proof or introduce a replacement Job queue.
- SQL Server immutable Requirement Set/Version/Snapshot/Import Run remains authoritative; versioned Schedule/Handoff leases fence distributed work. SQL transactions do not atomically cover ES/HTTP/filesystem changes.
- Product v4 Tasks require approved profile/version, superuser-controlled activation, owner/CAS revision and scoped canonical idempotency keys; do not weaken RBAC, Service Key scope, signed browser action capabilities or document ownership.
- Report Jobs keep owner-scoped SQLite phases/status/download and existing retry semantics; browser credentials only in memory; no blind replay on ambiguous POST and no stale auth download.

### Operator diagnostic trust and deployment
- OFF-0/1/2/3 checks, partial Linux host observations, standalone sidecars and synthetic CI are `PARTIAL_ONLY_NOT_ACCEPTANCE`; never equate `PASS_PARTIAL` with FULL_LIVE SQL→Agent/LLM→ES→DOCX or signed/disconnected release.
- OFF-1S strict listener/process/socket identity verification is required before privileged bearer requests. Production ES/SQL TLS identity must be verified; operator-only CA-verified IP SAN warnings do not attest endpoint identity. High-risk TLS exceptions require separate explicit authorization.
- Authenticated ES/SQL tests, real LLM, Requirement E2E and DOCX operations are separately opt-in. Real E2E Plan is immutable/process-local and validated after complete authorized preflight, with same-host private nofollow lock/opaque epoch; these controls are not cross-host atomic consistency. Time budgets are cooperative, not hard provider cancellation.
- Release source and selected file bytes must match separately trusted manifest hashes and secure nofollow paths; OFF-2 Wheel/metadata/ABI checks are not a complete transitive lock, signed provenance or airgap/restore proof. Never copy local registry, secrets or prompts into release/report evidence.
- Private Linux is updated using **Windows Robocopy/7z one-way incremental overlay**: do not instruct Git fetch/pull/worktree on the Linux host. Deleting a tracked path may leave a stale deployed file; only intentionally clean it after independent operator validation.

### ES retrieval and Editor search decisions
- Canonical date retrieval is #395 Event/Timeline precision and Evidence-local `event_ids`, with bounded candidate refill and incomplete-result reporting. #394 was CLOSED without merge. Never fabricate a date from article publication or another nested Event.
- Editor #398 is **separate** from SRAF report evidence retrieval: preserve GET `/v1/editor/search` allowed-index/RBAC/filter/pagination behavior and UI source projection. Prefer typed Mapping-informed nested `simple_query_string`; nested child queries must enter each parent nested context.
- Literal substring detection is limited to title/subject/UUID keyword/wildcard fields, <=6 clauses, 4–64 character single alphanumeric/underscore token; automatic only for terms with underscores, otherwise opt-in `search_mode=contains`. Keep conventional full-text results. Never execute arbitrary user-supplied query wildcards, scan raw article body with leading wildcard, modify live ES Mapping or silently reindex. Lack of keyword support results in an explicit warning, not invented recall.
- Leading-wildcard keyword operations may be expensive or disallowed by ES cluster policy. Synthetic CI is not real-index performance acceptance; measure true index p50/p95 and consider reviewed ngram/search-as-you-type migration in a separate explicitly authorized task if needed. PR #400 remains unmerged until current-head review and gates.

## Recent Changes

- 2026-11-11 #395 merged canonical Event/Timeline date integration; real private ES/LLM/DOCX not yet accepted.
- 2026-11-11 #396 special operator-only CA-verified SAN warning PR remains OPEN pending security assessment/high-risk permission.
- 2026-11-11 #400 Editor mapping-aware search candidate addresses Codex P1/P2 (API compatibility, typed multifields, verified archive-first compaction). Final-head Hosted CI, formal re-review and real ES throughput remain pending.

## Archived History

Full previous active record was archived verbatim at `.codex/archive/decisions.md-20261111-200000.md`, independently re-fetched with **identical** Git blob SHA `723b3602d143d5df5d15f773d23e43dbdebb6db2`. The archive retains historical design rationales and superseded plans; it is not evidence of current Hosted gates.
