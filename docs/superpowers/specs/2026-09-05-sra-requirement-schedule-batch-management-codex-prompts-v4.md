# SRA Requirement Schedule + Batch Management — Codex Execution Prompts v4

**Design:** `docs/superpowers/specs/2026-09-05-sra-requirement-schedule-batch-management-design-v4.md`
**Plan:** `docs/superpowers/plans/2026-09-05-sra-requirement-schedule-batch-management-plan-v4.md`

> **Codex Prompts v4 supersede Codex Prompts v3.** Prompts v1–v3 remain historical records. **Design v4 supersedes Design v3. Plan v4 supersedes Plan v3.** Do not execute any old prompt.

## Prompt A — Phase 1C-A v4 Closure

```text
# Codex Execution Contract — Phase 1C-A v4 Closure

Repository: hun186/poc-agent
Authoritative branch: main
Authority: 2026-09-05 Phase 1C Design v4 and Plan v4 only.

Design/Plan/Prompts v1–v3 are superseded historical records.
Do not execute old Prompt A.
Do not execute Prompt B yet.

This contract closes the already-merged Gate A implementation through Plan v4 C1–C8 only. It is not a greenfield replay of A1–A12 and does not authorize Phase 1C-B.

Before implementation, rebaseline actual current main: report pwd, repository root, branch, HEAD, status, latest log, remotes, and ancestry of the recorded baseline. Fetch only when configured/permitted. Current source is authoritative; never fabricate branch/SHA/PR/CI state. Read every applicable AGENTS.md, then repository memory in its required order. Read Design v4 and Plan v4 completely, then inspect current requirement_scheduler, schedule router/main, Editor audit/RBAC helpers, Phase 1B external_item_id schema, Phase 1A task identity interfaces, and all schedule tests.

Implement C1–C8 with strict RED then minimal GREEN changes and independently reviewable commits. Preserve canonical schema_version=2; direct fresh-v2 creation; exact whole-catalog PR #200/#201 v1 descriptors including the twelve-FK required/absent matrix; one-transaction ordered v1→v2 migration with marker 2 last; and persisted configuration validation that fails closed for invalid active/approved versions and always revalidates before later approval/activation.

Implement only Design v4's narrow PR #200 compatibility repair after proving Gate-B evidence absent: exact `phase1c-<batch_run_id>` to `reqrun-<batch_run_id>`, and selected exact internal requirement ID to the joined immutable Phase 1B `external_item_id`; retain skipped NULL, never truncate/hash, fail closed on any unexpected pattern, and never rewrite PR #201 canonical IDs. Preserve `NVARCHAR(240)`, same-schedule composite integrity, transactional SQL audit authority, safe bounded payload/errors, and at-least-once `append_audit_event` projection. Project `ts` from immutable outbox `created_at`, so retries preserve the same stable event ID and lifecycle timestamp. Make both success and failure metadata updates pending-row compare-and-set operations so a later failure cannot regress an already delivered row.

Do not claim SQL and filesystem are atomic or JSONL is exactly-once. Projection failure after SQL commit leaves domain and outbox committed/pending. Exact no-op lifecycle replay emits no duplicate state-transition event. Do not expose raw outbox internals publicly.

Outbound-execution prohibitions remain absolute. Do not implement or add: Phase 1A task import seam/bridge; Report Job submission; Agent or Elasticsearch execution; pre-handoff loop; recurring scheduling worker; manual-trigger execution API; remote reconciliation; Word history; Phase 2 UI; Windows GUI; direct Phase 1A SQLite access; imports of Agent, Elasticsearch execution, ReportJobWorker, or Word renderer; or a FastAPI scheduling thread. The bounded audit projector is not an execution worker.

Run every Plan v4 RED/GREEN command, focused/regression/full tests, compileall, diff check, prohibited-import and credential/runtime-artifact checks, and scope inspection. Run live SQL only with explicit authorization; otherwise record NOT EXECUTED. Update persistent memory with observed evidence, preserve historical review facts, commit all changes, and create a PR targeting main when authenticated tooling exists. Do not merge.

Report baseline/result SHAs, changes, exact commands/counts, migration/audit/crash/security evidence, live acceptance, deviations, final tree, and actual PR state. Do not self-declare Gate A PASS; that verdict belongs to post-merge human/ChatGPT review.

Successful completion wording:
Phase 1C-A v4 closure repository gate ready for post-merge Implementation Review.
Phase 1C-B NOT STARTED.
```

## Prompt B — Phase 1C-B (BLOCKED)

```text
# Codex Execution Contract — Phase 1C-B Execution Bridge

Repository: hun186/poc-agent
Authoritative branch: main
Authority: Phase 1C Design v4 / Plan v4 only; v1–v3 Design, Plan, and Prompts are superseded historical records.

BLOCKED. Execute only after all three facts are present and verified:
1. Phase 1C-A v4 closure PR merged;
2. post-merge Implementation Review explicitly PASS;
3. new actual main baseline recorded.

If any fact is absent, stop without code changes. Code presence, a green PR, or “ready for review” is not PASS. Rebaseline current main and verify merge ancestry before work. Read all repository instructions/memory and Design v4/Plan v4; inspect actual source because it overrides stale paths.

After the gate is explicitly opened, create a new reviewed Gate-B implementation plan derived from the still-valid Design-v4-incorporated Gate-B contracts; do not execute obsolete Plan-v2 task text as authority. Preserve at minimum:
- one narrow Phase 1A programmatic import seam shared with file import; Phase 1C never accesses Phase 1A SQLite;
- exact selected external_item_id task identity and deterministic phase1a_batch_id="reqrun-"+batch_run_id;
- second expiry check immediately before first Phase 1A handoff; already dispatched work continues with elapsed evidence;
- persisted non-secret phase1a_output_root_fingerprint before handoff and fail-closed verification on resume, reconciliation, and Word history;
- an explicit one-active `python -m requirement_scheduler worker [--once]`, never a FastAPI scheduler thread;
- restart recovery across SQL creation/import/submission/remote completion/artifact/finalization crash windows with one occurrence, one Phase 1A batch, and one logical Report Job;
- checkpoint anti-regression based only on immutable monotonic requirement_version_number with matching ID, never membership/run/completion order;
- manual trigger schedule-scoped idempotency `(schedule_id,trigger_request_id)`, no recurrence advance, and transactional SQL outbox audit authority for creation;
- Word-history root fingerprint verification before confined relative artifact resolution; Phase 1C neither copies nor renders DOCX and exposes no absolute path;
- existing Phase 1A Report Job HTTP client/state machine, authentication/RBAC, safe errors, SQL locking, and at-least-once audit projection.

Never import Agent, Elasticsearch execution, ReportJobWorker, or Word renderer; never add arbitrary SQL/options/schedule expressions, a duplicate execution engine, queue, distributed scheduler, UI, Windows GUI, cancellation, or automatic failed-job retry. Use strict TDD, independently reviewable commits, full regressions, honest live-acceptance status, and a separate PR. Do not weaken Design v4 schema/outbox/identity contracts.

Completion may state only that Phase 1C-B repository work is ready for post-merge review; deployment PASS requires real authorized acceptance.
```
