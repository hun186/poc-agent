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

## 2026-10-12 P2.1 review hardening — proposed HTTP contract (PR #288)

- `POST /v1/requirement-task-previews`: raw request body is rejected with HTTP 413 before multipart spooling if it exceeds 11 MiB including multipart framing. File content remains capped at 10 MiB. Direct `requirements_json` form fields are capped at 1 MiB to match Starlette multipart's field-size default; oversized form fields (including URL-encoded `requirements_json`) are rejected by Starlette before Product validation with framework HTTP 400. Valid-size fields that fail Product validation return stable HTTP 422 `requirement_preview_input_invalid`.
- Product HTTP previews (not internal Product create previews) cap decoded source rows at 5,000, with XLSX ZIP metadata preflight (maximum 2,000 entries, 20 MiB per member and 40 MiB aggregate expanded size). Oversized previews return 422 `requirement_preview_too_large`. API response samples at most 100 normalized rows, errors and warnings, with string values bounded to 1,024 characters. Counts cover all normalized rows in the accepted preview; `preview_truncated` denotes sample truncation.
- `GET /v1/requirement-runs`, `/{run_id}`, `/v1/requirement-tasks/{task_id}/runs` are bounded Run summary projections and do not return eagerly loaded `items`. Retrieve items with `GET /v1/requirement-runs/{run_id}/items?limit=50&offset=0` (`limit` 1–100) returning `{run_id,items,limit,offset}`.
- Task list/detail use one joined Product Task + Schedule SQL projection with `HOLDLOCK` on both tables, retaining SQL Server locks while reading both authorities rather than trusting default locking `READ COMMITTED`. Unexpected storage/presenter invariants map to masked HTTP 500 `persistence_error` rather than invalid-client-input 422.
- These adjustments remain subject to exact-head Codex re-review and deployed SQL Server/pytest acceptance; this contract does not claim operational PASS.

## 2026-10-12 P2.1 Codex round-three refinements (PR #288)

- Preview-only XLSX decoding (when `max_rows` is set) is bounded by at most 50,000 decoded cells, 128 worksheet columns and 8 MiB of decoded cell/string-value bytes; the 5,000-row and ZIP expansion caps still apply. Internal Phase 1B import without `max_rows` remains unchanged.
- `GET /v1/requirement-runs` and `GET /v1/requirement-tasks/{task_id}/runs` use a single paged joined SQL query per Run page, with inline failure-state evidence, rather than per-Run Task/Run lookups. The latter first checks the specific Product Task exists and is finalized. Public Run detail and paged Run Items stay separate.
- Product Run `links` exposes only implemented `self` and `items` relations. `artifacts` is deliberately absent until a separate, authorized P2 artifact endpoint is implemented.
- The above are code and test changes only: exact-head Codex review, runtime pytest and real SQL Server large-page/concurrency acceptance remain pending.

## 2026-10-12 P2.1 Codex round-four HTTP error and browser behavior

- A ZIP-like `.xlsx` upload whose Office workbook structure is malformed now has its parser-specific errors normalized in `read_bytes` to HTTP 422 `source_format_invalid`; unknown store/presenter `KeyError` remains a masked 500. Valid row/size rejections preserve `requirement_preview_too_large`.
- The raw request-body limiter is registered **inside** the configured CORS middleware: its HTTP 413 `requirement_preview_input_invalid` response includes allowed-origin CORS headers for browser callers. The 11 MiB pre-multipart cap is unchanged.
- Focused regressions cover valid-ZIP/invalid-workbook decoding and an oversized cross-origin preview request. Exact-head review and runtime pytest remain pending.

## 2026-10-12 P2.1 fifth-review input-error refinement

- The XLSX-only untrusted-upload parser boundary also normalizes openpyxl `TypeError` (for example malformed workbook `sheetId`) to HTTP 422 `source_format_invalid`. Unrelated Product presenter/store exceptions are not reclassified as client validation. Actual repository pytest and new exact-head review remain unverified.

## 2026-10-12 P2.1 sixth-review decoded-cell limits

- HTTP preview-only (`max_rows` supplied) CSV and JSON readers now also reject input with more than 128 columns/keys per row, 50,000 aggregate decoded cells, or 8 MiB decoded value/key bytes as `requirement_preview_too_large` (HTTP 422). CSV limits are checked before row dictionaries are appended; JSON is checked after its initial decode and before normalization. XLSX already had matching matrix bounds.
- These caps complement the existing 5,000-row limit, 10 MiB uploaded-file limit, and Starlette 1 MiB direct JSON form-field limit; none alter full internal Phase 1B reads where `max_rows=None`.
- Added sparse 128-column CSV matrix, 129-column CSV, wide JSON, and accepted small-input regressions. Actual repository pytest and exact-head Codex review remain unverified.

## 2026-10-12 P2.1 seventh-review JSON decoding boundary

- HTTP preview-only JSON arrays are processed one top-level object at a time; the complete input string may be decoded from UTF-8 but the full JSON array is **not** materialized via `json.loads()`. The reader detects the next object's boundaries while respecting nested structures and escaped strings, with a pre-object limit of 1 MiB, then enforces 5,000 rows, 128 fields/row, 50,000 total cells and 8 MiB decoded-value budget. Oversized previews return stable 422 `requirement_preview_too_large`; malformed JSON returns 422 `source_format_invalid`.
- Full internal Phase 1B JSON reads still use the preexisting whole-array parser only when `max_rows=None`. Regression tests include a 500,000-element compact array, quoted/nested values, malformed delimiters, oversized single rows and internal unbounded imports. Exact-head review and actual repository pytest/live SQL acceptance remain pending.

## 2026-10-12 P2.1 eighth-review JSON syntax/byte refinements

- Preview-only JSON's 1 MiB pre-object cap measures actual encoded UTF-8 bytes, including multibyte Chinese text, before invoking JSON decoding of that object. Element boundaries only accept a comma or closing square bracket, so invalid separator forms (e.g. `[{} } {"x":1}]`) reject as HTTP 422 `source_format_invalid`. Existing row/cell/output caps and internal Phase 1B reader behavior are unchanged. Regressions were added; exact-head review and executable pytest are still pending.

## 2026-10-12 P2.1 ninth-review JSON Unicode validation

- JSON preview's decoded-value UTF-8 budget normalizes encoding failures from invalid unpaired surrogate escapes in object keys, values and nested structures as HTTP 422 `source_format_invalid` rather than HTTP 500. Valid Unicode surrogate pairs remain accepted. This catch is local to preview row decoding and does not classify backend/storage failures as client-input errors. Exact-head review and real test execution remain outstanding.

## 2026-10-12 P2.1 tenth-review XLSX parser parity

- XLSX preview normalizes structurally invalid Office XML to 422 source_format_invalid both when openpyxl uses stdlib XML ParseError and when optional lxml emits XMLSyntaxError. The catch stays localized to user-upload XLSX reader errors; unexpected database/presenter failures remain masked 500. Added lxml-enabled malformed [Content_Types].xml fixture; actual project pytest and exact-head review still pending.

## 2026-10-12 P2.1 eleventh-review nested JSON resource controls

- Public JSON preview now enforces an additional **pre-object** nested-structure budget (5,000 structural markers per row and 100,000 total across one upload), counting syntactic container openings, separators, and object key/value colons outside JSON strings. This is in addition to the 1 MiB per-row UTF-8 byte cap and existing 5,000-row / 128-field / 50,000 top-level cell / 8 MiB decoded-value budgets. Exceeding structural bounds returns 422 `requirement_preview_too_large`. Internal Phase 1B imports without `max_rows` keep their historical semantics. Optional lxml support no longer uses try/except-wrapped imports, per project conventions. Tests added; runtime project pytest and exact-head review still pending.

## 2026-10-12 P2.1 twelfth-review JSON ingestion parity

- Uploaded JSON file and direct `requirements_json` multipart form-field previews now share the **same predecode** incremental JSON row/structure limits. The direct form's existing 1 MiB size limit remains; valid raw JSON is decoded into bounded row dictionaries then sent via the same Product preview service `requirements` input to preserve canonical input hashing/normalization. Malformed direct syntax retains 422 `requirement_preview_input_invalid`, while structurally oversized direct JSON returns 422 `requirement_preview_too_large`. Valid multirow JSON arrays retain top-level comma delimiters when the structural-token scanner checks a row's boundary. Added focused tests; hosted exact-head pytest and Codex re-review not yet verified.

## 2026-10-12 P2.1 thirteenth-review metadata/archive protections

- Public preview's `task` multipart JSON metadata is capped at 4,096 UTF-8 bytes **before** eager `json.loads` (422 `requirement_preview_input_invalid`); legitimate `profile_version_id` (max 128 chars) and `name` (max 240 chars) still fit.
- Uploaded XLSX previews scan raw ZIP EOCD plus central-directory entry headers to enforce a max of 2,000 members **before** Python `ZipFile` builds all member objects. Invalid metadata yields `requirement_preview_archive_invalid`; excessive members or ZIP64 sentinel variants yield `requirement_preview_too_large`; expanded-content limits remain. Malformed/missing/blank worksheet headers map to 422 `source_format_invalid`.
- Added narrow positive/negative tests; the new exact head still requires running actual pytest and hosted SQL Server acceptance.

## 2026-10-13 P2.1 fourteenth-review metadata encoding compatibility

- Public preview's `task` JSON metadata predecode byte ceiling is **8,192 bytes** (previous 4,096); this accommodates schema-valid maximum-length `profile_version_id` (128 code points) and `name` (240 code points) even with Python default JSON non-BMP surrogate-pair escaping, while limiting nested object preallocation. Inputs above the byte ceiling still return HTTP 422 `requirement_preview_input_invalid`, before parsing. New positive/negative regressions added; authoritative exact-head Codex review and actual runtime pytest remain pending.

## 2026-10-13 P2.1 fifteenth-review CSV predecode field budget

- Uploaded CSV Preview now preflights raw logical record field counts (**128 fields maximum**) BEFORE calling Python `csv.reader`, protecting against millions of comma-delimited columns in a <=10 MiB file. The preflight respects CSV quoted fields, doubled-quote escapes and quoted line breaks; `csv.reader` still performs actual parsing. Exceeding width maps to 422 `requirement_preview_too_large`. Previous matrix cell/row/byte budgets and non-preview Phase 1B full imports remain unchanged. New tests include 2.7 million header cells and 1 million data cells, escaped/multiline CSV and 128-field boundary. Exact-head Codex and runtime pytest remain unverified.

## 2026-10-13 P2.1 sixteenth-review XLSX no-sheet input

- XLSX preview now rejects a workbook with no declared/active worksheet as HTTP 422 `source_format_invalid`, instead of permitting an unhandled `AttributeError` to surface as HTTP 500. The check occurs immediately after selecting the configured/active sheet, before resource limits or header read. Added an archive-level regression, while exact-head Codex and repository pytest/SQL Server acceptance remain outstanding.
