# Codex Prompt v1 — Requirement Automatic Operator E2E Harness

Repository: `hun186/poc-agent`

You are implementing **Requirement Automatic Operator E2E Harness v1**.

The Design and Implementation Plan are authoritative requirements for this task:

- `Requirement Automatic Operator E2E Harness Design v1`
- `Requirement Automatic Operator E2E Harness Implementation Plan v1`

The Design was authored against hosted GitHub `main`:

```text
4fd6f1adad66c3cfc20a91ad556c6da7e8a2da9b
```

## 1. Mandatory source rebaseline before editing

Before changing any file:

1. Fetch the current **hosted GitHub `main`** for `hun186/poc-agent`.
2. Record its actual current HEAD SHA.
3. Do not assume `4fd6f1ad...` is still current.
4. Compare current affected source against the Design/Plan assumptions.

Authority rules:

```text
Post-merge:
  hosted GitHub main current HEAD is authoritative.

Pre-merge:
  hosted PR head + actual PR diff are authoritative candidate source.

Local/Codex SHA:
  implementation evidence only unless actually hosted.
```

If current hosted `main` differs from the Design baseline:

- inspect the actual diff/current source;
- if changes are unrelated and the Design remains valid, record the new base SHA and continue;
- if Requirement Import, Schedule, Handoff, Report Job, artifact, launcher, or API contracts materially conflict with the Design/Plan, STOP before implementation and report baseline drift;
- do not silently redesign around a material conflict.

Source code overrides stale documents.

Never invent a commit SHA.

---

## 2. Read before implementation

Read the complete approved Design and Implementation Plan first.

Then inspect current source, including at minimum:

```text
operator_e2e/test_phase0_api_routing_evidence.py

sra_api/main.py
sra_api/routers/requirements.py
sra_api/routers/requirement_models.py
sra_api/routers/requirement_schedules.py
sra_api/routers/editor_dependencies.py

data_ingestion/requirements/models.py
data_ingestion/requirements/readers.py
data_ingestion/requirements/service.py
data_ingestion/requirements/store.py

requirement_scheduler/models.py
requirement_scheduler/recurrence.py
requirement_scheduler/store.py
requirement_scheduler/schedule_worker.py
requirement_scheduler/coordinator.py
requirement_scheduler/legacy_report_job_gateway.py
requirement_scheduler/artifacts.py
requirement_scheduler/cli.py
requirement_scheduler/migrations.py

sra_api/routers/report_jobs.py

run_sra_api.sh

docs/operations/requirement-import.md
docs/operations/requirement-scheduling.md

relevant Requirement/Schedule/Handoff/Report Job/launcher tests
```

Do not implement from this prompt alone without reading source.

---

## 3. Scope

Build a one-command deployment-host operator harness whose primary invocation is:

```bash
python operator_e2e/test_requirement_schedule_e2e.py \
  --excel operator_e2e/input/requirement_e2e_3items.xlsx
```

Its job is to prove or diagnose:

```text
XLSX
→ Requirement Preview
→ Requirement Import
→ exact Snapshot
→ approved/enabled Schedule
→ REAL schedule-worker automatic claim
→ scheduled Batch
→ 3 Run Items
→ REAL handoff-worker
→ 3 Report Jobs
→ Agent / Elasticsearch / LLM
→ DOCX
→ reconciliation
→ terminal completed state
→ persisted SHA256 == actual SHA256
```

It must identify the failed stage automatically.

---

## 4. Explicitly out of scope

Do NOT implement or redesign:

```text
LangGraph
JT-1 Task/Attempt/Event Store
Requirement Task Center
GUI
OpenWebUI integration
new orchestration framework
Phase 1B redesign
Phase 1C redesign
Agent redesign
Report Job redesign
deployment manifest expansion
robocopy deployment verification
SD-1 through SD-7
offline release packaging redesign
```

Do not revisit deployment manifest work.

Do not modify `run_sra_api.sh` unless fresh source proves a direct Harness blocker and you stop/report that conflict first.

---

## 5. Strict TDD

Use strict test-driven development.

For every behavior:

1. write the failing test;
2. run it and confirm the expected failure;
3. implement the minimum change;
4. rerun the focused test;
5. run relevant regression tests.

Do not write production implementation first and tests afterward.

Do not weaken existing tests to make the implementation pass.

---

## 6. Production-side change budget

The Design expects only one minimal production-side observability change:

Extend existing `ScheduleStore.get_batch_run()` read projection to expose already-persisted evidence:

Batch:

```text
snapshot_id
phase1a_output_root_fingerprint
```

Run Item:

```text
remote_job_id
remote_job_state
```

These fields already exist in the current durable scheduler schema.

Do NOT:

- add a migration;
- add a new table;
- add a new write endpoint;
- change schedule claim semantics;
- change Handoff semantics;
- change Report Job ownership;
- change checkpoints;
- change artifact publication semantics.

If current source makes the above assumption invalid, stop and report instead of redesigning.

---

## 7. Harness file structure

Prefer:

```text
operator_e2e/test_requirement_schedule_e2e.py
operator_e2e/requirement_e2e_support.py
operator_e2e/requirement_e2e_profile_v1.json
tests/test_requirement_operator_e2e_harness.py
docs/operations/requirement-automatic-operator-e2e.md
```

Also update `.gitignore` for generated Requirement E2E outputs.

Keep the operator entry point simple.

Do not copy the old Phase 0 script's hardcoded Windows output path.

---

## 8. Existing Phase 0 conventions to retain

Reuse good existing operator conventions:

```text
bootstrap project environment
optional ignored operator_e2e/e2e.env.local
only SRA_E2E_* keys allowed in that file
credentials never hardcoded in Python
HTTP/API based operator workflow
bounded timeouts
clear exit status
```

Improve on unsafe/noisy behavior:

- never print raw Authorization headers;
- never dump credentials;
- never dump complete environment variables;
- never dump large HTTP bodies or runtime logs on success.

---

## 9. Fixture strategy

Use dedicated stable E2E fixtures:

```text
Profile
Source
Schedule shell
```

Per invocation create unique:

```text
e2e_run_id
Import Run
Snapshot
Schedule Version
scheduled Batch
Run Items
Report Job identities
evidence directory
```

Fixture rules:

```text
absent        -> create
exact match   -> reuse
partial exact -> safely complete normal lifecycle
drifted       -> fail closed
ambiguous     -> fail closed
```

Do not auto-repair unknown durable state.

Do not DELETE old runs/snapshots/versions.

---

## 10. Input contract

Harness v1 tests XLSX.

Use a tracked exact E2E profile definition based on canonical fields:

```text
external_item_id
title
prompt_content
source_updated_at
source_created_at
expires_at
```

Production Preview is authoritative.

PASS requires:

```text
accepted_count = 3
rejected_count = 0
```

After commit, verify exact imported Snapshot contains exactly 3 active Requirement items.

Do not accept workbook row count alone as evidence.

---

## 11. Automatic scheduling is non-negotiable

The Harness MUST NOT:

```text
POST /v1/requirement-schedules/{id}/runs
```

It MUST NOT execute:

```text
python -m requirement_scheduler schedule-worker --once
```

It MUST NOT directly invoke:

```text
coordinator.run_once()
```

Add tests that fail immediately if the Harness attempts the manual Run route.

The only accepted Batch is one actually materialized by the already-running production schedule-worker.

---

## 12. Schedule timing

For each invocation create a new immutable Schedule Version.

Use:

```text
timezone = UTC
run_policy = all_active
model = SRA_E2E_MODEL
```

Recurrence:

```json
{
  "kind": "interval",
  "every": 10080,
  "unit": "minutes",
  "anchor_at": "<near-future UTC time at second precision>"
}
```

Default anchor lead should be approximately 120 seconds.

Reason:

- first run happens soon;
- next run is seven days later;
- a Harness crash does not accidentally create a Report Job every minute.

After enable, trust the returned `next_run_at`.

If it is not in the permitted near-future window, fail safely and disable the schedule.

---

## 13. Automatic claim identity requirements

Before enable, capture existing Batch Run IDs.

Poll only reads until exactly one new matching scheduled Batch appears.

Require:

```text
trigger_type == scheduled
schedule_version_id == this invocation's schedule version
scheduled_for == captured initial next_run_at
snapshot_id == this invocation's snapshot
selected_count == 3
skipped_count == 0
```

No matching Batch by deadline:

```text
automatic_claim_timeout
```

More than one:

```text
multiple_scheduled_runs
```

Wrong snapshot/version/trigger:

fail with a safe identity mismatch category.

---

## 14. next_run_at

After automatic materialization and before cleanup:

verify:

```text
advanced_next_run_at > initial_next_run_at
```

and:

```text
advanced_next_run_at == scheduled_for + 10080 minutes
```

Then disable the exact E2E Schedule through the normal API.

---

## 15. Report Job proof

Do not infer Report Jobs from log timing.

For the exact Batch, require exactly three selected Run Items with:

```text
remote_job_id != null
```

Require:

```text
len(unique remote_job_id) == 3
```

Poll durable batch/run-item projection for:

```text
remote_job_state
execution_state
```

Do not require or expose the Handoff worker's internal Service Key.

The Harness must not impersonate the Handoff principal.

---

## 16. Terminal PASS

All three selected Run Items must end:

```text
remote_job_state == completed
execution_state == completed
```

Batch must end:

```text
state == completed
success_count == 3
failure_count == 0
```

If an item reaches:

```text
failed
recovery_required
expired
```

fail immediately rather than waiting for the overall timeout.

---

## 17. Artifact verification

For each item, require durable:

```text
artifact_relative_path
artifact_sha256
```

Use `SRA_E2E_REQUIREMENT_ARTIFACT_ROOT`.

Verify:

```text
configured root fingerprint == persisted batch root fingerprint
safe relative path
file exists
valid ZIP
[Content_Types].xml exists
word/document.xml exists
no traversal ZIP members
ZipFile.testzip() succeeds
actual SHA256 == persisted SHA256
```

Copy only verified DOCX bytes to the per-run evidence directory.

Do not delete the production artifact.

---

## 18. Worker readiness

Use current launcher identity evidence read-only.

Verify the already-running:

```text
schedule-worker
handoff-worker
```

using current launcher identity semantics:

- PID
- process start time
- UID
- cwd
- expected command

Do not send signals.

Do not restart anything.

Report Job Worker is embedded in API lifespan and currently has no separate public health endpoint; prove its functional readiness through actual Report Job progress instead of inventing a fake health test.

---

## 19. Retry / ambiguous writes

Reads may use bounded transient retry.

Writes must not use blind retry after timeout.

Rule:

```text
ambiguous write
→ reread durable state
→ identify winner
→ retry only if durable evidence proves no write occurred
```

Apply this particularly to:

- fixture creation;
- Schedule Version creation;
- approve/enable;
- Import Commit.

No direct SQL repair.

No UPDATE/DELETE against durable databases from the Harness.

---

## 20. Diagnostics / redaction

On success:

do not dump logs.

On failure:

bounded tail only from:

```text
SRA-API_output.txt
SRA-ScheduleWorker_output.txt
SRA-HandoffWorker_output.txt
```

Default cap:

```text
100 lines
64 KiB per log
```

Redact at minimum:

```text
Authorization
Bearer token
password
token
secret
service key
connection string
PWD
User ID credentials
```

Also redact every known credential literal currently held in Harness memory.

Never serialize credential file contents.

Never serialize all environment variables.

Add tests using synthetic sentinel secrets and assert they never appear in console/result/diagnostics.

---

## 21. Output

Each invocation writes a new directory:

```text
operator_e2e/output/requirement_e2e/<e2e_run_id>/
```

with:

```text
result.json
summary.txt
diagnostics.json
artifacts/
```

Do not overwrite older evidence.

Use atomic writes where practical.

`result.json` schema version:

```text
requirement_e2e_result_v1
```

Include safe IDs, states, counts, timestamps, SHA256 values and stage evidence.

Do not include:

```text
Authorization header
password
Service Key
connection string
prompt_content
source_raw
credential-store contents
```

---

## 22. Exit codes

Implement exactly:

```text
0 = PASS
2 = config / preflight / auth / input failure
3 = E2E functional chain failure or timeout
4 = Harness internal / evidence-write failure
5 = cleanup safety failure
```

Never return 0 for partial success.

---

## 23. Cleanup

Always attempt normal API cleanup if this invocation enabled the verified E2E schedule.

Cleanup action:

```text
disable schedule
```

Do NOT:

```text
DELETE DB state
UPDATE SQL manually
rewrite snapshot
reset checkpoint
change Batch state
rotate credentials
kill processes
```

If safe schedule disable fails, overall result is FAIL and exit 5.

---

## 24. Required stage reporting

At minimum retain detailed stages equivalent to:

```text
CONFIG_PREFLIGHT
API_READINESS
AUTH
PIPELINE_READINESS
RUNTIME_WORKERS
INPUT_VALIDATION
FIXTURE_PROFILE
FIXTURE_SOURCE
REQUIREMENT_PREVIEW
REQUIREMENT_IMPORT
SNAPSHOT
REQUIREMENT_ITEMS
SCHEDULE_FIXTURE
SCHEDULE_VERSION
SCHEDULE_APPROVE
SCHEDULE_ENABLE
AUTO_CLAIM
RUN_IDENTITY
RUN_SELECTION
NEXT_RUN_ADVANCE
HANDOFF
REPORT_JOBS
REMOTE_EXECUTION
ARTIFACT_RECONCILIATION
RUN_ITEMS_TERMINAL
BATCH_TERMINAL
DOCX_INTEGRITY
SHA256_MATCH
CLEANUP
FINAL_EVIDENCE
```

Each is:

```text
PASS
FAIL
NOT_REACHED
```

Console may group these into the simpler operator summary.

---

## 25. Offline requirement

The Harness must work with no external Internet access.

It may use only:

- local project files;
- locally installed Python dependencies;
- internal SRA API;
- internal SQL/ES/LLM indirectly through the production application;
- local process/filesystem evidence.

Do not add package download, GitHub lookup, cloud API, or external telemetry to Harness runtime.

GitHub rebaseline is an implementation/review activity, not a live Harness runtime dependency.

---

## 26. Tests

At minimum add focused tests for:

- env contract;
- redaction;
- result schema;
- exit codes;
- fixture create/reuse/drift/ambiguity;
- ambiguous write durable reread;
- exactly three preview/import items;
- no manual Run route;
- automatic Batch identity;
- wrong Snapshot rejection;
- multiple Batch rejection;
- next_run_at advancement;
- exactly three unique Report Job IDs;
- terminal failure detection;
- artifact root fingerprint;
- DOCX ZIP validation;
- SHA mismatch;
- worker identity verification;
- log redaction;
- cleanup failure;
- evidence output.

Then run relevant existing Requirement/Schedule/Handoff/Report Job/launcher regression tests specified in Implementation Plan.

Do not claim success without actual test output.

---

## 27. Git / PR rules

Work on an implementation branch, for example:

```text
feat/requirement-operator-e2e-harness-v1
```

Create a PR if implementation and tests are complete.

You MAY push the branch and create the PR.

You MUST NOT:

```text
merge the PR
enable auto-merge
push directly to hosted main
```

The user performs merge manually.

---

## 28. Completion report

Return:

```text
Hosted base main SHA:
Branch:
Candidate HEAD SHA:
PR:

Changed files:

Implemented behavior:

Production-side change:
Harness-side changes:

Tests added:
Test commands:
Test results:

Design deviations:
Plan deviations:

Remaining risks:

Live deployment Harness executed:
YES / NO

Fresh live Requirement E2E PASS:
YES / NO
```

If no live deployment Harness was executed, explicitly say:

```text
NO FRESH LIVE E2E PASS CLAIMED
```

Do not substitute old Golden Path evidence for fresh Harness acceptance.

Do not substitute HTTP 200 for semantic PASS.

Do not substitute Codex Completion Report for hosted-source review.
