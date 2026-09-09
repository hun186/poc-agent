# Codex Execution Contract — Requirement Schedule Runtime Automation v1.1

## Authorization and binding

- **Repository:** `hun186/poc-agent`
- **Authoritative design:** `docs/superpowers/specs/2026-09-09-sra-requirement-schedule-runtime-automation-design-v1.md`
- **Executable plan after review PASS:** `docs/superpowers/plans/2026-09-09-sra-requirement-schedule-runtime-automation-plan-v1.1.md`
- **Branch:** create a dedicated implementation branch from actual hosted `main`
- **Delivery:** commit implementation, open an implementation PR, and do **not** auto-merge

Plan v1 is **NOT AUTHORIZED**. Prompt v1 is **NOT AUTHORIZED**. Only Plan v1.1 + Prompt v1.1 may be executed after human/ChatGPT review **PASS**. Design v1 remains authoritative; there is no Design v1.1 or v2. Do not execute this Prompt during the documentation-correction task that created it.

## Fresh hosted rebaseline

Before editing, run and retain actual output:

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git fetch --all --prune
git branch --show-current
git rev-parse HEAD
git status --short
git log -1 --oneline
```

Record repository, branch, actual hosted `main` baseline SHA, and working-tree status. The documentation-correction baseline `a702dcf528cd6f77f26aa89aec665dcc8145acda` is historical, not evergreen. If hosted `main` is newer, use it. If no remote is configured or hosted state cannot be fetched, report the limitation and do not pretend the hosted baseline was verified.

Read `AGENTS.md`, all active `.codex` memory in prescribed order, Design v1, Plan v1.1, this Prompt v1.1, current Requirement Scheduler source/tests, and operations documentation completely. Verify from current source that `ScheduleStore.claim_due()` still claims at most one occurrence, has no automatic production caller, and `handoff-worker` remains the only implemented Requirement Scheduler command. If any premise or required interface materially differs, **STOP**, provide evidence, and return to Design/Plan review.

## Strict execution contract

Execute Plan v1.1 task-by-task with strict TDD:

1. write each exact focused failing test;
2. run and preserve the Plan's exact RED command and actual failure output;
3. state why the failure proves the missing behavior rather than an environment defect;
4. implement only the minimal production change required for GREEN;
5. run and preserve the exact GREEN output;
6. run focused, cross-phase, full-suite, compile, CLI, and static gates exactly as listed;
7. make the Plan's small exact-file commits; and
8. open an implementation PR without auto-merge.

Do not manufacture RED by breaking code. A newly added boundary test that already passes is retained as regression evidence and requires no production edit. Current source wins stale documentation, but it does not authorize architecture expansion.

## Frozen runtime requirements

- Parse only `REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL`, default `2.0`, as a finite float in inclusive range `0.1..300.0`. Invalid, non-finite, zero, negative, below-range, and above-range values fail startup before store initialization or claim and yield a nonzero exit. Never reuse `REQUIREMENT_HANDOFF_POLL_INTERVAL`.
- Use only the server-owned constant actor `requirement-schedule-worker`. No environment or CLI actor override is permitted.
- Inject the worker store and clock. Production clock is `datetime.now(timezone.utc)`. Reject a naive or non-UTC-aware injected result before claim.
- `schedule-worker --once` loads configuration, constructs and initializes/validates the store, obtains one aware UTC timestamp, calls `claim_due()` exactly once, and exits. It never loops, retries, sleeps, waits, or makes a second claim. No due or one successful claim exits `0`; safe `persistence_error`, startup/schema/config error, and unexpected/invariant error exit nonzero. Startup errors make zero claims.
- Continuous mode calls one claim per outer iteration. A successful claim rechecks stop state and may continue immediately; no-due and safe `persistence_error` call `stop_event.wait(poll_interval)`; safe persistence retry happens only on a later iteration; unexpected/invariant failure is fatal.
- `SIGTERM` and `KeyboardInterrupt` set the schedule worker stop event. Finish an in-flight `claim_due()` call; never force-cancel its SQL transaction. Do not alter existing `handoff-worker` signal semantics unless a directly affected regression proves it strictly necessary.
- Store authority remains unchanged: do not duplicate recurrence, `coalesce_latest`, due locking, occurrence uniqueness, snapshot materialization, policy, checkpoints, audit outbox, or `next_run_at` behavior.

## Absolute scope boundaries

Prefer changes only to:

```text
requirement_scheduler/schedule_worker.py
requirement_scheduler/cli.py
tests/test_requirement_schedule_worker.py
docs/operations/requirement-scheduling.md
.codex/*.md (actual evidence only)
```

Do not change `requirement_scheduler/store.py`, migrations, recurrence, handoff, coordinator, legacy gateway, `sra_api/main.py`, or `batch_scheduler/` unless a RED against freshly rebased source proves a genuine blocker. If that occurs, **STOP**, report evidence, and return to Design/Plan review rather than broadening the implementation PR.

Forbid all architecture expansion: no schema/migration/dependency, HTTP transport or gateway, Phase 1A SQLite/store/service, Report Job store/worker, handoff coordinator, Agent, Elasticsearch, Word renderer, FastAPI lifespan worker, distributed queue, retry engine, or cancellation engine. **JT-1 is forbidden. LangGraph is forbidden.** Do not restore a generic combined `worker` command.

Preserve existing evidence and regression contracts for PR #223 HTTP `202`/native `status`, PR #224 aware UTC SQL clock, and PR #225 `READPAST,READCOMMITTEDLOCK`. Do not rerun the operator's live Golden Path or the future three-item automatic acceptance without separate authorization.

## Required implementation completion report

Commit all implementation changes and create a review PR without merging. Report:

```text
Repository
Actual hosted baseline commit
Result commit
Branch
PR number / URL

Design v1 status
Plan v1 disposition
Plan v1.1 execution result
Prompt v1 disposition
Prompt v1.1 execution result

Exact runtime configuration implemented
Exact --once behavior implemented
Exact continuous/shutdown behavior implemented

Actual RED commands and complete relevant output
Actual GREEN commands and complete relevant output
Focused/cross-phase/full/static verification output
PR #223/#224/#225 preservation evidence

Changed-file report
Production schema/migration/dependency changes (must be none)
JT-1 work (must be none)
LangGraph work (must be none)

Deviations with source evidence
Risks
Live/deployment acceptance not executed
```

Distinguish fake/unit/store-fixture evidence from live deployment evidence. Request human/ChatGPT implementation review; do not self-award implementation or deployment PASS, and do not auto-merge.
