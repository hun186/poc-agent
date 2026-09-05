# SRA Requirement Schedule + Batch Management — Implementation Plan v5

**Design:** `docs/superpowers/specs/2026-09-05-sra-requirement-schedule-batch-management-design-v5.md`
**Design baseline:** `d56a8a061446400e324384f2719af3c95ba7d0af` (PR #204 merge)
**Scope:** future Phase 1C-A correction/closure only

> Plan v5 supersedes v4. Rebaseline actual `main` before execution. Current source overrides path and implementation assumptions. Use strict RED → minimal GREEN TDD and small reviewable commits. Do not begin Phase 1C-B.

## C1 — Real catalog evidence and corrected descriptors

Modify `requirement_scheduler/migrations.py` and migration test support. Replace the production-only `requirement_schedule_catalog()` hook with ordinary parameterized DB-API catalog queries over all nine `sys.*` views named by Design v5. Recording/scripted fakes expose only `execute/fetchone/fetchall` behavior.

Encode complete PR #200, PR #201, and canonical-v2 descriptors. Correct all seven stale v4 width claims (plus Run `run_policy`): preserve actual `32/20/16/32/32/16/32/32` character widths. Compare exact tables, columns, ordinals, byte lengths, PK/UQ order, index predicate and uniqueness, and complete FK parent/reference bindings; reject extras, equivalents, and hybrids. Model `FilteredIndex.is_unique` explicitly so occurrence indexes are unique and pending audit is not.

**RED:** classifier through realistic cursor rejects malformed/hybrid, wrong/missing/equivalent FK, wrong ordinal/type/length, and wrong index uniqueness/filter; it never invokes a custom method.
**GREEN:** both exact source shapes and canonical v2 classify uniquely.

## C2 — Explicit fresh-v2 DDL and marker authority

Replace v1 concatenation/string replacement with a standalone explicit canonical-v2 statement generator. Define exact ordering for schema/version bootstrap, canonical tables, keys/FKs, unique occurrence indexes, non-unique pending index, final marker write, marker re-read, and postvalidation. Use a recording DB-API connection to execute—not merely substring-inspect—the fresh path.

Require exactly one marker. Distinguish proven empty bootstrap from established zero-row state. Multiple/mixed/unknown values fail closed. Fresh and migrated paths re-read marker after writing 2; existing v2 performs no DDL/DML and only complete validation.

**RED:** executable fresh statement order, fresh postvalidation, singleton failures, marker-last, and existing-v2 validation-only.
**GREEN:** generated catalog equals the canonical descriptor exactly.

## C3 — Separate PR #200 and PR #201 migration programs

In `ScheduleStore.initialize()`, dispatch only after C1 classification. Both transactions prevalidate, postvalidate canonical v2, CAS marker last, re-read it, and roll back on every failure.

* PR #200: do not drop absent constraints; execute the full Gate-B absence query set; validate RequirementVersion/Requirement identity consistency; repair only reviewed placeholders; widen only `phase1a_task_id`; add missing internal FKs and composite owner UQ/FKs; create outbox.
* PR #201: never issue identity updates; preserve valid internal FKs; drop/replace only simple active-version/run-version FKs superseded by owner FKs; widen only `phase1a_task_id`; add owner UQ/composite FKs; create outbox.

Gate-B guards cover every Run/Item/checkpoint field listed in Design v5, Gate-A-reachable states, counters, and immutable Phase 1B identity joins. Add injection points at every validation, data update, DDL, postvalidation, marker write/re-read, and commit boundary.

**RED:** exact per-shape statement lists; PR #200 Gate-B/identity ambiguity rejection; PR #201 no identity mutation; rollback restores marker/data/catalog.
**GREEN:** both exact shapes reach identical canonical v2 and 240-character external IDs survive.

## C4 — Persisted configuration closure

Modify persisted config validation so the SQL string is explicitly coerced through `RunPolicy(run_policy)` or equivalent before constructing canonical config. Revalidate persisted recurrence, timezone, model, hash/status/approval and active pointer on migration and every approval/enable path.

**RED:** approved/enabled persisted `all_active`, `new_or_changed`, and `changed_only` succeed; invalid string/config fails safely; annotations alone are not relied on.
**GREEN:** valid active/approved rows migrate and operate; invalid rows cannot migrate/approve/enable.

## C5 — Exact outbox schema and safe events

Correct descriptors/DDL to the Design v5 names, widths, nullability, defaults, FK, and exact non-unique `(delivered_at,created_at,audit_event_id)` pending index. Do not retain PR #204 renames such as `payload_json`/`delivery_attempts`, nullable lifecycle schedule ID, wrong action width, or wrong index order.

Build each action payload from a positive allowlist; blacklist scanning can be defense-in-depth only. Verify canonical serialization, bounds, immutable fields, stable event ID, and absence of secrets/raw errors/paths/arbitrary metadata.

**RED/GREEN:** exact catalog and action-by-action allowlist tests plus lifecycle mutation/outbox rollback coupling.

## C6 — Bounded production projection and CAS semantics

Wire `requirement_scheduler.audit_delivery` into two bounded best-effort paths: after each successful lifecycle commit and after successful scheduler initialization. Inject the existing audit sink; add no FastAPI scheduling thread. Post-commit failure leaves domain response successful and event pending. Denials remain direct audit.

Pending reads are bounded/deterministic. Sink I/O is outside lifecycle SQL. Success and failure metadata updates both CAS pending rows. Interpret rowcount zero as benign lost race and report neither current failure nor a false current delivery. Preserve original ID/created-at timestamp over delays/retries; duplicate append remains allowed.

**RED/GREEN:** post-commit wiring, startup/delayed drain, sink failure, crash-before-mark retry, same ID/`ts`, and concurrent success/failure lost-race interleavings.

## C7 — Dedicated closure matrix

Create `tests/test_requirement_schedule_v5_closure.py` (or one demonstrably equivalent comprehensive matrix). It must call `ScheduleStore.initialize()` with realistic recording/scripted DB-API fakes using only normal cursor methods and cover:

1. fresh-v2 executable statements and postvalidation;
2. exact PR #200 and PR #201 migrations;
3. malformed/hybrid catalog and missing/wrong/equivalent FK rejection;
4. complete PR #200 Gate-B rejection, identity repair, 240-character ID, and rollback;
5. persisted RunPolicy and active/approved validation;
6. singleton marker, marker-last, re-read, and failure at every migration boundary;
7. exact outbox schema and non-unique pending index;
8. domain/outbox rollback coupling and post-commit/startup projection wiring;
9. delayed projection, crash-before-delivered retry, stable ID/timestamp, and concurrent CAS lost races;
10. action-specific safe payload allowlists; and
11. explicit absence of all Gate-B implementation.

## C8 — Verification and review handoff

Install requirements before pytest as repository instructions require. Run and record RED/GREEN focused tests, all Phase 1C tests, cross-phase regressions, full suite, compile/static checks, prohibited import scan, credentials/artifact scan, and changed-file scope. Live SQL runs only with explicit authorization; otherwise report it as NOT EXECUTED, not PASS. Update `.codex` memory without erasing history. Commit and open a PR; do not merge or self-award PASS.

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
PYTHONPATH=. pytest -q tests/test_requirement_schedule_v5_closure.py --tb=short
PYTHONPATH=. pytest -q tests/test_requirement_schedule_*.py --tb=short
PYTHONPATH=. pytest -q tests/test_requirement_*.py tests/test_batch_scheduler_*.py tests/test_phase0_security_acceptance.py --tb=short
PYTHONPATH=. pytest -q tests --tb=short
python -m compileall -q requirement_scheduler data_ingestion/requirements batch_scheduler sra_api api tests
git diff --check
! rg -n '(^| )(from|import) (agent|elasticsearch|api\.services\.report_job_worker|api\.core\.presenters)' requirement_scheduler
git diff --name-only "$BASELINE_SHA"...HEAD
```

Required completion wording:

```text
Phase 1C-A v5 closure ready for post-merge Implementation Review. Phase 1C-B NOT STARTED.
```
