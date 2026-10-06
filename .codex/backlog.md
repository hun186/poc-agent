# Backlog

## Current Summary

### Live acceptance (not executed by repository work)

- After merge and independent hosted-source review, run the Requirement automatic operator E2E only from an authorized deployment with valid `SRA_E2E_*` configuration. Repository tests do not prove a fresh live deployment PASS.
- Execute remaining authorized SQL Server acceptance for fresh/migrated schemas, rollback/failure injection, fencing/failover, concurrency/races, HA, and security rotation.
- Execute the complete Phase 0 Service-Key → real Elasticsearch/Agent/LLM → signed valid DOCX chain and post-pass credential rotation when an authorized environment is available.
- Execute pending unified-launcher deployment Gates SD-1 through SD-7, including durable output-root migration evidence. Do not replay or invent live evidence.

### Future architecture and product work

- Job Task JT-1 and LangGraph integration remain NOT STARTED and require new reviewed designs/plans.
- Requirement Product API + Task Center now has docs-only Design v1 and Implementation Plan v1 (`2026-10-01-sra-requirement-product-api-task-center-*`); implementation remains NOT STARTED. It must integrate with the existing SRA `/editor` management shell/Auth/RBAC, preserve import-versus-execution authorization separation, and never expose Handoff credentials or raw artifact paths to browsers. Design review additionally requires Schedule schema v4 product metadata/idempotency tables and keeps new-task/source provisioning superuser-only; implementation is still NOT STARTED.
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

- 2026-09-23: Push the deterministic LLM contract corrective to existing PR #271 when GitHub access is available, verify the hosted runtime SHA, then regenerate and commit provenance separately before deployment review.

- 2026-09-23: After the semantic-input corrective is hosted and deployed, rerun authorized functional E2E and inspect runtime Agent traces for Gaza, Taiwan Strait/gray-zone, and US-China/Indo-Pacific semantic preservation. Formal release acceptance still requires regenerated hosted provenance and `--verification release`.
- 2026-10-01: PR #277 re-review corrections require Schedule-before-Product-Task FK ordering, service-key idempotency bound to immutable key_id, idempotent task PATCH/update, and two-stage Product E2E (superuser provisioning followed by scoped service-key automation). Implementation remains NOT STARTED.
- 2026-10-01: PR #277 third-review correction requires preallocated import_run_id/snapshot_id and schedule_version_id plus authority-level same-ID replay; Product request reservation refs are intentionally non-FK. Implementation remains NOT STARTED.
- 2026-10-02: PR #277 latest review correction adds Product Task revision CAS + atomic mutable-PATCH finalization (state/audit/revision/safe result/request success in one Schedule transaction). Implementation remains NOT STARTED.
- 2026-10-02: PR #277 latest review correction makes Product-owned Schedule/source low-level HTTP mutation surfaces read-only while preserving reads and non-Product compatibility. Implementation remains NOT STARTED.
- 2026-10-02: PR #277 latest review corrections require same-transaction Product ownership fencing for low-level writes (including preallocated task-create reservations) and base_snapshot_id CAS for stale uncommitted input replacement. Implementation remains NOT STARTED.
- 2026-10-02: PR #277 latest review correction requires same-ID committed Requirement import recovery before RequirementImportService._prepare(), with A→S1, B→S2, delayed A replay regression. Implementation remains NOT STARTED.
- 2026-10-02: PR #277 final replay correction names recover_preallocated_import_result and requires it before _prepare; delayed A/S1 → B/S2 → replay A test must fail if _prepare is called. Implementation remains NOT STARTED.
- 2026-10-02: PR #277 latest review correction adds provisioning lifecycle gating and atomic task_create finalization so partial Task rows are hidden/inoperable until the owning create saga succeeds. Implementation remains NOT STARTED.
- 2026-10-02: PR #277 latest review corrections move once initial Run materialization and recurring enablement into atomic create finalization, and gate Product Run/history/artifact presenters by owning Task provisioning state. Implementation remains NOT STARTED.
- 2026-10-05: PR #277 latest review corrections split schedule-affecting PATCH into draft-only creation plus separate superuser-only task_version_activate CAS flow, and remove parent_run_id/retry ancestry from Product v1 (future work). Implementation remains NOT STARTED.
- 2026-10-06: PR #277 latest review corrections explicitly exclude draft-only proposal PATCH from Task revision increments/result_task_revision and reject mixed in-place + schedule-proposal PATCH before request reservation with requirement_task_patch_mixed_modes. Implementation remains NOT STARTED.
- 2026-10-06: PR #277 latest review corrections split P2.3 in-place vs draft-only revision semantics, define recurring product_state disabled/active as an atomic mirror of Schedule enabled false/true, reject run trigger while disabled, and add task_version_activate to the global idempotency retry checklist. Implementation remains NOT STARTED.
- 2026-10-06: PR #277 latest P1 correction makes first run_trigger admission atomic with Product Task state under the same Schedule DB lock, defines disable-first vs trigger-first ordering and same-key replay semantics, and requires a two-connection barrier regression. Implementation remains NOT STARTED.
