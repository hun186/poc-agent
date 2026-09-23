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
SRA_E2E_EXPECTED_SOURCE_SHA=2d50bed20a3e697020107ece218e7c001580e1df03adc1c30f8060c4e9118d03
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

### External capability policy

Pass `--external-mode live|auto|offline` (default `auto`). The deployment must
have the same `REQUIREMENT_E2E_EXTERNAL_MODE` value before the API and workers
start. The API process that owns `ReportJobWorker` resolves the plan during
lifespan startup, before a Report Job can be claimed. Both local and remote
harnesses read that process's authenticated runtime evidence; they never mutate
their own environment as a substitute for configuring the running deployment.
The harness rejects a requested/deployed-mode mismatch.
`live` fails if the model is not callable, the index is absent, the live mapping
lacks the query/runtime-required nested subset, or the canonical retrieval
phrases do not produce hits. `auto` records the stable probe category and uses a
semantic boundary mock only for an unsuitable dependency. `offline` skips both
network probes. No mode replaces Requirement import, scheduling, claiming,
handoff, Agent orchestration, report/DOCX generation, reconciliation, or durable
terminal checks.

Successful evidence is always explicit: `PASS / FULL_LIVE`, `PASS / HYBRID`, or
`PASS / OFFLINE`. `FULL_LIVE` additionally depends on the unchanged downstream
retrieval, artifact, reconciliation, and terminal acceptance checks; a ping by
itself cannot earn that classification. A later runtime failure never changes
the frozen backend and remains `FAIL / <category>`.

The live `indices.get_mapping()` response remains full index mapping authority.
The committed Requirement fixture has a dedicated root retrieval subset and a
separate czjLLM MultiDim writeback subtree (`nested`, `dynamic: strict`); that
subtree is not represented as a complete SRA root mapping. The probe checks only
the E2E-required paths, configured `SRA_REFERENCE_TEXT_FIELD`, and required
multifields through their Elasticsearch `fields` definitions.
`docs/taskSetting_Enrichment.py` supplies semantic/output rules, not type
authority. The fixtures cover Gaza humanitarian access, Taiwan Strait gray-zone
activity, and US-China/Indo-Pacific strategic competition with native `Event[]`,
referential `event_ids`, date-only `article_date_iso`, and verbatim evidence.
The bounded semantic backend evaluates the production query builder's required
`function_score`/bool/term/text/nested/range subset and fails visibly for an
unsupported query rather than returning every document.

The deterministic direct-LLM boundary models every `SRA_REPORT` caller contract
explicitly and fails as `unsupported_e2e_llm_contract` for an unknown system
prompt. The audited contracts are:

| Stage | Production prompt/caller | Raw response contract | Conditional |
| --- | --- | --- | --- |
| Router | `routing.TASK_ROUTER_SYSTEM` | JSON object with `mode`, `reason`, and configured `topic` | No |
| Query refiner | `query_refiner.REFINER_SYSTEM_PROMPT` plus time context | JSON object with semantics-preserving `refined_question` | `QUERY_REFINER_REPORT_ENABLED=1` |
| Topic extractor | `query_terms.extract_topic_terms_llm` | JSON string array | `TOPIC_LLM_URL` configured |
| Synonym expander | `query_terms.expand_synonyms_grouped_llm` | JSON object mapping terms to string arrays | `TOPIC_LLM_URL` configured and core terms present |
| Evidence field selector | `evidence_pack.LLM_FIELD_SELECTOR_SYSTEM` | JSON `fields` containing mandatory `ref_no` and `note` | selector mode `llm`/`hybrid` |
| Report writer | `report_prompt.REPORT_SYSTEM_PROMPT` | Evidence-grounded Markdown from the production `q/q0/t/agg/ev` JSON | No |

The smolagents DataAgent model is a separate boundary: its deterministic model
derives a business-theme query and instructs the real `CodeAgent` to invoke
`es_search_news`; it does not construct final evidence itself.

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
