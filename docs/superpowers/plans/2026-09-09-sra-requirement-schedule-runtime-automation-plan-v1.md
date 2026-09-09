# SRA Requirement Schedule Runtime Automation — Implementation Plan v1

**Repository:** `hun186/poc-agent`
**Planning baseline:** `b8bcd779815337bb386a97fc457a5f49663fb2b6` (PR #225 merge)
**Design:** `docs/superpowers/specs/2026-09-09-sra-requirement-schedule-runtime-automation-design-v1.md`
**Scope:** future Phase 1C runtime automation completion delta only
**Status:** plan for human/ChatGPT review; do not execute as part of the documentation task

> Re-fetch and rebaseline hosted `main` before execution. Current source wins stale paths. Execute strict **RED → minimal GREEN → focused regression → cross-phase regression → review**, retaining test output and small reviewable commits. Do not redesign architecture or auto-merge.

## Task 0 — Rebaseline and prove the gap

Read `AGENTS.md`, all active `.codex` memory, the Design, this Plan, the current `requirement_scheduler` source, related tests, and operations documentation completely. Record repository, branch, hosted baseline, clean status, and any source deviations. Prove with a scoped search that `ScheduleStore.claim_due()` still has no production runtime caller and that the only existing CLI command is `handoff-worker`. If an automatic caller exists, stop and return to design review rather than duplicate it.

**Review boundary:** no file modification before the source/authority contradiction check.

## Task 1 — RED: specify the focused worker contract

Create a focused schedule-worker test module using current test naming/fake-store conventions. Prefer `tests/test_requirement_schedule_worker.py` unless the actual rebaseline exposes a more specific established name. Tests must initially fail because the worker and CLI command do not exist.

Required RED cases:

1. no due schedule delegates once and creates no Batch Run;
2. one due schedule invokes `claim_due()` and the existing store materializes a scheduled Batch Run;
3. persisted `next_run_at` advances only through existing store behavior;
4. disabled schedules are ignored by the existing store query;
5. multiple due schedules are eventually processed over bounded iterations without duplicate occurrence identity;
6. restart/replay does not duplicate a scheduled occurrence;
7. a blocked poll wait is interruptible by graceful stop;
8. invalid configuration or schema initialization fails closed before the first claim;
9. CLI keeps `handoff-worker` unchanged and adds `schedule-worker` plus `--once`;
10. schedule-worker makes no HTTP request;
11. worker dependency/import inspection excludes Agent, Elasticsearch, `ReportJobWorker`, `ReportJobStore`, `BatchSchedulerService`, and Batch Scheduler store; and
12. runtime persistence errors use bounded wait/retry with safe evidence, while invariant/startup errors fail closed.

Use integration-style existing ScheduleStore fakes where needed for Batch Run/advancement/disabled/uniqueness proof. Do not reproduce recurrence algorithm cases in worker tests. Record the exact RED command/output and why it failed.

## Task 2 — Minimal GREEN: add the schedule-only runner

Create `requirement_scheduler/schedule_worker.py` (or document a source-consistent focused alternative) containing a dependency-injected runner/factory with:

- existing Requirement SQL registry and schedule/Requirement schema settings;
- bounded positive poll interval and bounded actor validation;
- `ScheduleStore.initialize()` before polling;
- injected aware-UTC clock;
- one `ScheduleStore.claim_due()` call per iteration;
- `stop_event.wait(...)` for interruptible idle/transient-error polling;
- no domain mutation outside the store; and
- safe fatal/transient/graceful-stop outcomes without raw exception disclosure.

Modify `requirement_scheduler/cli.py` minimally to add `schedule-worker [--once]`. Preserve `handoff-worker` construction and behavior byte-for-byte where practical; refactor shared registry/store construction only if tests demonstrate a clear need. Wire SIGTERM as well as KeyboardInterrupt to the stop event without placing work in FastAPI.

Do not modify `ScheduleStore.claim_due()`, migrations, schema, recurrence, handoff, gateway, Report Job, Agent, or FastAPI code. Run the focused tests to GREEN and retain output.

## Task 3 — Focused persistence and lifecycle regression

Run the new worker suite together with existing due-claim transaction, schedule store/service/API, recurrence, materialization, checkpoint, and CLI/handoff tests. Demonstrate:

- one-at-a-time claims eventually drain multiple due schedules;
- the unique scheduled occurrence and lost-race winner behavior remain store-owned;
- persisted advancement and disabled filtering are unchanged;
- `--once` validates startup and makes exactly one claim;
- stop interrupts the polling wait; and
- no HTTP/artifact/handoff call is reachable from the schedule worker.

If a failure exposes a pre-existing source blocker, stop and request a Design/Plan amendment; do not broaden the worker or silently redesign `claim_due()`.

## Task 4 — Operations and process supervision documentation

Update `docs/operations/requirement-scheduling.md` (or the current authoritative replacement) to remove stale Gate-A-only worker statements and document two separately supervised processes:

```text
python -m requirement_scheduler schedule-worker
python -m requirement_scheduler handoff-worker
```

Document optional `--once`, server-owned configuration, positive polling, startup failure, safe logging, SIGTERM behavior, restart/backoff, health/observability expectations, and the indirect SQL Batch Run/Run Item handoff. Include a systemd/container-oriented example without credentials. Explicitly state that no FastAPI lifespan scheduler, HTTP call, or execution dependency belongs to schedule-worker.

Update `.codex` memory/status only with actual implementation and verification evidence. Do not claim live automatic scheduling unless an authorized deployment run actually occurs.

## Task 5 — Cross-phase regression and static boundary gate

After the focused suite passes, install dependencies as required by `AGENTS.md`, then run the current equivalents of:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py --tb=short
PYTHONPATH=. pytest -q tests/test_requirement_schedule_*.py tests/test_requirement_handoff_*.py --tb=short
PYTHONPATH=. pytest -q tests/test_requirement_*.py tests/test_batch_scheduler_*.py tests/test_phase0_security_acceptance.py --tb=short
PYTHONPATH=. pytest -q tests --tb=short
python -m compileall -q requirement_scheduler data_ingestion/requirements batch_scheduler sra_api api tests
python -m requirement_scheduler --help
python -m requirement_scheduler schedule-worker --help
git diff --check
```

Add static import/dependency assertions precise enough to reject HTTP clients and the prohibited production dependencies without false positives from documentation/type-only terms. Confirm no migration/schema/dependency/lockfile changes and preserve PR #223's HTTP `202`/native status, PR #224's aware UTC SQL clock, and PR #225's `READPAST,READCOMMITTEDLOCK` behavior through existing tests.

## Task 6 — Review handoff and PR

Self-review the Design invariants and every diff. Report:

- repository, exact baseline/result SHA, branch, PR URL, and no auto-merge;
- changed files and behavior;
- RED output, GREEN output, focused and cross-phase output;
- deviations with source evidence;
- startup/runtime safety and dependency-boundary evidence;
- risks and all unexecuted live acceptance;
- preservation of the verified manual Phase 1C-B Golden Path; and
- explicit JT-1/LangGraph non-work.

Commit and open a review PR. Repository tests may establish implementation readiness, not deployment acceptance. Human/ChatGPT review owns acceptance of the implementation.

## Traceability matrix

| Design requirement | Plan proof |
|---|---|
| Existing store owns due semantics | Tasks 1–3 |
| One claim/iteration and eventual multiple-due progress | Tasks 1–3 |
| Aware UTC | Tasks 1–3, 5 |
| Interruptible bounded polling | Tasks 1–3 |
| Fatal startup vs transient persistence vs stop | Tasks 1–3 |
| Existing handoff-worker unchanged | Tasks 1, 2, 5 |
| No HTTP/execution/Phase 1A coupling | Tasks 1, 2, 5 |
| External supervision, not FastAPI | Tasks 2, 4, 5 |
| No schema/recurrence/materialization redesign | Tasks 0, 2, 5, 6 |
| Honest repository/live acceptance separation | Tasks 4, 6 |
