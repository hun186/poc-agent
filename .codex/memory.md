# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval is in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 security, Phase 1A Batch Scheduler, Phase 1B Requirement import, Phase 1C Schedule/Handoff, and the Report Job execution bridge are implemented. Job Task JT-1 and LangGraph remain NOT STARTED.
- Requirement scheduling uses external `schedule-worker` and `handoff-worker` processes supervised with the API by `run_sra_api.sh`; Report Job Worker remains API-lifespan owned.
- Requirement import authority is SQL Server with immutable Requirement Version/Snapshot history. Requirement recurrence/execution control is the separately versioned `sra_schedule` schema. Report Jobs own real Agent/LLM/Elasticsearch execution and DOCX production.
- Production jobs must never enter Requirement E2E semantic mocks. Verified E2E mock authority is job-scoped and isolated across tool threads.
- Operator E2E remains a deployment/technical observer. Repository tests or documentation review are not fresh live deployment acceptance.
- Formal Requirement deployment acceptance is still blocked by the unresolved live Elasticsearch `mapping_incompatible` condition identified during capability probing; repository/offline tests do not clear that blocker. Re-run authorized live mapping/capability acceptance after it is corrected.
- Requirement Product API + integrated Task Center Design/Plan v1 was approved and merged in PR #277. Implementation has started with the P1.0 Schedule schema v4 slice on `feat/requirement-product-schema-v4`; Product service/router/UI and create/update/run orchestration are not implemented yet.

## Requirement Product API + Task Center — Current Contract

- Product v1 integrates into the existing SRA management shell/Auth/RBAC; no second login, scheduler, queue, Report Job worker, or browser-owned execution path.
- Schedule schema v4 adds only `requirement_product_tasks` and `requirement_product_requests`.
- Product Task lifecycle is `provisioning|active|disabled`. One-time Tasks remain active after provisioning. Recurring Task `product_state` atomically mirrors Schedule `enabled`: active/true and disabled/false.
- New Task/source provisioning remains superuser-only. `db_operator` may preview, replace input on active Tasks, create prospective Schedule drafts, and trigger permitted Runs, but cannot approve/activate drafts or enable recurring automation.
- Schedule-affecting Task PATCH creates an immutable draft only. Product draft activation is a separate superuser-only `task_version_activate` operation. Low-level approval remains fenced for Product-owned Schedules.
- Product Task revision advances exactly once for successful in-place metadata/state PATCH and exactly once for successful draft activation. Draft-only proposal PATCH and input replacement do not increment Task revision; proposal `result_task_revision` remains NULL.
- Mixed in-place + schedule-proposal PATCH payloads are rejected before durable request reservation with `requirement_task_patch_mixed_modes`.
- Product-owned low-level Schedule/source mutation routes are fenced transactionally; reads remain available and non-Product resources retain existing mutation behavior.
- Product create finalization atomically releases initial execution and visibility: one-time initial Run is materialized inside the finalizer; recurring Schedule enablement/next-run calculation occurs inside the same finalizer; rollback leaves provisioning hidden/inoperable.
- Input replacement uses `base_snapshot_id` CAS. Same-ID committed import recovery occurs before `_prepare()`, so delayed replay cannot be reclassified against newer Requirement state.
- Product v1 does not persist `parent_run_id` retry ancestry. “Run again” creates an independent Run.
- Recurring disable and first manual Run admission serialize on the Product Task lock. Disable blocks new admissions but does not change replay semantics of already accepted `run_trigger` requests.
- Existing same-key/same-hash `run_trigger` requests are resolved by persisted ledger state before lifecycle checks: `reserved|in_progress|failed_recoverable` resume, `succeeded` replays success, and `failed_terminal` replays the same terminal error.
- Canonical Product request hashes bind operation plus all route/path target identities and semantic payload/input digest. At minimum Task-scoped operations include `task_id`; activation includes `task_id + schedule_version_id`; empty-body Run trigger still hashes `task_id`. Cross-resource reuse of one principal/operation/idempotency key must conflict, never replay another resource.

## Recent Changes

- 2026-10-06: Bound canonical Product idempotency hashes to path/target resource identities and added cross-Task / cross-version same-key conflict regressions to Design/Plan v1.
- 2026-10-06: Completed run-trigger admission/replay design: first admission is atomic with lifecycle state, and all persisted request states are resolved before new-admission checks.
- 2026-10-06: Defined recurring Product disabled-state mirroring and superuser-only draft activation, with revision/CAS and idempotency semantics.
- 2026-10-05: Split Schedule draft proposal from privileged activation; removed Product v1 durable retry-ancestry guarantee.
- 2026-10-02: Added Product provisioning visibility/execution gate, atomic ownership fences, input replacement snapshot CAS, and same-ID committed import recovery before preparation.
- 2026-10-06: Started Product implementation with P1.0 Schedule schema v4: two reviewed Product control-plane tables, catalog descriptors, v3→v4 migration/fresh bootstrap, and focused migration tests. Product service/API/UI remain unimplemented.
- 2026-10-06: PR #278 opening review found two P1 migration issues: whole-catalog checks/defaults were not normalized like SQL Server catalog evidence, and legacy Schedule migration/stateful tests still encoded v3 marker/index/default assumptions. Both were corrected; all Requirement Schedule test files were rescanned for remaining hard-coded v3/final-index assumptions before exact-head re-review.
- 2026-10-06: A subsequent review of the pre-fix head also confirmed Product default normalization and found the approved BIGINT revision contract was implemented as INT. `requirement_product_tasks.revision` plus request-ledger `base_task_revision` / `result_task_revision` are now BIGINT in DDL, catalog descriptors, tests, and Design/Plan.
- 2026-10-06: Review of the next pre-fix head found `normalize_sql_predicate()` removed brackets/whitespace inside quoted literals, weakening hex-character-class CHECK evidence. The shared normalizer now transforms only unquoted SQL syntax; quoted literal bytes/text are preserved, existing artifact/fingerprint descriptors retain `[^0-9a-f]`, and Product request-hash regressions reject the weakened `%^0-9a-f%` form.
- 2026-10-01: Added docs-only Requirement Product API + Task Center Design/Plan v1; PR #277 later merged and became implementation authority.
- 2026-10-01: Requirement Operator E2E CLI now follows deployed external mode by default when the operator omits the option.
- 2026-09-30: Isolated Requirement E2E semantic mocks from ordinary production jobs and propagated verified E2E authority safely into tool worker threads.

## Verification Summary

- PR #277 is merged. Product implementation is now IN PROGRESS at P1.0 schema v4 only; Product service/API/UI and later saga gates remain not implemented.
- Current P1.0 edits were source-reviewed through the hosted GitHub branch. Regression coverage now includes v4 DDL/descriptors/defaults, SQL Server catalog normalization, successful v3→v4 marker advancement, rollback on post-DDL catalog failure, and updated legacy/stateful migration fixtures. A local pytest PASS is not claimed because the execution container cannot resolve `github.com` to clone the hosted branch; post-fix exact-head Codex review remains required.
- No fresh live Requirement E2E, private SQL Server, Elasticsearch, LLM, Agent, deployment bootstrap, or DOCX acceptance was executed for this documentation task.
- Exact-head Codex review and hosted status checks are required for the P1.0 implementation PR before merge.
- Compaction verification: the 2026-10-06 memory and decisions archives have blob SHAs identical to the pre-compaction files at hosted head `364db0b1d04029570c2ff6a34b05269956751d3d`; active memory/decisions are 59/89 lines respectively, and all six required active `.codex/*.md` context files are below the AGENTS.md mandatory size/line/date-block thresholds.
- Historical test and deployment evidence is preserved in the archived memory files and should not be restated as fresh acceptance.

## Archived History

- `.codex/archive/memory.md-20261006-143100.md` — full active memory immediately before this compaction; includes all dated Product-review corrections and prior Requirement/E2E verification records through 2026-10-06.
- `.codex/archive/memory.md-20260915-170533.md` — earlier full pre-hardening history.
- Earlier archives referenced by those files remain under `.codex/archive/`.

## Compaction Record

- 2026-10-06: Compacted `.codex/memory.md`, `.codex/decisions.md`, `.codex/backlog.md`, and `.codex/known_issues.md` after robust AGENTS.md date/work-block counting. Full originals were archived first at `.codex/archive/memory.md-20261006-143100.md`, `.codex/archive/decisions.md-20261006-143100.md`, `.codex/archive/backlog.md-20261006-153400.md`, and `.codex/archive/known_issues.md-20261006-153400.md`.
- Verification: memory, decisions, backlog, and known-issues archives were created from complete hosted branch contents before active-file rewrites; archive blob SHAs exactly match the corresponding pre-compaction blobs. Recounting all six required active `.codex/*.md` files with both dated headings and dated work bullets leaves every file below the >40 KB, >400-line, and >20-work-block mandatory compaction triggers. Active files retain current Product/architecture contracts, unresolved acceptance blockers (including Elasticsearch `mapping_incompatible`), live backlog, and archive pointers.
