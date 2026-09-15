# Requirement automatic operator E2E harness

## Purpose and boundary

This deployment-host harness proves or diagnoses the complete XLSX Requirement path through
automatic scheduling, Handoff, Report Jobs, Agent execution, DOCX publication, reconciliation,
and durable terminal state. It stimulates the public HTTP control plane and only observes the
already-running production workers. An HTTP success response alone is never considered a pass.

The harness does **not** start or signal workers, invoke coordinator internals, access SQL
directly, repair durable state, or call the manual `POST /v1/requirement-schedules/{id}/runs`
route. It has no Internet dependency at runtime.

## Configuration

Create the ignored `operator_e2e/e2e.env.local`. Every entry must begin with `SRA_E2E_`.
Configure exactly one editor authentication mode:

```dotenv
SRA_E2E_EDITOR_USERNAME=acceptance-superuser
SRA_E2E_EDITOR_PASSWORD=<managed secret>
# Or use SRA_E2E_EDITOR_TOKEN instead of both fields above.

SRA_E2E_MODEL=SRA-Structured Retrieval Agent
SRA_E2E_REQUIREMENT_ARTIFACT_ROOT=/absolute/production/requirement/artifact/root
SRA_E2E_BASE_URL=http://127.0.0.1:9002
```

The identity must be authorized to create Requirement fixtures and to approve/enable schedules.
Do not provide a SQL connection string, Handoff Service Key, signing secret, or credential-store
contents. Optional timeout and path settings are documented by `--help` and the Design; defaults
are bounded and suitable for the normal deployment.

## Input and invocation

Prepare an XLSX containing exactly three production-valid rows with these headers:

```text
external_item_id, title, prompt_content, source_updated_at, source_created_at, expires_at
```

Then run from the repository root:

```bash
python operator_e2e/test_requirement_schedule_e2e.py \
  --excel operator_e2e/input/requirement_e2e_3items.xlsx
```

Production Preview is authoritative. The workbook must yield exactly three accepted and zero
rejected rows, and the committed Snapshot must independently contain exactly three active items.

## Evidence and interpretation

Each invocation gets a unique directory under
`operator_e2e/output/requirement_e2e/<e2e_run_id>/` containing:

* `result.json` — schema `requirement_e2e_result_v1`, safe durable identities, stages, counts,
  timestamps, states, and SHA-256 evidence.
* `summary.txt` — concise PASS/FAIL, exit code, and failing stage/category.
* `diagnostics.json` — empty/minimal on success; bounded, redacted API/Schedule/Handoff log tails
  on failure.
* `artifacts/` — copies of only the three independently verified DOCX files. Production files
  remain untouched.

Stages are `PASS`, `FAIL`, or `NOT_REACHED`. In particular, `AUTO_CLAIM` proves that the existing
schedule-worker created exactly one new `scheduled` Batch for this invocation's immutable
Schedule Version, occurrence, and Snapshot. `REPORT_JOBS` proves three distinct durable remote
job IDs. `DOCX_INTEGRITY` and `SHA256_MATCH` independently validate the ZIP package and persisted
digest.

Exit codes are:

| Code | Meaning |
| ---: | --- |
| 0 | Complete semantic PASS |
| 2 | Configuration, preflight, authentication, authorization, or input failure |
| 3 | Functional-chain failure or timeout |
| 4 | Internal harness or evidence-write failure |
| 5 | Schedule cleanup safety failure |

## Failure handling and cleanup

Fix the reported stage rather than inferring success from earlier stages. Diagnostics never
intentionally include credentials or Requirement prompt content. The harness always attempts to
disable the exact schedule it enabled through the normal API; failure to do so forces exit 5.

Do not delete or update SQL rows, rewrite Snapshots, reset checkpoints, change Batch state, kill
workers, or delete production artifacts. Historical Import Runs, Snapshots, Schedule Versions,
Batches, Run Items, Report Job identities, and artifacts are retained as durable evidence.
