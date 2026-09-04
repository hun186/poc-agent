# SRA Requirement Schedule + Batch Management — Implementation Plan v1

**Design authority:** `docs/superpowers/specs/2026-09-04-sra-requirement-schedule-batch-management-design-v1.md`<br>
**Repository/baseline used to author plan:** `hun186/poc-agent`, authoritative `main`; inspected checkout `work` at `bbaec0bf168ce9dd80f9c0a38dac27ad1542dc6f` (PR #197 present)<br>
**Scope:** later implementation only; this document creates no runtime behavior<br>
**Method:** strict TDD; preserve Phase 0 security, Phase 1A idempotency, and Phase 1B immutable SQL history

## 1. Execution rules and gates

Read `AGENTS.md`, active `.codex` memory, Design v1, and this plan completely before either gate. Rebaseline actual `main`; current source wins stale path assumptions. A deviation requires source evidence, incompatibility, minimal alternative, and risks in the PR report.

Each task starts with the named failing test, implements only enough to pass, runs the passing command, and commits at its boundary. Do not combine gates. Phase 1C-A must not create outbound Agent/Report Jobs and must not claim Phase 1C complete. Phase 1C-B must not begin until 1C-A implementation review is PASS and its merged `main` SHA is recorded.

## 2. Planned production layout

```text
requirement_scheduler/{__init__,models,recurrence,migrations,store,policy,service,phase1a_bridge,worker,__main__}.py
sra_api/routers/requirement_schedules.py
batch_scheduler/{input_loader,store}.py
sra_api/main.py
```

Tests use exact new paths `tests/test_requirement_schedule_*.py`, existing `tests/requirement_test_support.py`, and existing Phase 0/1A/1B tests.

# Merge Gate Phase 1C-A — Control Plane

## A1. Recurrence domain

**Files:** create `requirement_scheduler/__init__.py`, `requirement_scheduler/models.py`, `requirement_scheduler/recurrence.py`, `tests/test_requirement_schedule_recurrence.py`.<br>
**Interfaces:** consume frozen recurrence dictionaries, IANA timezone, offset-aware `after_utc`; produce validated `RecurrenceSpec` and `next_occurrence()` UTC datetime.<br>
**Failing test:** daily/weekly/monthly-last-day/interval; invalid timezone; naive anchor/`after_utc`; DST ambiguous/nonexistent; deterministic next result.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_recurrence.py --tb=short`<br>
**Minimal implementation:** exact allowlisted grammar, `ZoneInfo`, second precision, fold/nonexistent rules, elapsed interval arithmetic; reject extras and cron text.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_recurrence.py --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler tests/test_requirement_schedule_recurrence.py && git commit -m "feat: define requirement recurrence domain"`

## A2. Coalesced due calculation

**Files:** modify `requirement_scheduler/recurrence.py`, `tests/test_requirement_schedule_recurrence.py`.<br>
**Interfaces:** consume `next_run_at`, recurrence, `now_utc`; produce `(latest_due, first_after_now)` or no claim.<br>
**Failing test:** not-due returns none; multiple missed daily/weekly/monthly/interval instants coalesce to latest; bounded deterministic `next_run_at`; naive persisted times rejected.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_recurrence.py -k 'due or coalesce or deterministic or naive' --tb=short`<br>
**Minimal implementation:** add `coalesce_latest()` with interval arithmetic and bounded calendar traversal; never return historical lists.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_recurrence.py --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/recurrence.py tests/test_requirement_schedule_recurrence.py && git commit -m "feat: coalesce requirement schedule misfires"`

## A3. SQL schema v1 and validator

**Files:** create `requirement_scheduler/migrations.py`, `tests/test_requirement_schedule_migrations.py`; modify `tests/requirement_test_support.py`.<br>
**Interfaces:** consume validated Phase 1B/1C schema names and fake/real DB-API cursor; produce bootstrap/0→1 DDL and structural checks for five Phase 1C tables, keys, ordered columns, and cross-schema FKs.<br>
**Failing test:** fresh/v0 creates version 1 with marker last; valid v1 read-only validates; unknown/malformed/incorrect FK rolls back; no DML targets Phase 1B history.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py --tb=short`<br>
**Minimal implementation:** transactional statement builders and catalog checks for `schema_version`, schedules, versions, runs, items, checkpoint; exact configured cross-schema references.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/migrations.py tests/test_requirement_schedule_migrations.py tests/requirement_test_support.py && git commit -m "feat: add requirement schedule schema v1"`

## A4. ScheduleStore foundation

**Files:** create `requirement_scheduler/store.py`, `tests/test_requirement_schedule_store.py`; modify `tests/requirement_test_support.py`.<br>
**Interfaces:** consume existing `SqlRegistry`, named connection, two schemas; produce `initialize`, create/get/list schedule, and safe persistence errors.<br>
**Failing test:** parameterized create/list/get; validated bracket identifiers; timestamps UTC; requirement set existence; rollback/close and raw ODBC redaction.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_store.py -k 'initialize or create or list or get or persistence' --tb=short`<br>
**Minimal implementation:** mirror `RequirementStore` transaction discipline without importing its importer service or mutating Phase 1B rows.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_store.py -k 'initialize or create or list or get or persistence' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/store.py tests/test_requirement_schedule_store.py tests/requirement_test_support.py && git commit -m "feat: add requirement schedule store"`

## A5. Immutable versions and approval

**Files:** modify `requirement_scheduler/models.py`, `requirement_scheduler/store.py`, `requirement_scheduler/service.py` (create), `tests/test_requirement_schedule_store.py`, `tests/test_requirement_schedule_service.py` (create).<br>
**Interfaces:** consume draft config/actor and superuser-approved operation; produce monotonic immutable version, canonical hash, active pointer, retired prior version, deterministic next run.<br>
**Failing test:** draft cannot mutate; monotonic versions; duplicate config conflict; approval activates/switches version; approval atomic rollback; non-approved schedule cannot enable.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py -k 'version or approve or active or immutable' --tb=short`<br>
**Minimal implementation:** locked `MAX(version_number)+1`, canonical hash, insert-only versions, one approval transaction with recurrence calculation.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py -k 'version or approve or active or immutable' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py && git commit -m "feat: version and approve requirement schedules"`

## A6. Due occurrence claim and concurrency

**Files:** modify `requirement_scheduler/store.py`, `requirement_scheduler/service.py`, `tests/test_requirement_schedule_store.py`, `tests/test_requirement_schedule_service.py`.<br>
**Interfaces:** consume worker UTC clock; produce locked scheduled occurrence identity, advanced `next_run_at`, and idempotent existing-run result.<br>
**Failing test:** not due/disabled not claimed; one due creates one run; repeat does not duplicate; two scripted claimers hit unique protection; coalesced scheduled time and next time exact.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py -k 'due or claim or concurrent or disabled' --tb=short`<br>
**Minimal implementation:** `UPDLOCK,HOLDLOCK`, filtered unique identity, compare/re-read on duplicate, schedule-state update in one transaction.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py -k 'due or claim or concurrent or disabled' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/store.py requirement_scheduler/service.py tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py && git commit -m "feat: claim requirement schedule occurrences"`

## A7. Snapshot-bound run materialization

**Files:** modify `requirement_scheduler/store.py`, `requirement_scheduler/service.py`, `tests/test_requirement_schedule_materialization.py` (create), `tests/requirement_test_support.py`.<br>
**Interfaces:** consume active schedule/version and Phase 1B active snapshot rows; produce immutable run/item identities, bindings, order, and counts.<br>
**Failing test:** binds exact snapshot/version; later active switch leaves old run unchanged; source order retained; no active snapshot yields `blocked_no_snapshot`; rollback leaves no partial history.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_materialization.py -k 'snapshot or materialize or rollback' --tb=short`<br>
**Minimal implementation:** cross-schema SELECT under claim transaction and explicit run/item INSERT lists; no Phase 1B writes.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_materialization.py --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/store.py requirement_scheduler/service.py tests/test_requirement_schedule_materialization.py tests/requirement_test_support.py && git commit -m "feat: materialize snapshot-bound requirement runs"`

## A8. Policy selection

**Files:** create `requirement_scheduler/policy.py`, `tests/test_requirement_schedule_policy.py`; modify `requirement_scheduler/service.py`, `tests/test_requirement_schedule_materialization.py`.<br>
**Interfaces:** consume run policy, current version, checkpoint, expiry decision; produce selected/skipped and exact reason.<br>
**Failing test:** all_active reruns unchanged; new_or_changed initial/failure retry/success skip/version-change run; changed_only initial/failure no unchanged retry/version-change run.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_policy.py tests/test_requirement_schedule_materialization.py -k 'all_active or new_or_changed or changed_only' --tb=short`<br>
**Minimal implementation:** pure exhaustive policy function; integrate selection reasons without execution imports.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_policy.py tests/test_requirement_schedule_materialization.py -k 'policy or active or changed' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/policy.py requirement_scheduler/service.py tests/test_requirement_schedule_policy.py tests/test_requirement_schedule_materialization.py && git commit -m "feat: select requirement schedule policy work"`

## A9. Checkpoint state

**Files:** modify `requirement_scheduler/store.py`, `requirement_scheduler/service.py`, `tests/test_requirement_schedule_checkpoints.py` (create).<br>
**Interfaces:** consume evaluated items; produce locked/upserted last-seen state at materialization and read-only success fields for later bridge use.<br>
**Failing test:** null→current advances seen; all policies record seen; changed_only failure remains unchanged next run; transaction rollback restores prior checkpoint; schedule isolation.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_checkpoints.py --tb=short`<br>
**Minimal implementation:** checkpoint read/conditional upsert in materialization transaction; do not write successful fields in Gate A.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_checkpoints.py --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/store.py requirement_scheduler/service.py tests/test_requirement_schedule_checkpoints.py && git commit -m "feat: persist requirement schedule checkpoints"`

## A10. Selection-time expiry

**Files:** modify `requirement_scheduler/policy.py`, `requirement_scheduler/service.py`, `tests/test_requirement_schedule_deadlines.py` (create).<br>
**Interfaces:** consume Phase 1B `expires_at` and evaluation UTC; produce selected or immutable `expired_at_selection` evidence.<br>
**Failing test:** null/future eligible; past/equal skipped; aware UTC comparison; naive source rejected safely; expiry wins over each policy.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_deadlines.py -k selection --tb=short`<br>
**Minimal implementation:** one `expires_at > check_time` helper and materialization evidence; no handoff logic in Gate A.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_deadlines.py -k selection --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/policy.py requirement_scheduler/service.py tests/test_requirement_schedule_deadlines.py && git commit -m "feat: enforce requirement selection deadlines"`

## A11. Control-plane API, RBAC, and audit

**Files:** create `sra_api/routers/requirement_schedules.py`, `tests/test_requirement_schedule_api.py`; modify `sra_api/main.py`, `requirement_scheduler/models.py`, `requirement_scheduler/service.py`.<br>
**Interfaces:** consume existing `current_user`, `require_db_operator`, `require_superuser`, `authorize_role`, `append_audit_event`; produce schedule GET/POST/PATCH, version-create/approve endpoints only.<br>
**Failing test:** unauthenticated 401; reader GET and mutation denial; db_operator create/disabled edit/version but approve/enable denial; superuser approve/enable; successful and denied audits; safe errors; no manual trigger route in Gate A.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py --tb=short`<br>
**Minimal implementation:** opt-in lifespan store/service, exact Design API presenters, existing RBAC dependencies; no background worker and no outbound call.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py --tb=short`<br>
**Commit boundary:** `git add sra_api/routers/requirement_schedules.py sra_api/main.py requirement_scheduler tests/test_requirement_schedule_api.py && git commit -m "feat: add requirement schedule control api"`

## A12. Gate A verification and memory

**Files:** modify `docs/operations/requirement-scheduling.md` (create), `.codex/memory.md`, `.codex/architecture.md`, `.codex/api_contract.md`, `.codex/decisions.md`, `.codex/backlog.md`; modify `.codex/known_issues.md` only for observed limitations.<br>
**Interfaces:** consume completed A1–A11 evidence; produce operator docs and honest `Phase 1C-A PASS / Phase 1C incomplete` status.<br>
**Failing test:** documentation/static guard initially lacks schema, no-outbound warning, RBAC, coalescing, and Gate B dependency.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py tests/test_requirement_schedule_recurrence.py tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py tests/test_requirement_schedule_materialization.py tests/test_requirement_schedule_policy.py tests/test_requirement_schedule_checkpoints.py tests/test_requirement_schedule_deadlines.py --tb=short`<br>
**Minimal implementation:** document only tested Gate A behavior and update durable memory; run prohibited-import and changed-file secret scans.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_*.py tests/test_requirement_*.py tests/test_batch_scheduler_*.py tests/test_phase0_security_acceptance.py --tb=short && python -m compileall -q requirement_scheduler sra_api tests && ! rg -n '(^| )(from|import) (agent|elasticsearch|api\.services\.report_job_worker|api\.core\.presenters)' requirement_scheduler sra_api/routers/requirement_schedules.py && git diff --check`<br>
**Commit boundary:** `git add docs/operations/requirement-scheduling.md .codex && git commit -m "docs: record phase 1c control plane gate"`

**Gate A review result required:** all commands pass, migration reviewed, no outbound Report Job/Agent creation, actual resulting SHA reported, and human/ChatGPT implementation review records PASS. Otherwise Gate B is prohibited.

# Merge Gate Phase 1C-B — Execution Bridge

## B1. Phase 1A programmatic import seam

**Files:** modify `batch_scheduler/input_loader.py`, `batch_scheduler/store.py`, `tests/test_batch_scheduler_input.py`, `tests/test_batch_scheduler_store.py`.<br>
**Interfaces:** consume `batch_id`, `source_ref`, `source_sha256`, `output_root`, sequence of existing `BatchTaskSpec`; produce same persisted batch/tasks as file import.<br>
**Failing test:** direct task import succeeds; file import uses common path; same ID/hash is idempotent; different hash conflicts; no caller SQLite writes.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_batch_scheduler_input.py tests/test_batch_scheduler_store.py -k 'programmatic or common_import or conflict' --tb=short`<br>
**Minimal implementation:** introduce normalized loaded-batch/source reference interface and factor existing `import_batch` insertion transaction; preserve public CLI behavior.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_batch_scheduler_input.py tests/test_batch_scheduler_store.py --tb=short`<br>
**Commit boundary:** `git add batch_scheduler/input_loader.py batch_scheduler/store.py tests/test_batch_scheduler_input.py tests/test_batch_scheduler_store.py && git commit -m "feat: add batch scheduler programmatic import"`

## B2. Exact task translation

**Files:** create `requirement_scheduler/phase1a_bridge.py`, `tests/test_requirement_schedule_bridge.py`; modify `requirement_scheduler/models.py`.<br>
**Interfaces:** consume exact run/item/RequirementVersion and approved model; produce existing `BatchTaskSpec`.<br>
**Failing test:** exact task/prompt/safe filename/session/model/none schedule/ID-only metadata; arbitrary options/unknown metadata/secrets absent; duplicate unsafe IDs rejected.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_bridge.py -k 'task_spec or metadata or options or filename' --tb=short`<br>
**Minimal implementation:** allowlisted constructor and deterministic session; reuse Phase 1A filename confinement rather than rendering.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_bridge.py -k 'task_spec or metadata or options or filename' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/phase1a_bridge.py requirement_scheduler/models.py tests/test_requirement_schedule_bridge.py && git commit -m "feat: translate requirement run tasks"`

## B3. Deterministic batch fingerprint

**Files:** modify `requirement_scheduler/phase1a_bridge.py`, `tests/test_requirement_schedule_bridge.py`.<br>
**Interfaces:** consume ordered translated tasks/run identities/root identity; produce `reqrun-{batch_run_id}`, source reference, canonical SHA-256.<br>
**Failing test:** stable across restart; task order/content/model changes fingerprint; same import returns existing; conflicting fingerprint fails closed.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_bridge.py -k 'fingerprint or batch_identity or conflict' --tb=short`<br>
**Minimal implementation:** versioned canonical JSON and SHA-256, then call only `BatchSchedulerStore.import_tasks`.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_bridge.py -k 'fingerprint or batch_identity or conflict' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/phase1a_bridge.py tests/test_requirement_schedule_bridge.py && git commit -m "feat: fingerprint requirement batch handoff"`

## B4. Pre-handoff expiry recheck

**Files:** modify `requirement_scheduler/store.py`, `requirement_scheduler/phase1a_bridge.py`, `tests/test_requirement_schedule_deadlines.py`.<br>
**Interfaces:** consume selected items/current UTC before first import; produce eligible task set or terminal expiry evidence.<br>
**Failing test:** expires after selection/before handoff skipped; no task/Report Job; partial expiry imports remainder; replay after handoff does not re-expire dispatched task.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_deadlines.py -k 'handoff or partial or dispatched' --tb=short`<br>
**Minimal implementation:** locked compare-and-set from `handoff_pending`; exclude expired items before invoking seam.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_deadlines.py --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/store.py requirement_scheduler/phase1a_bridge.py tests/test_requirement_schedule_deadlines.py && git commit -m "feat: recheck deadlines before batch handoff"`

## B5. Worker claim and handoff loop

**Files:** create `requirement_scheduler/worker.py`, `requirement_scheduler/__main__.py`, `tests/test_requirement_schedule_worker.py`; modify `requirement_scheduler/service.py`.<br>
**Interfaces:** consume ScheduleStore, bridge, Phase 1A service, clock; produce bounded `run_once()` recovery/claim/handoff cycle and CLI continuous/once modes.<br>
**Failing test:** `--once`; continuous sleep; recovery precedes new claims; disabled/no-due harmless; credential/config fatal nonzero; no FastAPI thread.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'once or lifecycle or order or cli' --tb=short`<br>
**Minimal implementation:** dependency-injected worker and argparse entrypoint; mount nothing in FastAPI lifespan.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_worker.py -k 'once or lifecycle or order or cli' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/worker.py requirement_scheduler/__main__.py requirement_scheduler/service.py tests/test_requirement_schedule_worker.py && git commit -m "feat: run requirement scheduler worker"`

## B6. Phase 1A resume and import crash recovery

**Files:** modify `requirement_scheduler/phase1a_bridge.py`, `requirement_scheduler/worker.py`, `requirement_scheduler/store.py`, `tests/test_requirement_schedule_restart.py` (create).<br>
**Interfaces:** consume nonterminal SQL runs and existing Phase 1A batches/tasks; produce idempotent SQL handoff markers.<br>
**Failing test:** crash after SQL run; crash after Phase 1A import before SQL marker; restart uses same batch/fingerprint; mismatch blocks safely.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_restart.py -k 'sql_run or phase1a_import or marker or fingerprint' --tb=short`<br>
**Minimal implementation:** deterministic reconstruction, seam reimport, conditional SQL marker update; no direct SQLite query from Phase 1C.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_restart.py -k 'sql_run or phase1a_import or marker or fingerprint' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler tests/test_requirement_schedule_restart.py && git commit -m "feat: recover requirement batch handoff"`

## B7. Phase 1A submitting replay

**Files:** modify `batch_scheduler/store.py`, `batch_scheduler/service.py` only if regression exposes a gap; modify `tests/test_batch_scheduler_service.py`, `tests/test_requirement_schedule_restart.py`.<br>
**Interfaces:** consume existing Phase 1A `submitting` state/idempotency key; produce replay of one logical HTTP submit and persisted job identity.<br>
**Failing test:** response lost after remote create; restart resubmits same idempotency key; no second logical job; conflict terminal and safe.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_batch_scheduler_service.py tests/test_requirement_schedule_restart.py -k 'submitting or response_lost or idempotency' --tb=short`<br>
**Minimal implementation:** preserve/reuse current submitting path; make only the smallest Phase 1A correction proven necessary.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_batch_scheduler_service.py tests/test_requirement_schedule_restart.py -k 'submitting or response_lost or idempotency' --tb=short`<br>
**Commit boundary:** `git add batch_scheduler/store.py batch_scheduler/service.py tests/test_batch_scheduler_service.py tests/test_requirement_schedule_restart.py && git commit -m "test: prove requirement submit replay safety"` (omit unchanged production files).

## B8. Remote state synchronization

**Files:** modify `requirement_scheduler/phase1a_bridge.py`, `requirement_scheduler/store.py`, `requirement_scheduler/worker.py`, `tests/test_requirement_schedule_reconciliation.py` (create).<br>
**Interfaces:** consume Phase 1A public batch/task status; produce monotonic run-item remote/execution state and safe failures.<br>
**Failing test:** pending/running/failed/interrupted/completed mapping; remote completion before SQL reconciliation; repeated/out-of-order reconciliation cannot regress.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_reconciliation.py -k 'remote or monotonic or completed' --tb=short`<br>
**Minimal implementation:** public Phase 1A status adapter and locked conditional SQL transitions; no remote HTTP call outside Phase 1A.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_reconciliation.py -k 'remote or monotonic or completed' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler tests/test_requirement_schedule_reconciliation.py && git commit -m "feat: reconcile requirement task states"`

## B9. Artifact and deadline reconciliation

**Files:** modify `requirement_scheduler/phase1a_bridge.py`, `requirement_scheduler/store.py`, `tests/test_requirement_schedule_reconciliation.py`, `tests/test_requirement_schedule_deadlines.py`.<br>
**Interfaces:** consume Phase 1A downloaded output and current time; produce root-relative artifact identity and elapsed-deadline evidence.<br>
**Failing test:** DOCX exists before SQL marker; relative path stored; absolute/outside/wrong-task rejected; already-dispatched completion after expiry continues and records elapsed flag.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_reconciliation.py tests/test_requirement_schedule_deadlines.py -k 'artifact or elapsed or execution' --tb=short`<br>
**Minimal implementation:** validate resolved path under configured root and expected Phase 1A output identity; conditional evidence update.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_reconciliation.py tests/test_requirement_schedule_deadlines.py -k 'artifact or elapsed or execution' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler tests/test_requirement_schedule_reconciliation.py tests/test_requirement_schedule_deadlines.py && git commit -m "feat: reconcile requirement artifacts and deadlines"`

## B10. Successful checkpoints

**Files:** modify `requirement_scheduler/store.py`, `requirement_scheduler/worker.py`, `tests/test_requirement_schedule_checkpoints.py`, `tests/test_requirement_schedule_reconciliation.py`.<br>
**Interfaces:** consume exact succeeded item; produce idempotent last-successful version/item/time without older-run regression.<br>
**Failing test:** only success advances; failure does not; replay stable; newer checkpoint not overwritten by older completion; new_or_changed retries then skips after success.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_checkpoints.py tests/test_requirement_schedule_reconciliation.py -k 'successful or older or retry' --tb=short`<br>
**Minimal implementation:** locked conditional checkpoint update in reconciliation transaction.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_checkpoints.py tests/test_requirement_schedule_reconciliation.py -k 'successful or older or retry' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/store.py requirement_scheduler/worker.py tests/test_requirement_schedule_checkpoints.py tests/test_requirement_schedule_reconciliation.py && git commit -m "feat: reconcile successful requirement checkpoints"`

## B11. Batch Run finalization

**Files:** modify `requirement_scheduler/store.py`, `requirement_scheduler/worker.py`, `tests/test_requirement_schedule_reconciliation.py`, `tests/test_requirement_schedule_restart.py`.<br>
**Interfaces:** consume terminal item states/counts; produce one terminal run state and completion timestamps.<br>
**Failing test:** all success completed; skips plus success completed; any terminal execution failure completed_with_errors; fatal bridge conflict failed; partial restart remains running; repeated finalize stable.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_reconciliation.py tests/test_requirement_schedule_restart.py -k 'final or partial or completed_with_errors' --tb=short`<br>
**Minimal implementation:** derive counts from persisted items under lock and compare-and-set terminal state.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_reconciliation.py tests/test_requirement_schedule_restart.py -k 'final or partial or completed_with_errors' --tb=short`<br>
**Commit boundary:** `git add requirement_scheduler/store.py requirement_scheduler/worker.py tests/test_requirement_schedule_reconciliation.py tests/test_requirement_schedule_restart.py && git commit -m "feat: finalize requirement batch runs"`

## B12. Manual trigger API

**Files:** modify `sra_api/routers/requirement_schedules.py`, `requirement_scheduler/service.py`, `requirement_scheduler/store.py`, `tests/test_requirement_schedule_api.py`.<br>
**Interfaces:** consume superuser plus request ID; produce immediate snapshot-bound manual run without recurrence mutation.<br>
**Failing test:** reader/db_operator denial and audited; superuser success; same request ID idempotent; conflicting reuse 409; active version/snapshot server-selected; `next_run_at` unchanged.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py -k 'manual or trigger or request_id' --tb=short`<br>
**Minimal implementation:** add Design POST route and transactional manual materialization through common service.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py -k 'manual or trigger or request_id' --tb=short`<br>
**Commit boundary:** `git add sra_api/routers/requirement_schedules.py requirement_scheduler/service.py requirement_scheduler/store.py tests/test_requirement_schedule_api.py && git commit -m "feat: trigger manual requirement runs"`

## B13. Run/result APIs and Word history

**Files:** modify `sra_api/routers/requirement_schedules.py`, `requirement_scheduler/store.py`, `tests/test_requirement_schedule_api.py`, `tests/test_requirement_schedule_word.py` (create).<br>
**Interfaces:** consume authenticated user/run/item; produce safe paginated histories and authenticated canonical DOCX stream.<br>
**Failing test:** reader safe GET; unauthenticated 401; correct completed artifact; incomplete 409; wrong run/item 404; traversal/absolute/symlink escape rejected; MIME/no-store; absolute path absent everywhere.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py tests/test_requirement_schedule_word.py --tb=short`<br>
**Minimal implementation:** add run list/detail/items and confined Word endpoint referencing, never copying/rendering, Phase 1A artifact.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py tests/test_requirement_schedule_word.py --tb=short`<br>
**Commit boundary:** `git add sra_api/routers/requirement_schedules.py requirement_scheduler/store.py tests/test_requirement_schedule_api.py tests/test_requirement_schedule_word.py && git commit -m "feat: expose requirement batch history"`

## B14. Crash/security/regression gate

**Files:** modify tests only: `tests/test_requirement_schedule_restart.py`, `tests/test_requirement_schedule_security.py` (create), and defects' minimal owning files if a test proves one.<br>
**Interfaces:** consume full 1C worker/bridge; produce evidence for every crash and import boundary.<br>
**Failing test:** crash after SQL creation/import; submitting replay; remote completion before SQL; artifact before SQL; partial restart; no duplicate occurrence/batch/job; prohibited production imports.<br>
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_restart.py tests/test_requirement_schedule_security.py --tb=short`<br>
**Minimal implementation:** fill only uncovered recovery assertions/fixes; AST/import scan forbids Agent, Elasticsearch execution, ReportJobWorker, and Word renderer.<br>
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_*.py tests/test_batch_scheduler_*.py tests/test_requirement_*.py tests/test_phase0_security_acceptance.py --tb=short && ! rg -n '(^| )(from|import) (agent|elasticsearch|api\.services\.report_job_worker|api\.core\.presenters)' requirement_scheduler`<br>
**Commit boundary:** `git add tests/test_requirement_schedule_restart.py tests/test_requirement_schedule_security.py requirement_scheduler batch_scheduler && git commit -m "test: cover requirement scheduler restart boundaries"` (stage only files actually changed).

## B15. Full gate, operations, memory, and deployment procedure

**Files:** modify `docs/operations/requirement-scheduling.md`, `.codex/memory.md`, `.codex/architecture.md`, `.codex/api_contract.md`, `.codex/decisions.md`, `.codex/backlog.md`; `.codex/known_issues.md` only for observed limitations.<br>
**Interfaces:** consume all verified implementation; produce honest repository result and explicit authorized deployment procedure/status.<br>
**Failing test:** operational review initially lacks one-worker rule, recovery, Word root, scopes, rollback, or acceptance evidence.<br>
**RED command:** `rg -n 'coalesce_latest|python -m requirement_scheduler worker|SRA_BATCH_OUTPUT_ROOT|NOT EXECUTED|Phase 1C-B' docs/operations/requirement-scheduling.md .codex`<br>
**Minimal implementation:** update docs/memory with actual results and SHA; run deployment steps only with explicit authorization, otherwise retain NOT EXECUTED.<br>
**GREEN command:** `PYTHONPATH=. pytest tests -q --tb=short && python -m compileall -q requirement_scheduler batch_scheduler data_ingestion/requirements sra_api api tests && git diff --check && ! rg -n '(^| )(from|import) (agent|elasticsearch|api\.services\.report_job_worker|api\.core\.presenters)' requirement_scheduler && git status --short`<br>
**Commit boundary:** `git add docs/operations/requirement-scheduling.md .codex && git commit -m "docs: complete phase 1c execution bridge"`

## 3. Verification matrix traceability

| Required behavior | Primary tests/tasks |
|---|---|
| daily, weekly, monthly, interval, invalid timezone, naive rejection, deterministic next | `test_requirement_schedule_recurrence.py`, A1 |
| `coalesce_latest`, no backfill | recurrence tests, A2 |
| immutable/monotonic draft, superuser approval, switch, db_operator denial | store/service/API tests, A5/A11 |
| not due, one occurrence, repeat/concurrent protection, disabled | store/service tests, A6 |
| exact snapshot, later switch isolation, no active snapshot | materialization tests, A7 |
| all policy initial/retry/success/change behaviors | policy/checkpoint tests, A8/A9/B10 |
| expired selection/pre-handoff, dispatched continues, elapsed evidence | deadline tests, A10/B4/B9 |
| exact task mapping, no options, deterministic identities/fingerprint/conflict | bridge tests, B2/B3 |
| all six crash windows and partial restart | restart/reconciliation tests, B6–B9/B11/B14 |
| 401; reader GET/denials; operator allowed/denied; superuser; denial audit | API tests, A11/B12/B13 |
| correct/incomplete/wrong/traversal/no absolute Word path | Word/API tests, B13 |
| no Agent/ES/ReportJobWorker/renderer import | security test/static scan, A12/B14/B15 |

## 4. Real deployment acceptance procedure

Only an explicitly authorized operator may run this. Record actual merged SHAs and safe environment identity. Initialize/validate configured Phase 1C schema against Phase 1B; verify fresh or v0→1 and malformed fail-closed behavior; create/approve/enable schedules; race two due checks and prove one run; inspect exact snapshot/item policy and both expiry checks; execute a real Phase 1A/Report Job/Agent/DOCX chain; stop/restart at each documented crash window; verify no duplicate identities; download Word through authenticated history and test traversal; inspect audits and RBAC denials. Preserve Phase 1B live acceptance as its independent status.

If credentials/network/SQL are unavailable, report Phase 1C live deployment acceptance **NOT EXECUTED**, provide repository tests as substitute evidence only, and update `.codex/known_issues.md`.

## 5. Completion reports

Each gate reports repository, branch, baseline SHA, resulting SHA, PR status, changed files, behavior changes, test commands/counts, deviations with evidence, risks, live acceptance status, and clean working tree. Gate A status is only `Phase 1C-A control plane repository gate PASS; outbound execution absent; Phase 1C incomplete`. Gate B may declare Phase 1C repository completion only after its full gate passes; it may not claim deployment acceptance without the real procedure.
