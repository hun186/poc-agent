# API Contract

## Current Summary

- FastAPI routes live primarily under `sra_api/routers/`; `api/` preserves compatibility imports.
- Public integration surfaces include `GET /healthz`, `GET /v1/models`, `POST /v1/chat/completions`, document/fulltext retrieval, and synchronous Word export. Editor/Auth and data-management routes use bearer authentication and role checks.
- Persisted Report Jobs use `POST /v1/report/jobs`, `GET /v1/report/jobs/{job_id}`, and `GET /v1/report/jobs/{job_id}/word`. Jobs are owner scoped; completed artifacts must pass confinement and DOCX validation.
- Requirement import and schedule APIs expose authenticated source/profile/import, immutable snapshot/version, schedule lifecycle, manual run materialization, neutral Batch/Run Item status, and authorized artifact history without exposing credentials, prompts, absolute roots, or backend-native state.
- Requirement Product API routes are still NOT IMPLEMENTED. Schedule schema v4 Product Task/request persistence is merged, and P1.0A authority compatibility is implemented on PR #279: Requirement import accepts optional server-owned `import_run_id` / `snapshot_id` plus `expected_base_snapshot_id`, recovers terminal preallocated imports before preparation, and Schedule Version creation accepts an optional server-owned `schedule_version_id`. Manual Run continues to use `(schedule_id, trigger_request_id)` rather than caller-supplied `batch_run_id`. Planned Product mutations still require durable `Idempotency-Key`; canonical `request_sha256` binds operation + all route/path target identities + semantic payload/input digest.
- Excel-to-SQL endpoints provide dashboard task/config management, upload/preview/confirm, audit dashboards, controlled source-row reads/edits/deletes, and source statistics. Enabled-task allowlists and role boundaries remain authoritative.
- `GET /v1/operator-e2e/runtime-evidence` is authenticated, superuser-only, and read-only. Schema `requirement_e2e_runtime_evidence_v1` reports bounded deployment provenance identity, Schedule/Handoff worker identity, and artifact-root fingerprint.
- Runtime-evidence source failures include `release_provenance_missing`, `release_provenance_invalid`, `active_runtime_source_mismatch`, `unexpected_active_runtime_module`, `runtime_module_shadowing`, and `unexpected_runtime_input`. The last category means an actually selected/discovered release-managed input is absent from provenance.
- Requirement runtime evidence never reports the deployment-local SQL registry's contents, hash, resolved path, credentials, connection details, or query text; release provenance does not attest that privileged registry.
- `GET /v1/operator-e2e/batches/{batch_run_id}/items/{run_item_id}/artifact` is authenticated, superuser-only, accepts no path, and returns only the durable Handoff-published DOCX after metadata/root/confinement/ZIP/SHA-256 validation.
- Signed resource requests reject duplicate/unsupported query keys and substitutions before lookup, and successful responses use no-store/no-referrer/nosniff headers.

## Recent Changes

### 2026-09-18 Runtime-input evidence category

- `unexpected_runtime_input` propagates unchanged through the runtime evidence endpoint, remote evidence provider, and Harness preflight mapping so acceptance stops in `RUNTIME_WORKERS` before Preview/Import/Schedule mutation.
- Offline operator package verification uses the same shared bounded discovery policy without `.git`, GitHub, or network.

### 2026-09-18 Canonical provenance identity

- Deployment source evidence includes schema-v2 runtime path/hash entries and canonical provenance fingerprint. `reviewed_runtime_sha` remains audit metadata.

### 2026-09-16 Published artifact evidence

- The operator artifact route validates durable item identity, configured-root fingerprint, confinement, DOCX ZIP, and SHA-256 before returning bytes.

## Archived History

- `.codex/archive/api_contract.md-20260918-000000.md` — full pre-compaction API contract through 2026-09-18.
- Earlier archives referenced by that file remain under `.codex/archive/`.

### 2026-09-23 Runtime-evidence verification policy

- `GET /v1/operator-e2e/runtime-evidence` accepts `verification=release|functional` (default `release`). Functional requests may receive HTTP 200 with `deployment_source.identity_verified=false`, `attestation_status=mismatch`, and `attestation_category=active_runtime_source_mismatch`; capability, worker, and artifact-root evidence remains authoritative.
- Missing/malformed provenance, unexpected runtime input, unexpected active runtime modules, and module shadowing remain errors in both policies. The response still excludes secrets and deployment paths.

## 2026-10-06 Requirement Product P1.1 internal presenter contract

- Product HTTP routes remain **NOT IMPLEMENTED**.
- The internal Product presenter now defines bounded Task/Run shapes for later routes: authoritative Product Task identity, neutral Run status, immutable `schedule_version_id` / `snapshot_id` binding, Requirement Version identity, safe error category, artifact availability/digest, and relative future Product links.
- Backend-native Report Job state/IDs, absolute or relative artifact storage paths, output-root fingerprints, trigger-request identities, credentials, and E2E markers are not part of the Product presenter contract.
- Presenters treat `product_state=provisioning` as unavailable to ordinary Product presentation.
