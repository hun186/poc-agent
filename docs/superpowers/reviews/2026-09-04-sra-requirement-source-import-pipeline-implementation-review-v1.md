# SRA Requirement Source, Versioning & Import Pipeline — Implementation Review v1

## Baseline

- Repository: `poc-agent`
- Review source snapshot: `poc-agent_20260904-134758.zip`
- Codex reported baseline commit: `ee796957e74f7eeb89f54202e8e7dfa01a5c017f`
- Codex reported resulting commit: `1bc6544b95622a52b27fcfe1c053ff514406c501`
- Design: `docs/superpowers/specs/2026-09-04-sra-requirement-source-import-pipeline-design-v1.md`
- Plan: `docs/superpowers/plans/2026-09-04-sra-requirement-source-import-pipeline-plan-v1.md`
- Review version: v1

## Verdict

**NOT PASS for Phase 1B repository completion.**

No Design v2 is required. The architecture is consistent with Design v1, but several Major implementation/test gaps remain before the repository gate can be accepted. Live SQL Server deployment acceptance remains pending after repository completion.

## Independent verification evidence

The review environment could not install `pyodbc` / `elasticsearch` from the package index, so the full repository suite was not independently re-run. Codex's reported `14 / 62 / 384` passing results remain external execution evidence.

Fresh review-side checks:

- `python -m compileall -q data_ingestion/requirements sra_api api tests` -> PASS (one pre-existing SyntaxWarning outside Phase 1B).
- Prohibited Agent / Elasticsearch execution import scan in Phase 1B runtime -> 0 matches.
- Sample-specific production mapping branch scan -> 0 matches.
- With local dependency stubs, the pure Phase 1B profile/source/store/service/integration tests run -> **11 passed**.
- Reproduced failed-import diagnostics persistence gap: `RequirementStore.record_failed_import()` performs exactly one `import_runs` insert and no `import_run_rows` insert.
- Reproduced CSV duplicate-header collapse: `ITEMNO,CONTENT,CONTENT` becomes `{'ITEMNO': 'A1', 'CONTENT': 'second'}` rather than failing closed.
- Reproduced schema-version gap: a store initialized with schema version `0` raises `unsupported requirement schema version` and rolls back instead of migrating `0 -> 1`.
- Reproduced schema-validation gap: a version-`1` fake database can pass `initialize()` without any required-object validation query.

## Major findings

### Major 1 — Failed Import Runs do not persist row-level diagnostics

**Location**

- `data_ingestion/requirements/store.py`, `record_failed_import()` around lines 165–167.
- `commit_candidate()` stale/anomaly race paths around lines 145–146 and rollback around 160–161.

**Design / Plan requirement**

- Design v1 §9.2: failed Import Run records row-level diagnostics.
- Plan v1 Task 6 Step 3: insert `import_runs` plus `import_run_rows` diagnostics in the failed-import transaction.
- Plan v1 Task 6 Step 4: commit-time stale/anomaly re-evaluation must fail without activating a snapshot; failure recording must remain safe after rollback.

**Observed behavior**

`record_failed_import()` inserts only `import_runs`. It does not insert any `import_run_rows`. A commit-time stale/anomaly race rolls back and re-raises without creating a failed Import Run.

**Result**

The later Web UI cannot retrieve the required row-level repair diagnostics. Import audit/history is incomplete exactly for the error cases operators need to diagnose.

**Required fix**

Persist one deterministic `import_run_rows` observation/diagnostic per source row/error for failed candidate validation. For safe post-rollback stale/anomaly failures, create a separate failed Import Run with the relevant safe reason/row diagnostics and no RequirementVersion/Snapshot mutation.

**Version impact**

- Design: unchanged v1.
- Plan/Prompt: completion-delta update only.

---

### Major 2 — CSV duplicate headers are silently collapsed instead of failing closed

**Location**

- `data_ingestion/requirements/readers.py`, `read_csv_rows()`.

**Design / Plan requirement**

- Design v1 §19.1 requires duplicate/ambiguous headers to fail closed.
- Plan v1 Task 2 Step 3 requires empty/duplicate raw headers to be carried to strict resolution rather than silently collapsed.

**Observed behavior**

`csv.DictReader` collapses duplicate header names before profile resolution. Review reproduction:

```text
ITEMNO,CONTENT,CONTENT
A1,first,second
```

becomes:

```python
{'ITEMNO': 'A1', 'CONTENT': 'second'}
```

The ambiguity is lost and the last value silently wins.

**Result**

A malformed or changed CSV schema can import the wrong source column without an operator-visible mapping error.

**Required fix**

Preserve positional duplicate CSV headers using the same collision-preserving strategy as XLSX, or detect normalized duplicate headers before `DictReader` creates row mappings and fail with the stable ambiguity/format diagnostic. Add a regression test.

**Version impact**

- Design: unchanged v1.
- Plan/Prompt: completion-delta update only.

---

### Major 3 — SQL migration/startup contract is incomplete

**Location**

- `data_ingestion/requirements/migrations.py`
- `data_ingestion/requirements/store.py`, `initialize()`.

**Design / Plan requirement**

Plan v1 Task 3 requires:

```text
BEGIN
-> create schema/schema_version if absent
-> if version 0, create all v1 objects
-> validate required objects
-> set version = 1
-> COMMIT
```

Unknown versions must fail closed.

**Observed behavior**

1. Version `0` is treated as unsupported instead of being migrated to `1`.
2. Version `1` is accepted without validating required tables/columns/unique constraints/FKs.
3. Repository tests do not exercise this state machine with the required recording fake ODBC seam.

**Result**

A legitimate version-0 deployment cannot upgrade, while a malformed version-1 schema can pass startup and fail later under live traffic.

**Required fix**

Implement an explicit migration/version state machine and schema validator. Add recording fake-pyodbc tests for fresh, v0->v1, v1-valid, v1-malformed, unknown-version rollback, transaction commit/rollback, and required integrity objects.

**Version impact**

- Design: unchanged v1.
- Plan/Prompt: completion-delta update only.

---

### Major 4 — Required SQL transaction and API/RBAC regression coverage was not implemented

**Location**

- `tests/test_requirement_store.py`
- `tests/test_requirement_import_service.py`
- `tests/test_requirement_integration.py`
- `tests/test_requirement_api.py`
- `tests/requirement_test_support.py`

**Plan requirement**

- Task 3: recording fake pyodbc DDL/transaction tests.
- Task 4: real RequirementStore source/profile immutability/approval tests.
- Task 6: atomicity, rollback, stale/anomaly race, authoritative omission, upsert-delta carry-forward, snapshot binding.
- Task 7: full HTTP/RBAC matrix including unauthenticated 401, underprivileged 403, superuser-only enable/approve, upload acceptance/rejection, and safe error mapping.

**Observed behavior**

Most version/snapshot behavior is tested through `MemoryStore`, not `RequirementStore`. `test_requirement_store.py` currently checks only DDL text presence and schema-name rejection. API tests cover a superuser happy path and disabled-service 503, but not the required negative RBAC matrix.

**Result**

The reported test counts do not prove the most important SQL Server transaction and management-API security contracts. This is why the repository gate cannot yet be accepted even though all reported tests pass.

**Required fix**

Add the Plan-required recording fake ODBC tests against the actual `RequirementStore` transaction seam and complete the real HTTP RBAC/error matrix. Keep MemoryStore tests for fast domain behavior, but do not use them as the only proof of SQL-store correctness.

**Version impact**

- Design: unchanged v1.
- Plan/Prompt: completion-delta update only.

---

### Major 5 — Stable SQL/persistence error taxonomy is not fully wired

**Location**

- `data_ingestion/requirements/source_adapters.py`
- `data_ingestion/requirements/store.py`
- `sra_api/routers/requirements.py`, `_error()`.

**Design / Plan requirement**

- `sql_read_error` -> HTTP 503.
- `persistence_error` -> HTTP 500.
- Raw SQL/ODBC exception details must not be exposed to clients.

**Observed behavior**

Actual ODBC acquisition/persistence exceptions are generally propagated directly instead of being translated into stable domain errors. `_error()` has no `persistence_error -> 500` branch; unrecognized exceptions default to HTTP 400.

**Result**

Infrastructure failures can be misclassified as operator input errors and automation cannot reliably distinguish retryable SQL outages from repairable data/profile errors.

**Required fix**

Translate source SQL failures to `sql_read_error`, store/transaction failures to `persistence_error`, keep safe server-side logging/audit detail, and return only stable machine-readable codes. Add HTTP tests for both cases.

**Version impact**

- Design: unchanged v1.
- Plan/Prompt: completion-delta update only.

## Minor / improvement findings

1. The delivered ZIP contains ignored `.pytest_cache` / `__pycache__` artifacts. This does not indicate a Git cleanliness problem but is worth excluding from future source ZIPs.
2. The `sql_query` adapter relies on the privileged registry/operator to supply a read-only database credential. Make the read-only database-principal requirement explicit in operations documentation and regression coverage; do not rely on parsing SQL text as a security boundary.
3. `import_runs.row_count` should be derived from source row observations rather than `len(candidate.rows) + len(candidate.diagnostics)`, because duplicate/stale/anomaly diagnostics may refer to rows that are already counted as normalized rows.

## What is accepted

The review accepts the following architecture/implementation directions and they should not be redesigned in the completion delta:

- isolated `data_ingestion/requirements/` domain;
- manual/file-path/named-SQL source adapters;
- configuration-driven Import Profile mapping;
- immutable profile versions with explicit active version;
- stable Requirement identity and immutable RequirementVersion model;
- authoritative/upsert-delta snapshot semantics;
- atomic active-snapshot switch inside the SQL transaction;
- Phase 1B separation from Agent/Elasticsearch/Word/Phase 1C dispatch;
- optional startup gate behind `REQUIREMENT_PIPELINE_ENABLED`;
- supplied Taiwan workbook mapping remains configuration-driven, not hard-coded in production Python.

## Gate status

```text
Phase 1B Design v1                         PASS / unchanged
Phase 1B architecture direction            PASS
Phase 1B repository implementation gate    NOT PASS
Phase 1B live SQL Server acceptance        NOT READY / NOT EXECUTED
Phase 1C                                   DO NOT START YET
```

## Recommended next action

Create **Phase 1B Plan v1.1 / Codex Prompt v1.1 completion delta** only. Do not create Design v2 and do not reimplement completed source/profile/snapshot architecture. The delta should close the five Major findings above, run the full repository gate again, and then return for Implementation Review v2 before live SQL Server acceptance.
