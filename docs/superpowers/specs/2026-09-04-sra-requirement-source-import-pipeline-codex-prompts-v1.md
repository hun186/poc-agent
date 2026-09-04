# Codex Prompt — Phase 1B Requirement Source, Versioning & Import Pipeline Implementation Contract v1

You are implementing **Phase 1B — Requirement Source, Versioning & Import Pipeline** in the `poc-agent` repository.

This prompt is an execution contract. Do not redesign the system unless actual source proves a blocking incompatibility. If a non-blocking source/path detail differs from the plan, adapt minimally to the current repository while preserving Design v1 invariants.

## Authoritative artifacts

Read these before changing code:

1. `docs/superpowers/specs/2026-09-04-sra-requirement-source-import-pipeline-design-v1.md`
2. `docs/superpowers/plans/2026-09-04-sra-requirement-source-import-pipeline-plan-v1.md`
3. `docs/superpowers/specs/2026-09-04-sra-batch-scheduler-core-design-v1.md`
4. `docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md`
5. Current `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/memory.md`, `.codex/known_issues.md`, `.codex/backlog.md`

**Design version:** Phase 1B Design v1  
**Plan version:** Phase 1B Implementation Plan v1  
**Supersedes:** none  
**Planning source snapshot:** `poc-agent_20260904-103101.zip`  
**Historical Phase 1A report:** previously identified resulting commit `82108d9e32b733084c7b97eff868abc17fe0380e0`; do **not** assert or fabricate this commit if the actual repository says otherwise.

## Mandatory repository preflight

Before implementation, inspect the actual repository and report internally/at completion:

```bash
pwd
git status --short
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
```

Also inspect the actual current versions of:

```text
batch_scheduler/
data_ingestion/excel_to_sql/
sra_api/routers/excel_to_sql.py
sra_api/routers/editor_dependencies.py
sra_api/main.py
requirements.txt
tests/
```

The actual source tree is authoritative for exact paths/function names. Do not follow a stale plan path blindly. If source moved, use the current equivalent and record the deviation. Do not invent a Git remote, PR, branch, or commit.

## Required implementation method

Use TDD task-by-task. Follow the Plan v1 task order unless source dependencies require a small reorder. For each task:

```text
write focused failing test
→ run and observe expected RED
→ implement minimum Design-v1 behavior
→ rerun focused test GREEN
→ run nearby regression tests
→ commit the coherent task when the environment supports commits
```

Do not weaken validation, transactionality, authorization, audit, path confinement, secret handling, or fail-closed behavior just to make tests pass.

## Non-negotiable architecture

Implement this flow:

```text
manual upload / file path / named SQL query
        ↓
Source Adapter
        ↓
approved immutable Import Profile Version
        ↓
strict mapping + datetime normalization + deterministic hashes
        ↓
staging/version analysis
        ↓
SQL Server Requirement control-plane store
        ↓
immutable active Requirement Set Snapshot
        ↓
Phase 1C later
```

Do **not** implement or duplicate:

```text
cron/recurrence
all_active/new_or_changed/changed_only selection
Batch Run creation
Report Job submission
Agent execution
Elasticsearch retrieval/indexing for Requirement state
Word generation/download history
Phase 2 Web UI
Windows GUI
```

Do not make Phase 1B call Agent, Elasticsearch, Report Job worker, or Word internals. Preserve the Phase 1A HTTP-only execution boundary.

## Blocking invariants

Treat these as implementation-review blockers:

1. No browser action is required to re-import a previously configured file-path/SQL source.
2. No Taiwan/sample source column name is hard-coded into Requirement core logic.
3. Import Profile Versions are immutable. Changed mapping = new version.
4. Imports use only an explicitly approved profile version; draft versions do not silently become active.
5. A failed candidate import never switches the active snapshot.
6. Same `UPDT` + different source payload is `source_version_anomaly` and does not activate.
7. Older `UPDT` is `stale_source_version` and does not roll active state backward.
8. `DeadlineDT` is normalized into `expires_at`; this phase stores it but does not implement recurring dispatch.
9. SQL Server is Requirement control-plane source of truth; Phase 1A SQLite and Elasticsearch are not.
10. Raw DB passwords, bearer/service keys, connection strings, credential digests, or resolved secret env values never enter profile JSON, source rows, provenance, logs, audit payloads, or API responses.
11. `file_path` acquisition cannot escape configured allowed roots.
12. `sql_query` uses privileged named connection/query references; API callers cannot submit executable arbitrary SQL.
13. Manual upload filenames are metadata only; they do not select server paths.
14. Preview does not mutate RequirementVersion/Snapshot/active membership.
15. Every snapshot stores exact source fingerprint and exact Import Profile Version.
16. Authoritative omission changes only new snapshot membership; historical Requirement/Version rows remain.
17. Existing Phase 0 security and Phase 1A Batch Scheduler behavior remains intact.
18. `REQUIREMENT_PIPELINE_ENABLED=false` must preserve existing SRA startup without Requirement SQL config; when enabled, invalid Requirement control-plane configuration/schema initialization fails closed at startup.

## Hash semantics required for Design §8.2

Implement:

```text
source_row_hash        = full normalized mapped row including source_updated_at
source_payload_hash    = same normalized mapped row excluding source_updated_at
execution_content_hash = title + prompt_content + expires_at
```

Persist `source_payload_hash` as an implementation support field. Use it to distinguish source clock-only changes/provenance-only changes from actual source payload changes without weakening the required forensic `source_row_hash`.

## Required source/profile security model

Follow the existing reviewed-config RBAC style:

```text
read-only list/detail                authenticated current_user
create/update source                 db_operator+
create/patch profile metadata       db_operator+
create new profile version           db_operator+
approve/make profile version active  superuser only
enable/disable profile               superuser only
enable a source                      superuser only
preview                              db_operator+; may select a draft profile version
import commit                        db_operator+; uses enabled profile.active_version_id
```

Use existing RBAC dependencies/audit patterns. Underprivileged access must remain 403; unauthenticated access 401. Do not create a parallel auth system.

Source configuration accepted by the API must be constrained by source type:

```text
manual_upload → non-secret format/display options only
file_path     → approved path/file options only
sql_query     → connection_ref + query_ref only
```

Reject source configuration containing raw password/token/authorization/connection-string or executable raw SQL fields. `file_path` directory+pattern acquisition must resolve to exactly one file or fail closed. If source/profile `source_mode` values disagree, fail with `profile_invalid`.

## SQL Server store requirements

Use explicit migration/schema versioning from v1. Do not use the generic Excel→SQL auto-create-table path for Requirement domain tables.

The v1 schema must cover at least:

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

Add the supporting fields required by Plan v1: source mode, `import_profiles.enabled`, explicit `import_profiles.active_version_id`, profile-version approval status/audit, and `source_payload_hash`. Preserve import-run statuses `acquiring`, `validating`, `staged`, `committed`, `failed`.

For a valid candidate, active snapshot creation must be one transaction:

```text
lock/re-read source/current versions
→ re-evaluate stale/anomaly rules
→ create missing Requirements
→ insert immutable RequirementVersions as needed
→ record accepted Import Run/rows
→ create Snapshot + SnapshotItems
→ merge prior membership for upsert_delta only
→ switch active_snapshot_id
→ mark import committed
→ commit
```

Any error rolls back activation. Failed validation/import diagnostics may be recorded separately, but must not create a partially active candidate.

## Required Phase 1B management API

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

Exact naming may adapt to existing router conventions only if semantics remain equivalent and you record the deviation.

Wire the Requirement store into the existing FastAPI lifespan behind `REQUIREMENT_PIPELINE_ENABLED`. Disabled mode must not require Requirement DB settings; enabled mode must initialize/validate schema v1 and fail startup on invalid configuration.

Manual sources use multipart upload on preview/import. Preview may explicitly name a draft `profile_version_id` for operator review and must remain side-effect free. Committed import must use the logical profile's explicit approved `active_version_id`; never silently choose the newest draft. File-path and SQL sources acquire from saved source configuration. All three converge on the same domain service.

## Taiwan simulation workbook regression contract

Do not commit the user's binary workbook unless it is already intentionally tracked. Create a deterministic XLSX test fixture with worksheet `工作表1`, 10 rows, and exact headers:

```text
ITEMNO
TITLE
CONTENT<one trailing space>
UPDT
DeadlineDT
CreateApeno
UpdateApeno
CrtDT
```

Check in an example Import Profile under `config/requirements/` that maps these fields through configuration. Prove:

```text
10 accepted rows
10 active snapshot memberships
CONTENT trailing-space header normalized
UPDT/CrtDT -> UTC-aware canonical timestamps
DeadlineDT -> expires_at
CreateApeno/UpdateApeno preserved as provenance IDs
snapshot binds exact profile version + source fingerprint
```

No production `if header == "ITEMNO"` / workbook-specific mapping branch is allowed.

## Required tests and verification

Run the exact focused suite from Plan v1, then existing Phase 1A/Phase 0 regressions, then full repository tests.

Minimum final verification:

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

PYTHONPATH=. pytest tests -q --tb=short
python -m compileall -q data_ingestion/requirements sra_api api tests
git diff --check
```

Run a scope guard confirming Phase 1B does not import direct Agent/ES/Word/Report Job worker execution dependencies. Run credential scans without printing any secret value.

If a required test fails because the actual source reveals a real defect, fix the defect within Design v1, add/retain the regression test, and rerun. Do not delete/relax tests simply to get GREEN.

## Live deployment acceptance

A real SQL Server Requirement-store smoke is desirable but requires an explicitly authorized control-plane database and credentials.

If the environment cannot reach or is not authorized for the actual SQL Server:

```text
Live SQL Server Phase 1B acceptance: NOT EXECUTED
```

This is not a repository test failure. Do not substitute a mock and call it real acceptance. Do not repurpose unrelated credentials. Do not claim PASS without execution evidence.

If live access is available, verify schema v1, 10-row snapshot import, invalid-row fail-closed behavior, and same-UPDT/different-content anomaly behavior. Do not run Agent/ES/Word as part of Phase 1B acceptance.

## Documentation and durable memory

Update:

```text
.env.example
docs/operations/requirement-import.md
README.md
.codex/api_contract.md
.codex/architecture.md
.codex/memory.md
.codex/known_issues.md
.codex/backlog.md
```

Keep `.codex` facts consistent with actual test counts and actual deployment evidence. Do not carry forward stale “missing document” or old test-count statements as current facts.

## Completion report contract

At the end, report:

```text
Repository
Branch
Baseline commit
Resulting commit
Design version
Plan version
Working-tree status
Changed files
Behavior changes
Exact focused test command + pass/fail/error counts
Exact Phase 0/1A regression command + counts
Exact full-suite command + counts
compileall result
git diff --check result
scope/import guard result
tracked-secret scan result
live SQL Server acceptance: PASS / FAIL / NOT EXECUTED
Deviations from Plan v1
Remaining issues/risks
PR status
```

For every deviation, state why it was necessary and whether it changes Design v1. Do not invent a PR if no remote/integration exists.

A repository PASS statement is allowed only after fresh verification. A deployment PASS statement is allowed only if the real SQL Server acceptance was actually executed.
