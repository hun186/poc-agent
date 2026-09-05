# SRA Requirement Schedule + Batch Management — Codex Execution Prompts v5

**Design:** `docs/superpowers/specs/2026-09-05-sra-requirement-schedule-batch-management-design-v5.md`
**Plan:** `docs/superpowers/plans/2026-09-05-sra-requirement-schedule-batch-management-plan-v5.md`
**Reviewed baseline:** `d56a8a061446400e324384f2719af3c95ba7d0af` (PR #204 merge)

> Prompts v5 supersede v4. Older Design/Plan/Prompts remain historical and must not be executed.

## Prompt A — Phase 1C-A v5 correction/closure

```text
# Codex Execution Contract — Phase 1C-A v5 Closure

Repository: hun186/poc-agent
Authoritative branch: main
Authority: Design v5 and Plan v5 only.

Do Phase 1C-A correction/closure only. Do not execute Prompt B or implement any Gate-B feature.

Before edits, rebaseline actual hosted main. Report repository, branch, HEAD, status, remotes, latest log, and ancestry; fetch when configured. Read all applicable AGENTS.md and .codex memory in required order. Read Design v5 and Plan v5 completely. Inspect actual PR #200, #201, and #204 migrations/store/audit/router/tests. Current source overrides stale documentation. Never fabricate SHA, PR, CI, test, or deployment state.

Use strict TDD: for every Plan v5 task demonstrate a relevant RED failure, implement the minimum GREEN correction to the actual PR #204 implementation, run focused tests, review the diff, and use independently reviewable commits. Production catalog classification must execute real parameterized SQL Server sys-catalog queries through normal DB-API execute/fetchone/fetchall; never add a fake-only production cursor hook. Encode exact source-derived v1 descriptors: PR #200 and PR #201 share all vocabulary widths, and differ primarily in reviewed internal FKs/constraints. Compare complete columns, keys, unique/non-unique filtered indexes, and FK bindings, rejecting extras/equivalents/hybrids.

Generate explicit canonical-v2 DDL rather than joining v1 SQL and using broad string replacements. Require one marker row, marker 2 last, marker re-read after fresh/migration, and validation-only existing-v2 startup. Implement separate PR #200/#201 migrations. PR #200 must prove every Gate-B absence and immutable RequirementVersion identity relation before its one-time placeholder repair; do not drop absent constraints. PR #201 preserves identities/internal FKs and replaces only simple owner links superseded by composites. Both widen only phase1a_task_id, postvalidate complete canonical v2, and fully roll back on any failure.

Explicitly coerce persisted run_policy strings through RunPolicy (or equivalent), proving all three supported values and safe invalid rejection. Reconcile the exact authoritative outbox: action 96, actor, non-null schedule, nullable version/reserved run, safe_payload_json, created/delivery fields, and the non-unique filtered pending index on delivered_at,created_at,audit_event_id. Payload security uses per-action positive allowlists.

Wire bounded best-effort projection after committed lifecycle mutations and after successful scheduler initialization, without a FastAPI scheduling thread. Projection failure cannot change a committed successful domain response. Denial stays on direct audit. Both metadata outcomes CAS delivered_at IS NULL; zero rows is a benign lost race, not a current failure/success claim. At-least-once duplicates retain the same audit_event_id and lifecycle ts from outbox.created_at.

Create and run the complete test_requirement_schedule_v5_closure.py matrix against ScheduleStore.initialize() and realistic DB-API recording/scripted fakes. Run focused Phase 1C, cross-phase, full repository, compile, diff, security/artifact, and scope checks from Plan v5. Install dependencies first. Record exact results and limitations in persistent memory without erasing history. Commit all intended changes and create a PR targeting main; do not merge. Do not call repository readiness PASS: only a post-merge human/ChatGPT Implementation Review may do so.

Do not add a Phase 1A bridge/import, Report Job/Agent/Elasticsearch execution, recurring scheduler worker, manual execution, reconciliation, Word history, UI, direct Phase 1A SQLite access, or a FastAPI scheduling thread.

Expected completion wording:
Phase 1C-A v5 closure ready for post-merge Implementation Review. Phase 1C-B NOT STARTED.
```

## Prompt B — Phase 1C-B (BLOCKED)

```text
# Codex Execution Contract — Phase 1C-B Execution Bridge

Repository: hun186/poc-agent
Authoritative branch: main
Authority: the v5 design family plus a future reviewed Gate-B plan.

BLOCKED. Make no code, test, or documentation implementation change unless all three are verified:
1. the Phase 1C-A v5 implementation PR is merged;
2. a post-merge human/ChatGPT Implementation Review explicitly records PASS;
3. the new actual main baseline is recorded.

If any condition is absent, stop and report the missing gate. A green PR, merged code, or “ready for review” is not PASS. Once all gates exist, rebaseline actual main, inspect actual source, and first create/review a Gate-B implementation plan consistent with Design v5 and the still-valid Gate-B contracts incorporated from earlier designs. Do not silently redesign schema v2, identity, same-schedule integrity, transactional outbox, at-least-once projection, event timestamp, or CAS semantics.

Use strict TDD and a separate PR. Phase 1C must use the narrow Phase 1A seam, never Phase 1A SQLite or server execution internals; preserve exact external item and reqrun identities, second expiry check, output-root fingerprint, one-active external worker, restart reconciliation, version-number checkpoint anti-regression, schedule-scoped manual idempotency, safe Word references, RBAC, and transactional audit. Never add a FastAPI scheduler thread, duplicate execution engine, queue, arbitrary SQL/options, UI, or automatic failed-job retry. Do not merge or self-award deployment PASS.
```
