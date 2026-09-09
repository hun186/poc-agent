# SRA Requirement Schedule Runtime Automation — Implementation Plan v1.1

**Goal:** Add the missing, externally supervised Requirement schedule due-claim process without changing the existing scheduling or handoff authorities.

**Architecture:** `schedule-worker` is a schedule-only OS process. It validates configuration and the existing `ScheduleStore`, then delegates one due occurrence per bounded iteration to `ScheduleStore.claim_due()`. It communicates with the unchanged `handoff-worker` only through SQL-authoritative Batch Run and Run Item state. It performs no HTTP, execution, rendering, or FastAPI work.

**Tech Stack:** Python 3, `argparse`, `threading.Event`, timezone-aware `datetime`, the existing SQL Server `ScheduleStore`, and pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-sra-requirement-schedule-runtime-automation-design-v1.md` (authoritative Design v1).

**Baseline:** `a702dcf528cd6f77f26aa89aec665dcc8145acda` was the clean local baseline when this correction was written. No Git remote was configured, so hosted `main` could not be queried. Future execution must fetch and bind the actual hosted `main`, using a newer SHA when present.

**Supersedes:** Implementation Plan v1 only. Plan v1 is **NOT AUTHORIZED**. Design v1 is unchanged and remains authoritative.

**Global Constraints:** Execute only after Plan v1.1 and Prompt v1.1 receive human/ChatGPT review **PASS**. Use strict RED → minimal GREEN, retain actual output, create an implementation PR, and do not auto-merge. Add no schema, migration, dependency, HTTP/client/gateway, FastAPI worker, generic combined worker, JT-1, or LangGraph work. Do not alter recurrence, coalescing, locks, scheduled uniqueness, snapshot materialization, policy, checkpoints, audit outbox, or `next_run_at` calculations. Never run the live Golden Path without separate operator authorization.

## Frozen implementation contract

### Configuration and identity

The only new runtime setting is:

| Contract | Exact value |
|---|---|
| Environment variable | `REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL` |
| Default | `2.0` seconds |
| Type | finite `float` |
| Inclusive valid range | `0.1 <= value <= 300.0` |

Parsing rejects malformed values, `NaN`, positive or negative infinity, zero, negatives, values below `0.1`, and values above `300.0`. Rejection is a startup configuration failure: do not initialize the store, do not call `ScheduleStore.claim_due()`, emit only a safe category, and return a nonzero process exit. Never reuse or overload `REQUIREMENT_HANDOFF_POLL_INTERVAL`; the processes have separate responsibilities.

The audit actor is the server-owned constant `requirement-schedule-worker`. It is not configurable by environment or CLI. Every claim is exactly:

```python
ScheduleStore.claim_due(
    now_utc=<aware UTC clock result>,
    actor="requirement-schedule-worker",
)
```

This is a system-process identity rather than an authenticated human actor, provides stable audit attribution, adds no configuration surface, and fits the existing actor column's 128-character bound.

### Exact conceptual interfaces

Create `requirement_scheduler/schedule_worker.py` with this public dependency-injected shape (type refinements may name existing protocols, but must not add a second domain result):

```python
SCHEDULE_WORKER_ACTOR = "requirement-schedule-worker"

class RequirementScheduleWorker:
    def run_once(self) -> object | None:
        ...

    def run(self, stop_event) -> None:
        ...
```

Constructor dependencies are the already-constructed `ScheduleStore`, validated finite poll interval, and a zero-argument clock. The production clock default is exactly `datetime.now(timezone.utc)`. `run_once()` obtains one clock value, rejects a naive or non-UTC-aware value before claiming, makes exactly one `claim_due()` call with the stable actor, and returns the store result unchanged or `None`. The worker has no HTTP/client/gateway dependency.

The environment factory loads the existing `SqlRegistry` from `REQUIREMENT_SQL_REGISTRY_FILE` (default `config/requirements/sql_registry.json`), creates `ScheduleStore` with `REQUIREMENT_CONTROL_DB_CONNECTION` (default `requirement_control`), `REQUIREMENT_SCHEDULE_DB_SCHEMA` (default `sra_schedule`), and `REQUIREMENT_DB_SCHEMA` (default `sra_requirement`), and calls `initialize()` exactly once before any claim.

### Exact one-shot semantics

`python -m requirement_scheduler schedule-worker --once` performs exactly:

```text
load config
→ construct ScheduleStore
→ initialize/validate store
→ obtain one aware UTC timestamp
→ call ScheduleStore.claim_due(...) exactly once
→ exit
```

There is no loop, retry, sleep, wait, or second claim even if another schedule is already due. No due schedule exits `0`. One successfully claimed/materialized occurrence exits `0`. A safe `persistence_error` from `claim_due()` emits only that category, performs no retry, and exits nonzero. Startup/config/schema failure exits nonzero and must make zero claims. An unexpected/invariant exception fails closed and exits nonzero. This is a deterministic test/operator diagnostic surface, not a drain command.

### Exact continuous semantics

`python -m requirement_scheduler schedule-worker` performs startup validation, then:

```text
while not stop_event.is_set():
    now = aware UTC
    call claim_due() once

    successfully claimed occurrence:
        check stop state
        continue to the next bounded iteration

    no due occurrence:
        stop_event.wait(poll_interval)

    safe persistence_error:
        emit only the safe category
        stop_event.wait(poll_interval)

    unexpected/invariant failure:
        fail closed and exit nonzero
```

Each iteration processes at most one occurrence and rechecks stop state. A successful claim may proceed immediately to the next iteration. There is no unbounded inner-drain function; the SQL store remains responsible for selecting only one due occurrence.

For `schedule-worker`, `SIGTERM` and `KeyboardInterrupt` both set the worker stop event. Every wait is `stop_event.wait(poll_interval)`. The worker completes an in-flight `claim_due()` database call and then stops; it never force-cancels a SQL transaction. Existing `handoff-worker` signal behavior is outside this completion delta and must remain unchanged unless a directly affected regression proves a strict necessity; otherwise record any improvement as future operations work.

## Task 0 — Rebaseline and enforce the stop gate

**Files:** No changes.

**Interfaces:** Hosted Git `main`; current `ScheduleStore.claim_due(*, now_utc, actor)`; current CLI parser.

- [ ] Run `pwd`, `git rev-parse --show-toplevel`, `git remote -v`, `git fetch --all --prune`, `git branch --show-current`, `git rev-parse HEAD`, `git status --short`, and `git log -1 --oneline`; record repository, branch, baseline SHA, and status.
- [ ] Read `AGENTS.md`, all active `.codex/*.md`, Design v1, Plan v1.1, Prompt v1.1, current Requirement Scheduler source/tests, and operations documentation completely.
- [ ] Run `rg -n "claim_due|handoff-worker|schedule-worker" requirement_scheduler tests docs/operations` and inspect call sites rather than relying on text matches.
- [ ] Confirm `claim_due()` still claims at most one occurrence and no production automatic caller exists.
- [ ] STOP, report evidence, and return to Design/Plan review if the premise or a required interface differs materially. Do not modify files in that case.

## Task 1 — Configuration and worker one-shot RED/GREEN

**Files:** `tests/test_requirement_schedule_worker.py`, `requirement_scheduler/schedule_worker.py`.

**Interfaces:** `SCHEDULE_WORKER_ACTOR`; `RequirementScheduleWorker.run_once() -> object | None`; injected zero-argument clock; exact poll parser for `REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL`.

- [ ] Write exact failing tests named `test_poll_interval_defaults_to_2_seconds`, `test_poll_interval_accepts_inclusive_bounds`, and parametrized `test_poll_interval_rejects_invalid_values` covering `0`, negative, `0.099`, `300.001`, malformed text, `NaN`, `inf`, and `-inf`.
- [ ] Write exact failing tests named `test_run_once_no_due_claims_exactly_once`, `test_run_once_claimed_returns_existing_result_exactly_once`, `test_run_once_persistence_error_is_fatal_without_wait`, `test_run_once_rejects_naive_clock_before_claim`, and `test_run_once_uses_aware_utc_and_stable_actor`.
- [ ] Run exact RED command `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'poll_interval or run_once' --tb=short`.
- [ ] State expected RED reason: import/collection fails because `requirement_scheduler.schedule_worker` and its exact configuration/worker interfaces do not exist.
- [ ] Implement minimal code: finite inclusive interval parsing, stable actor constant, injected aware-UTC clock validation, and exactly one store delegation in `run_once()`; add no alternate result model.
- [ ] Run exact GREEN command `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'poll_interval or run_once' --tb=short`.
- [ ] State expected GREEN result: every selected test passes; fake store records exactly one claim or zero for a naive clock, actor is exact, and persistence failure records no wait.
- [ ] Commit exact files with `git add requirement_scheduler/schedule_worker.py tests/test_requirement_schedule_worker.py && git commit -m "Add schedule worker one-shot contract"`.

## Task 2 — Continuous loop, safe failure, and shutdown RED/GREEN

**Files:** `tests/test_requirement_schedule_worker.py`, `requirement_scheduler/schedule_worker.py`.

**Interfaces:** `RequirementScheduleWorker.run(stop_event) -> None`; injected event exposing `is_set()` and `wait(seconds)`; safe category `persistence_error` only.

- [ ] Write exact failing test `test_run_no_due_claims_once_then_waits_interruptibly` asserting one claim followed by `stop_event.wait(2.0)`.
- [ ] Write exact failing test `test_run_one_due_then_no_due_reaches_next_bounded_iteration` asserting the successful first claim immediately reaches a second claim and the no-due result waits.
- [ ] Write exact failing test `test_run_multiple_due_claims_one_per_iteration_until_stopped` using a fake store queue and asserting each claim is a separate top-level iteration with a stop-state check between calls.
- [ ] Write exact failing test `test_run_persistence_error_emits_safe_category_waits_then_retries_later` asserting no raw exception text, one wait, and retry only after that wait.
- [ ] Write exact failing test `test_run_unexpected_invariant_error_is_fatal` asserting the exception is not converted into successful completion.
- [ ] Write exact failing tests `test_sigterm_sets_schedule_worker_stop_event` and `test_keyboard_interrupt_sets_schedule_worker_stop_event` at the CLI seam, asserting an in-flight fake claim returns before termination and no force-cancel hook exists.
- [ ] Run exact RED command `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'run_ or sigterm or keyboard' --tb=short`.
- [ ] State expected RED reason: `run()` and schedule-worker signal wiring do not yet satisfy the bounded iteration, safe retry, and stop-event assertions.
- [ ] Implement minimal code with one `run_once()` call per outer iteration, immediate bounded continuation only after a claim, and `stop_event.wait(poll_interval)` only for no-due or safe persistence failure. Set the stop event for SIGTERM/KeyboardInterrupt and finish the current claim.
- [ ] Run exact GREEN command `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'run_ or sigterm or keyboard' --tb=short`.
- [ ] State expected GREEN result: all selected tests pass with one claim per iteration, interruptible waits, later-iteration persistence retry, fatal invariant behavior, and graceful stop after the current call.
- [ ] Commit exact files with `git add requirement_scheduler/schedule_worker.py tests/test_requirement_schedule_worker.py && git commit -m "Add bounded schedule worker loop"`.

## Task 3 — CLI startup and compatibility RED/GREEN

**Files:** `tests/test_requirement_schedule_worker.py`, `requirement_scheduler/cli.py`.

**Interfaces:** `schedule-worker [--once]`; existing `handoff-worker`; schedule factory initializes the store once before invoking worker mode; no CLI actor option.

- [ ] Write exact failing tests `test_cli_accepts_schedule_worker`, `test_cli_accepts_schedule_worker_once`, `test_cli_keeps_handoff_worker`, and `test_cli_rejects_generic_worker`.
- [ ] Write exact failing tests `test_cli_once_no_due_exits_zero_after_one_claim`, `test_cli_once_claimed_exits_zero_after_one_claim`, `test_cli_once_persistence_error_exits_nonzero_without_wait`, and `test_cli_startup_failure_exits_nonzero_with_zero_claims`.
- [ ] Write exact failing test `test_invalid_schedule_config_prevents_store_construction_and_claim` for every rejected interval category and assert configuration validation precedes registry/store construction.
- [ ] Write exact failing test `test_cli_and_environment_cannot_override_schedule_actor` asserting parser help has no actor flag and an actor-like environment variable is ignored.
- [ ] Run exact RED command `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'cli or startup or config_prevents' --tb=short`.
- [ ] State expected RED reason: the parser accepts only `handoff-worker`, and no schedule-worker factory/startup/exit mapping exists.
- [ ] Implement minimal CLI parsing, factory initialization, one-shot exit mapping, continuous invocation, and safe error-category emission while preserving existing `handoff-worker` construction and behavior.
- [ ] Run exact GREEN command `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'cli or startup or config_prevents' --tb=short`.
- [ ] State expected GREEN result: exact command compatibility and exit assertions pass; invalid startup makes zero claims; actor has no override surface.
- [ ] Commit exact files with `git add requirement_scheduler/cli.py tests/test_requirement_schedule_worker.py && git commit -m "Expose schedule worker CLI"`.

## Task 4 — Store delegation and process-boundary RED/GREEN

**Files:** `tests/test_requirement_schedule_worker.py` only unless the RED evidence exposes a genuine blocker.

**Interfaces:** Existing `ScheduleStore.initialize()` and `ScheduleStore.claim_due()`; Python AST/import graph rooted at `requirement_scheduler.schedule_worker`.

- [ ] Write exact focused integration tests `test_existing_store_materializes_one_scheduled_occurrence_per_claim`, `test_existing_store_eventually_processes_multiple_due_occurrences`, and `test_existing_store_owns_advancement_disabled_filtering_and_occurrence_uniqueness`, reusing existing store fakes/fixtures rather than restating recurrence algorithms or SQL locking implementation.
- [ ] Write exact AST/import test `test_schedule_worker_import_graph_excludes_execution_dependencies` that resolves imports and rejects `requests`, `httpx`, `urllib` HTTP transport, `batch_scheduler.store`, `BatchSchedulerService`, `ReportJobStore`, `ReportJobWorker`, `LegacyReportJobGateway`, `RequirementHandoffCoordinator`, `agent`, Elasticsearch, and Word renderer dependencies without naive substring matching.
- [ ] Run exact RED command `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'existing_store or import_graph' --tb=short`.
- [ ] State expected RED reason: new boundary assertions initially expose any accidental prohibited import or a missing delegation proof; if they instead pass immediately, retain them as regression evidence and do not manufacture a production change.
- [ ] Implement minimal code only if RED identifies a defect in `schedule_worker.py`; do not change store, recurrence, handoff, coordinator, gateway, migrations, API, or Batch Scheduler code.
- [ ] Run exact GREEN command `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'existing_store or import_graph' --tb=short`.
- [ ] State expected GREEN result: delegation tests pass through existing store behavior and AST/import assertions prove the process boundary.
- [ ] Commit exact files with `git add tests/test_requirement_schedule_worker.py requirement_scheduler/schedule_worker.py && git commit -m "Prove schedule worker boundaries"`; omit the production path from `git add` when unchanged.

If any RED against freshly rebased source requires changing `requirement_scheduler/store.py`, `migrations.py`, `recurrence.py`, `handoff.py`, `coordinator.py`, `legacy_report_job_gateway.py`, `sra_api/main.py`, or `batch_scheduler/`, **STOP**, report the failing output and source evidence, and return to Design/Plan review. Never silently broaden scope.

## Task 5 — Operations documentation RED/GREEN

**Files:** `docs/operations/requirement-scheduling.md`.

**Interfaces:** Separately supervised `schedule-worker` and `handoff-worker`; schedule poll environment contract; operator-only acceptance procedure.

- [ ] Write an exact failing static documentation check in the shell that requires both commands, `--once`, the exact poll variable/default/range, stable actor, SIGTERM/current-claim behavior, safe failure categories, and the no-live-self-run warning.
- [ ] Run exact RED command `python - <<'PY'
from pathlib import Path
p = Path('docs/operations/requirement-scheduling.md').read_text()
required = ['schedule-worker', 'handoff-worker', '--once', 'REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL', '2.0', '0.1', '300.0', 'requirement-schedule-worker', 'SIGTERM', 'persistence_error', 'separate authorization']
assert all(value in p for value in required)
PY`.
- [ ] State expected RED reason: current operations documentation does not contain the complete frozen runtime and acceptance contract.
- [ ] Implement minimal documentation for separate systemd/container supervision, restart/backoff, safe observability, startup failure, no FastAPI/HTTP/execution coupling, and the live acceptance sequence below, without credentials.
- [ ] Run the exact GREEN command from the RED step unchanged.
- [ ] State expected GREEN result: the static documentation assertion exits `0` and manual inspection confirms the statements are operationally coherent.
- [ ] Commit exact files with `git add docs/operations/requirement-scheduling.md && git commit -m "Document schedule worker operations"`.

The documented future operator acceptance is:

```text
import >= 3 active Requirements
→ approved/enabled schedule
→ wait for next_run_at
→ schedule-worker automatically materializes ONE scheduled Batch Run
→ 3 selected Run Items
→ existing handoff-worker automatically submits them
→ 3 Report Jobs
→ 3 DOCX
→ automatic reconciliation
→ Batch completed
→ success_count = 3
→ failure_count = 0
```

It permits no manual trigger and no manual coordinator `run_once()`. Codex must not execute it without separate authorization. It is deployment acceptance, not repository unit-test evidence.

## Task 6 — Cross-phase verification and memory RED/GREEN

**Files:** `.codex/memory.md`; `.codex/architecture.md`, `.codex/known_issues.md`, `.codex/decisions.md`, or `.codex/backlog.md` only when actual implementation evidence requires an append.

**Interfaces:** Existing test suites and CLI; persistent-memory append rules.

- [ ] Write exact failing memory assertion requiring an implementation record with actual baseline, RED/GREEN results, changed paths, and explicit unexecuted live acceptance.
- [ ] Run exact RED command `rg -n 'Requirement schedule-worker implementation|RED evidence|GREEN evidence|live acceptance.*NOT EXECUTED' .codex/memory.md`.
- [ ] State expected RED reason: persistent memory has no implementation record before implementation is complete.
- [ ] Implement minimal memory appends using only actual results; do not claim deployment acceptance.
- [ ] Run exact GREEN command `rg -n 'Requirement schedule-worker implementation|RED evidence|GREEN evidence|live acceptance.*NOT EXECUTED' .codex/memory.md`.
- [ ] State expected GREEN result: scoped output identifies the new honest implementation record.
- [ ] Run these exact repository gates:

```bash
PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py --tb=short

PYTHONPATH=. pytest -q \
  tests/test_requirement_schedule_*.py \
  tests/test_requirement_handoff_*.py \
  --tb=short

PYTHONPATH=. pytest -q \
  tests/test_requirement_*.py \
  tests/test_batch_scheduler_*.py \
  tests/test_phase0_security_acceptance.py \
  --tb=short

PYTHONPATH=. pytest -q tests --tb=short

python -m compileall -q \
  requirement_scheduler \
  data_ingestion/requirements \
  batch_scheduler \
  sra_api \
  api \
  tests

python -m requirement_scheduler --help
python -m requirement_scheduler schedule-worker --help

git diff --check
```

- [ ] Confirm existing regressions preserve PR #223 Report Job HTTP `202`/native `status`, PR #224 aware UTC SQL clock, and PR #225 `READPAST,READCOMMITTEDLOCK` queue behavior.
- [ ] Confirm no schema, migration, dependency, lockfile, or prohibited-boundary file changed.
- [ ] Commit exact files with `git add .codex/memory.md .codex/architecture.md .codex/known_issues.md .codex/decisions.md .codex/backlog.md && git commit -m "Record schedule worker verification"`, staging only memory files actually changed.

## Task 7 — Review handoff and implementation PR

**Files:** No additional implementation files.

**Interfaces:** Git commit and pull-request review workflow.

- [ ] Inspect `git diff <actual-hosted-main>...HEAD`, `git diff --check`, and `git status --short`; reconcile every changed path to Tasks 1–6.
- [ ] Report actual RED and GREEN output, all verification output, changed files, source-backed deviations, risks, and live acceptance not executed.
- [ ] Report production schema/migration/dependency changes as none; JT-1 work as none; LangGraph work as none.
- [ ] Open a dedicated implementation PR with exact baseline/result SHA and no auto-merge.
- [ ] Request human/ChatGPT implementation review and do not self-award repository or deployment PASS.

## Traceability

| Frozen requirement | Proof task |
|---|---|
| Exact environment/default/finite range and startup failure | Tasks 1, 3 |
| Stable non-overridable actor | Tasks 1, 3 |
| Exactly one one-shot claim and exit taxonomy | Tasks 1, 3 |
| One claim per continuous iteration and bounded retry | Task 2 |
| Aware UTC and naive rejection before claim | Task 1 |
| SIGTERM/KeyboardInterrupt finish current claim | Task 2 |
| Existing store remains lifecycle authority | Task 4 |
| No execution/HTTP/Phase 1A coupling | Task 4 |
| Existing handoff CLI compatibility | Task 3 |
| Exact cross-phase gates and PR #223/#224/#225 preservation | Task 6 |
| Operator-only three-item automatic acceptance | Task 5 |

