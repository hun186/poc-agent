# SRA Requirement Source, Versioning & Import Pipeline — Implementation Plan v1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-04  
**Repository:** `poc-agent`  
**Baseline:** `poc-agent_20260904-103101.zip` source snapshot. The preceding Phase 1A Codex report named resulting commit `82108d9e32b733084c7b97eff868abc17fe0380e0`, but the ZIP has no `.git` metadata, so execution must re-baseline the actual repository and must not invent a commit.  
**Design:** `docs/superpowers/specs/2026-09-04-sra-requirement-source-import-pipeline-design-v1.md`  
**Design version:** Phase 1B Design v1  
**Supersedes:** none  
**Depends on:** Phase 0 Unified Security Boundary v3; Phase 1A Batch Scheduler Core v1 and its repository implementation

**Goal:** Build a configuration-driven Requirement ingestion control plane that acquires manual/file-path/SQL sources, maps changing schemas through immutable approved Import Profile Versions, atomically persists auditable Requirement/RequirementVersion history and immutable active snapshots in SQL Server, and exposes management/preview/import APIs for Phase 1C and the later Web UI.

**Architecture:** Add a focused `data_ingestion/requirements/` domain. Source acquisition, profile interpretation, canonical normalization/version analysis, SQL Server persistence, and API routing remain separate units. The SQL Server Requirement store is authoritative; Elasticsearch, Agent execution, Report Jobs, Word generation, Phase 1A scheduler transport state, and Phase 1C recurrence/dispatch remain outside this phase.

**Tech Stack:** Python 3.x, FastAPI/Pydantic v2, `openpyxl`, stdlib `csv/json/hashlib/zoneinfo`, `python-dateutil`, `pyodbc`, existing SRA RBAC/audit helpers, pytest.

## Global Constraints

- Preserve the HTTP-only execution boundary already established by Phase 1A. Phase 1B must not import or execute Agent, Elasticsearch, Report Job worker, or Word-export internals.
- SQL Server is the authoritative Requirement control-plane store. Do not put Requirement identity/version/snapshot correctness in Elasticsearch or the Phase 1A SQLite database.
- Reuse generic helpers only when their behavior satisfies Design v1. In particular, existing Excel header helpers that choose a first match on ambiguity must **not** be reused for strict Requirement mapping where ambiguity must fail closed.
- `manual_upload`, `file_path`, and `sql_query` all converge on the same normalization/version/snapshot service.
- No source-specific column name may be hard-coded into Requirement core logic. The Taiwan simulation workbook is represented by an Import Profile, not Python branches.
- Import Profile Versions are immutable after creation. Creating changed mappings creates version `N+1`; historical versions are never rewritten.
- A failed candidate import must never replace the current active snapshot.
- Same `UPDT` + different source payload is a `source_version_anomaly`; older `UPDT` is `stale_source_version`; both fail closed for activation.
- `DeadlineDT` is normalized and persisted as `expires_at`; Phase 1B does not implement schedule recurrence or Report Job dispatch.
- Persist UTC-aware canonical datetimes. Naive source datetimes require the profile `source_timezone`; never guess from server local time.
- Source/profile rows, logs, API output, and provenance must never expose DB passwords, bearer/service keys, connection-string secrets, or credential digests.
- SQL source definitions use privileged named connection/query references. Do not execute arbitrary SQL supplied by an unprivileged request.
- Server-side file-path acquisition must enforce configured allowed roots. User filenames never choose server destinations.
- Profile transforms are a fixed allowlist: `trim`, `normalize_whitespace`, `empty_to_null`, `to_text`, `to_int`, `to_datetime`. No arbitrary Python/eval/shell.
- Preview is side-effect free with respect to Requirement/Version/Snapshot state. Commit/import is explicit.
- For `authoritative_snapshot`, omission removes membership only from the new snapshot; it never deletes Requirement history. `upsert_delta` omission has no removal meaning.
- Every activated snapshot must bind the exact source fingerprint and exact Import Profile Version used.
- Existing Phase 0 security and Phase 1A scheduler tests must stay green.
- Preserve backward-compatible startup: Phase 1B is gated by `REQUIREMENT_PIPELINE_ENABLED`. When false, existing SRA startup does not require Requirement SQL configuration; when true, Requirement store configuration/schema initialization fails closed at startup rather than silently serving a broken control plane.

### Implementation interpretation note for Design §8.2

Design v1 requires both a forensic full-row hash and the ability to recognize “newer UPDT but otherwise same row.” Implement three deterministic hashes:

```text
source_row_hash      = complete normalized mapped row, including source_updated_at
source_payload_hash  = normalized mapped row excluding source_updated_at
execution_content_hash = title + prompt_content + expires_at
```

`source_row_hash` and `execution_content_hash` remain the required persisted design fields; `source_payload_hash` is an additional implementation field that makes the §8.2 comparison unambiguous without weakening the design.

---

## File Structure

Create these focused units unless the actual repository has a newer equivalent that should be extended instead:

```text
data_ingestion/requirements/
  __init__.py                 public domain exports only
  models.py                   enums and immutable/Pydantic domain models
  profile.py                  profile schema, strict header mapping, transforms, timezone normalization
  hashing.py                  canonical JSON and deterministic hashes
  readers.py                  XLSX/CSV/JSON row readers
  connections.py              named ODBC connection/query registry and secret-safe config resolution
  source_adapters.py          manual/file_path/sql_query acquisition
  migrations.py              explicit SQL Server Requirement schema migration v1
  store.py                    Requirement SQL persistence and atomic snapshot transaction
  service.py                  preview/import orchestration and version analysis

sra_api/routers/
  requirement_models.py       API request/response models
  requirements.py             Phase 1B management endpoints and RBAC/audit wiring

config/requirements/
  import_profile.taiwan-investment-security.v1.example.json
  sql_registry.example.json

docs/operations/
  requirement-import.md

tests/
  test_requirement_profile.py
  test_requirement_source_adapters.py
  test_requirement_store.py
  test_requirement_import_service.py
  test_requirement_api.py
  test_requirement_integration.py
```

Modify:

```text
sra_api/main.py               include requirements router
.env.example                  non-secret Requirement runtime variables
README.md                     link Phase 1B operations docs only
.codex/api_contract.md        management API contract
.codex/architecture.md        Requirement control-plane boundary
.codex/memory.md              durable Phase 1B state
.codex/known_issues.md        actual remaining deployment issues only
.codex/backlog.md             Phase 1C handoff items
```

Do not modify `agent/`, Report Job execution behavior, Word rendering, or Elasticsearch ingestion for this plan.

---

### Task 1: Domain models, strict profile grammar, hashing, and datetime normalization

**Files:**
- Create: `data_ingestion/requirements/__init__.py`
- Create: `data_ingestion/requirements/models.py`
- Create: `data_ingestion/requirements/profile.py`
- Create: `data_ingestion/requirements/hashing.py`
- Test: `tests/test_requirement_profile.py`

**Interfaces:**
- Consumes: `data_ingestion.excel_to_sql.utils.normalize_header` and `normalize_header_key` only where they preserve strict fail-closed semantics; `dateutil.parser`; `zoneinfo.ZoneInfo`.
- Produces:
  - `SourceType`, `SourceMode`, `ProfileVersionStatus`
  - `ImportProfileDocument`, `FieldMappingSpec`
  - `CanonicalRequirementRow`
  - `RowDiagnostic`, `NormalizedCandidate`
  - `normalize_source_datetime(value, timezone_name) -> datetime`
  - `normalize_rows(raw_rows, profile) -> NormalizedCandidate`
  - `canonical_sha256(value) -> str`

- [ ] **Step 1: Write failing profile/header/datetime/hash tests**

Create tests proving exact Design v1 behavior:

```python
from datetime import timezone
import pytest

from data_ingestion.requirements.models import ImportProfileDocument
from data_ingestion.requirements.profile import normalize_rows


def test_trailing_space_content_header_maps_strictly():
    profile = ImportProfileDocument.model_validate(_sample_profile())
    candidate = normalize_rows([
        {
            "ITEMNO": "A001",
            "TITLE": " Test title ",
            "CONTENT ": " prompt body ",
            "UPDT": "2026-09-04 09:00:00",
            "DeadlineDT": "2026-09-10 18:00:00",
            "CreateApeno": 11,
            "UpdateApeno": 12,
            "CrtDT": "2026-09-01 08:00:00",
        }
    ], profile)
    row = candidate.rows[0]
    assert row.external_item_id == "A001"
    assert row.prompt_content == "prompt body"
    assert row.source_updated_at.utcoffset() == timezone.utc.utcoffset(row.source_updated_at)


def test_ambiguous_normalized_header_fails_closed():
    profile = ImportProfileDocument.model_validate(_sample_profile())
    raw = _sample_row()
    raw["CONTENT  "] = "second value"
    candidate = normalize_rows([raw], profile)
    assert candidate.has_errors
    assert any(d.code == "mapping_ambiguous_column" for d in candidate.diagnostics)


def test_same_execution_fields_share_execution_hash_even_when_provenance_changes():
    first = normalize_rows([_sample_row(UpdateApeno=10)], _profile()).rows[0]
    second = normalize_rows([_sample_row(UpdateApeno=11)], _profile()).rows[0]
    assert first.source_row_hash != second.source_row_hash
    assert first.execution_content_hash == second.execution_content_hash
```

Also cover unknown config fields, unsupported transforms, missing required fields, `to_int`, invalid timezone names, naive datetime + configured timezone, timezone-aware input preservation, and unparseable datetime failure.

- [ ] **Step 2: Run the profile tests and verify RED**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_requirement_profile.py --tb=short
```

Expected: collection/import failure because the new package does not exist.

- [ ] **Step 3: Implement the immutable/Pydantic models**

Use strict Pydantic models (`extra="forbid"`) for profile grammar. The core shape must be equivalent to:

```python
class FieldMappingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: str
    aliases: tuple[str, ...] = ()
    required: bool = False
    type: Literal["text", "int", "datetime", "bool", "json"] = "text"
    match: Literal["exact", "normalized", "prefix", "contains"] = "normalized"
    transforms: tuple[Literal[
        "trim", "normalize_whitespace", "empty_to_null", "to_text", "to_int", "to_datetime"
    ], ...] = ()
    default: object | None = None


class ImportProfileDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    format: Literal["xlsx", "csv", "json", "sql_rows"]
    source_timezone: str
    source_mode: SourceMode = SourceMode.AUTHORITATIVE_SNAPSHOT
    worksheet: WorksheetSpec | None = None
    mapping: dict[str, FieldMappingSpec]
```

Restrict canonical mapping keys to:

```text
external_item_id
title
prompt_content
source_updated_at
expires_at
source_created_by
source_updated_by
source_created_at
```

Required canonical outputs are `external_item_id`, `title`, `prompt_content`, `source_updated_at`, and `source_created_at`.

- [ ] **Step 4: Implement strict header resolution and safe transforms**

Normalize source header labels with trimming/case policy, but fail on ambiguity rather than selecting a first match. Provide deterministic match precedence:

```text
exact → normalized → prefix → contains
```

A match mode may use only its own level and stricter levels; it must never silently downgrade an ambiguous match. Apply only the transform allowlist from Global Constraints.

- [ ] **Step 5: Implement timezone-aware datetime normalization**

Use `ZoneInfo(profile.source_timezone)`. For a naive parsed datetime, attach the profile zone and convert to UTC. For an aware input, convert directly to UTC. Return aware UTC `datetime` values; never call `datetime.now().astimezone()` to guess a source zone.

- [ ] **Step 6: Implement canonical hashing**

Canonicalize dictionaries with stable sorted JSON, UTF-8, compact separators, and normalized datetime ISO strings. Produce:

```python
source_row_hash = canonical_sha256(full_normalized_row)
source_payload_hash = canonical_sha256({k: v for k, v in full_normalized_row.items() if k != "source_updated_at"})
execution_content_hash = canonical_sha256({
    "title": title,
    "prompt_content": prompt_content,
    "expires_at": expires_at,
})
```

- [ ] **Step 7: Run Task 1 tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_profile.py --tb=short
```

Expected: all Task 1 tests pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add data_ingestion/requirements tests/test_requirement_profile.py
git commit -m "feat: add requirement import profile domain"
```

---

### Task 2: Source readers, path confinement, and named SQL connection/query registry

**Files:**
- Create: `data_ingestion/requirements/readers.py`
- Create: `data_ingestion/requirements/connections.py`
- Create: `data_ingestion/requirements/source_adapters.py`
- Create: `config/requirements/sql_registry.example.json`
- Test: `tests/test_requirement_source_adapters.py`

**Interfaces:**
- Consumes: Task 1 profile/models; existing `data_ingestion.excel_to_sql.sql_utils.detect_odbc_driver` may be reused for driver selection.
- Produces:
  - `AcquiredSource`
  - `read_xlsx_rows`, `read_csv_rows`, `read_json_rows`
  - `SqlRegistry.load(path)` and `open_named_connection(name)`
  - `acquire_source(source, *, upload_bytes=None, upload_filename=None) -> AcquiredSource`

- [ ] **Step 1: Write failing adapter/security tests**

Cover:

```python
def test_file_path_rejects_escape_from_allowed_root(tmp_path): ...
def test_manual_upload_filename_is_metadata_only(): ...
def test_sql_source_uses_connection_and_query_refs_not_request_sql(): ...
def test_xlsx_csv_json_all_return_row_dicts(): ...
def test_sql_registry_public_view_never_contains_password_or_env_value(): ...
```

Also assert `.xls` is rejected, JSON accepts only an array of objects in Phase 1B, and `source_uri_display` strips credentials/query secrets.

- [ ] **Step 2: Run Task 2 tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_source_adapters.py --tb=short
```

- [ ] **Step 3: Implement row readers**

`read_xlsx_rows` uses the selected worksheet/header row/first data row from the approved profile and returns source row number plus raw header/value mapping. `read_csv_rows` uses `utf-8-sig`. `read_json_rows` accepts a top-level list of objects only. Empty/duplicate raw headers are carried to Task 1 strict resolution rather than silently collapsed.

- [ ] **Step 4: Implement path confinement**

Read allowed roots from `REQUIREMENT_SOURCE_ALLOWED_ROOTS` using `os.pathsep`. Resolve the configured file and every allowed root with `Path.resolve(strict=False)`, compare with `os.path.commonpath`, and account for Windows case normalization via `os.path.normcase`. Reject a path not contained in at least one configured root with `PermissionError("source_path_outside_allowed_root")`.

- [ ] **Step 5: Implement named SQL registry without stored secrets**

The example registry contains only environment variable references:

```json
{
  "connections": {
    "requirement_control": {
      "driver": "auto",
      "server_env": "REQUIREMENT_CONTROL_DB_SERVER",
      "database_env": "REQUIREMENT_CONTROL_DB_DATABASE",
      "trusted_connection_env": "REQUIREMENT_CONTROL_DB_TRUSTED_CONNECTION",
      "user_env": "REQUIREMENT_CONTROL_DB_USER",
      "password_env": "REQUIREMENT_CONTROL_DB_PASSWORD",
      "encrypt": true,
      "trust_server_certificate": true
    }
  },
  "queries": {
    "external_requirement_view": {
      "connection_ref": "external_requirement_readonly",
      "sql": "SELECT ITEMNO, TITLE, CONTENT, UPDT, DeadlineDT, CreateApeno, UpdateApeno, CrtDT FROM dbo.RequirementExportView"
    }
  }
}
```

The registry is privileged server configuration. API source objects store only `connection_ref`/`query_ref`. The runtime resolves environment variables in memory and never serializes resolved secrets back into source/profile/API output.

- [ ] **Step 6: Implement source adapters**

`manual_upload` requires upload bytes and a safe metadata filename; it never writes to a user-selected path. `file_path` reads only allowed roots. `sql_query` resolves an admin-reviewed `query_ref`, uses its named read-only connection credential, calls `cursor.execute(reviewed_sql)` with no user-provided SQL fragments, converts cursor rows to dictionaries, and fingerprints canonical returned rows.

- [ ] **Step 7: Run Task 2 tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_source_adapters.py --tb=short
```

- [ ] **Step 8: Commit Task 2**

```bash
git add data_ingestion/requirements config/requirements/sql_registry.example.json tests/test_requirement_source_adapters.py
git commit -m "feat: add requirement source adapters"
```

---

### Task 3: Explicit SQL Server Requirement schema migration and store initialization

**Files:**
- Create: `data_ingestion/requirements/migrations.py`
- Create: `data_ingestion/requirements/store.py`
- Test: `tests/test_requirement_store.py`

**Interfaces:**
- Consumes: Task 2 named connection registry.
- Produces:
  - `RequirementStore(registry, connection_ref, schema)`
  - `RequirementStore.initialize()`
  - schema version `1`
  - read helpers used by later tasks

- [ ] **Step 1: Write failing migration/store tests**

Use a recording fake pyodbc connection/cursor to assert explicit SQL Server DDL and transaction behavior without requiring a developer SQL Server. Tests must assert that no generic `auto_create_missing_fields` path is called and that the schema includes all Design v1 entities.

Required tables:

```text
schema_version
requirement_sources
import_profiles
import_profile_versions
requirements
requirement_versions
requirement_sets
import_runs
import_run_rows
requirement_set_snapshots
requirement_snapshot_items
```

Add `source_mode` to sources; keep `import_profiles.enabled` from Design v1 and add `import_profiles.active_version_id`; add implementation fields `source_payload_hash` plus profile-version `status/approved_by/approved_at`, with required uniqueness/foreign keys. `active_version_id` is the explicit superuser-controlled pointer used by committed imports.

- [ ] **Step 2: Run store tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py -k migration --tb=short
```

- [ ] **Step 3: Implement migration v1**

Use a validated SQL identifier for `REQUIREMENT_DB_SCHEMA` (default `sra_requirement`). `initialize()` must:

```text
BEGIN transaction
→ create schema if absent
→ create schema_version if absent
→ if version 0, create all v1 tables/indexes/FKs
→ validate required objects
→ set version = 1
→ COMMIT
```

Do not continue from an unknown schema version. Raise a clear startup/configuration error rather than guessing.

Required unique constraints include:

```text
requirement_sources(source_id)
import_profiles(profile_id)
import_profile_versions(profile_id, version_number)
requirements(source_id, external_item_id)
requirement_versions(requirement_id, version_number)
requirement_sets(source_id)
requirement_snapshot_items(snapshot_id, requirement_id)
```

- [ ] **Step 4: Implement connection lifecycle and read helpers**

Every store operation obtains a fresh pyodbc connection from the named control-plane connection unless an explicit connection is passed for an existing transaction. Keep `autocommit=False`. Provide safe conversion helpers for SQL rows to dictionaries and UTC datetimes.

- [ ] **Step 5: Run migration/store tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py -k migration --tb=short
```

- [ ] **Step 6: Commit Task 3**

```bash
git add data_ingestion/requirements/migrations.py data_ingestion/requirements/store.py tests/test_requirement_store.py
git commit -m "feat: add requirement sql store schema"
```

---

### Task 4: Source and Import Profile persistence with reviewed activation

**Files:**
- Modify: `data_ingestion/requirements/store.py`
- Test: `tests/test_requirement_store.py`

**Interfaces:**
- Produces:
  - `create_source`, `list_sources`, `get_source`, `patch_source`
  - `create_profile`, `list_profiles`, `get_profile`, `patch_profile`
  - `create_profile_version`, `approve_profile_version`, `get_active_profile_version`

- [ ] **Step 1: Write failing CRUD/immutability/approval tests**

Cover:

```text
source identity and source_mode persisted
source_config_json round-trips without secrets
new profile version increments monotonically
profile version JSON and sha256 never update in place
new version starts draft
superuser approval atomically sets profile.active_version_id to that immutable version
committed import resolves exactly profile.active_version_id
retired/draft version is not selected for committed import
preview may explicitly select a draft profile_version_id without activating it
referenced historical profile version remains readable
```

- [ ] **Step 2: Run Task 4 tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py -k 'source or profile' --tb=short
```

- [ ] **Step 3: Implement source persistence**

Persist `source_config_json` only after validating it against source type:

```text
manual_upload: no server path/query credentials
file_path: path plus optional file_pattern only; a directory+pattern must resolve to exactly one file or fail closed
sql_query: connection_ref + query_ref only
```

Reject keys such as `password`, `token`, `authorization`, `connection_string`, raw `sql`, or raw `query` in source API configuration. If both source and profile declare `source_mode`, they must match; mismatches are `profile_invalid` and cannot preview/commit as if they were equivalent.

- [ ] **Step 4: Implement immutable reviewed profile versions**

`create_profile_version` validates `ImportProfileDocument`, computes `profile_sha256`, and inserts a `draft` version. There is no update method for `profile_json`. `approve_profile_version` changes only review fields/status and atomically sets `import_profiles.active_version_id` to that immutable version; it is idempotent when the same version is already active. `patch_profile` may enable/disable the logical profile but never edits a historical version. Committed import resolves exactly the enabled profile's `active_version_id`; it must not silently pick a draft or merely "latest" row.

- [ ] **Step 5: Run Task 4 tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_store.py -k 'source or profile' --tb=short
```

- [ ] **Step 6: Commit Task 4**

```bash
git add data_ingestion/requirements/store.py tests/test_requirement_store.py
git commit -m "feat: persist requirement sources and profiles"
```

---

### Task 5: Side-effect-free preview and current-version analysis

**Files:**
- Create: `data_ingestion/requirements/service.py`
- Test: `tests/test_requirement_import_service.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `RequirementImportService.preview(source_id, *, profile_version_id=None, upload_bytes=None, upload_filename=None) -> ImportPreview`
  - version classification: `new`, `changed`, `unchanged`, `provenance_only`, `expired`, `stale`, `anomaly`, `removal_candidate`

- [ ] **Step 1: Write failing preview/version-analysis tests**

Create deterministic current-store state and assert:

```python
same UPDT + same source_row_hash -> unchanged
newer UPDT + changed source_payload_hash -> changed
newer UPDT + same source_payload_hash -> unchanged execution/provenance observation
same UPDT + different source_payload_hash -> source_version_anomaly
older UPDT -> stale_source_version
same execution_content_hash + provenance changes -> provenance_only, not executable change
```

Also assert preview does not create RequirementVersion, Snapshot, or active-snapshot updates.

- [ ] **Step 2: Run Task 5 tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_import_service.py -k preview --tb=short
```

- [ ] **Step 3: Implement preview orchestration**

Flow exactly:

```text
load source (preview is allowed before source enablement)
→ resolve profile version: explicit draft/approved version for preview, otherwise profile.active_version_id
→ acquire source
→ parse raw rows
→ normalize/map rows
→ compare against current Requirement versions
→ compute authoritative removals when applicable
→ return diagnostics/counts/candidate metadata
```

If mapping/profile/date/duplicate/stale/anomaly diagnostics include errors, preview returns them but remains non-mutating.

- [ ] **Step 4: Implement duplicate and expiry counts**

Duplicate normalized `external_item_id` in one candidate is `duplicate_external_item_id`. `expires_at <= preview_time` contributes to preview `expired_count`, but Phase 1B still preserves the row/version in the canonical snapshot; expiry affects Phase 1C dispatch eligibility, not historical ingestion.

- [ ] **Step 5: Run Task 5 tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_import_service.py -k preview --tb=short
```

- [ ] **Step 6: Commit Task 5**

```bash
git add data_ingestion/requirements/service.py tests/test_requirement_import_service.py
git commit -m "feat: add requirement import preview"
```

---

### Task 6: Atomic import commit, immutable Requirement versions, and active snapshots

**Files:**
- Modify: `data_ingestion/requirements/store.py`
- Modify: `data_ingestion/requirements/service.py`
- Test: `tests/test_requirement_import_service.py`
- Test: `tests/test_requirement_store.py`

**Interfaces:**
- Produces:
  - `RequirementImportService.commit(...) -> ImportCommitResult`
  - `RequirementStore.commit_candidate(candidate, context) -> ImportCommitResult`
  - `RequirementStore.record_failed_import(...)`
  - snapshot/read APIs for later router task

- [ ] **Step 1: Write RED tests for atomicity and version invariants**

Required cases:

```text
successful authoritative import creates 1 snapshot and activates it
10 valid rows produce 10 snapshot memberships
invalid row creates failed Import Run diagnostics but leaves prior active snapshot unchanged
same-UPDT/different-payload fails and leaves active snapshot unchanged
older-UPDT fails and leaves active snapshot unchanged
missing authoritative item is absent from new snapshot but historical Requirement/Versions remain
upsert_delta carries prior membership forward unless explicitly updated
snapshot binds source_sha256 and exact profile_version_id
```

Add a race test where current RequirementVersion changes between preview and commit; commit must re-evaluate under transaction and fail rather than activate a stale candidate.

- [ ] **Step 2: Run Task 6 tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_import_service.py tests/test_requirement_store.py -k 'commit or snapshot or atomic or stale or anomaly' --tb=short
```

- [ ] **Step 3: Implement failed-import recording separate from activation**

For candidate validation failure, insert an `import_runs` row with `status='failed'` plus `import_run_rows` diagnostics in its own transaction. Do not create/modify RequirementVersion or Snapshot rows.

- [ ] **Step 4: Implement the valid candidate transaction**

Use one SQL transaction and the Design v1 import-run statuses `acquiring`, `validating`, `staged`, `committed`, `failed`:

```text
BEGIN
→ lock/read source + RequirementSet active snapshot
→ re-read/lock each affected logical Requirement/current version
→ re-evaluate stale/same-UPDT anomaly rules
→ create missing logical Requirement rows
→ insert immutable RequirementVersion rows only when a new source version is required
→ create Import Run + accepted row observations
→ create immutable Requirement Set Snapshot
→ create snapshot memberships
→ for upsert_delta merge prior active membership for omitted requirements
→ update requirement_sets.active_snapshot_id
→ mark import_run committed
→ COMMIT
```

Any exception rolls back the whole activation transaction. After rollback, record a failed Import Run only if doing so cannot misrepresent a partially committed candidate.

- [ ] **Step 5: Implement immutable snapshot/query read methods**

Provide:

```python
list_requirement_sets()
list_snapshots(requirement_set_id)
get_snapshot(snapshot_id)
list_snapshot_items(snapshot_id)
get_import_run(import_run_id)
```

Snapshot item responses include the exact `requirement_version_id` and canonical execution fields but never credentials.

- [ ] **Step 6: Run Task 6 tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_import_service.py tests/test_requirement_store.py --tb=short
```

- [ ] **Step 7: Commit Task 6**

```bash
git add data_ingestion/requirements/store.py data_ingestion/requirements/service.py tests/test_requirement_import_service.py tests/test_requirement_store.py
git commit -m "feat: add atomic requirement snapshots"
```

---

### Task 7: Phase 1B management API, RBAC, audit, preview, and commit endpoints

**Files:**
- Create: `sra_api/routers/requirement_models.py`
- Create: `sra_api/routers/requirements.py`
- Modify: `sra_api/main.py`
- Test: `tests/test_requirement_api.py`
- Test: `tests/test_requirement_startup.py`

**Interfaces:**
- Consumes: Task 6 service/store; existing `current_user`, `require_db_operator`, `require_superuser`; existing `append_audit_event`.
- Produces authenticated management API resources for Phase 2 UI and Phase 1C.

- [ ] **Step 1: Write failing HTTP/RBAC tests**

Use FastAPI `TestClient`/dependency overrides consistent with existing tests. Also prove `REQUIREMENT_PIPELINE_ENABLED=false` preserves existing app startup without Requirement DB configuration, while enabled+invalid Requirement DB configuration fails closed. Required matrix:

```text
GET list/detail resources: authenticated user allowed
POST/PATCH source: db_operator+ only
source enabled false may be created by db_operator
source enable true: superuser only
POST/PATCH profile metadata: db_operator+; enabling/disabling profile: superuser only
POST profile version: db_operator+ only
approve profile version / make it active: superuser only
preview: db_operator+ and may explicitly evaluate a draft profile version without activation
import commit: db_operator+ and requires profile.enabled + profile.active_version_id approved
manual source preview/import requires upload file
file_path/sql_query preview/import rejects upload file
unauthenticated -> 401
underprivileged -> 403 with existing RBAC audit
```

Assert API responses never contain `password`, resolved environment secret values, bearer tokens, or connection strings.

- [ ] **Step 2: Run Task 7 tests RED**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_api.py tests/test_requirement_startup.py --tb=short
```

- [ ] **Step 3: Implement request/response models**

Use `extra='forbid'` and explicit source config unions. Do not accept arbitrary SQL text in source requests. Response models expose safe source config, profile metadata/version hashes/status, preview counts/diagnostics, import run status, snapshots, and items.

- [ ] **Step 4: Implement stable domain error to HTTP mapping**

Return machine-readable `detail.code` values from Design v1. Use at least:

```text
400: source_format_invalid, profile_invalid, mapping_missing_required_column, datetime_parse_error, duplicate_external_item_id
403: source_path_outside_allowed_root
404: unknown source/profile/version/import/snapshot IDs
409: stale_source_version, source_version_anomaly
503: source_unavailable, sql_read_error, requirement_pipeline_disabled
500: persistence_error
```

Do not expose raw SQL/ODBC exception strings containing credentials. Preserve safe diagnostic codes/messages for the UI.

- [ ] **Step 5: Implement management endpoints**

Implement resource semantics equivalent to:

```text
GET    /v1/requirement-sources
POST   /v1/requirement-sources
GET    /v1/requirement-sources/{source_id}
PATCH  /v1/requirement-sources/{source_id}

GET    /v1/requirement-import-profiles
POST   /v1/requirement-import-profiles
GET    /v1/requirement-import-profiles/{profile_id}
PATCH  /v1/requirement-import-profiles/{profile_id}
POST   /v1/requirement-import-profiles/{profile_id}/versions
POST   /v1/requirement-import-profiles/{profile_id}/versions/{version_number}/approve

POST   /v1/requirement-sources/{source_id}/preview
POST   /v1/requirement-sources/{source_id}/import
GET    /v1/requirement-import-runs/{import_run_id}

GET    /v1/requirement-sets
GET    /v1/requirement-sets/{requirement_set_id}/snapshots
GET    /v1/requirement-snapshots/{snapshot_id}
GET    /v1/requirement-snapshots/{snapshot_id}/items
```

For manual sources, preview/import accept multipart `UploadFile`. Preview may include an optional `profile_version_id` so a db_operator can review a draft mapping before superuser activation. Commit/import always uses the profile's approved `active_version_id`. For file-path/SQL sources, the adapter acquires data from saved source configuration.

- [ ] **Step 6: Add safe audit events**

Audit at minimum:

```text
requirement.source.created
requirement.source.updated
requirement.profile.created
requirement.profile.version_created
requirement.profile.version_approved
requirement.profile.updated
requirement.import.previewed
requirement.import.committed
requirement.import.failed
```

Audit payloads include IDs, actor, status/counts, and reason codes only; never raw source rows or credentials.

- [ ] **Step 7: Wire router and optional Requirement store initialization into the real app**

Modify the existing `sra_api/main.py` lifespan rather than creating a second app. When `REQUIREMENT_PIPELINE_ENABLED` is false, do not require SQL registry/control-plane settings and leave the rest of SRA behavior unchanged. When true, load the named control-plane connection, initialize/validate schema v1, create `RequirementImportService`, and place it on `app.state`. Initialization/configuration failure must abort startup instead of exposing a partially configured Requirement API. Router dependencies return a clear 503 only for the intentionally disabled feature state.

- [ ] **Step 8: Run Task 7 tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_api.py tests/test_requirement_startup.py --tb=short
```

- [ ] **Step 9: Commit Task 7**

```bash
git add sra_api/routers/requirement_models.py sra_api/routers/requirements.py sra_api/main.py tests/test_requirement_api.py tests/test_requirement_startup.py
git commit -m "feat: add requirement import management api"
```

---

### Task 8: Supplied-workbook-equivalent integration regression

**Files:**
- Create: `tests/test_requirement_integration.py`
- Create: `config/requirements/import_profile.taiwan-investment-security.v1.example.json`

**Interfaces:**
- Consumes: all Phase 1B domain services.
- Produces: deterministic proof of the observed 8-column/10-row contract without committing the user's binary workbook.

- [ ] **Step 1: Write a deterministic 10-row XLSX fixture generator in the test**

Create workbook `工作表1` with exact headers:

```python
headers = [
    "ITEMNO", "TITLE", "CONTENT ", "UPDT", "DeadlineDT",
    "CreateApeno", "UpdateApeno", "CrtDT",
]
```

Generate ten unique `ITEMNO` rows with timezone-naive Excel datetimes and representative creator/updater IDs.

- [ ] **Step 2: Add the example Import Profile JSON**

The checked-in example must map the sample workbook entirely by config and include:

```json
{
  "format": "xlsx",
  "source_timezone": "Asia/Taipei",
  "source_mode": "authoritative_snapshot",
  "worksheet": {
    "name": "工作表1",
    "header_row": 1,
    "first_data_row": 2,
    "trim_headers": true,
    "case_sensitive": false
  },
  "mapping": {
    "external_item_id": {"source": "ITEMNO", "required": true, "transforms": ["trim", "to_text"]},
    "title": {"source": "TITLE", "required": true, "transforms": ["trim", "normalize_whitespace"]},
    "prompt_content": {"source": "CONTENT", "aliases": ["CONTENT "], "required": true, "transforms": ["trim"]},
    "source_updated_at": {"source": "UPDT", "required": true, "type": "datetime", "transforms": ["to_datetime"]},
    "expires_at": {"source": "DeadlineDT", "required": false, "type": "datetime", "transforms": ["empty_to_null", "to_datetime"]},
    "source_created_by": {"source": "CreateApeno", "required": false, "type": "int", "transforms": ["empty_to_null", "to_int"]},
    "source_updated_by": {"source": "UpdateApeno", "required": false, "type": "int", "transforms": ["empty_to_null", "to_int"]},
    "source_created_at": {"source": "CrtDT", "required": true, "type": "datetime", "transforms": ["to_datetime"]}
  }
}
```

- [ ] **Step 3: Assert exact canonical mapping and 10-member snapshot**

The integration test imports through the real profile/parser/service/store seam used by repository tests and asserts:

```text
10 accepted rows
10 snapshot memberships
CONTENT<space> normalized correctly
UPDT/CrtDT persisted UTC-aware
DeadlineDT -> expires_at
CreateApeno/UpdateApeno preserved as provenance IDs
source fingerprint + profile version bound to snapshot
```

Do not branch production code on these header names.

- [ ] **Step 4: Run integration test GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_requirement_integration.py --tb=short
```

- [ ] **Step 5: Commit Task 8**

```bash
git add tests/test_requirement_integration.py config/requirements/import_profile.taiwan-investment-security.v1.example.json
git commit -m "test: cover requirement workbook import"
```

---

### Task 9: Runtime configuration, operations documentation, and API contract memory

**Files:**
- Modify: `.env.example`
- Create: `docs/operations/requirement-import.md`
- Modify: `README.md`
- Modify: `.codex/api_contract.md`
- Modify: `.codex/architecture.md`
- Modify: `.codex/memory.md`
- Modify: `.codex/known_issues.md`
- Modify: `.codex/backlog.md`

**Interfaces:**
- Produces operator/developer instructions; no new runtime behavior.

- [ ] **Step 1: Document non-secret environment configuration**

Add placeholders only:

```dotenv
REQUIREMENT_PIPELINE_ENABLED=false
REQUIREMENT_SQL_REGISTRY_FILE=config/requirements/sql_registry.json
REQUIREMENT_CONTROL_DB_CONNECTION=requirement_control
REQUIREMENT_DB_SCHEMA=sra_requirement
REQUIREMENT_SOURCE_ALLOWED_ROOTS=
```

Document that actual DB server/user/password environment variables are named by the privileged SQL registry and must not be committed.

- [ ] **Step 2: Write operations documentation**

`docs/operations/requirement-import.md` must cover:

```text
source types and allowed-root behavior
creating draft profile versions
superuser approval
manual upload preview/import
file_path and sql_query import
strict snapshot activation
UPDT anomaly/stale semantics
DeadlineDT stored now / dispatched in Phase 1C later
backup requirements
safe diagnostics and secret handling
Phase 1B non-goals
```

- [ ] **Step 3: Update durable project memory**

Record that Requirement SQL is the control plane, Phase 1B never dispatches Report Jobs, and Phase 1C owns schedule policy/Batch Run creation. Remove stale statements only when source proves they are obsolete; archive oversized memory per repository conventions.

- [ ] **Step 4: Run docs/static secret scan**

Use a focused scan that detects actual raw Service Key/credential-looking literals without treating documented environment variable names as secrets.

- [ ] **Step 5: Commit Task 9**

```bash
git add .env.example docs/operations/requirement-import.md README.md .codex
git commit -m "docs: document requirement import operations"
```

---

### Task 10: Repository verification gate and scope guard

**Files:**
- Modify tests only if verification exposes a real regression and the fix remains inside Design v1.

- [ ] **Step 1: Run focused Phase 1B suite**

```bash
PYTHONPATH=. pytest -q \
  tests/test_requirement_profile.py \
  tests/test_requirement_source_adapters.py \
  tests/test_requirement_store.py \
  tests/test_requirement_import_service.py \
  tests/test_requirement_api.py \
  tests/test_requirement_startup.py \
  tests/test_requirement_integration.py \
  --tb=short
```

Expected: 0 failures, 0 errors.

- [ ] **Step 2: Run Phase 1A and Phase 0 regression gates**

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
  tests/test_phase0_security_acceptance.py \
  --tb=short
```

Expected: 0 failures, 0 errors.

- [ ] **Step 3: Run full repository suite**

```bash
PYTHONPATH=. pytest tests -q --tb=short
```

Expected: 0 failures, 0 errors.

- [ ] **Step 4: Run compile/static checks**

```bash
python -m compileall -q data_ingestion/requirements sra_api api tests
git diff --check
```

Also verify no Phase 1B source imports Agent/Elasticsearch/Word/Report Job worker internals:

```bash
rg -n "from (agent|api\.services\.report_job_worker|api\.services\.word_export)|import (agent|elasticsearch)" data_ingestion/requirements sra_api/routers/requirements.py
```

Expected: no prohibited direct execution dependency.

- [ ] **Step 5: Run tracked-secret and source-config scans**

Verify no actual credentials are tracked and no Requirement source/profile sample contains raw `password`, raw bearer/service keys, or connection strings. Do not print matched secret values in the completion report.

- [ ] **Step 6: Commit only if verification required a legitimate fix**

If no changes were needed, do not create an empty commit.

---

### Task 11: Optional live SQL Server Phase 1B deployment acceptance

**Files:** none unless a real deployment issue requires a Plan-v1-consistent fix.

**Interfaces:** validates deployment configuration only; does not execute Agent/ES/Word.

- [ ] **Step 1: Detect whether the Codex/runtime environment has an explicitly authorized Requirement control-plane SQL Server and operator credentials**

Do not infer credentials and do not repurpose unrelated production DB credentials. If unavailable, report `NOT EXECUTED` and continue to the completion report; do not claim PASS or FAIL.

- [ ] **Step 2: If available, initialize the Requirement schema**

Run against an isolated approved test database/schema and verify schema version `1` and required tables/constraints.

- [ ] **Step 3: Exercise the deterministic 10-row workbook through the real management/API or domain deployment path**

Verify preview shows 10 accepted rows and commit activates a 10-member snapshot with exact profile/source fingerprint binding.

- [ ] **Step 4: Exercise fail-closed activation**

Re-run with one invalid datetime and verify the previous active snapshot remains unchanged. Re-run same `UPDT` with changed content and verify `source_version_anomaly` and no activation.

- [ ] **Step 5: Record evidence without exposing secrets**

Report DB/schema name only if non-sensitive, import/snapshot IDs, counts/statuses, and test result. Never print resolved passwords or connection strings.

---

## Plan Completion Criteria

Implementation is repository-complete only when:

1. All Design v1 acceptance criteria map to implemented tests and behavior.
2. The Taiwan 8-column/10-row workbook contract is proven by configuration-driven integration test with no workbook-specific production branch.
3. Profile versions are immutable and explicitly approved before imports use them.
4. Manual/file-path/SQL sources converge on one canonical preview/import service.
5. Same-UPDT anomalies and stale rollbacks fail closed.
6. Failed imports cannot replace active snapshots.
7. Snapshot membership/history semantics work for `authoritative_snapshot` and `upsert_delta`.
8. SQL source/path safety and secret redaction are tested.
9. Management API RBAC follows existing project roles and reviewed-config pattern.
10. Existing Phase 0 and Phase 1A tests remain green.
11. Phase 1B contains no schedule recurrence, due-item selection, Report Job dispatch, Agent execution, Elasticsearch indexing, or Word generation.
12. Live SQL Server acceptance is clearly labeled PASS only if actually executed; otherwise `NOT EXECUTED` is acceptable for repository completion and remains a deployment risk.
