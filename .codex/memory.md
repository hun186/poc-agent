# Project Memory

## Current Summary

- SRAF is the core report-writing/report-creation system; automated Requirement scheduling is an additional application. This FastAPI + Elasticsearch/Agent system uses `sra_api/` (with `api/` compatibility), `agent/`, `data_ingestion/` and `requirement_scheduler/`.
- SQL Server is the authority for immutable Requirement Version/Snapshot; the separately versioned `sra_schedule` schema is authority for recurring schedules, coordinator leases and Handoff. Report Jobs execute real Agent/LLM/ES and create DOCX. Do not create parallel auth, scheduler or report execution paths.
- Requirement Product Task/Create/Update authority, durable request idempotency, and ownership fences described below remain architectural contracts; verify the **current Hosted** state of Product PR #288 and later slices rather than inferring their merge from old work logs.
- OFF-1B through OFF-1H operator diagnostic slices are now merged through PR #304 (`main` merge `8d891e72acdc17981c1498377ceaffaee74ec28a`). These are **partial operator observations**, not actual Linux acceptance.
- Current OFF-1I branch `feat/sraf-off1i-handoff-lease-snapshot` (PR #305) adds a separate, explicitly gated HANDOFF-LEASE snapshot. Its query can only certify one active database lease row at the SQL server's clock instant, not the current local Worker owner or actual schedule progress.
- Deployment-authoritative real ES Mapping remains unresolved (historic `mapping_incompatible` and relocated Docker IP SAN warning). Real SQL, LLM, Worker/Report Job, DOCX, and physical network-isolation acceptance have **not** been established by Github Hosted CI.

## Requirement Product — Current Contract

- Product v1 integrates into the existing SRA management shell/Auth/RBAC. There is no second login or separate execution subsystem.
- Product Task lifecycle is `provisioning|active|disabled`. One-time Tasks remain active after provisioning; recurring Task state mirrors Schedule enablement: active/true and disabled/false.
- Product create is superuser-only. Preview remains side-effect free. Product presenters suppress Report Job native states/IDs, credentials, absolute paths, E2E markers, and trigger-request internals.
- Durable Product mutations use `requirement_product_requests` with principal + operation + idempotency key + canonical request hash. Cross-resource identities are included in hashes so one key cannot replay another Task/version.
- P1.3 one-time create preallocates cross-authority IDs, commits Requirement import/Snapshot and Schedule authorities, then atomically materializes the initial manual Run while making the Product Task visible. One-time selection semantics are anchored to the durable request `created_at`; audit/materialization timestamps use actual finalization time.
- P1.4 recurring create approves the initial Schedule Version while keeping recurrence disabled during provisioning. Its finalizer atomically enables the Schedule, computes the first due through existing Phase 1C recurrence logic, marks the Task active, and marks the request succeeded. It does not create an initial manual Run.
- Scheduled occurrence selection is evaluated at canonical `scheduled_for`, not later worker claim time. Runs with `selected_count == 0` terminalize to `completed` in the materialization transaction so empty Runs cannot remain stranded.
- P1.5 classifies Task PATCH semantics before durable reservation:
  - in-place mode: `name` and/or recurring `enabled`;
  - schedule-proposal mode: `timezone`, `recurrence`, `run_policy`, and/or `model`;
  - mixed modes are rejected before any request reservation.
- P1.5 reservation locks the Product Task, rejects provisioning, persists `base_task_revision`, and preallocates `schedule_version_id` only for schedule proposals.
- P1.5 in-place finalization locks request/Task/Schedule, enforces revision CAS, allows name changes for normal Product operators, requires superuser for recurring enable/disable, atomically mirrors recurring Task/Schedule state, increments Task revision exactly once, stores `result_task_revision`, audit metadata, bounded result, and request success.
- A same-state `enabled=true|false` in-place PATCH does not recompute or shift `next_run_at`; only a real disabled→enabled transition calculates a fresh due. One-time Tasks do not support enabled-state transitions in v1.
- P1.5 schedule-proposal updates create exactly one immutable request-owned draft and never approve/activate it, change active Schedule Version, change `next_run_at`, change enabled state, or increment Product Task revision. Successful proposal requests keep `result_task_revision=NULL`.
- Schedule-proposal retry first recovers the exact preallocated draft identity if it already exists; it does not rebuild the draft from a newer active config after a crash. Draft activation remains a separate P1.5A superuser-only operation using the proposal's persisted `base_task_revision` CAS anchor.
- P1.6 transactional low-level Product ownership fences were implemented and merged through PR #286; P1.7 Snapshot CAS and its exact Hosted merge/deployment state must be checked independently. Do not rewrite old unverified Product work as deployed acceptance.

## Verification and Acceptance

- Never treat Hosted CI, 19 OFF-0 schema-only checks, stubbed SQL/network tests, or a Worker PID/DB lease snapshot as FULL_LIVE; no live deployment is modified via these PRs.
- Before Merge: verify exact current PR HEAD, Hosted CI success on that HEAD, completed formal Codex Review with zero open P1/P2 and zero unresolved Review Threads, plus the user's explicit `merge` command. Do not use stale snapshots.
- OFF-1F local Ollama generation requires actual same-listener PID, server `OLLAMA_NO_CLOUD=1` and compatible version; loopback/inventory alone cannot disprove cloud forwarding. OFF-1G SQL uses a separately granted readonly diagnostic account, strict TLS peer identity and constant SELECT, not a proof of actual SQL principal read-only authority.
- OFF-1H reads bounded launcher Schedule/Handoff identity files and matches trusted /proc start/uid/cwd/exact argv; no progress/SQL lease proof. The canonical verifier now rejects symlink/FIFO races and arbitrary appended role strings.
- OFF-1I only under `--probe-network --probe-sql-read --probe-worker-lease`, requiring OFF-1G success, reads one parametrized TOP(2) lease predicate query. No SQL mutation, owner/token exposure, local owner association or Schedule worker heartbeat. Feature acceptance remains NOT_TESTED.

## Recent Changes

- 2026-10-24 PR #304: merged after exact-head Codex CLEAN; Host CI 1,047 OFF-1H-focused tests, 2 existing E2E Worker tests and 19 OFF-0 checks PASS. Shared Worker verifier hardened and old E2E tests updated. No Linux rollout.
- 2026-10-24 PR #303: OFF-1G SQL Server fixed-query diagnostic merged; 1,008 pytest and OFF-0 19 PASS. SQL read access and TLS still need operator validation.
- 2026-10-24 PR #302: OFF-1F controlled local Ollama generation merged after fixing cloud-forwarding P1; 956 focused pytest, 1,131 OFF-1A and OFF-0 19 PASS on exact reviewed head.
- 2026-10-24 PRs #298–301: partial ES selector/mapping/search, matrix, LLM inventory slices merged after their own review gates; prior per-commit details are fully archived.
- 2026-10-24 PR #305: OFF-1I Handoff lease snapshot initial Hosted CI run #40080725404 passed 1,079 focused pytest, 2 legacy E2E tests and 19 OFF-0; first Codex review raised P1 about mandatory memory compaction, **not yet CLEAN**. Exact new HEAD re-review required after this archival/compaction.
- 2026-10-24: mandatory AGENTS.md §Memory Compaction triggered (>20 dated work records). Full unchanged active memory and backlog were copied to the timestamped archives below and re-fetched byte-identical before condensing. Unresolved Product, ES, SQL, Worker and OFF-1I work kept here and in `.codex/backlog.md`.

## Archived History

- `.codex/archive/memory.md-20261024-170825.md` — byte-identical 38,469-character active Project Memory before this 2026-10-24 compaction, including all 2026-10-22 through OFF-1I detailed review chronology.
- `.codex/archive/backlog.md-20261024-170825.md` — byte-identical 20,489-character active backlog before this compaction, preserving every historical open/closed task statement.
- `.codex/archive/memory.md-20261021-165000.md` and `.codex/archive/backlog.md-20261021-165000.md` — earlier full histories; follow their archive chains for legacy Product and OFF records.
- Other active `.codex/architecture.md`, `api_contract.md`, `decisions.md`, and `known_issues.md` remain separate project context; do not replace their authority with this summary.

## Compaction Record

- 2026-10-24: archived both source files first, re-fetched each and verified identical full text and Git blob SHA. Then condensed active records below the 20-block/200-line target. This compaction changes **only documentation**, not any acceptance claim. Verify the new exact PR HEAD with real Hosted tests and formal Codex review before merge.
