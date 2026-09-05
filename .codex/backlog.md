# 待辦事項（Backlog）

## 2026-09-04 Phase 1B / 1C handoff

- Execute real SQL Server Phase 1B acceptance from an explicitly authorized environment.
- Implement the authoritative Phase 1C Design/Plan in two reviewed gates: 1C-A control plane first, then 1C-B execution bridge only after Gate A review PASS. Phase 1C owns recurrence, due/expiry selection, Batch Run creation, and Phase 1A handoff; it remains not implemented.
- After repository completion, execute real Phase 1C SQL/worker/Report Job/DOCX acceptance from an explicitly authorized environment. Repository fake SQL/transport evidence must not be called deployment acceptance.

## Current Summary

### Phase 0 deployment acceptance

- From an operator environment with private deployment and Elasticsearch access, run the complete Service Key → report/analysis Router → real Elasticsearch evidence → long Agent synthesis → signed Word → valid DOCX chain.
- Only after the real E2E passes, create and smoke-test replacement acceptance credentials, revoke prior credentials, verify their next protected request returns 401, and move the harness to environment/ignored local configuration. Preserve existing working credentials until then.
- Future Phase 0/3 security work includes per-end-user OpenWebUI identity propagation, integration credential rotation, per-principal quotas/rate limits, request size limits, and observability. Batch Scheduler, Server Dashboard, and Windows GUI remain outside Phase 0.

### Report Jobs and retrieval

- Consider Report Job retention/cleanup, capacity/metrics, cancel, retry, webhook, and shared queue/object storage. Current single-process SQLite/local disk is not HA or exactly-once.
- Separately design structured retrieval exclusions/directives before changing Data Agent, Tool, or `query_meta` contracts.
- Continue multi-event event-cluster merging, selectors, Editor event-list workflows, and event-level/nested indexing work described in `docs/multidim_event_json_multi_event_todo.md`.

### Authentication, UI, and audit

- For multi-worker deployments, move login/registration/reset throttles to shared infrastructure; evaluate MFA/re-authentication, CSP/XSS hardening, HttpOnly cookies with CSRF protection, and stronger registration abuse controls.
- Consolidate reusable reset-token, navigation, and audit-tool components; add browser E2E coverage when Playwright/runtime is available.
- If audit volume grows, add server-side category/action and user filtering plus export support.

### Data ingestion and consistency

- Replace remaining naive UTC datetime calls with timezone-aware values.
- Consider downloadable Excel import error rows and clearer alias/match diagnostics.
- Design SQL View mode with explicit schema/name/permissions, safe identifiers, audit/hash/downstream semantics, and no stub claims.
- Define SQL/ES lineage plus delete outbox/tombstone and reviewed reconciliation instead of synchronous cross-system hard deletion.

## Recent Changes

- 2026-09-03: Review v3 repository completion items were implemented and freshly verified; only operator deployment acceptance and post-pass credential hygiene remain for Phase 0.
- 2026-09-02: Unified security-boundary foundations, signed capabilities, Service Keys, and owner-aware Report Jobs were completed. Historical details are archived.

## Archived History

- `.codex/archive/backlog.md-20260903-000000.md` — compacted 2026-09-03; contains all prior Phase 0 audit entries and dated backlog details from 2026-06-11 through 2026-09-03.

## 2026-09-04 Phase 1 deployment follow-up

- From the private operator network, execute the documented two-task tabular-plus-JSON real SRA/Elasticsearch Batch Scheduler acceptance, exercise stop/resume against the same remote job, inspect both DOCX reports, then create/test a replacement key and revoke/verify the old key. Do not treat repository mocked transport tests as this acceptance.

## 2026-09-04 Phase 1C v2 implementation gates

- Phase 1C Design v1 / Plan v1 / Prompts v1 are superseded by v2 after Design Review v1. Implement only v2 in two reviewed gates; 1C-A remains not started, and 1C-B remains prohibited until 1C-A is merged, its Implementation Review is PASS, and the new actual `main` baseline is recorded.

## 2026-09-04 Phase 1C-A follow-up

- Phase 1C-B remains prohibited until Gate A is merged and its human/ChatGPT Implementation Review records PASS. Gate B owns the Phase 1A seam/bridge, pre-handoff expiry, worker, reconciliation, manual trigger execution, and root-bound Word history.
- Execute Phase 1C live SQL Server acceptance only from an explicitly authorized environment; repository fake-ODBC evidence is not deployment acceptance.

## 2026-09-04 Phase 1C-A Review v1 blocker

- Resolve Finding G through a reviewed design change that makes schedule lifecycle mutation and durable audit acceptance atomic (or explicitly redefines the authority contract). Phase 1C-B remains prohibited until this blocker and Gate A review are closed.

## 2026-09-05 Phase 1C-A v3 closure

- Implement Design/Plan v3 C1–C8: canonical schema v2; direct fresh-v2 initialization; recognized PR #200/#201 v1 migration; 240-character exact task identity; same-schedule composite constraints; transactional lifecycle audit outbox; bounded at-least-once JSONL projection; and failure/security/regression evidence.
- Phase 1C-A current implementation exists but repository gate is NOT PASS pending the v3 closure PR and explicit post-merge Implementation Review. Phase 1C-B is NOT STARTED and remains prohibited until that PASS and a new actual `main` baseline are recorded.
