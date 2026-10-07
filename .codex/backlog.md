# Backlog

## Current Summary

### Live acceptance still pending

- Formal Requirement deployment acceptance remains incomplete. After merge and independent hosted-source review, run the Requirement automatic operator E2E only from an authorized deployment with valid `SRA_E2E_*` configuration; repository tests/docs do not prove a fresh live PASS.
- Resolve the live Elasticsearch `mapping_incompatible` blocker, then rerun authorized Elasticsearch capability/mapping acceptance plus the real Requirement → Schedule/Handoff → Report Job → Agent/LLM/Elasticsearch → DOCX path.
- Execute remaining authorized SQL Server acceptance for fresh/migrated schemas, rollback/failure injection, fencing/failover, concurrency/races, HA, and security rotation.
- Execute the complete Phase 0 Service-Key → real Elasticsearch/Agent/LLM → signed valid DOCX chain and post-pass credential rotation when an authorized environment is available.
- Execute pending unified-launcher deployment Gates SD-1 through SD-7, including durable output-root migration evidence. Do not replay or invent live evidence.

### Future architecture and product work

- Requirement Product API + Task Center Design/Plan v1 is approved (PR #277). P1.0 schema v4, P1.0A authority-supplied IDs, and P1.1 Product presenters/identities are merged through PR #280. P1.2 side-effect-free Product preview is merged in PR #281. P1.3 one-time create orchestration is the current slice; recurring create, routers, activation/run flows, UI, Product E2E, and browser E2E remain pending.
- Product implementation must integrate with the existing SRA `/editor` management shell/Auth/RBAC, reuse Phase 1B Requirement Import + Phase 1C Schedule/Handoff + Report Job, and never expose Handoff credentials or raw artifact paths to browsers.
- Product v1 requires Schedule schema v4 Product Task/request control-plane tables, superuser-only provisioning/activation, durable idempotency/resource-bound canonical hashes, revision/CAS rules, transactional ownership fences, provisioning visibility gates, atomic Run admission vs disable, and reviewed Product E2E coverage.
- Job Task JT-1 and LangGraph integration remain NOT STARTED and require new reviewed designs/plans.
- Consider Report Job retention, metrics, cancel/retry/webhook, shared queue/object storage, and HA/exactly-once strategy.
- Continue structured retrieval/event-cluster improvements and reference-text backfill/content coverage work.
- Consider stronger per-process worker loaded-module attestation only through a separately reviewed IPC design.
- Consider stronger sanitized SQL-registry attestation only as separately reviewed future work; do not expose the private deployment registry or add a manual expected-hash variable.

### Security, UI, and ingestion debt

- Evaluate shared auth throttling, MFA/re-authentication, CSP/XSS hardening, HttpOnly/CSRF design, stronger registration controls, and reusable audit/reset/navigation components.
- Add browser E2E when Playwright/runtime is available and improve audit server-side filtering/export as volume grows.
- Replace remaining naive UTC datetimes; improve Excel import error exports/diagnostics; design SQL View support and SQL/ES lineage/delete reconciliation.

## Recent Changes

- 2026-10-06: Product implementation started after PR #277 merge. Current slice is P1.0 Schedule schema v4 only; all higher Product gates remain pending.
- 2026-10-05: PR #277 split schedule proposal from privileged activation and explicitly deferred durable Run retry ancestry from Product v1.
- 2026-10-02: PR #277 added Product revision CAS, transactional low-level ownership fencing, input replacement snapshot CAS, same-ID import recovery before preparation, provisioning lifecycle gating, and atomic create finalization.
- 2026-10-01: PR #277 established docs-only Product API + Task Center design, Schedule schema v4 Product metadata/idempotency, preallocated cross-authority IDs, and two-stage superuser/service-key Product E2E.
- 2026-09-23: Requirement E2E semantics/provenance corrections remained subject to authorized deployment re-acceptance; archived history contains the superseded hosted-access operational details.
- 2026-09-18: bounded runtime-input provenance and Harness v2 were implemented; live deployment re-acceptance remains separate work.

## Archived History

- `.codex/archive/backlog.md-20261006-153400.md` — complete active backlog immediately before this compaction, including all 21 dated PR #277 work-record entries and earlier pending acceptance items.
- `.codex/archive/backlog.md-20260918-000000.md` — earlier full pre-compaction backlog with historical gates and superseded status detail.
- Earlier archives referenced by those files remain under `.codex/archive/`.

## Compaction Record

- 2026-10-06: Compacted active `.codex/backlog.md` after it exceeded the AGENTS.md >20 work-record trigger. Full text was archived before rewrite; unresolved live-acceptance work, Product NOT STARTED status, future architecture items, security/UI/ingestion debt, and the Elasticsearch `mapping_incompatible` blocker remain active.

## 2026-10-07 Requirement Product implementation status

- P1.0 schema v4, P1.0A authority identities, P1.1 Product presenters/identities, P1.2 preview, and P1.3 one-time create are merged through PR #282.
- P1.4 recurring Product create/finalization is implemented on `feat/requirement-product-recurring-create-p1-4` and requires exact-head Hosted review/check evidence before merge.
- Keep P1.4 limited to recurring create service/store finalization, provisioning release semantics, immutable initial-next-run replay evidence, and focused tests.
- Product HTTP router/UI, P1.5 Task update/draft activation, P1.6 atomic low-level ownership fences, P1.7 input replacement, and later Product API gates remain pending.


- 2026-10-07 P1.3 exact-head review P1 profile-binding race was fixed on the same branch; exact-head Codex re-review/check evidence is required before merge.


- 2026-10-07 P1.3 second exact-head review findings (P1 recovery ordering, P2 zero-row run) were fixed on the same branch; exact-head re-review/check evidence remains required before merge.


- 2026-10-07 P1.3 third exact-head review findings (P1 preview normalization regression, P2 expired-only zero-select run) were fixed; exact-head re-review/check evidence remains required before merge.


- 2026-10-07 P1.3 fourth exact-head review findings (P1 exact preview normalization block, P1 durable eligibility time) were fixed; exact-head re-review/check evidence remains required before merge.


- 2026-10-07 P1.3 fifth exact-head review finding (P1 finalizer selection-time drift) was fixed; exact-head re-review/check evidence remains required before merge.


- 2026-10-07 P1.4 recurring create current slice: exact-head Hosted Codex review/check evidence is required before merge. After P1.4, continue with the next planned Product gate rather than folding P1.5/P1.6 into this PR.


- 2026-10-07 P1.4 exact-head review P1 audit-payload rollback was fixed on the same branch; exact-head Codex re-review/check evidence is required before merge.


- 2026-10-07 P1.4 second exact-head review findings (P2 stale recurrence-release clock, P2 first-occurrence zero-selection) were fixed; exact-head Codex re-review/check evidence remains required before merge.
