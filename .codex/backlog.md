# Backlog

## Current Summary

### Live acceptance (not executed by repository work)

- After merge and independent hosted-source review, run the Requirement automatic operator E2E only from an authorized deployment with valid `SRA_E2E_*` configuration. Repository tests do not prove a fresh live deployment PASS.
- Execute remaining authorized SQL Server acceptance for fresh/migrated schemas, rollback/failure injection, fencing/failover, concurrency/races, HA, and security rotation.
- Execute the complete Phase 0 Service-Key → real Elasticsearch/Agent/LLM → signed valid DOCX chain and post-pass credential rotation when an authorized environment is available.
- Execute pending unified-launcher deployment Gates SD-1 through SD-7, including durable output-root migration evidence. Do not replay or invent live evidence.

### Future architecture and product work

- Job Task JT-1 and LangGraph integration remain NOT STARTED and require new reviewed designs/plans.
- Requirement Task Center/operator workflow remains FUTURE / NOT STARTED; preserve import-versus-execution authorization separation and never expose Handoff credentials or raw artifact paths to browsers.
- Consider Report Job retention, metrics, cancel/retry/webhook, shared queue/object storage, and HA/exactly-once strategy.
- Continue structured retrieval/event-cluster improvements and reference-text backfill/content coverage work.
- Consider stronger per-process worker loaded-module attestation only through a separately reviewed IPC design.
- Consider stronger sanitized SQL-registry attestation only as a separately reviewed future design; do not expose the private deployment registry or add a manual expected-hash variable.

### Security, UI, and ingestion debt

- Evaluate shared auth throttling, MFA/re-authentication, CSP/XSS hardening, HttpOnly/CSRF design, stronger registration controls, and reusable audit/reset/navigation components.
- Add browser E2E when Playwright/runtime is available and improve audit server-side filtering/export as volume grows.
- Replace remaining naive UTC datetimes; improve Excel import error exports/diagnostics; design SQL View support and SQL/ES lineage/delete reconciliation.

## Recent Changes

- 2026-09-18: bounded runtime-input provenance omission is implemented in repository code and awaits merge plus independent review; no live Golden Path was run.
- 2026-09-16: Harness v2 and canonical schema-v2 release provenance were implemented; live re-acceptance remains pending.
- 2026-09-10: externally supplied evidence established a narrow three-item automatic technical Golden Path, but does not close broader deployment matrices.

## Archived History

- `.codex/archive/backlog.md-20260918-000000.md` — full pre-compaction backlog, including historical gates and superseded status detail.
- Earlier archives referenced by that file remain under `.codex/archive/`.

- 2026-09-22: Run live and auto capability-adaptive Requirement acceptance on an authorized deployment, including FULL_LIVE retrieval/content acceptance and final DOCX/durable state. Rebase/retarget the capability slice onto the hosted PR #270 content branch if that prerequisite remains unmerged; hosted PR state was inaccessible from this environment.

- 2026-09-23: After GitHub access is restored, push the runtime corrective to the existing PR #271 branch, verify the hosted runtime commit resolves, regenerate provenance against that hosted SHA, commit/push provenance separately, and re-read the final hosted diff. Do not reuse the prior local-only `2161ee5e...` anchor.
