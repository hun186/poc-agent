# SRA Requirement Source, Versioning & Import Pipeline — Implementation Plan v1.1 (Completion Delta)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five Major implementation/test gaps identified by Phase 1B Implementation Review v1 without redesigning or reimplementing the completed Phase 1B architecture.

**Architecture:** Preserve Design v1 and the merged Phase 1B implementation. This plan changes only the import failure audit seam, CSV duplicate-header handling, SQL Server schema migration/validation, actual `RequirementStore` transaction/RBAC regression coverage, and stable SQL/persistence error translation. Phase 1C scheduling and Phase 1A dispatch behavior remain out of scope.

**Tech Stack:** Python 3.x, FastAPI/Pydantic v2, `openpyxl`, stdlib `csv/json/hashlib/zoneinfo`, `python-dateutil`, `pyodbc`, existing SRA RBAC/audit helpers, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-sra-requirement-source-import-pipeline-design-v1.md`

**Authoritative Review:** `docs/superpowers/reviews/2026-09-04-sra-requirement-source-import-pipeline-implementation-review-v1.md`

**Supersedes:** `docs/superpowers/plans/2026-09-04-sra-requirement-source-import-pipeline-plan-v1.md` **only for the remaining completion work described in Review v1.** Completed v1 behavior remains authoritative and must not be reworked unless needed to fix a listed regression.

## Baseline Binding

- Repository: `poc-agent`
- Authoritative source snapshot for this plan: `poc-agent_20260904-134758.zip` (user-confirmed latest merged source)
- Codex-reported Phase 1B implementation commit contained in the merged lineage: `1bc6544b95622a52b27fcfe1c053ff514406c501`
- Actual branch/HEAD after merge: **must be discovered by Codex preflight; do not invent or replace it with the implementation commit above.**
- Design version: Phase 1B Design v1 — unchanged
- Review version: Phase 1B Implementation Review v1
- Plan version: v1.1

## Global Constraints

- Do not create Design v2 unless an actual Design v1 requirement is impossible or contradictory in the current source.
- Do not implement Phase 1C recurrence, eligibility selection, Batch Run creation, Report Job submission, or Web UI.
- Do not redesign `data_ingestion/requirements/`, move Phase 1B into `batch_scheduler`, or duplicate Agent/Elasticsearch/Word execution logic.
- Preserve `REQUIREMENT_PIPELINE_ENABLED=false` backward-compatible startup behavior.
- Preserve reviewed Import Profile activation: committed imports resolve the enabled profile's explicit `active_version_id`; draft versions may be previewed but not committed.
- Preserve source safety: no arbitrary SQL in API source objects, no credentials in source/profile/API output, and file-path access remains confined to configured roots.
- SQL Server control-plane operations use explicit transactions with `autocommit=False`; no generic auto-create-table importer.
- External HTTP responses expose stable safe codes only; raw SQL/ODBC exception text, credentials, connection strings, or query text must not leak.
- Keep the existing Phase 0 and Phase 1A security/behavior gates passing.
- TDD is required for every behavioral fix: demonstrate a failing regression before the production change where practical, then GREEN.

## Files Expected to Change

Primary runtime files:

```text
data_ingestion/requirements/readers.py
data_ingestion/requirements/migrations.py
data_ingestion/requirements/store.py
data_ingestion/requirements/source_adapters.py
sra_api/routers/requirements.py
```

Primary tests/support:

```text
tests/requirement_test_support.py
tests/test_requirement_source_adapters.py
tests/test_requirement_store.py
tests/test_requirement_import_service.py
tests/test_requirement_api.py
tests/test_requirement_integration.py
```

Documentation/memory may change only as required by Task 6:

```text
docs/operations/requirement-import.md
.codex/api_contract.md
.codex/architecture.md
.codex/backlog.md
.codex/decisions.md
.codex/known_issues.md
.codex/memory.md
```

---

### Task 0: Rebaseline the merged repository and preserve completed Phase 1B behavior

**Files:**
- Read: `AGENTS.md`
- Read: `docs/superpowers/specs/2026-09-04-sra-requirement-source-import-pipeline-design-v1.md`
- Read: `docs/superpowers/reviews/2026-09-04-sra-requirement-source-import-pipeline-implementation-review-v1.md`
- Read: `docs/superpowers/plans/2026-09-04-sra-requirement-source-import-pipeline-plan-v1.1.md`
- Read: current Phase 1B runtime/tests listed above

**Interfaces:**
- Consumes: merged source currently checked out by Codex.
- Produces: a recorded actual repository baseline for the completion report.

- [ ] **Step 1: Record actual repository baseline**

Run:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
```

Record repository, branch, HEAD, and working-tree state. If HEAD is not `1bc6544b...`, treat the actual checked-out source as authoritative and verify that the reviewed Phase 1B files are present before editing.

- [ ] **Step 2: Read Design v1, Review v1, Plan v1.1, and actual source**

Confirm that each of Review v1 Major 1–5 is still present or already independently fixed. If a finding is already fixed, keep the existing implementation and add/retain the required regression evidence instead of replacing it.

- [ ] **Step 3: Run the current targeted Phase 1B tests before changes**

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

Record the baseline result. Existing tests passing does not waive the Review v1 missing-regression requirements.

---

### Task 1: Persist failed-import row diagnostics, including post-rollback stale/anomaly failures

**Files:**
- Modify: `data_ingestion/requirements/store.py`
- Modify: `tests/requirement_test_support.py`
- Modify: `tests/test_requirement_store.py`
- Modify: `tests/test_requirement_import_service.py`

**Interfaces:**
- Consumes: `NormalizedCandidate`, `RowDiagnostic`, `AcquiredSource`, existing `RequirementStore.commit_candidate()`.
- Produces:
  - failed `import_runs` with one or more `import_run_rows` diagnostic observations;
  - prior active snapshot unchanged on validation/stale/anomaly failure;
  - no Requirement/RequirementVersion/Snapshot mutation in failed-import persistence.

- [ ] **Step 1: Add failing tests for validation-failure diagnostics**

Add a recording fake ODBC connection/cursor in `tests/requirement_test_support.py` that can record `execute`, `commit`, `rollback`, and scripted `fetchone`/`fetchall` results.

Add tests against the real `RequirementStore` asserting:

```python
result = store.record_failed_import(source, version, acquired, candidate, actor="operator")
assert result["status"] == "failed"
assert one INSERT targets import_runs
assert one INSERT per candidate diagnostic targets import_run_rows
assert every diagnostic row preserves source_row_number, external_item_id, diagnostic_code
assert connection.commit_count == 1
assert connection.rollback_count == 0
```

Also assert `row_count` reflects source row observations, not `len(candidate.rows) + len(candidate.diagnostics)` when multiple diagnostics refer to the same source row.

- [ ] **Step 2: Run the new failed-import tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py -k 'failed_import or diagnostic' --tb=short
```

Expected before fix: no `import_run_rows` inserts and incorrect/missing row observation accounting.

- [ ] **Step 3: Implement failed-import diagnostic persistence in one transaction**

Refactor `record_failed_import()` so it obtains one connection and performs:

```text
BEGIN implicit transaction
→ INSERT import_runs(status='failed')
→ INSERT deterministic import_run_rows observations/diagnostics
→ COMMIT
```

Rules:

- One source row may have multiple diagnostics; preserve each diagnostic deterministically.
- `diagnostic_message` must be safe and bounded for the schema column.
- Do not create Requirement, RequirementVersion, Requirement Set, Snapshot, or Snapshot Item rows.
- On persistence failure, rollback and raise the stable persistence-domain error defined in Task 5.

- [ ] **Step 4: Add failing commit-time stale/anomaly race tests**

Use a recording fake ODBC script where preview/candidate preparation would have been valid, but `commit_candidate()` re-reads a newer current version under `UPDLOCK,HOLDLOCK` and detects:

```text
stale_source_version
source_version_anomaly
```

Assert:

```text
main commit transaction rolls back
prior active snapshot is not changed
no new RequirementVersion/Snapshot survives
then a separate failed Import Run is committed
failed Import Run contains the safe stale/anomaly diagnostic row
```

- [ ] **Step 5: Implement safe post-rollback failed-run recording**

In `commit_candidate()`, distinguish domain stale/anomaly failures from unrelated persistence failures. For stale/anomaly:

```text
rollback mutation transaction
close transaction connection
build safe RowDiagnostic for the affected source row
record failed Import Run in a new transaction
return/raise according to existing service/API contract without activating a snapshot
```

Do not attempt to write the failed run before rolling back the mutation transaction.

- [ ] **Step 6: Run Task 1 GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py tests/test_requirement_import_service.py -k 'failed_import or diagnostic or stale or anomaly' --tb=short
```

- [ ] **Step 7: Commit Task 1**

```bash
git add data_ingestion/requirements/store.py tests/requirement_test_support.py tests/test_requirement_store.py tests/test_requirement_import_service.py
git commit -m "fix: persist requirement import diagnostics"
```

---

### Task 2: Make CSV duplicate/empty headers fail closed without losing ambiguity

**Files:**
- Modify: `data_ingestion/requirements/readers.py`
- Modify: `tests/test_requirement_source_adapters.py`
- If required only for strict resolution compatibility: `data_ingestion/requirements/profile.py`

**Interfaces:**
- Consumes: CSV bytes and existing profile normalization.
- Produces: row mappings that preserve duplicate raw header positions or a stable `source_format_invalid`/mapping ambiguity failure before data loss.

- [ ] **Step 1: Add failing duplicate-header regressions**

Add tests for at least:

```text
ITEMNO,CONTENT,CONTENT
A1,first,second
```

and normalized duplicates such as:

```text
ITEMNO,CONTENT,CONTENT 
A1,first,second
```

Assert the reader/profile pipeline never silently returns only `CONTENT='second'` as an unambiguous row.

Also test an empty CSV header position containing non-empty data.

- [ ] **Step 2: Run duplicate-header tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_source_adapters.py -k 'csv and (duplicate or header)' --tb=short
```

- [ ] **Step 3: Replace `csv.DictReader` collapse with collision-preserving parsing**

Use `csv.reader` for the header row and subsequent rows. Preserve every column position using the same collision strategy as XLSX, for example repeated labels gain deterministic trailing spaces before profile normalization, while empty labels receive deterministic `__column_N` names.

Required properties:

```text
UTF-8-SIG decoding preserved
source row numbers still start at 2
ragged rows do not silently discard non-empty cells
normalized duplicate headers remain detectable by strict profile resolution
```

Do not special-case the Taiwan sample headers.

- [ ] **Step 4: Run Task 2 GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_source_adapters.py tests/test_requirement_profile.py --tb=short
```

- [ ] **Step 5: Commit Task 2**

```bash
git add data_ingestion/requirements/readers.py data_ingestion/requirements/profile.py tests/test_requirement_source_adapters.py
git commit -m "fix: reject ambiguous requirement csv headers"
```

If `profile.py` is unchanged, omit it from `git add`.

---

### Task 3: Implement the SQL Server schema 0→1 migration state machine and canonical schema validation

**Files:**
- Modify: `data_ingestion/requirements/migrations.py`
- Modify: `data_ingestion/requirements/store.py`
- Modify: `tests/requirement_test_support.py`
- Modify: `tests/test_requirement_store.py`

**Interfaces:**
- Consumes: named SQL Server control-plane connection, validated schema identifier.
- Produces:
  - fresh database → canonical schema v1;
  - version 0 → canonical schema v1;
  - valid version 1 → validated, no destructive rebuild;
  - malformed version 1 → startup failure/rollback;
  - unknown version → fail closed/rollback.

- [ ] **Step 1: Add recording fake ODBC migration tests**

The fake must support ordered SQL recording and scripted result sets sufficient to assert transaction state, not merely string-presence in generated DDL.

Add cases:

```text
fresh: schema_version table absent/empty → create v1 objects → validate → write version 1 → commit
v0: version row=0 → create/repair only allowed v1 objects → validate → update version 1 → commit
v1-valid: version row=1 → validate canonical objects → commit without version rewrite/destructive rebuild
v1-malformed: version row=1 but missing required table/column/UQ/FK → rollback + startup error
unknown: version row=2 or 99 → rollback + unsupported-version error
DDL/validator exception → rollback
```

- [ ] **Step 2: Run migration state-machine tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py -k 'migration or schema_version or schema_validation' --tb=short
```

- [ ] **Step 3: Separate bootstrap DDL, version inspection, and validation**

In `migrations.py`, keep `SCHEMA_VERSION = 1` and introduce focused helpers such as:

```python
def bootstrap_schema_statements(schema: str) -> list[str]: ...
def migration_0_to_1_statements(schema: str) -> list[str]: ...
def validation_queries(schema: str) -> list[SchemaCheck]: ...
```

Exact names may follow existing style, but responsibilities must remain separate and testable.

The validator must prove all required Design v1 objects, including:

```text
all 11 Phase 1B tables
required columns used by runtime SQL
UQ_import_profile_version
UQ_requirement_identity
UQ_requirement_version
PK_requirement_snapshot_items
required foreign keys for profile/source/requirement/snapshot/version relations
```

Do not accept schema version `1` based only on the integer row.

- [ ] **Step 4: Implement `RequirementStore.initialize()` state machine**

Required order:

```text
open connection (autocommit false)
→ bootstrap schema + schema_version container if absent
→ read schema version (missing row is treated as 0)
→ if version == 0: execute 0→1 migration statements
→ elif version == 1: no migration
→ else: raise unsupported requirement schema version
→ validate canonical schema/integrity objects
→ if migrated: persist version = 1 only after validation succeeds
→ COMMIT
```

Any exception before commit must rollback. Never partially mark version 1 before successful validation.

- [ ] **Step 5: Run Task 3 GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py -k 'migration or schema_version or schema_validation' --tb=short
```

- [ ] **Step 6: Commit Task 3**

```bash
git add data_ingestion/requirements/migrations.py data_ingestion/requirements/store.py tests/requirement_test_support.py tests/test_requirement_store.py
git commit -m "fix: validate requirement schema migrations"
```

---

### Task 4: Prove actual `RequirementStore` transaction, version, snapshot, and concurrency contracts

**Files:**
- Modify: `tests/requirement_test_support.py`
- Modify: `tests/test_requirement_store.py`
- Modify: `tests/test_requirement_import_service.py`
- Modify runtime `data_ingestion/requirements/store.py` only where a new real-store regression proves a defect.

**Interfaces:**
- Consumes: the actual `RequirementStore`, not `MemoryStore`, at the SQL transaction seam.
- Produces: repository evidence for Design v1 versioning/snapshot atomicity.

- [ ] **Step 1: Expand the recording fake ODBC seam**

Support scripted transactions for:

```text
source/profile CRUD
profile version MAX(version_number)+1 locking
profile approval active_version_id update
current version lookup
commit_candidate requirement/version/snapshot flow
prior snapshot membership lookup for upsert_delta
forced exception at selected SQL statement
commit/rollback counters
```

The fake must preserve ordered calls so tests can assert that active snapshot switching occurs after all writes and before commit.

- [ ] **Step 2: Add actual-store source/profile tests**

Against `RequirementStore`, assert:

```text
new profile versions are monotonic and immutable
new version starts draft
approval updates only review fields/status plus profile.active_version_id
committed import resolves only enabled + approved active_version_id
draft version can be explicitly previewed but is never implicitly committed
source_config persisted without secret/executable fields
```

- [ ] **Step 3: Add actual-store snapshot/atomicity tests**

Cover both source modes:

```text
authoritative_snapshot: omitted old item is absent from new snapshot, historical prior snapshot remains readable
upsert_delta: omitted old item is carried forward into new snapshot
same UPDT + same payload: reuse version
newer UPDT + changed content: insert next RequirementVersion
same UPDT + changed payload: rollback + failed-run diagnostic, no active switch
older UPDT: rollback + failed-run diagnostic, no active switch
forced exception after RequirementVersion insert but before active_snapshot_id update: rollback leaves prior state authoritative
forced exception after snapshot items but before commit: rollback
```

Assert `source_snapshot_sha256` and `import_profile_version_id` are bound to the committed snapshot.

- [ ] **Step 4: Run actual-store tests RED/GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py tests/test_requirement_import_service.py -k 'store or profile or snapshot or rollback or authoritative or upsert or anomaly or stale' --tb=short
```

If a test reveals a runtime defect, apply the smallest fix in `store.py`; do not redesign the domain.

- [ ] **Step 5: Commit Task 4**

```bash
git add data_ingestion/requirements/store.py tests/requirement_test_support.py tests/test_requirement_store.py tests/test_requirement_import_service.py
git commit -m "test: cover requirement sql transaction contracts"
```

If runtime code is unchanged, omit it from `git add`.

---

### Task 5: Complete SQL/persistence error taxonomy and HTTP/RBAC regressions

**Files:**
- Modify: `data_ingestion/requirements/source_adapters.py`
- Modify: `data_ingestion/requirements/store.py`
- Modify: `sra_api/routers/requirements.py`
- Modify: `tests/test_requirement_source_adapters.py`
- Modify: `tests/test_requirement_api.py`

**Interfaces:**
- Produces stable domain errors:
  - `sql_read_error` → HTTP 503
  - `persistence_error` → HTTP 500
- Preserves existing safe errors/status codes for source/profile/mapping/stale/anomaly conditions.

- [ ] **Step 1: Add source SQL exception regression**

Script a named SQL connection whose `cursor()`, `execute()`, or `fetchall()` raises an exception containing a fake sensitive DSN/password fragment.

Assert `acquire_source()` raises a stable domain error whose public string/code is exactly `sql_read_error` and does not contain the sensitive fragment. The connection must still close.

- [ ] **Step 2: Add store persistence exception regressions**

For `_execute`, `initialize`, `record_failed_import`, profile approval, and `commit_candidate`, inject representative ODBC failures and assert:

```text
rollback when a transaction is open
connection closes
public/domain error is persistence_error except where initialize uses its documented startup/configuration error wrapper
raw driver/credential text is not exposed to API response
```

Internal server logging may retain safe contextual metadata, but do not log raw credential values.

- [ ] **Step 3: Add real HTTP authentication/RBAC matrix**

Use the existing FastAPI auth dependency behavior rather than overriding all dependencies to the same user.

Required API cases:

```text
no authenticated user → 401
read-only/non-operator user attempts create/patch/preview/import → 403
DB operator can create draft source/profile/version and preview
DB operator cannot enable source/profile → 403
DB operator cannot approve version → 403
superuser can enable and approve
safe GET endpoints remain available to authenticated roles allowed by existing current_user policy
manual multipart upload accepted only for manual_upload source
upload to file_path/sql_query source rejected with stable safe error
sql_read_error → 503 detail.code=sql_read_error
persistence_error → 500 detail.code=persistence_error
stale_source_version/source_version_anomaly → 409
pipeline disabled → 503
```

Also assert existing RBAC audit events still occur for denied role actions through the dependency layer.

- [ ] **Step 4: Run Task 5 tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_source_adapters.py tests/test_requirement_api.py -k 'sql_read_error or persistence_error or rbac or unauth or forbidden or upload' --tb=short
```

- [ ] **Step 5: Implement stable exception translation**

At the source adapter boundary, wrap SQL acquisition failures after configuration validation as `sql_read_error` while preserving connection close semantics.

At the store boundary, translate ODBC/transaction persistence failures to a stable `persistence_error` domain exception. Do not convert known domain exceptions such as `stale_source_version`, `source_version_anomaly`, `profile_invalid`, or `source_disabled` into persistence errors.

Update `_error()` in `sra_api/routers/requirements.py` to include:

```text
persistence_error -> 500
sql_read_error -> 503
```

Preserve the existing mappings for 400/403/404/409/503 codes. Unknown internal exceptions must not default to a misleading 400; map them to a safe 500 unless they are known client/domain errors.

- [ ] **Step 6: Run Task 5 GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_source_adapters.py tests/test_requirement_api.py --tb=short
```

- [ ] **Step 7: Commit Task 5**

```bash
git add data_ingestion/requirements/source_adapters.py data_ingestion/requirements/store.py sra_api/routers/requirements.py tests/test_requirement_source_adapters.py tests/test_requirement_api.py
git commit -m "fix: harden requirement import error boundaries"
```

---

### Task 6: Update Phase 1B operations docs and durable project memory

**Files:**
- Modify: `docs/operations/requirement-import.md`
- Modify as applicable: `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/backlog.md`, `.codex/decisions.md`, `.codex/known_issues.md`, `.codex/memory.md`

**Interfaces:**
- Documents only behavior actually implemented/tested in Tasks 1–5.

- [ ] **Step 1: Update SQL source operational contract**

Document that a `sql_query` registry entry must use a database principal with read-only permissions for the reviewed source query. SQL text parsing is not a security boundary; the registry + database permissions are.

- [ ] **Step 2: Document migration and failure diagnostics**

Document:

```text
schema version 0 upgrades to 1
version 1 is structurally validated at startup
unknown/malformed schema fails closed
failed imports retain row-level diagnostics
same-UPDT anomaly/stale races do not switch active snapshot
```

- [ ] **Step 3: Update durable memory/status**

Remove any statement that Phase 1B repository gate is complete if it predates this v1.1 verification. Record Review v1 findings as resolved only after the relevant tests pass. Keep live SQL Server acceptance marked pending until actually executed.

- [ ] **Step 4: Commit Task 6**

```bash
git add docs/operations/requirement-import.md .codex
git commit -m "docs: update requirement import hardening"
```

---

### Task 7: Run the Phase 1B v1.1 repository verification gate and optional live SQL Server acceptance

**Files:**
- No production changes unless verification exposes a regression.
- Update `.codex` status only with verified results if needed.

**Interfaces:**
- Produces final repository gate evidence for Review v2.

- [ ] **Step 1: Run focused Phase 1B suite**

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

Required: 0 failures, 0 errors.

- [ ] **Step 2: Run Phase 1A/Phase 0 regression gate**

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

Required: 0 failures, 0 errors.

- [ ] **Step 3: Run full repository gate**

```bash
PYTHONPATH=. pytest tests -q --tb=short
python -m compileall -q data_ingestion/requirements batch_scheduler sra_api api tests
git diff --check
rg -n "from (agent|api\.services\.report_job_worker|api\.services\.word_export)|import (agent|elasticsearch)" data_ingestion/requirements sra_api/routers/requirements.py
rg -n 'ITEMNO|DeadlineDT|CreateApeno|UpdateApeno' data_ingestion/requirements sra_api/routers/requirements.py
```

Required:

```text
full pytest: 0 failures / 0 errors
compileall: exit 0
git diff --check: exit 0
prohibited execution imports: 0 matches
sample-specific production mapping branches: 0 matches
```

Run the repository's existing tracked credential/runtime-artifact scans as documented by Phase 0/1A. Do not print secret values.

- [ ] **Step 4: Optional authorized live SQL Server acceptance**

Execute only if Codex has explicit access to the intended Requirement control-plane SQL Server and credentials. Otherwise mark **NOT EXECUTED**, not failed and not passed.

When authorized, prove:

```text
fresh/v0 schema initializes to canonical v1
version-1 canonical schema validates
10-row Taiwan workbook imports through real SQL Server
active snapshot has exactly 10 memberships
import run binds exact profile version + source fingerprint
invalid row creates failed run + row diagnostic, prior active snapshot unchanged
same-UPDT/different-payload is rejected and recorded, no active switch
older-UPDT is rejected and recorded, no active switch
forced transaction failure rolls back partial RequirementVersion/Snapshot writes
```

Do not reuse unrelated production credentials.

- [ ] **Step 5: Final working-tree and completion evidence**

```bash
git status --short
git log --oneline -n 8
```

The working tree must be clean before claiming completion.

## Completion Criteria

Phase 1B v1.1 repository completion may be declared **PASS** only if all of the following are true:

1. Failed Import Runs persist row-level diagnostics.
2. Commit-time stale/anomaly races rollback domain mutations and record a safe failed run without switching active snapshot.
3. CSV duplicate/normalized-duplicate headers no longer silently collapse.
4. Fresh and schema-version-0 databases converge to canonical schema version 1.
5. Schema version 1 is structurally validated for required tables/columns/unique constraints/foreign keys; malformed v1 fails closed.
6. Unknown schema versions fail closed and rollback.
7. Actual `RequirementStore` transaction tests prove source/profile activation, immutable versions, authoritative omission, upsert-delta carry-forward, snapshot binding, and rollback atomicity.
8. Real HTTP tests prove the required 401/403/superuser/DB-operator matrix.
9. SQL acquisition failures map to `sql_read_error`/503 without raw ODBC leakage.
10. Persistence failures map to `persistence_error`/500 without raw ODBC leakage.
11. Phase 1B focused tests, Phase 1A/Phase 0 regressions, and full repository tests have 0 failures/errors.
12. No Phase 1C behavior or duplicated Agent/Elasticsearch/Word execution logic was introduced.
13. Live SQL Server acceptance is either PASS with explicit evidence or accurately declared NOT EXECUTED; repository completion must not be represented as live deployment acceptance.

## Required Completion Report

Codex must report:

```text
Repository
Branch
Baseline commit actually observed
Resulting commit
Design version: v1
Authoritative Review: Implementation Review v1
Plan version: v1.1
Changed files
Working-tree state

Major 1 failed-import diagnostics: PASS/FAIL + evidence
Major 2 CSV duplicate-header fail-closed: PASS/FAIL + evidence
Major 3 schema migration/validation: PASS/FAIL + evidence
Major 4 real RequirementStore/RBAC regressions: PASS/FAIL + evidence
Major 5 error taxonomy: PASS/FAIL + evidence

Focused Phase 1B tests: command + pass/fail/error counts
Phase 1A/Phase 0 regression tests: command + counts
Full repository tests: command + counts
compileall / diff / static scans

Live SQL Server acceptance: PASS / FAIL / NOT EXECUTED
If executed: exact behaviors proven, without credentials
If not executed: why it was unavailable

Deviations from Design/Plan
Remaining issues/risks
PR status
```

Do not claim Phase 1B deployment acceptance PASS solely from fake ODBC or repository tests.
