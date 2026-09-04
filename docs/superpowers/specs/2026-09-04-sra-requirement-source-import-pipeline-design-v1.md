# SRA Requirement Source, Versioning & Import Pipeline — Design Specification v1

**Date:** 2026-09-04  
**Repository:** `poc-agent` (repository URL not available from ZIP snapshot)  
**Branch:** not available from ZIP snapshot  
**Commit / baseline:** `poc-agent_20260904-103101.zip` source snapshot. The immediately preceding Codex completion report identified resulting commit `82108d9e32b733084c7b97eff868abc17fe0380e0`, but `.git` metadata is not present in this ZIP, so this design does not independently assert that commit.  
**Reference source sample:** `臺灣投顧公司_指導小組安全風險資訊蒐集要項_模擬資料_10項(1).xlsx`  
**Depends on:** SRA Unified API Security Boundary Design v3; SRA Batch Scheduler Core Design v1; Phase 1A Batch Scheduler repository implementation  
**Supersedes:** none  
**Scope:** Phase 1B — Requirement Source, Versioning & Import Pipeline  
**Next phase dependency:** Phase 1C — Schedule Policy + Batch Management API

## 1. Purpose

Phase 1A created a resumable Batch Scheduler Core that can normalize canonical task files, submit Report Jobs through the existing SRA HTTP API, reconcile remote state, and publish completed DOCX files locally.

Phase 1B moves one level upstream. Its purpose is to make recurring report production independent of a human repeatedly uploading the same spreadsheet. A requirement list may be maintained externally and updated over time; the system must be able to fetch that source automatically, interpret changing source schemas through a versioned import profile, persist an authoritative and auditable canonical requirement history in SQL, and expose an immutable requirement-set snapshot that Phase 1C can schedule repeatedly.

The central design principle is:

```text
External source format
        ↓
Source Adapter
        ↓
Versioned Import Profile
        ↓
Staging + validation
        ↓
Canonical Requirement SQL Store
        ↓
Immutable active Requirement Set Snapshot
        ↓
Phase 1C schedule / batch-run creation
        ↓
Phase 1A Batch Scheduler Core
        ↓
SRA Report Job API → Router → Elasticsearch → Agent → Word
```

The Web UI is an operator surface over these services; it is not the automation engine and must not be required for recurring execution.

## 2. Observed sample source schema

The supplied simulation workbook contains one worksheet, `工作表1`, with 10 data rows and these eight source columns:

```text
ITEMNO
TITLE
CONTENT 
UPDT
DeadlineDT
CreateApeno
UpdateApeno
CrtDT
```

`CONTENT ` contains a trailing space in the actual header. This is deliberate evidence that the importer must normalize headers before semantic mapping rather than hard-code exact spreadsheet labels.

The source-field semantics supplied by the project owner are:

- `ITEMNO`: stable source-side requirement identifier.
- `TITLE`: requirement title.
- `CONTENT`: requirement text / Agent prompt body.
- `UPDT`: source last-update datetime.
- `DeadlineDT`: requirement validity deadline; after expiration it must not be newly dispatched.
- `CreateApeno`: creator personnel sequence ID.
- `UpdateApeno`: last updater personnel sequence ID.
- `CrtDT`: source creation datetime.

The sample is an input contract example, not a hard-coded application schema. Future sources may rename, split, combine, add, or remove columns.

## 3. Roadmap position

The active roadmap is refined as follows:

1. **Phase 0 — Unified Security Boundary**: repository gate and real Service Key → SRA → Elasticsearch → long Agent → Word E2E passed.
2. **Phase 1A — Batch Scheduler Core**: repository implementation present; HTTP-only execution boundary preserved.
3. **Phase 1B — Requirement Source, Versioning & Import Pipeline**: this design.
4. **Phase 1C — Schedule Policy + Batch Management API**: recurring schedules, due-item selection, batch-run lifecycle, task/result APIs, Word history links.
5. **Phase 2 — Server Web UI**: operators manage sources, profiles, schedules, runs, failures, and downloads through the Phase 1B/1C APIs.
6. **Phase 3 — Windows GUI / Operator Client**.
7. **Phase 4 — Operations / hardening / scale-out**.

This phase must not reimplement the Agent, Elasticsearch retrieval, Word rendering, Report Job worker, or Phase 1A execution state machine.

## 4. Architectural decision

### 4.1 SQL is the authoritative Requirement control-plane store

Requirement sources, import-profile versions, requirement versions, snapshots, and import audit history are control-plane data. They belong in SQL, not Elasticsearch. The production target for Phase 1B is the project's existing SQL Server/ODBC deployment pattern, in a dedicated Requirement schema/database chosen by deployment configuration; it is not the Phase 1A local SQLite file.

Elasticsearch remains the Agent retrieval plane for news, reports, structured events, and other evidence. Requirement data may be projected into Elasticsearch in a future phase if semantic search over very large requirement libraries becomes necessary, but Elasticsearch is not a Phase 1B dependency for requirement identity or scheduling correctness.

```text
               Control Plane
Excel / SQL / file path
        ↓
Requirement SQL Store ──→ Phase 1C Scheduler
                              ↓
                         Phase 1A Core
                              ↓
                           SRA API
                              ↓
                    Elasticsearch / Agent
               Retrieval / Execution Plane
```

### 4.2 Reuse the existing configuration-driven ingestion philosophy

The repository already has `data_ingestion/excel_to_sql/` and configuration examples under `config/excel_to_sql/` supporting configurable source location, sheet/header selection, source-to-destination mappings, type conversion, header matching, hashing, retry, archive, audit, and operator review.

Phase 1B should reuse safe, generic parsing concepts and small shared helpers where appropriate, especially:

- header trimming / normalization;
- exact / normalized / prefix / contains matching;
- date/datetime normalization;
- deterministic row hashing;
- safe config review/redaction patterns.

It must not make the Requirement domain depend on a generic auto-create-table importer. Requirement tables have fixed migrations, invariants, foreign keys, and version semantics. The Requirement importer therefore owns its domain schema and transactions.

### 4.3 Source acquisition, schema interpretation, and scheduling are separate responsibilities

A source says **where bytes/rows come from**. An import profile says **how rows become canonical requirements**. A schedule says **when an active snapshot should be turned into a new Batch Run**.

Changing an Excel column name must require an Import Profile change, not Scheduler code. Changing a weekly job to daily must require a Schedule change, not an Import Profile change.

## 5. Source model

### 5.1 Supported Phase 1B source types

Phase 1B supports these source adapters:

1. `manual_upload` — operator uploads `.xlsx`, `.csv`, or `.json` through an authenticated management API.
2. `file_path` — importer reads a configured local path, UNC path, or mounted network share.
3. `sql_query` — importer reads a configured read-only SQL source using a named connection reference and a reviewed query/view definition.

Phase 1B does not require S3/object storage, HTTP scraping, Google Drive, SharePoint, or message queues. Those can be added as adapters later without changing the canonical store.

### 5.2 Source configuration

Minimum canonical source fields:

```text
source_id
name
source_type
source_config_json
import_profile_id
enabled
created_by
created_at
updated_by
updated_at
```

`source_config_json` contains only non-secret adapter configuration such as path, file pattern, worksheet, SQL view/query identifier, or format hints.

Database passwords, tokens, and network secrets must not be embedded in the Import Profile or source row. SQL-backed sources reference a named connection whose secret material is supplied through the project's protected runtime configuration / environment mechanism.

### 5.3 Source modes

Every source declares one of two membership modes:

- `authoritative_snapshot`: each successful import is the complete current requirement list. Items absent from the new source are absent from the new active snapshot, but historical Requirement and RequirementVersion rows are retained.
- `upsert_delta`: imported rows add/update requirements but omission does not remove existing active membership. This mode is appropriate only for sources that explicitly deliver deltas.

Spreadsheet lists are `authoritative_snapshot` by default.

## 6. Import Profile model

### 6.1 Profiles are versioned and immutable once used

A logical `import_profile` has one or more immutable `import_profile_versions`.

Editing a mapping creates version `N+1`; it never mutates version `N` after an Import Run references it. Historical runs therefore remain reproducible.

Minimum fields:

```text
import_profiles
  profile_id
  name
  description
  enabled
  created_by
  created_at

import_profile_versions
  profile_version_id
  profile_id
  version_number
  format
  profile_json
  profile_sha256
  created_by
  created_at
  retired_at
```

### 6.2 Header and field mapping grammar

The profile may define:

- worksheet/table selector;
- header row and first data row;
- `trim_headers`;
- case-sensitive or case-insensitive matching;
- source-column aliases;
- match mode: `exact`, `normalized`, `prefix`, `contains`;
- required/optional fields;
- canonical type: `text`, `int`, `datetime`, `bool`, `json`;
- safe transforms from an allowlist;
- default values;
- composed/template fields;
- source timezone;
- source membership mode.

Phase 1B must not support arbitrary Python, arbitrary expression evaluation, shell commands, or unreviewed SQL fragments inside mapping transforms.

### 6.3 Minimum safe transform allowlist

The first version should support only deterministic transforms required by known data:

```text
trim
normalize_whitespace
empty_to_null
to_text
to_int
to_datetime
```

Additional transforms require explicit implementation and tests. Prompt templates may compose already-mapped fields but may not execute code.

### 6.4 Sample profile for the supplied workbook

The supplied workbook should be representable by a profile with semantics equivalent to:

```yaml
profile_id: taiwan-investment-security-requirements
version: 1
format: xlsx
source_timezone: Asia/Taipei
source_mode: authoritative_snapshot

worksheet:
  name: 工作表1
  header_row: 1
  first_data_row: 2
  trim_headers: true
  case_sensitive: false

mapping:
  external_item_id:
    source: ITEMNO
    required: true
    transforms: [trim, to_text]

  title:
    source: TITLE
    required: true
    transforms: [trim, normalize_whitespace]

  prompt_content:
    source: CONTENT
    aliases: ["CONTENT "]
    required: true
    transforms: [trim]

  source_updated_at:
    source: UPDT
    required: true
    type: datetime

  expires_at:
    source: DeadlineDT
    required: false
    type: datetime

  source_created_by:
    source: CreateApeno
    required: false
    type: int

  source_updated_by:
    source: UpdateApeno
    required: false
    type: int

  source_created_at:
    source: CrtDT
    required: true
    type: datetime
```

This is documentation of the intended config grammar; it is not a runtime config file created by this design step.

## 7. Canonical Requirement model

### 7.1 Stable identity

The stable logical identity is scoped by source:

```text
(source_id, external_item_id)
```

`ITEMNO` maps to `external_item_id` for the supplied source.

A logical Requirement is not duplicated every time its content changes. Instead, changes produce immutable RequirementVersion rows.

### 7.2 Canonical fields

Minimum `requirements` fields:

```text
requirement_id
source_id
external_item_id
created_at
```

Minimum `requirement_versions` fields:

```text
requirement_version_id
requirement_id
version_number
title
prompt_content
source_updated_at
expires_at
source_created_by
source_updated_by
source_created_at
source_row_hash
execution_content_hash
source_raw_json
created_at
```

`source_raw_json` retains the normalized source-row evidence necessary to explain how the version was produced; it must not contain source-connection credentials.

### 7.3 Two hashes serve different purposes

`source_row_hash` hashes the complete normalized mapped source row used for audit/version anomaly detection.

`execution_content_hash` hashes only fields that affect execution semantics, initially:

```text
title
prompt_content
expires_at
```

This distinction allows the system to record provenance-only changes such as `UpdateApeno` without pretending the Agent prompt changed.

## 8. Datetime and deadline semantics

### 8.1 Canonical timezone

Source spreadsheets commonly contain timezone-naive Excel datetimes. The Import Profile therefore requires `source_timezone` for datetime-bearing sources; the supplied profile uses `Asia/Taipei`.

The importer:

1. parses Excel/CSV/JSON datetime values according to the profile;
2. interprets naive values in `source_timezone`;
3. converts them to timezone-aware canonical values;
4. persists canonical UTC timestamps while retaining source raw values in provenance JSON.

A datetime that cannot be interpreted unambiguously is a validation error. It is not guessed from server local time.

### 8.2 `UPDT` semantics

`UPDT` maps to `source_updated_at` and is the source-side version timestamp.

For the same `(source_id, external_item_id)`:

- same `source_updated_at` + same `source_row_hash` → idempotent no-op;
- newer `source_updated_at` + changed row → create a new RequirementVersion;
- newer `source_updated_at` + same row → provenance update may be recorded as a new import observation, but a new executable RequirementVersion is not required;
- older `source_updated_at` than the current source version → stale-source anomaly; do not roll the active version backward;
- same `source_updated_at` + different `source_row_hash` → `source_version_anomaly`; do not silently overwrite.

### 8.3 `DeadlineDT` semantics

`DeadlineDT` maps to `expires_at`.

Phase 1B stores and validates it. Phase 1C consumes it as a dispatch eligibility gate:

```text
expires_at is NULL OR expires_at > dispatch_check_time
    => eligible

expires_at <= dispatch_check_time
    => expired / skipped; do not create a new Report Job
```

Eligibility is checked both when selecting run items and immediately before remote submission.

If a Report Job was already successfully created before the deadline and the deadline passes while the long Agent is running, Phase 1C does not cancel that already-dispatched job solely because the deadline elapsed. The run item records that the deadline elapsed during execution.

## 9. Import pipeline and atomic activation

### 9.1 Pipeline

Every import follows:

```text
Acquire source
    ↓
Capture source fingerprint / metadata
    ↓
Parse rows
    ↓
Normalize headers
    ↓
Apply Import Profile Version
    ↓
Convert datatypes
    ↓
Validate identity / datetime / required fields
    ↓
Compute hashes
    ↓
Stage all rows
    ↓
Detect duplicates / stale versions / version anomalies
    ↓
Build candidate Requirement Set Snapshot
    ↓
Atomic commit + active-snapshot switch
```

### 9.2 No partially active snapshots

The default Phase 1B policy is strict snapshot activation.

If an authoritative import contains an invalid required field, duplicate identity, unparseable required datetime, stale rollback, or source-version anomaly, the new snapshot is not activated. The prior active snapshot remains current and safe for recurring automation.

The Import Run records row-level diagnostics so an operator can repair the source/profile and retry.

Phase 1B does not implement a configurable partial-activation mode. That can be reconsidered only with a concrete operational need.

### 9.3 Duplicate identities

Two rows in one candidate authoritative snapshot with the same normalized `external_item_id` are an import failure. The importer must not silently pick first/last.

### 9.4 Missing-row behavior

For `authoritative_snapshot`, a previously active requirement omitted from a newly activated snapshot simply loses membership in the new snapshot. Its Requirement and RequirementVersion history are never deleted.

For `upsert_delta`, omission has no membership-removal meaning.

## 10. Requirement Set Snapshot model

Each successful import activates one immutable snapshot.

Minimum fields:

```text
requirement_sets
  requirement_set_id
  source_id
  name
  active_snapshot_id
  created_at

requirement_set_snapshots
  snapshot_id
  requirement_set_id
  import_run_id
  source_snapshot_sha256
  import_profile_version_id
  created_at
  activated_at

requirement_snapshot_items
  snapshot_id
  requirement_id
  requirement_version_id
  source_order
  PRIMARY KEY(snapshot_id, requirement_id)
```

A future Batch Run must reference the exact `snapshot_id` used. It must not depend on whatever requirement versions happen to be current later.

## 11. Import Run and provenance model

Minimum fields:

```text
import_runs
  import_run_id
  source_id
  import_profile_version_id
  source_uri_display
  source_sha256
  status
  row_count
  accepted_count
  rejected_count
  started_at
  completed_at
  actor_kind
  actor_id
  error_summary

import_run_rows
  import_run_id
  source_row_number
  external_item_id
  row_status
  source_row_hash
  diagnostic_code
  diagnostic_message
```

`source_uri_display` is a safe display value; secrets are never persisted in URI query strings or audit records.

Suggested statuses:

```text
acquiring
validating
staged
committed
failed
```

## 12. Management API boundary for Phase 1B

Phase 1B exposes operator-management endpoints needed by the later Web UI. These endpoints manage sources, profiles, imports, and canonical snapshots; they do not create Agent Report Jobs.

Recommended resource shape:

```text
GET    /v1/requirement-sources
POST   /v1/requirement-sources
GET    /v1/requirement-sources/{source_id}
PATCH  /v1/requirement-sources/{source_id}

GET    /v1/requirement-import-profiles
POST   /v1/requirement-import-profiles
GET    /v1/requirement-import-profiles/{profile_id}
POST   /v1/requirement-import-profiles/{profile_id}/versions

POST   /v1/requirement-imports/upload
POST   /v1/requirement-sources/{source_id}/preview
POST   /v1/requirement-sources/{source_id}/import
GET    /v1/requirement-import-runs/{import_run_id}

GET    /v1/requirement-sets
GET    /v1/requirement-sets/{requirement_set_id}/snapshots
GET    /v1/requirement-snapshots/{snapshot_id}
GET    /v1/requirement-snapshots/{snapshot_id}/items
```

Exact endpoint naming may follow current router conventions during implementation, but resource semantics and security boundaries are fixed by this design.

Manual upload is one Source Adapter invocation, not a special execution path. A Web UI upload and a scheduled UNC-path import must produce the same staged canonical model and snapshot semantics.

## 13. Security and authorization

### 13.1 Human management access

Source/profile creation or modification changes what future automated reports will execute and is therefore privileged control-plane configuration.

Management writes require authenticated authorized operator/editor roles under the existing application RBAC. Profile approval/enabling should follow the existing reviewed-config pattern used by Excel→SQL task configuration rather than allowing any authenticated user to activate arbitrary mappings.

Read-only dashboard views may be available to broader authenticated roles according to existing RBAC policy.

### 13.2 SQL source safety

`sql_query` sources are admin-managed and read-only.

Phase 1B must not accept arbitrary SQL text from an unprivileged end user and execute it with a privileged database connection. Prefer reviewed views or saved query definitions. If parameterized SELECT text is supported, it is stored in privileged source configuration and validated against the configured read-only connection policy.

### 13.3 Path safety

`file_path` sources are read-only acquisition targets. Path configuration must be subject to an allowed-root policy when server-side local paths are used. Manual upload storage uses server-generated names; user filenames are metadata only and cannot select arbitrary server destinations.

### 13.4 Secret hygiene

Import profiles, source rows, snapshot metadata, logs, and API responses must not expose database passwords, bearer keys, connection-string secrets, or credential digests. Existing redaction helpers should be reused where they fit.

## 14. Integration with Phase 1A Batch Scheduler

Phase 1B does not submit Report Jobs itself.

Phase 1C will select eligible items from a specific active snapshot and translate each selected RequirementVersion to Phase 1A's `BatchTaskSpec` semantics:

```text
task_id      = external_item_id within that batch
prompt       = prompt_content
filename     = sanitized title/external_item_id derived filename
session_id   = stable run/task-specific session identity
model        = configured/default SRA report model
scheduled_at = null when passed to the already-triggered batch
metadata     = {
  requirement_id,
  requirement_version_id,
  requirement_set_id,
  snapshot_id,
  source_id,
  import_profile_version_id,
  source_updated_at,
  expires_at
}
```

The Batch Run owns execution history. RequirementVersion history is never overwritten with the latest Word result.

## 15. Phase 1C scheduling contract prepared by this design

Phase 1B persists the data required for these Phase 1C run policies:

- `all_active`: every schedule occurrence reruns all non-expired requirements in the chosen snapshot even when `UPDT` is unchanged. This is the default for continuously refreshed intelligence requirements.
- `new_or_changed`: run requirements that have never completed successfully or whose active RequirementVersion changed since the last successful run.
- `changed_only`: run only requirements whose executable RequirementVersion changed.

The policy itself belongs to Phase 1C; Phase 1B must not embed recurrence logic into import profiles.

## 16. API/UI preview behavior

Before activating a new source/profile combination, operators should be able to preview:

- detected worksheet/table;
- normalized headers;
- resolved mapping for every canonical field;
- source row count;
- candidate new / changed / unchanged / expired counts;
- rows with mapping or datetime errors;
- stale-version anomalies;
- same-UPDT/different-hash anomalies;
- candidate removals for `authoritative_snapshot`.

Preview is side-effect free. Only explicit import/activation commits a new snapshot.

The Phase 2 Web UI can render this preview without reimplementing parsing logic in JavaScript.

## 17. Error handling

Failures are classified so automation can distinguish operator repair from transient infrastructure failure:

```text
source_unavailable
source_format_invalid
profile_invalid
mapping_missing_required_column
datetime_parse_error
duplicate_external_item_id
stale_source_version
source_version_anomaly
sql_read_error
persistence_error
```

Transient source/SQL acquisition failures may be retried by the caller according to bounded policy. Mapping, duplicate, stale-version, and anomaly failures are not blindly retried; they require source/profile correction or explicit operator action.

No failure path activates a partial candidate snapshot.

## 18. Migration and deployment boundary

Requirement control-plane tables use explicit schema versioning/migrations from their first implementation. Do not use generic `auto_create_missing_fields` behavior for these tables.

Development/test environments may use an isolated test database where practical, but production is a shared server-side SQL store suitable for Phase 2 Web UI and Phase 1C scheduler access. The Phase 1A local SQLite database remains separate and continues to hold scheduler execution transport state only.

Backups must include Requirement tables and Import Profile history because active automation cannot be reconstructed faithfully from current Excel alone once sources change over time.

## 19. Testing strategy

Phase 1B implementation must add tests at these layers.

### 19.1 Profile and normalization tests

- trailing-space header `CONTENT ` maps to `prompt_content` after normalization;
- alias/match modes resolve deterministically;
- duplicate normalized headers fail closed when ambiguous;
- required fields fail before activation;
- unsupported transforms/config fields fail closed;
- naive Excel datetimes use configured `source_timezone`;
- invalid datetime does not fall back to server local time.

### 19.2 Versioning tests

For one `(source_id, external_item_id)`:

- same UPDT + same hash → no new active version;
- newer UPDT + changed content → new version;
- same UPDT + changed hash → anomaly and no activation;
- older UPDT → stale rollback rejection;
- provenance-only change does not falsely report executable content change.

### 19.3 Snapshot tests

- successful authoritative import creates immutable snapshot;
- missing item is absent only from the new snapshot, not deleted historically;
- any invalid row prevents active-snapshot switch;
- failed import leaves previous active snapshot unchanged;
- profile version and source fingerprint are bound to snapshot.

### 19.4 Source-adapter tests

- manual XLSX/CSV/JSON and path-based source normalize through the same domain service;
- SQL adapter is read-only and uses a named connection reference;
- path source cannot escape allowed roots;
- secrets are redacted from API/log representations.

### 19.5 Integration tests

Use the supplied 10-row simulation workbook as a fixture or generate an equivalent deterministic workbook in tests. Assert the exact canonical mapping of `ITEMNO`, `TITLE`, `CONTENT`, `UPDT`, `DeadlineDT`, `CreateApeno`, `UpdateApeno`, and `CrtDT` and confirm the resulting active snapshot contains 10 requirement memberships.

No Phase 1B test may mock away its own mapping/version/snapshot logic. Elasticsearch and long Agent execution are outside this phase and remain covered by Phase 0/1A/1C acceptance paths.

## 20. Acceptance criteria

Phase 1B repository implementation is acceptable only when all of the following hold:

1. The supplied sample workbook imports through a versioned profile without hard-coded workbook-specific Python logic.
2. `CONTENT ` header normalization is proven by regression test.
3. The canonical store preserves stable requirement identity and immutable versions.
4. `UPDT` stale/same-timestamp anomaly rules are enforced.
5. `DeadlineDT` is normalized to `expires_at` and is available for Phase 1C eligibility checks.
6. Creator/updater/source-created audit fields are preserved without becoming authorization identities.
7. Import is staged and a new active snapshot is switched atomically only after full validation.
8. Authoritative-snapshot omission does not delete history.
9. Import Profile versions are immutable once referenced by an Import Run.
10. Manual upload, file-path acquisition, and SQL-query acquisition converge on the same canonical import service.
11. Source/profile secrets are never persisted into requirement rows, logs, or API responses.
12. Existing Phase 0 security and Phase 1A Batch Scheduler tests remain passing.
13. API preview and commit paths return enough diagnostics for Phase 2 Web UI without duplicating parsing logic client-side.
14. No Report Job, Agent, Elasticsearch, or Word execution logic is duplicated inside Phase 1B.

## 21. Non-goals

Phase 1B deliberately does not implement:

- cron/recurrence scheduling;
- `all_active` / `new_or_changed` / `changed_only` execution selection;
- Batch Run creation;
- Agent Report Job dispatch;
- Word result-history APIs;
- final operator dashboard pages;
- Windows GUI;
- Elasticsearch indexing of Requirement control data;
- arbitrary user-defined code transforms;
- partial snapshot activation.

Those boundaries keep Phase 1B focused on trustworthy source acquisition, schema adaptation, versioning, and canonical persistence.

## 22. Design rationale and rejected alternatives

### Alternative A — Web UI upload directly creates Batch Tasks

Rejected as the primary architecture. It is simple for one-off use but requires a person to re-upload on every daily/weekly run and couples automation to the browser. It also makes historical source/profile reproduction weaker.

### Alternative B — Scheduler reads Excel directly every time

Rejected as the canonical architecture. It automates file access but leaves schema mapping, identity/version history, missing-row semantics, and audit state inside the scheduler. A future format change would then risk execution logic.

### Alternative C — Source → versioned Import Profile → SQL snapshot → Scheduler

**Selected.** It separates source format from execution, supports recurring unattended operation, provides immutable historical evidence, reuses the project's existing configuration-driven ingestion philosophy, and gives Phase 2 Web UI a stable API-backed control plane.

## 23. Design invariants

The following are blocking invariants for later implementation review:

1. No browser action is required for a previously configured recurring source to be imported again.
2. No source-specific column name is hard-coded into core Requirement logic.
3. An Import Profile change never rewrites the historical profile version used by an old run.
4. A failed candidate import never replaces the previous active snapshot.
5. A same-UPDT/different-content row is never silently accepted as an ordinary update.
6. An expired requirement is never newly dispatched by Phase 1C after `expires_at <= dispatch_check_time`.
7. Requirement SQL is the control-plane source of truth; Elasticsearch is not required for requirement identity/version state.
8. Requirement ingestion does not bypass Phase 1A/SRA Report Job HTTP boundaries to execute Agents directly.
9. Raw credentials never enter Import Profile JSON, Requirement rows, source provenance, logs, or API responses.
10. Every Batch Run in Phase 1C will be able to name the exact Requirement Set Snapshot and Import Profile Version from which it was produced.
