# SRA Requirement Schedule + Batch Management — Implementation Plan v4

**Design:** `docs/superpowers/specs/2026-09-05-sra-requirement-schedule-batch-management-design-v4.md`
**Design-time baseline:** `fe621409f52b8387a833f502b7ff47c128000583` (PR #202 merge); rebaseline actual `main` before execution
**Scope:** incremental Phase 1C-A v4 Closure Gate only

> **Plan v4 supersedes Plan v3.** Plans v1–v3 remain historical records and must not be executed. Design v4 and Codex Prompts v4 likewise supersede v3. This is incremental C1–C8 closure work—not a greenfield replay of A1–A12—and does not start Phase 1C-B.

## 1. TDD and gate rules

For C1–C8, add the stated failing test, run RED and retain its failure evidence, make the minimum implementation, run GREEN, review the diff, and commit only that task. Current source wins stale file assumptions, but authority/transaction/security changes require review rather than silent redesign. Every SQL connection uses autocommit false; every exception before commit invokes rollback and closes the connection. No test may call fake ODBC evidence live SQL acceptance.

Common invariants: schedule/version/run identities and historical selection evidence are immutable; only documented pointers/lifecycle/delivery fields are mutable. `REQUIREMENT_SCHEDULE_DB_SCHEMA` and `REQUIREMENT_DB_SCHEMA` remain independent validated identifiers. No task adds Phase 1A bridge/import, execution worker, manual execution, remote reconciliation, Word history, UI, Agent/Elasticsearch/ReportJobWorker/renderer import, direct Phase 1A SQLite access, or FastAPI scheduling thread.

## C1 — Canonical schema-v2 descriptors and known-v1 classification

**Exact files:** modify `requirement_scheduler/migrations.py`, `tests/test_requirement_schedule_migrations.py`, `tests/requirement_schedule_test_support.py` (create only if shared recording-catalog fixtures warrant it).
**Interfaces:** public `SCHEMA_VERSION = 2`; private canonical descriptors for columns/PKs/UQs/FKs/indexes; private `classify_v1_catalog(cursor,schedule_schema,requirement_schema) -> Literal["pr200_v1","pr201_v1"]`; v2 `validation_queries(...)`/`validate_catalog_evidence(...)`.
**Locks/tables:** classifier reads `schema_version` and catalog metadata only; no domain-row lock or DDL in this task.
**Transaction:** caller-owned read transaction; classification completes before any mutation.
**Immutable/mutable:** descriptors/classification result are immutable; no persisted field is mutable.
**Failure:** wrong type/length/nullability/ordinal, unknown/missing/ambiguous key, unexpected FK binding, hybrid shape, or non-singleton marker raises safe `unsupported_requirement_schedule_schema`; raw driver/catalog details do not escape.
**Retry/idempotency:** repeated classification is read-only and deterministic.

**RED test:** prove descriptors require schema 2, outbox objects, composite ownership keys/FKs, pending-index order, and `phase1a_task_id` byte length 480. Encode Design v4's full columns/type/length/nullability/ordinal, PK/UQ and filtered-index descriptors and its twelve-row FK matrix. Fixtures distinguish exact PR #200/#201 shapes; assert every required/absent FK and both generations' seven width differences; reject extra/equivalent FKs, malformed catalogs, and every arbitrary hybrid.
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py -k 'v2 or classify or pr200 or pr201 or malformed or composite or outbox' --tb=short`
**GREEN test:** the same command passes, plus existing strict catalog tests remain green.
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py --tb=short`
**Commit boundary:** `git add requirement_scheduler/migrations.py tests/test_requirement_schedule_migrations.py tests/requirement_schedule_test_support.py && git commit -m "test: define requirement schedule schema v2"` (omit an uncreated support file).

## C2 — Fresh-v2 initialization and transactional v1→v2 migration

**Exact files:** modify `requirement_scheduler/migrations.py`, `requirement_scheduler/store.py`, `tests/test_requirement_schedule_migrations.py`, `tests/test_requirement_schedule_store.py`, and the C1 support fake if created.
**Interfaces:** private `canonical_v2_statements(...)`, `migration_1_to_2_statements(v1_shape,...)`, and deterministic `ScheduleStore.initialize()` dispatch.
**Locks/tables:** transaction locks singleton `schema_version` with `UPDLOCK,HOLDLOCK`; migration reads catalog plus schedule/version/run rows needed for ownership checks.
**Transaction/order:** `BEGIN`; lock singleton marker; classify and validate exact v1 catalog; validate persisted schedule/version config; validate same-schedule bindings; for PR #200 validate Gate-B absence then repair exact legacy identities; widen task ID; replace composite ownership constraints; create outbox; validate complete canonical v2 catalog/data; compare-and-set marker 1→2 **last**; re-read marker; `COMMIT`. Fresh/0 creates v2 directly. Version 2 validates without DDL; all other states rollback.
**Immutable/mutable:** schema shape and marker change; the sole domain-history mutation is Design v4's exact, one-time PR #200 identity repair. PR #201 identities and immutable configuration are never rewritten.
**Failure:** any classification/data/DDL/post-validation/marker failure rolls back; v1 marker stays 1 and no partial v2 is visible.
**Retry/idempotency:** restart sees wholly v1 and repeats, or wholly v2 and read-only validates; no downgrade.

**RED test:** empty DB creates canonical v2 directly and writes 2 last; empty version 0 does likewise. PR #200 invalid approved timezone and invalid active recurrence fail with marker 1. A valid legacy version migrates. An invalid draft/retired version may migrate only under Design v4's historical-only constraints, and persisted-row revalidation rejects its later approval/activation even while disabled. Cover invalid interval offset/precision, recurrence evidence, run policy, and blank/oversize model. Malformed type/nullability/FK/orphan/active mismatch fails. Inject failure during repair and at ALTER/UQ/FK/outbox/post-validation/marker; assert rollback of every identity, DDL, outbox, and marker change. v2 performs zero DDL/marker DML; future version fails closed.
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_store.py -k 'fresh_v2 or v1_to_v2 or rollback or existing_v2 or future_version' --tb=short`
**GREEN test:** assert exact SQL recording, commit/rollback counts, DDL order, marker-last order, and no history UPDATE/DELETE.
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_store.py --tb=short`
**Commit boundary:** `git add requirement_scheduler/migrations.py requirement_scheduler/store.py tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_store.py tests/requirement_schedule_test_support.py && git commit -m "feat: migrate requirement schedule schema to v2"` (stage only existing/changed files).

## C3 — Narrow PR #200 identity repair, 240-character identity, and same-schedule integrity

**Exact files:** modify `requirement_scheduler/migrations.py`, `requirement_scheduler/store.py` only if validation reveals a runtime assumption, `tests/test_requirement_schedule_migrations.py`, `tests/test_requirement_schedule_materialization.py`, `tests/test_requirement_schedule_transactions.py`.
**Interfaces:** materialization continues returning `MaterializedRun`; canonical `phase1a_task_id NVARCHAR(240) NULL` stores the selected exact external identity and skipped items use `None`; canonical composite UQ/FKs use Design v4 names/order.
**Locks/tables:** migration locks marker and validates `requirement_schedules`, `requirement_schedule_versions`, `requirement_batch_runs`; materialization retains schedule/version/snapshot/checkpoint `UPDLOCK,HOLDLOCK`.
**Transaction:** widening and UQ/FK replacement occur inside C2 migration after mismatch validation; materialization and item insert remain in their existing one transaction.
**Immutable/mutable:** PR #200 exact legacy identities are the only one-time exception; all PR #201/canonical IDs, configuration, and run bindings remain byte-for-byte immutable.
**Failure:** before repair prove every applicable run/item evidence field is NULL/absent and no state/counter/checkpoint could come from Gate B. Any Gate-B-like evidence, unexpected `phase1c-`/internal-ID pattern, skipped non-NULL task, missing/ambiguous Requirement join, mismatch, or orphan aborts the whole migration. Never guess, truncate, hash, or substitute.
**Retry/idempotency:** migrated IDs compare exactly before/after; materialization replay preserves existing run identity.

**RED test:** PR #200 `blocked_no_snapshot` and normal-run batch IDs change exactly from `phase1c-<run>` to `reqrun-<run>`; selected internal `requirement_id != external_item_id` changes exactly to joined external ID; skipped remains `NULL`; a 240-character external ID repairs exactly. PR #201 canonical IDs remain byte-for-byte unchanged and receive no identity UPDATE. Unexpected identity patterns and each Gate-B evidence field/state fail closed. Inject repair failure and prove repair/DDL/outbox/marker rollback. Also reject cross-schedule pointers/bindings and assert UQ-before-FK order.
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_materialization.py tests/test_requirement_schedule_transactions.py -k '240 or task_id or same_schedule or mismatch or widen' --tb=short`
**GREEN test:** all identity/materialization/migration tests pass without normalization substitution.
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_materialization.py tests/test_requirement_schedule_transactions.py --tb=short`
**Commit boundary:** `git add requirement_scheduler/migrations.py requirement_scheduler/store.py tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_materialization.py tests/test_requirement_schedule_transactions.py && git commit -m "fix: align schedule task identity and version ownership"` (omit unchanged runtime files).

## C4 — Transactional audit-outbox schema and domain model

**Exact files:** modify `requirement_scheduler/migrations.py`, `requirement_scheduler/models.py`, `requirement_scheduler/store.py`, `tests/test_requirement_schedule_migrations.py`; create `tests/test_requirement_schedule_audit_outbox.py`.
**Interfaces:** frozen internal `ScheduleAuditEvent`; private `_enqueue_audit_event(cursor,event)`; bounded `list_pending_audit_events(limit)` and delivery metadata methods reserved for C6. Stable IDs are opaque ≤64 characters.
**Locks/tables:** enqueue uses caller's transaction/cursor; pending operations target outbox rows only.
**Transaction:** no enqueue method commits; lifecycle caller owns commit. Delivery metadata is never mixed with lifecycle mutation.
**Immutable/mutable:** event/action/actor/entity IDs/payload/created time immutable; only delivery attempt/time/code/delivered time mutable.
**Failure:** serialization rejects non-allowlisted fields, non-object/oversize payload, unstable action, or secret-shaped keys; insert error becomes safe `persistence_error` for caller rollback.
**Retry/idempotency:** PK event identity prevents duplicate insert; no event identity regeneration during delivery.

**RED test:** exact types/nullability/index; canonical bounded JSON; all action vocabulary; reject password/token/service-key/connection-string/raw-SQL/raw-ODBC/prompt/absolute-path/traceback/arbitrary-body fields and oversize values.
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_audit_outbox.py -k 'schema or payload or action or secret or immutable' --tb=short`
**GREEN test:** same suite passes and emitted projection shape always includes stable `audit_event_id`.
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_audit_outbox.py --tb=short`
**Commit boundary:** `git add requirement_scheduler/migrations.py requirement_scheduler/models.py requirement_scheduler/store.py tests/test_requirement_schedule_migrations.py tests/test_requirement_schedule_audit_outbox.py && git commit -m "feat: add requirement schedule audit outbox domain"`.

## C5 — Lifecycle mutation and outbox in one SQL transaction

**Exact files:** modify `requirement_scheduler/store.py`, `requirement_scheduler/service.py`, `tests/test_requirement_schedule_store.py`, `tests/test_requirement_schedule_service.py`, `tests/test_requirement_schedule_transactions.py`, `tests/test_requirement_schedule_audit_outbox.py`.
**Interfaces:** store lifecycle methods accept actor/action evidence internally and enqueue before their existing commit; service preserves public signatures.
**Locks/tables:** create locks identity/Requirement set as currently required; rename/enable/disable lock schedule `UPDLOCK,HOLDLOCK`; version creation locks schedule/version-number range; approval locks schedule and involved version rows. Each transaction writes its affected rows plus outbox.
**Transaction:** open → locks/validate → mutation → enqueue stable event → commit. No filesystem call occurs inside SQL.
**Immutable/mutable:** logical schedule identity/set and version rows remain immutable as v2 specified; name, enabled, active pointer, next-run timing, audit delivery metadata are the only relevant mutable fields.
**Failure:** injected outbox insert after prospective mutation rolls back schedule/version/pointer changes; domain failure commits no event.
**Retry/idempotency:** exact approve/enable/disable no-op returns existing state and emits no second transition event; retries after rollback may generate a new uncommitted candidate ID, but only one committed transition/event exists.

**RED test:** each of create, rename, version create, approve, enable, disable has one transaction/event/action; inject outbox failure for schedule and version paths and prove no partial state; inject domain failure and prove no event; exact no-op replay produces no duplicate.
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py tests/test_requirement_schedule_transactions.py tests/test_requirement_schedule_audit_outbox.py -k 'lifecycle or enqueue or rollback or noop or idempotent' --tb=short`
**GREEN test:** ordered recording proves mutation and event precede the same sole commit.
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py tests/test_requirement_schedule_transactions.py tests/test_requirement_schedule_audit_outbox.py --tb=short`
**Commit boundary:** `git add requirement_scheduler/store.py requirement_scheduler/service.py tests/test_requirement_schedule_store.py tests/test_requirement_schedule_service.py tests/test_requirement_schedule_transactions.py tests/test_requirement_schedule_audit_outbox.py && git commit -m "feat: atomically audit schedule lifecycle changes"`.

## C6 — Bounded at-least-once JSONL projection

**Exact files:** create `requirement_scheduler/audit_delivery.py`, `tests/test_requirement_schedule_audit_delivery.py`; modify `requirement_scheduler/store.py` and `sra_api/main.py` only for bounded startup wiring selected by implementation.
**Interfaces:** `drain_audit_outbox(store, sink, *, limit: int, now_utc: datetime) -> AuditDrainResult`; sink is injected and compatible with `append_audit_event(event_dict)`.
**Locks/tables:** bounded pending read orders `(created_at,audit_event_id)` and uses short outbox-only claim/update locks (`UPDLOCK,READPAST` where supported); no schedule row is locked during filesystem I/O.
**Transaction:** committed rows are read/claimed; sink call occurs outside lifecycle transaction. Success and failure metadata updates are short transactions with `WHERE audit_event_id=? AND delivered_at IS NULL` (or equivalent CAS). A zero-row race is benign and never regresses delivered state.
**Immutable/mutable:** event payload/identity immutable; delivery metadata monotonic.
**Failure:** sink exception never rolls back domain state, never escapes raw exception/path, records only `audit_sink_write_failed`, and processing remains bounded.
**Retry/idempotency:** projection sets `ts` from immutable `outbox.created_at` in canonical UTC ISO form. Delayed and duplicate projection preserves identical `audit_event_id` and lifecycle `ts`; delivery/attempt clocks remain SQL metadata. At-least-once duplicates remain allowed; delivered rows are skipped.

**RED test:** limit/order; delayed append retains original `created_at` as `ts`; crash-before-mark retry yields two records with the same ID and same `ts`; sink failure leaves pending with safe code. Concurrent-style interleave: projector A appends/marks delivered, projector B fails later, B's conditional failure update affects zero rows and final SQL remains delivered with no misleading pending failure. Test success CAS too; make no exactly-once assertion and add no thread/lease/queue.
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_audit_delivery.py --tb=short`
**GREEN test:** delivery suite passes with injected `events.append` and raising sinks.
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_audit_delivery.py tests/test_audit.py --tb=short`
**Commit boundary:** `git add requirement_scheduler/audit_delivery.py requirement_scheduler/store.py sra_api/main.py tests/test_requirement_schedule_audit_delivery.py && git commit -m "feat: project schedule audits with bounded retries"` (omit unchanged wiring files).

## C7 — API success/denial authority integration

**Exact files:** modify `sra_api/routers/requirement_schedules.py`, optionally `sra_api/main.py` for dependency wiring, `tests/test_requirement_schedule_api.py`, `tests/test_requirement_schedule_audit_outbox.py`; do not alter `sra_api/routers/editor_dependencies.py` or `sra_api/services/editor_audit.py` unless a regression proves compatibility is broken.
**Interfaces:** lifecycle routes call transaction-aware store/service only; post-commit bounded drain is injected/non-authoritative; `authorize_role()` remains denial path.
**Locks/tables:** success uses C5 transaction locks/outbox; denial reaches no schedule/outbox row.
**Transaction:** route never appends success directly before/after mutation as its sole evidence; it may drain only after commit.
**Immutable/mutable:** API response contract remains; no public outbox/error payload is added.
**Failure:** outbox insert failure returns safe persistence failure with mutation rolled back; post-commit projection failure still returns committed domain success and leaves pending evidence; denial stays HTTP 403 plus direct JSONL denial event.
**Retry/idempotency:** no-op success retry does not enqueue duplicate transition; projection retry uses stable event ID.

**RED test:** authenticated success creates SQL event and removes route-level direct success append; operator/superuser matrix; denied request calls existing direct audit and inserts no outbox; projection failure does not turn committed success into HTTP failure; public response contains no payload/delivery error.
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py tests/test_requirement_schedule_audit_outbox.py -k 'audit or denial or projection or lifecycle or rbac' --tb=short`
**GREEN test:** full API suite passes with action-specific created/updated/version-created/version-approved/enabled/disabled evidence.
**GREEN command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py tests/test_requirement_schedule_audit_outbox.py --tb=short`
**Commit boundary:** `git add sra_api/routers/requirement_schedules.py sra_api/main.py tests/test_requirement_schedule_api.py tests/test_requirement_schedule_audit_outbox.py && git commit -m "fix: route schedule audits through sql authority"` (omit unchanged files).

## C8 — Migration, crash, security, and regression closure gate

**Exact files:** create `tests/test_requirement_schedule_v4_closure.py`; modify only defects' minimal owning files; update `docs/operations/requirement-scheduling.md` and applicable `.codex/*.md` with observed results.
**Interfaces:** consumes the whole Gate A closure and produces review evidence, not a self-awarded PASS.
**Locks/tables:** tests assert marker/schedule/version/run/outbox locks and transaction ordering from C1–C7.
**Transaction:** failure injection covers every pre/post migration and audit boundary; successful operations show exactly one lifecycle commit plus independent delivery metadata commits.
**Immutable/mutable:** assert historical IDs/config/run bindings/event bodies immutable; only approved lifecycle/delivery fields mutate.
**Failure:** all malformed/mismatch/secret/crash cases fail closed or remain safely retryable exactly as Design v4 specifies.
**Retry/idempotency:** prove fresh/v1/v2 restart dispatch, no duplicate transition event, and duplicate JSONL projection with stable event ID.

**RED test:** one matrix covers all Design v4 proofs: fresh v2; exact PR #200/#201 descriptors; narrow identity repair and Gate-B-evidence rejection; legacy active/approved config validation and historical-only invalid draft approval rejection; rollback at every ordered migration boundary; existing-v2 read-only; future version; 240-character identity; outbox/domain/projection/CAS failures; original lifecycle timestamp; forbidden data; and Gate B absence.
**RED command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_v4_closure.py --tb=short`
**GREEN test:** focused closure, all Phase 1C, Phase 1B, Phase 1A, Phase 0/security, full repository, compile/static/scope checks have zero failures/errors (warnings reported honestly).
**GREEN commands:**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_schedule_*.py --tb=short
PYTHONPATH=. pytest -q tests/test_requirement_*.py tests/test_batch_scheduler_*.py tests/test_phase0_security_acceptance.py --tb=short
PYTHONPATH=. pytest -q tests --tb=short
python -m compileall -q requirement_scheduler data_ingestion/requirements batch_scheduler sra_api api tests
git diff --check
! rg -n '(^| )(from|import) (agent|elasticsearch|api\.services\.report_job_worker|api\.core\.presenters)' requirement_scheduler
git diff --name-only -- requirement_scheduler sra_api api data_ingestion/requirements batch_scheduler tests
```

The final scope command may list only files intentionally implemented by this future closure, never Gate B modules. Live SQL acceptance runs only with explicit authorization; otherwise record NOT EXECUTED.
**Commit boundary:** `git add tests/test_requirement_schedule_v4_closure.py docs/operations/requirement-scheduling.md .codex requirement_scheduler sra_api && git commit -m "test: close phase 1c-a v4 repository gate"` (stage only files actually changed; never stage Gate B work).

## 2. Traceability matrix

| Required proof | Tasks |
|---|---|
| fresh v2, marker last, v2 read-only, future fail closed | C1, C2, C8 |
| exact PR #200/#201 catalog/FK allowlist; no hybrids | C1, C2, C8 |
| active/approved legacy config validation; invalid draft cannot activate | C2, C8 |
| narrow PR #200 repair, Gate-B absence, PR #201 preservation, exact 240-char ID | C2, C3, C8 |
| same-schedule composite UQ/FKs and mismatch rollback | C1–C3, C8 |
| exact outbox schema, stable ID, safe payload | C1, C4, C8 |
| mutation + event same transaction; no-op dedupe | C5, C7, C8 |
| projection created-at `ts`, success/failure pending CAS, concurrent monotonicity | C6–C8 |
| success SQL authority vs direct denial audit | C7, C8 |
| no Gate B execution/import/worker/Word scope | every task, C8 gate |

## 3. Closure report wording

After all tests pass and the PR is created, report exactly:

```text
Phase 1C-A v4 closure repository gate ready for post-merge Implementation Review.
Phase 1C-B NOT STARTED.
```

Do not declare Gate A PASS. A human/ChatGPT post-merge review owns that verdict.
