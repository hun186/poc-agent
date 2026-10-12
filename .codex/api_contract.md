# API Contract

## Current Summary

- FastAPI routes live primarily under `sra_api/routers/`; `api/` preserves compatibility imports.
- Public integration surfaces include `GET /healthz`, `GET /v1/models`, `POST /v1/chat/completions`, document/fulltext retrieval, and synchronous Word export. Editor/Auth and data-management routes use bearer authentication and role checks.
- Persisted Report Jobs use `POST /v1/report/jobs`, `GET /v1/report/jobs/{job_id}`, and `GET /v1/report/jobs/{job_id}/word`. Jobs are owner scoped; completed artifacts must pass confinement and DOCX validation.
- Requirement import and schedule APIs expose authenticated source/profile/import, immutable snapshot/version, schedule lifecycle, manual run materialization, neutral Batch/Run Item status, and authorized artifact history without exposing credentials, prompts, absolute roots, or backend-native state.
- Requirement Product HTTP routes are still NOT IMPLEMENTED. P1.0 schema v4, P1.0A authority compatibility, and P1.1 Product presenter/identity boundaries are merged. P1.2 internal preview is merged. P1.3 adds an internal one-time durable Product create service/store contract; Product HTTP routes, recurring create, update/run routes, and other Product mutations remain future gates. Planned Product mutations still require durable `Idempotency-Key`; canonical `request_sha256` binds operation + all route/path target identities + semantic payload/input digest.
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


## 2026-10-07 Requirement Product P1.2 internal preview contract

- No Product HTTP route is introduced by P1.2.
- Internal `RequirementProductService.preview_input(...)` requires an explicit approved `profile_version_id` and exactly one input form: uploaded bytes + filename, or direct Requirement JSON.
- Output contains `source_sha256`, row/accepted/rejected counts, `has_errors`, `normalized_preview`, row `errors`/`warnings`, and profile identity (`profile_id`, `profile_version_id`, `version_number`, `profile_sha256`, format, source mode).
- The normalized preview excludes raw source dictionaries and internal row/content hashes. Preview does not reserve idempotency, create Requirement/Schedule/Product persistence, or materialize work.


## 2026-10-07 Requirement Product P1.3 internal one-time create contract

- No Product HTTP route is introduced by P1.3.
- Internal one-time create requires superuser authority, `Idempotency-Key`, task name, explicit approved/current-active Requirement profile version, exactly one Product input form, and a validated `ScheduleVersionCreate`.
- Durable `task_create` reservation is keyed by user principal + operation + idempotency key and binds a canonical request SHA over execution kind, name, profile-version identity, input digest/name, and Schedule config digest.
- Reservation preallocates and persists `task_id`, `source_id`, `import_run_id`, `snapshot_id`, `schedule_id`, and `schedule_version_id`.
- Successful one-time finalization stores only bounded safe result IDs/revision plus `batch_run_id`; Product response is rebuilt through existing Task/Run presenters, so trigger-request identity, raw paths, credentials, Report Job native state, and E2E internals remain suppressed.


## 2026-10-07 Requirement Product P1.4 internal recurring create contract

- No Product HTTP route is added by P1.4.
- Internal recurring create is superuser-only and uses the same durable `task_create` reservation namespace as one-time create. `execution_kind=recurring` is included in the canonical request hash, so reusing one idempotency key across once/recurring payloads conflicts.
- Before finalization the Product Task is `provisioning`, the initial Schedule Version is approved/active, and the Schedule is recurrence-disabled with no next-run time.
- Successful finalization returns Product Task presentation plus immutable recurrence evidence containing the initial approved Schedule Version ID and create-time `initial_next_run_at`.
- There is no initial Product Run in a successful recurring create response.


## 2026-10-08 Requirement Product P1.5 internal Task update contract

- No Product HTTP route is introduced by P1.5. Internal `RequirementProductService.update_task(...)` is the service contract that P2 will expose later.
- Every update requires Task identity, user principal, idempotency key, and exactly one semantic mode:
  - in-place: `name` and/or `enabled`;
  - schedule proposal: `timezone`, `recurrence`, `run_policy`, and/or `model`.
- Mixed modes fail with `requirement_task_patch_mixed_modes` before ledger reservation. Empty patch fails with `requirement_task_patch_invalid`. Invalid timezone/name/model/recurrence/run-policy is validated before mutation; recurring enabled-state changes require superuser.
- Canonical `task_update` request hashes bind `task_id + mode + normalized patch`. Same principal/operation/key with changed Task or payload conflicts.
- Reservation persists `base_task_revision`; proposal mode also persists a preallocated `schedule_version_id`.
- Successful in-place result is bounded metadata containing Task revision/state and Schedule name/enabled/active-version/next-run snapshot. `result_task_revision` equals the single committed new revision.
- Successful schedule-proposal result contains Task ID, originating `base_task_revision`, Schedule ID, exact draft Schedule Version ID/number/digest/status. It does not expose a new Task revision; ledger `result_task_revision` remains NULL.
- Proposal retry recovers an existing exact request-owned draft before consulting current active Schedule config. P1.5 never approves or activates that draft.


## 2026-10-08 Requirement Product P1.5A internal activation contract

- Product HTTP Task routes are still not introduced in this gate. Internal `RequirementProductService.activate_task_version(...)` is the activation contract that P2 will expose later.
- Activation is superuser-only and requires `task_id`, exact `schedule_version_id`, and an idempotency key. Canonical request hashing binds both target identities.
- The draft must be proven to originate from exactly one successful Product `task_update` schedule proposal. The activation request copies that proposal's persisted `base_task_revision`; arbitrary Schedule drafts are rejected with `requirement_task_version_invalid`.
- Successful activation returns bounded metadata: Task revision/state, Schedule/version identity, approved status, enabled state, and next-run snapshot. Replay returns the same stored bounded result and does not approve or increment revision again.
- Stale originating revision terminalizes the activation with `requirement_task_conflict`; if the exact target is still draft it is retired without changing current active Schedule/Task semantics.
- The existing low-level `POST /v1/requirement-schedules/{schedule_id}/versions/{version_number}/approve` now returns 409 `requirement_product_owned_schedule` for Product-owned Schedule identities. This is an interim precheck until P1.6 makes ownership checking and mutation atomic.

## 2026-10-11 Requirement Product P1.6 low-level mutation fencing

- Product HTTP Task routes remain **NOT IMPLEMENTED** by this gate.
- Existing low-level Schedule read/history endpoints remain readable, but the public mutation endpoints for rename, recurring enable/disable, Schedule Version creation, Schedule Version approval, and manual Run materialization return HTTP 409 `requirement_product_owned_schedule` when the target identity is Product-reserved/owned.
- Existing Requirement source GET/list/preview remain unchanged. Public source PATCH and import return HTTP 409 `requirement_product_owned_source` for Product-reserved/owned source identities.
- These responses are enforced transactionally in the stores, not by a router read/precheck. Product internal orchestration uses separate reviewed internal methods and is not subject to the public low-level fence.

## 2026-10-12 Requirement Product P1.7 internal input replacement

- P1.7 provides an internal Product service entrypoint `replace_task_input(...)`; HTTP `POST /v1/requirement-tasks/{task_id}/input` remains deferred to P2.
- Idempotent `input_replace` reservations persist the Product Task/source identity, original Requirement `base_snapshot_id`, and server-preallocated `import_run_id`/`snapshot_id`. Provisioning Tasks cannot reserve replacement requests.
- Requirement Import reuses its existing preallocated-ID terminal recovery **before** parsing or classification and its same-transaction `expected_base_snapshot_id` CAS for the first import attempt. A stale uncommitted reservation terminally fails with `requirement_input_conflict`, without moving the active snapshot backward.
- Success is recorded only after proving the exact committed import/snapshot pair. A previously committed replacement can be replayed after later replacements without changing the latest active snapshot. Exposed results contain bounded IDs/status only; raw uploaded bytes, paths and prompt contents are not saved in the Product request ledger.
- Existing low-level source import remains subject to the P1.6 ownership fence; Product's internal authority route remains distinct.

## 2026-10-12 P2.1 Product API read + preview (in review)

- Router `sra_api/routers/requirement_tasks.py` exposes authenticated `GET /v1/requirement-tasks`, `GET /v1/requirement-tasks/{task_id}`, `GET /v1/requirement-tasks/{task_id}/runs`, `GET /v1/requirement-runs`, `GET /v1/requirement-runs/{run_id}`, and `GET /v1/requirement-runs/{run_id}/items` using existing Product presenters, and `POST /v1/requirement-task-previews` for db_operator+.
- Preview accepts multipart `task` JSON with explicit approved `profile_version_id` and exactly one `file` (.xlsx/.csv/.json) or `requirements_json` field; 10 MiB input cap. No import/Task/Run mutation. Full P2.2 media/expected-SHA acceptance is separate.
- All Product list/detail/run lookups use authoritative finalized Task identity; provisioning or unowned Runs are omitted/unavailable. Task and Run read access requires existing human bearer authentication. No service-key scope is introduced in P2.1.
- `requirement_product_service` is registered only when both Requirement Import and Schedule authorities start. Unavailable dependency returns bounded 503 error. Store/adapter exceptions are mapped to safe Product error codes; raw paths or backend errors are not returned.
- This PR contains NO create, PATCH, input replacement, activation, Run triggering, artifact download or Task Center UI endpoints. Their v1 gates remain pending.
