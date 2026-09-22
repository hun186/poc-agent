# Requirement automatic operator E2E harness

## Before first run

1. Copy `operator_e2e/e2e.env.example` to `operator_e2e/e2e.env.local`.
2. Edit only the local file with real deployment values and credentials.
3. Never commit `e2e.env.local`; it is intentionally ignored by Git.
4. The same local file may contain the optional Phase 0 Service Keys used by
   `test_phase0_api_routing_evidence.py`: `SRA_E2E_OPENWEBUI_KEY`,
   `SRA_E2E_READ_ONLY_KEY`, and `SRA_E2E_REPORT_KEY`.
5. Requirement Editor authentication and Phase 0 routing/authorization Service Keys are
   separate roles and must not be assumed interchangeable. In particular, do not alias
   `SRA_E2E_EDITOR_TOKEN` to `SRA_E2E_REPORT_KEY` unless the operator independently provisioned
   that credential with every required Requirement control-plane scope. Requirement acceptance
   needs an identity authorized for fixture creation/import and Schedule approval/enablement.
   Remote mode additionally requires a **superuser** Editor user session because its runtime and
   artifact evidence routes are superuser-only; an ordinary Editor is not sufficient.
6. Use the Linux deployment host for local mode. Windows/Spyder is supported only as the remote
   operator client described below.

Windows/Spyder is not a supported local-mode acceptance runtime, but it is supported as the
remote-mode operator client. An `unsupported_platform` result on Windows is a local preflight
result and does **not** prove that the production deployment failed.

## Purpose and boundary

This deployment-host harness proves or diagnoses the complete XLSX Requirement path through
automatic scheduling, Handoff, Report Jobs, Agent execution, DOCX publication, reconciliation,
and durable terminal state. It stimulates the public HTTP control plane and only observes the
already-running production workers. An HTTP success response alone is never considered a pass.

The harness does **not** start or signal workers, invoke coordinator internals, access SQL
directly, repair durable state, or call the manual `POST /v1/requirement-schedules/{id}/runs`
route. It has no Internet dependency at runtime.

## Configuration

Start from the tracked, credential-free `operator_e2e/e2e.env.example` and create the ignored
`operator_e2e/e2e.env.local`. Every entry must begin with `SRA_E2E_`.
Configure exactly one editor authentication mode:

```dotenv
SRA_E2E_EDITOR_USERNAME=acceptance-superuser
SRA_E2E_EDITOR_PASSWORD=<managed secret>
# Or use SRA_E2E_EDITOR_TOKEN instead of both fields above.

SRA_E2E_MODEL=SRA-Structured Retrieval Agent
SRA_E2E_REQUIREMENT_ARTIFACT_ROOT=/absolute/production/requirement/artifact/root
SRA_E2E_BASE_URL=http://127.0.0.1:9002
SRA_E2E_EXPECTED_SOURCE_SHA=816ffac9039530a86955c590b0fa68830757a620229d85630f5e42c12f542403
```

Authentication is mode-specific. Local mode uses an authorized control-plane identity according
to the existing local contract. Remote mode requires a superuser Editor session/token, both for
the same fixture/Schedule operations and for the superuser-only operator evidence surfaces. When
`SRA_E2E_EDITOR_TOKEN` is used remotely, it means a valid superuser user-session bearer token—not
an arbitrary Phase 0 Service Key. An ordinary Editor cannot produce a remote PASS.
Do not provide a SQL connection string, Handoff Service Key, signing secret, or credential-store
contents. Optional timeout and path settings are documented by `--help` and the Design; defaults
are bounded and suitable for the normal deployment.

The optional expected hash and release provenance bind different inputs:

* `SRA_E2E_EXPECTED_SOURCE_SHA` is the 64-character lowercase SHA-256 of the XLSX input bytes.
  Input validation compares it only with the actual uploaded workbook digest.
* Repository-root `REQUIREMENT_E2E_PROVENANCE.json` is the release authority. Schema v2 carries the
  reviewed Git identity as audit metadata and SHA-256 of every exact package byte. The normal operator
  does not enter a SHA and neither `.git` nor GitHub access is required. The deprecated
  `SRA_E2E_EXPECTED_RUNTIME_SHA`, when supplied, is only an additional consistency assertion and a
  disagreement with provenance fails before mutation.

Generate provenance on the external reviewed source/release machine and copy it with the package:

```bash
python tools/requirement_e2e_provenance.py \
  --reviewed-sha <reviewed-hosted-main-sha> \
  --output REQUIREMENT_E2E_PROVENANCE.json
```

Generation accepts exact source bytes or, for eligible text only, the complete LF-to-CRLF checkout
transformation, and records SHA-256 of the actual package bytes. `.py`, `.json`, `.yaml`, `.yml`,
`.toml`, `.ini`, `.cfg`, `.txt`, `.md`, `.html`, `.css`, and `.js` are EOL-eligible. Shell scripts,
Office files, images, archives, and unknown formats remain exact-only. Deployment verification never
normalizes bytes. Generated output remains excluded; inactive Python residue remains warning-only,
while loaded/discovered/shadowing modules and managed-byte drift fail closed.

## Input and invocation

The canonical XLSX is a deployment-managed mirror of
`data/要項excel/requirement_e2e_three.xlsx` and contains exactly three production-style
Requirement rows with these source headers:

```text
ITEMNO, TITLE, CONTENT, UPDT, DeadlineDT, CreateApeno, UpdateApeno, CrtDT
```

The Harness uses the reviewed Taiwan investment/security import profile to map `CONTENT` into
`prompt_content`. After Import, the canonical run additionally requires every imported
`ITEMNO -> prompt_content` value to match the workbook's full `ITEMNO -> CONTENT` value.
Prompt text is compared in memory only and is not written to result/evidence files.

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

## Harness v2 local and remote acceptance

Harness v2 has two explicit complete modes and no automatic detection or fallback. `local` is the
default and remains Linux deployment-host only. Windows/Spyder is supported for remote-operator
acceptance; use `--mode remote`. A remote PASS is complete acceptance and does not normally need a
local rerun. A local PASS is also complete and does not need a remote run. On remote FAIL/BLOCKED,
inspect the preserved stage/evidence; a separate local run may be used for diagnosis. Operators may
intentionally run both after major deployment/bootstrap/worker/security changes.

The canonical `operator_e2e/input/requirement_e2e_3items.xlsx` is resolved relative to the script
and used by default with its known SHA-256 enforced automatically:

```bash
# Linux deployment host (equivalent to --mode local)
python operator_e2e/test_requirement_schedule_e2e.py
```

```powershell
# Windows remote operator
python operator_e2e/test_requirement_schedule_e2e.py `
  --mode remote
```

A custom workbook uses `--excel /path/to/custom.xlsx` and its actual digest is recorded. Remote mode
does not require `SRA_E2E_REQUIREMENT_ARTIFACT_ROOT`; the authenticated, superuser-only read-only
`GET /v1/operator-e2e/runtime-evidence` route proves deployment source, both launcher-managed worker
identities, and the configured Handoff artifact-root fingerprint without returning paths, PIDs,
cmdlines, credentials, or environment values. For each durable Batch/Run Item identity, the
superuser-only `GET /v1/operator-e2e/batches/{batch_run_id}/items/{run_item_id}/artifact` route
looks up (never accepts from the client) the durable relative path and SHA, validates the configured
Handoff root fingerprint, confinement, DOCX ZIP, and SHA, and returns the exact Requirement artifact
published under `REQUIREMENT_HANDOFF_OUTPUT_ROOT`. The upstream Report Job `/word` copy is not Remote
PASS artifact authority. The operator independently repeats DOCX ZIP and SHA validation before
retaining the bytes under the invocation's `artifacts/` directory.

Both remote evidence routes require a superuser Editor user session. HTTP 401 and 403 are reported
as remote evidence authentication and authorization failures rather than network unavailability.

The local provenance defaults to repository-root `REQUIREMENT_E2E_PROVENANCE.json`; `--provenance`
selects an explicit path. Operator and deployment compare SHA-256 of canonical validated provenance
JSON, so equal reviewed Git metadata with different package maps cannot pass. Results use
`requirement_e2e_result_v2`; `summary.txt` always includes `ACCEPTANCE_MODE` and sets
`FRESH_LIVE_REQUIREMENT_E2E_PASS` to `YES` only on complete PASS.

The operator-process lock is checkout/output-local (`fcntl` on POSIX, `msvcrt` for remote Windows),
not a distributed global lock. Immutable fixture/run identity and drift detection remain the safe
interference boundary. The Harness never launches the other mode automatically.
