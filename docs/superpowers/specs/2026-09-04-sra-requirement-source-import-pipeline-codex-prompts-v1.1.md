# Codex Prompt — Phase 1B Requirement Import Completion Delta v1.1

You are implementing a narrowly scoped completion delta for the existing SRA `poc-agent` repository.

## Execution Contract

This is **not** a redesign and **not** a new Phase 1B implementation. The merged Phase 1B architecture already exists. Your job is to close exactly the remaining repository gaps identified by Implementation Review v1 while preserving completed behavior.

### Authoritative documents

Read these before editing:

1. `docs/superpowers/specs/2026-09-04-sra-requirement-source-import-pipeline-design-v1.md`
2. `docs/superpowers/reviews/2026-09-04-sra-requirement-source-import-pipeline-implementation-review-v1.md`
3. `docs/superpowers/plans/2026-09-04-sra-requirement-source-import-pipeline-plan-v1.1.md`
4. The actual current repository source and tests.

Design v1 remains authoritative. Review v1 is the authoritative implementation review. Plan v1.1 supersedes Plan v1 only for the remaining completion delta.

### Baseline discipline

The review source snapshot was `poc-agent_20260904-134758.zip`, user-confirmed as the latest merged source at review time. The earlier Phase 1B implementation commit reported by Codex was `1bc6544b95622a52b27fcfe1c053ff514406c501`, but the repository may now be at a merge commit or later commit.

Before changes run:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
```

Record the actual repository, branch, baseline HEAD, and working-tree state. **Do not invent a commit and do not replace the actual HEAD with `1bc6544b...`.**

If actual source paths differ from the Plan because the repository moved after review, inspect the current implementation and apply the same required behavior at the actual location. Current source takes precedence over stale line numbers. Report any deviation.

## Scope: close exactly these five Major findings

### Major 1 — Failed import diagnostics

Fix the real `RequirementStore` so failed Import Runs persist row-level `import_run_rows` diagnostics. Also handle commit-time stale/anomaly races safely:

```text
mutation transaction detects stale/anomaly
→ rollback all domain/snapshot mutations
→ close mutation transaction
→ record a separate failed Import Run with safe row diagnostic(s)
→ prior active snapshot remains unchanged
```

Do not create/retain RequirementVersion or Snapshot changes for a failed run.

### Major 2 — CSV duplicate headers

Replace the current `csv.DictReader` behavior that silently collapses duplicate columns. Preserve positional duplicate/empty headers using a collision-preserving strategy compatible with strict profile normalization, or fail before data loss with the stable format/ambiguity error. Add duplicate and normalized-duplicate regressions.

### Major 3 — SQL schema migration and validation

Implement the Design/Plan migration contract:

```text
fresh database / missing version row → treat as version 0
version 0 → migrate to canonical v1
version 1 → validate canonical schema
unknown version → fail closed
malformed v1 → fail closed
```

Validation must prove required Phase 1B tables, runtime-required columns, unique constraints/primary key, and foreign keys. Set schema version 1 only after migration and validation succeed in the same transaction. Roll back on error.

### Major 4 — Real RequirementStore and HTTP/RBAC evidence

Do not use `MemoryStore` as the only proof of SQL-store correctness. Build/extend a recording fake ODBC seam and test the actual `RequirementStore` for:

```text
profile version immutability/monotonicity/approval
active_version_id commit selection
authoritative omission
upsert_delta carry-forward
same-UPDT reuse
newer-UPDT new version
same-UPDT anomaly rollback
older-UPDT stale rollback
forced transaction rollback
snapshot/profile/source fingerprint binding
```

Complete HTTP tests for:

```text
unauthenticated 401
underprivileged 403
DB operator allowed operations
DB operator cannot enable or approve
superuser enable/approve
manual-upload constraints
safe error mapping
```

Use the real dependency/RBAC behavior where possible; do not override every auth dependency to the same user and call that a matrix.

### Major 5 — Stable SQL/persistence error taxonomy

Translate source SQL acquisition failures to stable `sql_read_error` and HTTP 503. Translate store/transaction persistence failures to stable `persistence_error` and HTTP 500. Never expose raw SQL/ODBC errors, credentials, connection strings, or reviewed SQL text in HTTP responses.

Known domain errors such as stale/anomaly/profile/source validation must retain their existing semantics/status codes and must not be swallowed into persistence errors.

## Non-negotiable preservation constraints

Do not:

- create Design v2 unless a genuine Design contradiction/blocker is proven;
- implement Phase 1C recurrence, due-item selection, Batch Run creation, Report Job dispatch, or Web UI;
- redesign or relocate the Phase 1B domain unnecessarily;
- duplicate Agent, Elasticsearch, Report Job worker, or Word export execution logic;
- weaken `REQUIREMENT_PIPELINE_ENABLED=false` compatibility;
- allow committed imports to use draft/unapproved profile versions;
- accept arbitrary SQL in API source objects;
- weaken file-path confinement;
- persist or print raw credentials;
- claim live SQL acceptance from fake ODBC tests.

Keep changes minimal and reviewable. If a Review finding is already fixed in the actual baseline, preserve it and add/verify the regression instead of replacing it.

## Required development method

Use TDD for behavioral changes:

```text
write/extend regression
→ run targeted test and demonstrate RED where practical
→ implement minimum fix
→ rerun GREEN
→ continue to next finding
```

Follow the task order in Plan v1.1. Use separate commits per meaningful task when practical. If you choose a different commit grouping, explain why; do not sacrifice correctness merely to match commit count.

## Required tests and gates

At minimum run:

```bash
PYTHONPATH=. pytest -q \
  tests/test_requirement_profile.py \
  tests/test_requirement_source_adapters.py \
  tests/test_requirement_store.py \
  tests/test_requirement_import_service.py \
  tests/test_requirement_api.py \
  tests/test_requirement_startup.py \
  tests/test_requirement_integration.py --tb=short
```

Then Phase 1A / Phase 0 regressions:

```bash
PYTHONPATH=. pytest -q \
  tests/test_batch_scheduler_input.py \
  tests/test_batch_scheduler_store.py \
  tests/test_batch_scheduler_client.py \
  tests/test_batch_scheduler_service.py \
  tests/test_batch_scheduler_cli.py \
  tests/test_batch_scheduler_security.py \
  tests/test_report_jobs_api.py \
  tests/test_report_job_store.py \
  tests/test_report_job_worker.py \
  tests/test_job_authorization.py \
  tests/test_service_key_store.py \
  tests/test_service_key_api.py \
  tests/test_phase0_security_acceptance.py --tb=short
```

Then full/static gates:

```bash
PYTHONPATH=. pytest tests -q --tb=short
python -m compileall -q data_ingestion/requirements batch_scheduler sra_api api tests
git diff --check
rg -n "from (agent|api\.services\.report_job_worker|api\.services\.word_export)|import (agent|elasticsearch)" data_ingestion/requirements sra_api/routers/requirements.py
rg -n 'ITEMNO|DeadlineDT|CreateApeno|UpdateApeno' data_ingestion/requirements sra_api/routers/requirements.py
```

Expected:

```text
all pytest gates: 0 failures, 0 errors
compileall: pass
diff check: pass
prohibited direct execution imports: 0 matches
sample-specific runtime branches: 0 matches
tracked credential/runtime artifact scans: pass without printing secret values
working tree: clean after commit
```

## Live SQL Server acceptance

If and only if this environment has explicit authorized access to the intended Requirement control-plane SQL Server and credentials, run the Plan v1.1 live acceptance proving:

```text
fresh/v0 → v1
v1 structural validation
10-row Taiwan workbook import
10 active snapshot memberships
profile version + source fingerprint binding
invalid-row failed-run diagnostics
same-UPDT anomaly rejection/no active switch
older-UPDT rejection/no active switch
transaction rollback/no partial state
```

If the private SQL Server or credentials are unavailable, report **NOT EXECUTED**. Do not reuse unrelated credentials. Do not call repository/fake-ODBC evidence live acceptance.

## Documentation

Update `docs/operations/requirement-import.md` and durable `.codex` project memory to reflect only verified behavior. Explicitly document that named `sql_query` sources rely on reviewed registry SQL plus a database principal with read-only permission; SQL text parsing is not the security boundary.

Ensure this review file is tracked at:

```text
docs/superpowers/reviews/2026-09-04-sra-requirement-source-import-pipeline-implementation-review-v1.md
```

Do not rewrite Review v1 to make the implementation look better. It is historical review evidence.

## Completion report contract

Your final response must include:

```text
Repository
Branch
Actual baseline commit
Resulting commit
Design v1
Authoritative Review v1
Plan v1.1
Working-tree state
Changed files

Major 1 diagnostics: PASS/FAIL + exact test evidence
Major 2 CSV duplicate headers: PASS/FAIL + exact test evidence
Major 3 migration/schema validation: PASS/FAIL + exact test evidence
Major 4 RequirementStore/RBAC coverage: PASS/FAIL + exact test evidence
Major 5 error taxonomy: PASS/FAIL + exact test evidence

Focused Phase 1B suite result
Phase 1A/Phase 0 regression result
Full repository result
compileall/diff/static/security scans

Live SQL Server acceptance: PASS / FAIL / NOT EXECUTED
Credential handling statement
Deviations from Design/Plan
Remaining issues/risks
PR status
```

Do not say "Phase 1B complete" unless the repository completion criteria in Plan v1.1 all pass. Even then, distinguish **repository gate PASS** from **live SQL Server deployment acceptance** if the latter was not executed.
