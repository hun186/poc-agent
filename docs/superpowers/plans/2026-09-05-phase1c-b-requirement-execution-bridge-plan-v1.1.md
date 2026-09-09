# Phase 1C-B Requirement Execution Bridge Implementation Plan v1.1

Repository: `hun186/poc-agent`
Branch: `docs/phase1c-b-plan-v1.1-correction`
Actual hosted baseline: `cf89843daea1d3c5b51891c5bcf40c408a19b09b` (PR #211 merge; local checkout is the same commit; this checkout has no configured remote, so no newer hosted commit could be discovered)
Source snapshot: `cf89843daea1d3c5b51891c5bcf40c408a19b09b`
Design v1: `docs/superpowers/specs/2026-09-05-job-task-orchestration-boundary-design-v1.md` (still authoritative; no Design v2)
Supersedes Plan v1: `docs/superpowers/plans/2026-09-05-phase1c-b-requirement-execution-bridge-plan-v1.md`
Reason for supersession: Human/ChatGPT Plan Review v1 was **NOT PASS** because Plan v1 incorrectly treated a legitimate same-RequirementVersion successful re-run as a checkpoint conflict and omitted the first-handoff transaction that freezes the server-owned output-root fingerprint.
Status: **PLAN CORRECTION ONLY / IMPLEMENTATION NOT STARTED**

> This v1.1 correction changes only (1) same-version successful re-run/checkpoint semantics and (2) first-handoff output-root fingerprint binding. All other Design v1 and Plan v1 architecture remains unchanged. Historical Plan v1 is retained; no Design v2 is created. No Phase 1C-B, JT-1, or LangGraph implementation is authorized by this document.

Revalidation note (2026-09-09): this historical plan was authored from the PR #211 merge snapshot above. The current local checkout started at `af38b9d60bb18ba1929f7876c26c10a11fd0e161` (PR #219 merge), with no configured remote or local `main` ref; consequently `git fetch --all --prune` could not establish a newer hosted authority and `git checkout main` could not run. Source review at that local baseline confirms that Plan v1 still contains both review defects, while this v1.1 document contains the required corrections. Later commits have implemented Phase 1C-B, so the `IMPLEMENTATION NOT STARTED` statements in this plan record the plan-issuance gate rather than the current repository implementation status. This revalidation is documentation-only and makes no production, test, dependency, JT-1, or LangGraph change.

## 1. Gate contract and source reconciliation

This plan implements only **Gate 1C-B — Requirement execution compatibility bridge** after a separate human/ChatGPT plan review. Design v1 supersedes the discussion notes as architecture authority. Actual source at the snapshot confirms:

- `requirement_scheduler/migrations.py` has exact-validated canonical `SCHEMA_VERSION = 2`. `requirement_batch_runs` already owns `phase1a_source_sha256`, `phase1a_output_root_fingerprint`, counters, deadline evidence, and lifecycle timestamps. `requirement_batch_run_items` already owns `remote_job_id`, `remote_job_state`, `artifact_relative_path`, errors, expiry/deadline flags, and handoff/dispatch/remote/artifact/completion timestamps. `requirement_schedule_item_state` owns monotonic success checkpoints. The SQL audit outbox is authoritative.
- `ScheduleStore.materialize_run()` binds an approved schedule version and active Requirement snapshot, uses schedule-scoped scheduled/manual uniqueness, records immutable Requirement Version ID/number, updates seen evidence, and leaves selected items at `handoff_pending`. Disable and version activation affect future recurrence, not materialized rows.
- Report Job HTTP is `POST /v1/report/jobs`, `GET /v1/report/jobs/{job_id}`, and `GET /v1/report/jobs/{job_id}/word`; there is no cancel route. Create accepts `prompt`, optional logical `filename`/`session_id`, `model`, empty `options`, and metadata. Its owner-scoped `Idempotency-Key` returns the existing job only for the same normalized request and returns 409 for semantic conflict.
- Report Job native states are exactly `queued`, `running`, `completed`, `failed`, `interrupted`. Owner isolation is `(principal.kind, principal.subject)`. The dedicated credential therefore must resolve to the same stable logical service principal across rotation and carry create/read/download scopes.
- `ReportJobStore` is private SQLite authority. `ReportJobWorker` is a FastAPI-lifespan daemon thread; restart turns stale `running` into `interrupted`. It calls `execute_agent_turn()`, whose explicit session ID still reads mutable history, memory, last structured output, and citation reuse state. Deterministic isolation is mandatory.
- `batch_scheduler.sra_client` and `batch_scheduler.output` contain useful narrow HTTP retry/content-type and confined DOCX publication ideas, but the client currently conflates 401/403 and the controller expects `pending` although Report Job emits `queued`. Reuse requires extraction or independent bridge helpers without importing `BatchSchedulerService`, `BatchSchedulerStore`, or `batch_scheduler.store`; its SQLite lifecycle is never embedded.
- `agent/data_agent/builder.py` imports smolagents; no LangGraph source exists. The bridge remains above both frameworks and never imports Agent internals.

The two Plan v1 review findings remain present in the source snapshot: Gate A correctly permits `phase1a_output_root_fingerprint` to remain NULL at materialization, and no Gate-B terminal checkpoint implementation exists yet. They are Plan-level corrections, not a Design v1 conflict. This checkout has no configured Git remote or local `main` ref; the checked-out commit exactly matches the supplied authoritative hosted baseline. Implementation must re-fetch and rebaseline before Task 1.

## 2. Required architecture and authority

```text
Requirement Scheduler
        |
        v
Requirement Handoff Coordinator (independent CLI process)
        |
        v
Execution Submission Boundary (neutral contracts)
        |
        v
Legacy ReportJob Gateway (only native-string boundary)
        |
        v
existing /v1/report/jobs HTTP API
        |
        v
existing ReportJobWorker
        |
        v
Existing SRA / smolagents internals
```

SQL Server remains Requirement control-plane authority. The HTTP Report Job service remains legacy execution authority. Files under the configured Requirement output root become Requirement publication authority only after verified download and atomic reconciliation. No SQL transaction spans HTTP or filesystem I/O.

## 3. Frozen canonical v3 data contract

Task 1 must encode these exact names, types, ordinals, constraints, defaults, indexes, and relationships in the full catalog descriptor and explicit fresh-v3 DDL. Existing canonical-v2 objects are unchanged except the explicitly listed v3 column and constraints; Phase 1B tables are read-only.

### 3.1 `requirement_handoff_submissions` (new)

| Ordinal | Column | SQL Server contract |
|---:|---|---|
| 1 | `submission_id` | `NVARCHAR(64) NOT NULL` |
| 2 | `run_item_id` | `NVARCHAR(64) NOT NULL` |
| 3 | `workflow_id` | `NVARCHAR(64) NOT NULL` |
| 4 | `semantic_manifest_json` | `NVARCHAR(MAX) NOT NULL` |
| 5 | `semantic_fingerprint` | `CHAR(64) NOT NULL` |
| 6 | `legacy_session_id` | `NVARCHAR(240) NOT NULL` |
| 7 | `created_at` | `DATETIMEOFFSET NOT NULL` |
| 8 | `prepared_at` | `DATETIMEOFFSET NOT NULL` |

Constraints are `PK_requirement_handoff_submissions(submission_id)`, `UQ_requirement_handoff_submission_item(run_item_id)`, and `FK_handoff_submission_item(run_item_id) -> sra_schedule.requirement_batch_run_items(run_item_id) ON DELETE/UPDATE NO ACTION`. Checks are `CK_handoff_submission_workflow CHECK(workflow_id=N'report_v1')` and `CK_handoff_submission_fingerprint CHECK(semantic_fingerprint NOT LIKE '%[^0-9a-f]%' AND LEN(semantic_fingerprint)=64)`. The manifest is immutable after insert. One selected Run Item therefore has at most one logical submission; no remote state, artifact path, or completion field is duplicated here.

### 3.2 `requirement_handoff_coordinator_leases` (new)

| Ordinal | Column | SQL Server contract |
|---:|---|---|
| 1 | `control_domain` | `NVARCHAR(64) NOT NULL` |
| 2 | `owner_id` | `NVARCHAR(128) NOT NULL` |
| 3 | `lease_token` | `CHAR(64) NOT NULL` |
| 4 | `fencing_generation` | `BIGINT NOT NULL` |
| 5 | `heartbeat_at` | `DATETIMEOFFSET NOT NULL` |
| 6 | `expires_at` | `DATETIMEOFFSET NOT NULL` |
| 7 | `updated_at` | `DATETIMEOFFSET NOT NULL` |

Constraints are `PK_requirement_handoff_coordinator_leases(control_domain)`, `UQ_requirement_handoff_lease_token(lease_token)`, `CK_requirement_handoff_lease_generation CHECK(fencing_generation>0)`, and `CK_requirement_handoff_lease_window CHECK(expires_at>heartbeat_at)`. Gate B uses the singleton value `control_domain=N'requirement-report-v1'`. Each acquisition inserts generation 1 or atomically replaces only an expired row with `fencing_generation + 1`; renew requires exact domain/owner/token/generation and unexpired database time.

### 3.3 Existing Run Item v3 extension

Append `artifact_sha256 CHAR(64) NULL` to `requirement_batch_run_items`, with `CK_requirement_batch_run_item_artifact_sha256 CHECK(artifact_sha256 IS NULL OR (artifact_sha256 NOT LIKE '%[^0-9a-f]%' AND LEN(artifact_sha256)=64))`. Persisting this digest is required to distinguish the crash window “identical final file already exists” from a conflicting pre-existing file. `artifact_relative_path` remains the path authority; no absolute path is persisted.

### 3.4 Canonical manifest and identifiers

`submission_id = "rhsub_" + sha256("requirement-handoff-v1\\0" + run_item_id).hexdigest()[:48]`; `legacy_session_id = "requirement-handoff:" + submission_id`; `workflow_id = "report_v1"`. The Report Job `Idempotency-Key` is the exact `submission_id` (length 54, inside the existing 200-character API/store limit).

`semantic_manifest_json` is UTF-8 canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, no NaN) with exactly:

```json
{
  "contract_version": 1,
  "workflow_id": "report_v1",
  "source_identity": {
    "schedule_id": "...", "schedule_version_id": "...", "batch_run_id": "...",
    "run_item_id": "...", "snapshot_id": "...", "requirement_id": "...",
    "requirement_version_id": "...", "requirement_version_number": 1
  },
  "execution_input": {
    "resolved_prompt": "...", "resolved_model": "...",
    "output_contract": "docx_v1", "logical_filename": "..."
  },
  "execution_policy": {
    "deadline_at": "RFC3339 UTC seconds", "legacy_session_id": "requirement-handoff:rhsub_..."
  }
}
```

`semantic_fingerprint = sha256(semantic_manifest_json.encode("utf-8")).hexdigest()`. Prompt input is reconstructed from the exact immutable Requirement Version content through the existing Phase 1B store/query boundary and a versioned `report_v1` template; model comes from the bound approved Schedule Version; logical filename is deterministically `requirement-<safe requirement_id>-v<requirement_version_number>.docx`; deadline is reconstructed from the exact immutable Requirement Version `expires_at` bound by the Run Item (with the item selection evidence checked), never from a mutable latest row. Mutable latest rows, conversation sessions, credentials, coordinator ID/token/generation, retries, polling timestamps, trace IDs, and business actor do not enter the manifest. Every replay reconstructs and byte-compares JSON, fingerprint, session, workflow, and submission; any drift raises `internal_contract_violation` and does not POST with a new key.

## 4. Neutral contracts and state machine

Create immutable dataclasses/enums in `requirement_scheduler/execution.py`:

```python
class ExecutionState(StrEnum):
    PENDING="pending"; RUNNING="running"; RECONCILING="reconciling"
    RECOVERY_REQUIRED="recovery_required"; COMPLETED="completed"; FAILED="failed"

class FailureCategory(StrEnum):
    TRANSPORT_AMBIGUOUS="transport_ambiguous"; REMOTE_UNAVAILABLE="remote_unavailable"
    AUTHENTICATION_FAILED="authentication_failed"; AUTHORIZATION_FAILED="authorization_failed"
    SEMANTIC_CONFLICT="semantic_conflict"; REMOTE_EXECUTION_FAILED="remote_execution_failed"
    DEADLINE_EXCEEDED="deadline_exceeded"; ARTIFACT_INVALID="artifact_invalid"
    ARTIFACT_PUBLICATION_FAILED="artifact_publication_failed"
    RECONCILIATION_UNKNOWN="reconciliation_unknown"; PERSISTENCE_FAILED="persistence_failed"
    INTERNAL_CONTRACT_VIOLATION="internal_contract_violation"

@dataclass(frozen=True)
class ExecutionHandle: submission_id: str; remote_job_id: str
@dataclass(frozen=True)
class ExecutionStatus: state: ExecutionState; native_observed_at: datetime; safe_error: ExecutionFailure|None
@dataclass(frozen=True)
class ExecutionFailure: category: FailureCategory; safe_message: str; retryable_operation: bool
class ExecutionGateway(Protocol):
    def submit(self, manifest: ExecutionManifest, *, idempotency_key: str) -> ExecutionHandle: ...
    def inspect(self, handle: ExecutionHandle) -> ExecutionStatus: ...
    def download_artifact(self, handle: ExecutionHandle) -> bytes: ...
```

Only `requirement_scheduler/legacy_report_job_gateway.py` sees native states: `queued -> pending`, `running -> running`, `completed -> completed`, `failed -> failed`, `interrupted -> recovery_required`; unknown starts `reconciling` and becomes `recovery_required` after bounded re-inspection. Requirement control logic never compares native strings. There is no cancel method because the backend has no authoritative cancel capability.

Existing `execution_state` uses these Gate-B transitions: `handoff_pending -> submitting -> pending -> running|reconciling -> completed|failed|recovery_required`; pre-submit expiry is `handoff_pending -> expired`; artifact processing keeps remote truth `completed` but item state `reconciling` until publication, then `completed`, or `recovery_required` on irreconcilable artifact/deadline ambiguity. CAS always includes expected item state plus active lease `control_domain`, `owner_id`, `lease_token`, `fencing_generation`, and `expires_at > database_now`.

## 5. Retry, deadline, security, audit, and artifact rules

- Bounded automatic retries apply only to the same-submission POST after timeout/connection/429/502/503/504, status polling of the same `remote_job_id`, and artifact download of that same job. Exponential backoff is capped and interruptible. 401 maps to `authentication_failed`, 403 to `authorization_failed`, 409 to `semantic_conflict`; each stops active retry. Unknown/malformed responses fail closed.
- Remote `failed` or `interrupted`, deadline ambiguity, invalid/publication-failed artifacts, and 409 never create another Report Job, submission, run, or key. A failed/ambiguous run never self-materializes a replacement. Lease expiry only removes ownership; successor reconciliation decides truth.
- Deadline cannot fabricate cancellation/failure. Since Report Job has no cancel API, an overdue active/unknown job is reconciled and becomes `recovery_required` if truth remains unresolved. The bridge never kills the worker, edits Report Job SQLite, or deletes its artifact.
- `RequirementHandoffConfig` resolves API base URL, stable logical service-principal name, credential reference/value, connect/read timeouts, poll interval, heartbeat interval, lease duration, retry/backoff limits, batch size, and server-owned output root at runtime. Require `heartbeat_interval < lease_duration / 3`, positive bounded values, HTTPS except explicit test/local policy, and create/read/download scopes. No secret is persisted/logged/audited/fingerprinted. Principal rotation must preserve the owner subject or existing jobs become inaccessible and startup fails closed.
- Every Gate-B domain mutation inserts an outbox event in the same SQL transaction. Extend `_audit_event()` positive allowlists for `requirement_handoff.prepared`, `.dispatched`, `.reconciled`, `.remote_authorization_failed`, `.artifact_reconciled`, `.item_completed`, `.item_failed`, and `.item_recovery_required`. Allowed payload keys are only applicable safe IDs (including Batch Run ID and Run Item ID), workflow ID, output-root fingerprint, fencing generation, neutral state/category, artifact digest, and relative artifact ref; never prompt/Requirement text, token, raw body, SQL/ODBC text, traceback, absolute path, arbitrary metadata, backend trace, or LangGraph state. Report Job continues to own its security/authorization audit.
- Output-root lifecycle is authoritative and one-way: materialization may leave `phase1a_output_root_fingerprint` NULL; the first Gate-B Prepare resolves the currently configured server-owned Requirement artifact root, canonicalizes its identity, computes a non-secret SHA-256 fingerprint, and binds it exactly once before any remote side effect. If already non-NULL, exact equality permits replay/reconciliation without rewriting; mismatch fails closed before POST, download, or publication. Schedule configuration change, process restart, or deployment configuration change can never rebind an existing Run. Submit, acknowledge, reconcile, download, publish, and terminal closure all verify the exact frozen fingerprint. The output root is server authority and never caller authority.
- Artifact destination derives from the frozen `phase1a_output_root_fingerprint` and configured server root. Each resume verifies `sha256(normalized server-owned root identity)` equals the snapshot before filesystem access. Resolve a deterministic contained relative path from Run/Item identity and logical filename. Download to a same-directory temp file, flush/fsync, verify content type at the gateway, ZIP integrity and required `[Content_Types].xml` plus `word/document.xml`, compute SHA-256, then atomically create the final file and fsync the directory. Never overwrite. If final exists, validate and hash it: matching expected/download digest is reconciled; mismatch is `artifact_publication_failed`/`recovery_required`. Persist only relative path and digest.

## 6. Transaction and startup algorithms

**Prepare (SQL TX #1):** begin the SQL transaction; prove the active lease/fence; lock the selected `handoff_pending` item and its owning Batch Run plus bound version/snapshot/Requirement Version; prove schedule changes do not alter materialized identities; and perform the second database-time expiry check. If expired, atomically mark the item expired, close eligible counters without checkpoint, enqueue safe audit, and commit without submission or root binding. Otherwise resolve the current server-owned Requirement artifact output root, canonicalize its identity, and compute its non-secret fingerprint. Inspect the locked Run's `phase1a_output_root_fingerprint`: when NULL, CAS NULL to the computed fingerprint under the active lease/fence and expected Run state; when non-NULL and equal, retain it byte-for-byte; when non-NULL and different, fail closed and roll back. Then reconstruct the immutable manifest, insert or verify the stable submission, CAS `handoff_pending -> submitting`, stamp handoff timestamps, update Run evidence, enqueue `prepared` audit (safe IDs/workflow/fingerprint only), and commit. Only after commit may `POST /v1/report/jobs` occur; no SQL transaction spans HTTP. A failure after fingerprint binding but before submission insert rolls the fingerprint back to NULL, and a failure after submission insert rolls back both binding and submission.

**Submit:** POST the exact legacy payload (`prompt`, logical filename, deterministic session, approved model, `{}` options, allowlisted correlation metadata only) with Bearer credential and `Idempotency-Key=submission_id`. A timeout may mean remote creation succeeded.

**Acknowledge (SQL TX #2):** re-prove active lease/fence, reconstruct/compare immutable submission semantics, CAS expected `submitting|reconciling`, set existing `remote_job_id`, translated `remote_job_state`, `dispatched_at`, Run `handed_off_at`, and enqueue `dispatched`; commit. A stale response cannot update SQL. If remote success occurred but ACK was lost, restart replays exactly the same POST, which returns the same owner-scoped job; it never changes key/session/payload.

**Reconcile before new work:** initialize/validate v3, acquire lease, scan bounded existing submissions in `submitting`, `pending`, `running`, and `reconciling` order by `handoff_started_at,run_item_id`; first replay missing-ACK submissions, then inspect known jobs, then recover completed artifacts/terminal closure. Only after this backlog is boundedly processed may the loop prepare new `handoff_pending` items.

**Terminal closure (one SQL transaction):** re-prove fence and expected item state; for success prove remote completion, artifact relative path/digest/reconciliation, and exact equality with the frozen output-root fingerprint. Run Item terminal success and Requirement checkpoint advancement are distinct outcomes: a valid successful item may be terminal `completed` while checkpoint advancement is a no-op. CAS the item terminal, recompute Run counters from authoritative item rows (not increments), and derive Run terminality. Lock the Requirement checkpoint and apply exactly:

- **A — no prior successful checkpoint:** advance to the incoming RequirementVersion ID/number and Run Item.
- **B — stored version number lower than incoming:** advance to the incoming identity and Run Item.
- **C — stored version number higher than incoming:** allow current Run Item success; leave checkpoint unchanged (no regression).
- **D — equal version number and equal immutable `requirement_version_id`:** allow current Run Item success and leave checkpoint unchanged, whether `last_successful_run_item_id` equals or differs from the current Run Item. Same-item replay is idempotent; a different-item intentional same-version business re-run is also valid.
- **E — equal version number but different `requirement_version_id`:** fail closed as an immutable identity/monotonic-number consistency anomaly.

Insert terminal item/Run/audit evidence in the same transaction and commit. Failed, expired, interrupted/`recovery_required`, deadline ambiguity, or invalid/unreconciled artifact never advances checkpoint. Failure injection must prove item/counters/checkpoint/outbox all roll back together. A successful lower-version or same-version execution is never converted into execution failure merely because checkpoint advancement is a no-op.

## 7. TDD implementation tasks

Each task is an independently reviewable RED -> minimal GREEN commit. Rebaseline hosted `main` and update the plan header/source facts before executing any task if it advanced.

### Task 1 — Canonical schema v3 and transactional v2 -> v3 migration

**Goal:** Make v3 the only accepted Gate-B catalog without weakening v2 authority.
**Files:** Modify `requirement_scheduler/migrations.py`, `requirement_scheduler/store.py`; create `tests/test_requirement_schedule_v3_migration.py`.
**Interfaces:** `SCHEMA_VERSION = 3`; `canonical_v3_statements(schema, requirement_schema) -> list[str]`; `migration_2_to_3_statements(schema) -> list[str]`; complete v2/v3 descriptors.
**Dependencies:** Accepted exact canonical v2 classifier and stateful DB-API harness from `tests/test_requirement_schedule_v5_closure.py`.

**Failing tests first:** Fresh v3 exact catalog; existing v3 validation-only; exact v2 recognition then migration; malformed/hybrid/extra object/marker mismatch rejection; no Phase 1B mutation; rollback injection before/after every DDL, postvalidation, marker CAS/re-read, and commit.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_v3_migration.py --tb=short`
**Expected failure:** imports/constants and v3 tables/column are absent; current initializer accepts only marker 2.
**Minimal implementation steps:** Freeze the v2 predecessor descriptor unchanged; explicitly generate full fresh-v3 DDL (all v2 objects plus §3 objects/column); lock singleton marker; classify complete v2 before mutation; add `artifact_sha256`, both tables, keys/checks/indexes in one transaction; validate full v3 catalog; CAS marker `2 -> 3` last with rowcount one; re-read marker/catalog; commit. Fresh creates v3 directly. Existing v3 does zero DDL/DML. Reject 0 in established schema, v1, malformed v2, hybrid v2/v3, future marker, and unknown objects.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_v3_migration.py tests/test_requirement_schedule_v5_closure.py --tb=short`
**Expected PASS:** every catalog/migration/rollback case passes and historical v2 closure evidence remains green.
**Commit boundary:** `feat(requirement-scheduler): add canonical handoff schema v3`.

### Task 2 — Submission manifest, identity, fingerprint, and isolated session

**Goal:** Produce and durably verify one immutable semantic submission per selected item.
**Files:** Create `requirement_scheduler/execution.py`, `requirement_scheduler/handoff.py`, `tests/test_requirement_handoff_manifest.py`; modify `requirement_scheduler/store.py`.
**Interfaces:** `ExecutionManifest`, `build_execution_manifest(materialized_source)`, `semantic_fingerprint(manifest)`, `ScheduleStore.prepare_or_verify_submission(...)`.
**Dependencies:** Task 1 schema.

**Failing tests first:** Stable ID/fingerprint/session; exact manifest field/type/UTC encoding; one item -> one submission; same replay byte equality; duplicate race returns the winner only if identical; prompt/model/filename/deadline/source drift fails closed; operational metadata exclusion; no mutable-latest lookup.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_manifest.py --tb=short`
**Expected failure:** modules and submission store methods do not exist.
**Minimal implementation steps:** Add frozen types and canonical serializer from §§3–4; reconstruct via exact joins on materialized IDs; insert under unique Run Item constraint; on duplicate re-read and constant-time compare all immutable fields; return `internal_contract_violation` on any difference. Do not add Task/Attempt concepts.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_manifest.py tests/test_requirement_schedule_materialization.py --tb=short`
**Expected PASS:** deterministic/replay/race/drift cases pass without changing Gate-A materialization.
**Commit boundary:** `feat(requirement-scheduler): persist immutable handoff manifests`.

### Task 3 — Coordinator lease and fencing

**Goal:** Guarantee one active coordinator and reject every stale mutation/HTTP response.
**Files:** Create `requirement_scheduler/lease.py`, `tests/test_requirement_handoff_lease.py`; modify `requirement_scheduler/store.py`.
**Interfaces:** `LeaseProof(control_domain, owner_id, lease_token, fencing_generation, expires_at)`; `acquire_lease`, `renew_lease`, `release_lease`, and fenced CAS helpers.
**Dependencies:** Task 1.

**Failing tests first:** first owner, concurrent loser, exact renew, expiry, successor generation increment, stale owner/token/generation rejection, database-time boundary, overflow fail-closed, stale post-HTTP ACK rejection.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_lease.py --tb=short`
**Expected failure:** no lease persistence/API exists.
**Minimal implementation steps:** Generate owner and random opaque 64-hex token at startup; use `UPDLOCK,HOLDLOCK` and database UTC; insert or expired-row CAS takeover; increment BIGINT generation with overflow guard; renew only exact active proof; make every Gate-B store mutation join/check lease proof in the same transaction. Release is best-effort exact-proof expiry and never transfers authority.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_lease.py tests/test_requirement_schedule_transactions.py --tb=short`
**Expected PASS:** exactly one active proof exists and stale effects are fenced.
**Commit boundary:** `feat(requirement-scheduler): add coordinator lease fencing`.

### Task 4 — Legacy ReportJob Gateway and neutral state/error contract

**Goal:** Isolate all HTTP/native Report Job semantics behind the neutral boundary.
**Files:** Create `requirement_scheduler/legacy_report_job_gateway.py`, `requirement_scheduler/config.py`, `tests/test_requirement_report_job_gateway.py`; optionally extract backwards-compatible narrow transport code from `batch_scheduler/sra_client.py` without importing its store/service.
**Interfaces:** `ExecutionGateway` from §4 and `LegacyReportJobGateway(config, session, sleep)`; runtime credential resolver callable.
**Dependencies:** Task 2 contracts; actual Report Job API.

**Failing tests first:** POST success; queued/running/completed/failed/interrupted/unknown translation; timeout, connection error, 401, 403, 409, 429, 502/503/504; invalid JSON/shape/job ID/content type; bounded attempts; exact payload/key/session; no credential disclosure.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_report_job_gateway.py --tb=short`
**Expected failure:** gateway is absent; current Batch client maps wrong state/credential granularity.
**Minimal implementation steps:** Implement three HTTP methods only; separate authentication/authorization/conflict/transient/contract categories; parse with strict allowlisted fields; translate native strings in one function; keep response bodies out of raised safe failures; preserve Batch Scheduler public behavior if a helper is extracted.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_report_job_gateway.py tests/test_report_jobs_api.py tests/test_batch_scheduler_client.py --tb=short`
**Expected PASS:** full HTTP/state matrix passes and legacy suites remain green.
**Commit boundary:** `feat(requirement-scheduler): add legacy report job gateway`.

### Task 5 — Fenced second-expiry prepare transaction

**Goal:** Persist intent/audit before remote I/O and prevent expired submissions.
**Files:** Modify `requirement_scheduler/handoff.py`, `requirement_scheduler/store.py`; create `tests/test_requirement_handoff_prepare.py`.
**Interfaces:** `prepare_next(lease, now_utc) -> PreparedHandoff | None`; bounded eligible-item query.
**Dependencies:** Tasks 2–3.

**Failing tests first:** eligible selected item; second expiry at/either side of deadline; first prepare with NULL fingerprint binds it before transport; same root replay accepts without rewrite; root change before first prepare binds the then-authoritative root; root change after binding fails before POST; restart with same root succeeds and restart with changed root fails; failure after fingerprint write/before submission rolls back fingerprint to NULL; failure after submission insert rolls back fingerprint and submission; stale owner cannot bind/change; schedule disabled/version changed after materialization still eligible; duplicate race; outbox rollback; no HTTP inside transaction.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_prepare.py --tb=short`
**Expected failure:** no prepare transaction exists.
**Minimal implementation steps:** Implement SQL TX #1 from §6 with database time, exact immutable joins, locked Batch Run and one-time root-fingerprint CAS/verification, submission insert/verification, `handoff_pending -> submitting` CAS, Run timestamps, and `requirement_handoff.prepared` outbox. Expiry marks `expired_before_handoff=1`, never creates a submission, and atomically updates eligible terminal counters/audit without checkpoint.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_prepare.py tests/test_requirement_schedule_deadlines.py --tb=short`
**Expected PASS:** expiry/race/fence/audit cases pass and zero transport calls occur before commit.
**Commit boundary:** `feat(requirement-scheduler): prepare fenced handoff intent`.

### Task 6 — Submit crash window and idempotent acknowledgement

**Goal:** Survive ambiguous POST and lost local ACK without duplicate execution.
**Files:** Modify `requirement_scheduler/handoff.py`, `requirement_scheduler/store.py`; create `tests/test_requirement_handoff_submit.py`.
**Interfaces:** `submit_prepared(prepared, lease)`, `acknowledge_submission(..., expected_state, lease)`.
**Dependencies:** Tasks 4–5.

**Failing tests first:** success; timeout before known outcome; remote created/ACK rollback or process crash; replay same job; 409 conflict no new key; stale HTTP response fenced; persistence failure; 401/403 stop; 429/5xx bounded same-submission retry.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_submit.py --tb=short`
**Expected failure:** no dispatch workflow exists.
**Minimal implementation steps:** Commit TX #1; call gateway outside SQL; preserve byte-identical request; execute fenced TX #2 CAS to persist existing Run Item remote fields/timestamps and audit. On ambiguous transport set/recover `reconciling` under fence, never create a replacement.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_submit.py tests/test_report_job_store.py --tb=short`
**Expected PASS:** ACK-loss replay resolves one remote job and all stale/conflict/security paths fail closed.
**Commit boundary:** `feat(requirement-scheduler): submit and acknowledge idempotent handoffs`.

### Task 7 — Startup and ongoing reconciliation

**Goal:** Reconcile unfinished authority before admitting new handoffs.
**Files:** Create `requirement_scheduler/reconciliation.py`, `tests/test_requirement_handoff_reconciliation.py`; modify `requirement_scheduler/handoff.py`, `requirement_scheduler/store.py`.
**Interfaces:** `reconcile_batch(lease, limit, now_utc) -> ReconcileResult`; deterministic state/order query.
**Dependencies:** Task 6.

**Failing tests first:** missing ACK replay; pending/running polling; failed closure; interrupted recovery-required; unknown then bounded recovery-required; deadline during active execution; lease loss; stale response; new work blocked until startup batch; no new Report Job after terminal state.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_reconciliation.py --tb=short`
**Expected failure:** reconciliation module absent.
**Minimal implementation steps:** Implement §6 ordering, bounded same-remote polling, Run `reconciled_at`, item neutral state/error, and same-transaction action audit. Unknown/overdue unresolved truth halts at `recovery_required`; do not fabricate cancellation or failure.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_reconciliation.py tests/test_report_jobs_lifecycle.py --tb=short`
**Expected PASS:** every restart/native/unknown/deadline case preserves one submission/remote job.
**Commit boundary:** `feat(requirement-scheduler): reconcile unfinished report handoffs`.

### Task 8 — Safe DOCX publication and crash reconciliation

**Goal:** Make artifact publication confined, durable, digest-proven, and restart-safe.
**Files:** Create `requirement_scheduler/artifacts.py`, `tests/test_requirement_handoff_artifacts.py`; modify `requirement_scheduler/handoff.py`, `requirement_scheduler/store.py`; optionally extract a narrow helper from `batch_scheduler/output.py` while keeping its behavior.
**Interfaces:** `ArtifactPublisher(root).publish_or_reconcile(run_item_id, logical_filename, bytes, expected_root_fingerprint) -> PublishedArtifact(relative_path, sha256)`.
**Dependencies:** Tasks 4 and 7; v3 digest column.

**Failing tests first:** exact previously bound fingerprint is required for publication; valid DOCX; invalid ZIP; missing required entries; root drift; replay/restart same root; changed-root restart fails closed; traversal/containment; temp flush/fsync/atomic rename; identical existing artifact after crash; different existing artifact; publication error; persisted digest mismatch; relative-only persistence; no blind overwrite.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_artifacts.py --tb=short`
**Expected failure:** existing helper rejects all pre-existing files and has no digest/root-snapshot reconciliation.
**Minimal implementation steps:** Implement §5 algorithm; gateway validates media type, publisher validates package; use deterministic Run/Item relative destination; compare existing validated digest rather than delete; fenced SQL records `artifact_relative_path`, `artifact_sha256`, `artifact_reconciled_at`, and audit only after filesystem proof.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_artifacts.py tests/test_batch_scheduler_security.py tests/test_report_job_worker.py --tb=short`
**Expected PASS:** valid/crash paths reconcile and all ambiguous/security paths fail closed without overwrite.
**Commit boundary:** `feat(requirement-scheduler): publish reconciled requirement artifacts`.

### Task 9 — Atomic terminal counters and monotonic checkpoint closure

**Goal:** Define Requirement success strictly beyond remote completion.
**Files:** Modify `requirement_scheduler/store.py`, `requirement_scheduler/handoff.py`; create `tests/test_requirement_handoff_completion.py`.
**Interfaces:** `close_completed_item(lease, evidence)`, `close_failed_or_recovery_item(lease, failure)`.
**Dependencies:** Task 8.

**Failing tests first:** no previous success advances checkpoint; older stored version advances; newer stored version allows current item success with checkpoint unchanged; same version + same `requirement_version_id` + same Run Item is idempotent success; same version + same `requirement_version_id` + DIFFERENT Run Item allows current item success with checkpoint unchanged; same version number + DIFFERENT `requirement_version_id` fails closed; lower-version successful completion allows item success without checkpoint regression; invalid artifact no checkpoint; failure no checkpoint; `recovery_required` no checkpoint; expired no checkpoint; exact Run counters; atomic item/counters/checkpoint/audit rollback at every statement.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_completion.py --tb=short`
**Expected failure:** no Gate-B closure methods exist.
**Minimal implementation steps:** Implement terminal TX in §6 with locks/CAS and recomputed counters. Require all six success proofs before item success. Separate terminal success from checkpoint advancement; implement Cases A–E in §6 with version-number ordering and equal-number immutable RequirementVersion identity guard; enqueue completion/failure/recovery audit in the transaction.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_completion.py tests/test_requirement_schedule_checkpoints.py tests/test_requirement_schedule_transactions.py --tb=short`
**Expected PASS:** valid same/lower-version business executions can succeed with checkpoint no-op; checkpoint never regresses/advances on identity ambiguity and injected failure rolls back the entire closure.
**Commit boundary:** `feat(requirement-scheduler): close handoffs atomically`.

### Task 10 — Independent Coordinator CLI loop

**Goal:** Run Gate B as a separately supervised, lease-owning process.
**Files:** Create `requirement_scheduler/coordinator.py`, `requirement_scheduler/cli.py`, `requirement_scheduler/__main__.py`, `tests/test_requirement_handoff_coordinator.py`; modify only configuration wiring documentation as needed.
**Interfaces:** `RequirementHandoffCoordinator.run(stop_event)`, `run_once()`, CLI `python -m requirement_scheduler handoff-worker`.
**Dependencies:** Tasks 3 and 7–9.

**Failing tests first:** initialize -> acquire -> reconcile -> new work ordering; poll cadence; bounded batch; heartbeat; graceful SIGTERM/KeyboardInterrupt; lease loss immediate I/O stop; crash restart; transient idle; auth failure halt; invalid config.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_coordinator.py --tb=short`
**Expected failure:** no coordinator entry point exists.
**Minimal implementation steps:** Add explicit dependency construction and interruptible waits. Default finite configuration: poll 2s, heartbeat 10s, lease 45s, batch 20, request retries 3, capped backoff 5s (all configurable within validated bounds). Renew before work and between remote stages; on loss discard responses and exit nonzero. Do not alter `sra_api/main.py` or start a FastAPI thread.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_coordinator.py tests/test_batch_scheduler_cli.py --tb=short`
**Expected PASS:** lifecycle ordering and shutdown/ownership behavior pass with no embedded scheduler.
**Commit boundary:** `feat(requirement-scheduler): add external handoff coordinator`.

### Task 11 — Existing management/manual/status API integration

**Goal:** Expose existing materialization and neutral status without adding execution-control or cancel APIs.
**Files:** Modify existing Requirement Schedule router located by rebaseline (`sra_api/routers/requirement_schedules.py` if still current), its schemas/service, and `tests/test_requirement_schedule_api.py`; no Report Job route changes.
**Interfaces:** Preserve schedule-scoped manual `trigger_request_id`; status adds neutral item execution/error and relative artifact evidence already owned by SQL. No remote owner, native state, absolute path, prompt, credential, retry, or cancel field.
**Dependencies:** Tasks 4 and 9.

**Failing tests first:** same schedule+manual identity same Run; different schedule scope/new identity new current-source Run; disabled schedule policy as already specified; status owner/RBAC; native strings absent; no cancel/retry endpoint; pagination bounds.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py tests/test_requirement_schedule_materialization.py --tb=short`
**Expected failure:** Gate-A API cannot present finalized neutral Gate-B evidence.
**Minimal implementation steps:** Reuse existing manual materialization endpoint rather than create a replacement; map persisted neutral state through response schema; preserve prospective disable/version semantics. Do not synchronously execute or wake a FastAPI worker.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_schedule_api.py tests/test_requirement_schedule_materialization.py tests/test_requirement_schedule_service.py --tb=short`
**Expected PASS:** manual/status/RBAC contracts pass without execution-control expansion.
**Commit boundary:** `feat(requirement-scheduler): expose neutral handoff status`.

### Task 12 — Security, audit, and credential failure matrix

**Goal:** Prove principal separation, safe evidence, and same-transaction Gate-B audits.
**Files:** Modify `requirement_scheduler/store.py`, config/gateway; create `tests/test_requirement_handoff_security_audit.py`.
**Interfaces:** Action allowlists and `CredentialProvider.resolve(logical_principal) -> SecretStr/value-at-call-time`; no impersonation inputs.
**Dependencies:** Tasks 4–11.

**Failing tests first:** stable service owner across credential rotation; wrong owner inaccessible; missing/401/403 halt; no `X-Run-As`, owner payload, metadata owner; each required action; allowlist rejection; domain+outbox rollback; secret/prompt/body/error/path/trace exclusion; existing Report Job denial audit unchanged.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_security_audit.py --tb=short`
**Expected failure:** Gate-B actions/provider do not exist.
**Minimal implementation steps:** Extend positive allowlists exactly; resolve credential immediately before each call; use business actor only for origin/correlation audit; sanitize all failure messages to stable codes; add no credential columns/config serialization.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_security_audit.py tests/test_report_jobs_api.py tests/test_requirement_schedule_audit_outbox.py --tb=short`
**Expected PASS:** security/audit matrix passes with no sensitive evidence.
**Commit boundary:** `feat(requirement-scheduler): enforce handoff security audit contract`.

### Task 13 — Cross-phase regression and forbidden-boundary gates

**Goal:** Prove Gate B did not absorb legacy controllers or future architecture.
**Files:** Create `tests/test_requirement_handoff_boundaries.py`; change production only to remove violations found by RED.
**Interfaces:** AST/import and schema-catalog negative assertions.
**Dependencies:** Tasks 1–12.

**Failing tests first:** production import graph rejects `smolagents`, `langgraph`, `agent.agent`, `agent.report_agent`, `ReportJobWorker`, `ReportJobStore`, `batch_scheduler.store`; catalog rejects Task/Attempt/Event Store/queue tables; no Report Job/Batch SQLite opens; no FastAPI lifespan coordinator; no dependency changes; no cancel engine. Tests may inspect prohibited modules only as negative evidence.
**Exact test command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_boundaries.py --tb=short`
**Expected failure:** initially catches any boundary drift introduced by prior tasks, or passes immediately when boundaries are clean.
**Minimal implementation steps:** Use AST/import graph and exact catalog assertions; remove any prohibited coupling rather than allowlist it. Run Phase 1C, Report Job, Batch Scheduler, Phase 1B/security, then full suite after dependency preflight.
**Exact verification command:** `PYTHONPATH=. pytest -q tests/test_requirement_handoff_boundaries.py tests/test_requirement_schedule_*.py tests/test_report_job*.py tests/test_batch_scheduler_*.py --tb=short`
**Expected PASS:** boundary and cross-phase suites pass; no forbidden module or schema appears.
**Commit boundary:** `test(requirement-scheduler): lock execution bridge boundaries`.

### Task 14 — Documentation, persistent memory, and acceptance handoff

**Goal:** Record actual implementation evidence without self-awarding deployment acceptance.
**Files:** Modify `.codex/memory.md`, `.codex/architecture.md`, `.codex/api_contract.md`, `.codex/known_issues.md`, `.codex/decisions.md`, `.codex/backlog.md`, and this plan only where actual reviewed implementation differs; create operator documentation only if required by established convention.
**Interfaces:** Final acceptance checklist and commands below.
**Dependencies:** Tasks 1–13 complete; hosted rebaseline recorded.

**Failing tests first:** Documentation assertions verify schema/state/action names, plan task completion evidence, exact source SHA, and mandatory NOT EXECUTED wording.
**Exact test command:** `python - <<'PY'
from pathlib import Path
p=Path('docs/superpowers/plans/2026-09-05-phase1c-b-requirement-execution-bridge-plan-v1.md').read_text()
for x in ('schema v3','requirement_handoff_submissions','requirement_handoff_coordinator_leases','Phase 1C-B'):
    assert x in p
PY`
**Expected failure:** memory/API/architecture still describe Gate B as entirely absent until implementation evidence is recorded.
**Minimal implementation steps:** Update persistent memory by append/required compaction, preserve history, record RED/GREEN outputs and limitations, and keep JT-1/LangGraph future. Install dependencies before pytest per repository policy; do not use credentials or live SQL without authorization.
**Exact verification command:** `python -m compileall -q requirement_scheduler sra_api batch_scheduler tests && PYTHONPATH=. pytest -q tests --tb=short && git diff --check`
**Expected PASS:** compile/full repository/static checks pass; live SQL/private Agent E2E is explicitly NOT EXECUTED unless separately authorized.
**Commit boundary:** `docs: record phase1c-b bridge acceptance evidence`.

## 8. Consolidated acceptance matrix

The task tests collectively must prove: fresh v3, canonical v2 -> v3, failure rollback at every boundary, malformed/hybrid/marker/extra-object rejection, complete postvalidation; stable one-to-one submission/semantic fingerprint/session/replay/race; first-prepare output-root binding before transport, same-root replay/restart, pre-bind current-root authority, post-bind drift rejection, stale-fence rejection, and transactional binding/submission rollback; lease acquire/renew/expiry/successor/stale fencing; every POST/timeout/ACK-loss/replay/409/401/403/429/502/503/504/shape case; all five native states plus unknown; valid/invalid/missing-entry/root/path/existing-identical/existing-different/publication/digest artifact cases; completed+artifact success; no-prior/older checkpoint advancement; newer/lower incoming successful completion with checkpoint no-op; same-version same-RequirementVersion same/different-item success with checkpoint no-op; equal-number different-RequirementVersion fail-closed; failure/recovery_required/expired/invalid-artifact no checkpoint; atomic item/counter/checkpoint/audit rollback; prospective disable/version changes, pre-handoff expiry, manual identity idempotency/new identity; and every forbidden import/storage/platform assertion.

Final implementation verification commands (after required `python -m pip install --upgrade pip` and `python -m pip install -r requirements.txt`) are:

```bash
PYTHONPATH=. pytest -q tests/test_requirement_handoff_*.py tests/test_requirement_report_job_gateway.py tests/test_requirement_schedule_v3_migration.py --tb=short
PYTHONPATH=. pytest -q tests/test_requirement_schedule_*.py tests/test_report_job*.py tests/test_batch_scheduler_*.py --tb=short
PYTHONPATH=. pytest -q tests --tb=short
python -m compileall -q requirement_scheduler sra_api batch_scheduler tests
git diff --check
! rg -n '(^| )(from|import) (smolagents|langgraph|agent\.agent|agent\.report_agent)|ReportJobWorker|ReportJobStore|batch_scheduler\.store' requirement_scheduler --glob '*.py'
```

## 9. Explicit non-scope

Phase 1C-B does **not** add LangGraph or its dependency/checkpointing; Task table; Attempt table; Execution Event Store; generic Job Task API or execution queue; production Workflow Registry, Runtime Profile, or Capability Profile infrastructure; smolagents/direct Agent orchestration refactor; ReportJobWorker or ReportJobStore replacement/access; Report Job SQLite access; Batch Scheduler SQLite access; automatic failed execution retry; backend cancel engine; or FastAPI scheduler/coordinator thread. It does not implement JT-1/JT-2+, rename the legacy worker as a future worker, or claim distributed exactly-once behavior.

## 10. Design v1 coverage matrix

| Design authority | Gate classification | Plan task(s) |
|---|---|---|
| §§1–4 source/boundary/gates | Implement bridge only; JT-1/JT-2 frozen | 1, 4, 10, 13 |
| §5 and decisions 1–10 | Framework-neutral boundary now; registry/adapters mostly JT-1/JT-2 | 2, 4, 13; future items explicitly non-scope |
| §6 and decisions 11–27 | Task/Attempt/Execution Worker future; only coordinator lease, neutral translation/recovery apply now | 3, 4, 7, 10, 13 |
| §7 and decisions 28–29 | Execution Event Store future; Gate-B artifact/error/audit separation now | 4, 8, 9, 12, 13 |
| §8 and decisions 30–44 | Profiles/port/LangGraph future; fixed `report_v1`, runtime secret and no backend authority apply now | 2, 4, 12, 13 |
| §9.1–9.4 | Exact manifest, schema v3, identity domains, isolated session | 1, 2 |
| §9.5–9.8 | durable intent, fencing, state/retry/deadline/cancel | 3, 5, 6, 7, 10 |
| §9.9–9.12 | artifact, closure/checkpoint, schedule/manual, security/audit | 8, 9, 11, 12 |
| §§10–12 | Legacy capabilities implemented; future port/LangGraph frozen | 4, 7, 13 |
| §13 acceptance evidence | Implemented by test matrix | 1–14 |
| §§14–15 supersession/next gate | Preserved; no stale prompt execution | 14 |

### Decision ledger #1–#62 disposition

| Decisions | Disposition | Tasks |
|---|---|---|
| 1, 3, 7 | Future gradual engines/port/fallback invariant; no engine implementation | 4, 13 |
| 2, 4–6, 9–10 | Neutral fixed `report_v1`, caller cannot select backend, normalized gateway; registry/aliases remain future | 2, 4, 13 |
| 8 | Static registry is JT-1 production non-scope | 13 |
| 11–15 | Formal Task API/Worker/DB claims/adapters are JT-1; coordinator is a distinct process | 10, 13 |
| 16 | Future cooperative cancel semantics; legacy bridge truthfully exposes no cancel | 4, 7, 11, 13 |
| 17–19 | Gate-B lease/heartbeat, ownership-loss meaning, reconcile-before-action | 3, 7, 10 |
| 20–22 | Task/Attempt/retry/checkpoint identities are JT-1/JT-2 non-scope | 13 |
| 23–24 | Immutable manifest now; future Task/Attempt snapshots deferred to JT-1 | 2, 6 |
| 25 | Future Attempt artifact selection; Gate-B publication stays compatibility-scoped | 8, 13 |
| 26–27 | Neutral state translation | 4, 7 |
| 28 | Execution Event Store is JT-1 non-scope | 13 |
| 29 | SQL domain audit kept separate from future execution events | 12, 13 |
| 30–36 | Profiles/typed future infrastructure non-scope; server-fixed model/output/workflow and no framework leakage now | 2, 4, 12, 13 |
| 37–38 | Runtime credentials and secret exclusion | 4, 12 |
| 39–40 | Neutral safe failures; retryability separate from authority | 4, 6, 7, 12 |
| 41–43 | No graph mirror; opaque remote ID; same-backend reconciliation only | 6, 7, 13 |
| 44 | Semantic change requires new workflow/contract; drift fails | 2, 6 |
| 45 | Gate-B only submission boundary + legacy gateway | 4, 13 |
| 46 | No fake Task/Attempt idempotency; submission is its own domain | 2, 13 |
| 47 | Artifact/side-effect reconciliation; future Attempt selection deferred | 8, 9, 13 |
| 48 | Deadline distinct from lease/transport and cannot prove failure | 3, 5, 7 |
| 49 | Native anti-corruption and ambiguous recovery-required | 4, 7 |
| 50 | Deterministic isolated session, no conversational authority | 2, 6 |
| 51 | Exact materialized identity and stable semantic replay | 2, 5, 6 |
| 52 | Durable intent/stable idempotency/no exactly-once or key bypass | 5, 6, 7 |
| 53 | External fenced coordinator; no transaction across HTTP | 3, 5, 6, 10 |
| 54 | Artifact-proven terminal success is distinct from checkpoint advancement; valid same/lower-version executions may succeed with checkpoint no-op | 8, 9 |
| 55 | Manual scoped idempotency permits a new business Run against the same immutable RequirementVersion; its success need not rewrite the checkpoint | 7, 9, 11 |
| 56 | First Prepare binds the server-owned root fingerprint exactly once before POST; all later stages verify it; safe relative/digest/reconcile/no overwrite | 5, 8, 9 |
| 57 | Business actor distinct from stable service owner | 4, 12 |
| 58 | Control/backend/future event audit separation and safe correlation | 12, 13 |
| 59 | Prospective schedule changes only | 5, 11 |
| 60 | Failure classification separate; bounded same-operation retry only | 4, 6, 7, 8 |
| 61 | Explicit gateway capabilities; no fake cancel | 4, 7, 11, 13 |
| 62 | Gate freeze: bridge, then JT-1, then versioned LangGraph | 13, 14 |

## 11. Review gate

A reviewer may reject any task independently if its RED test, exact interfaces/schema, transaction ordering, safe evidence, or boundary proof is incomplete. Implementation begins only after this plan is approved and a fresh execution contract is issued. The old Gate-B prompt remains stale and must not run.

```text
Phase 1C-B Implementation: NOT STARTED
Job Task JT-1 Implementation: NOT STARTED
LangGraph Integration: NOT STARTED
Live SQL Server Acceptance: NOT EXECUTED
Existing pre-Design-v1 Phase 1C-B execution prompt: STALE / MUST NOT RUN
Phase 1C-B Plan v1: SUPERSEDED / NOT PASS
Phase 1C-B Plan v1.1: READY FOR HUMAN/CHATGPT REVIEW
Next gate: Human/ChatGPT Phase 1C-B Plan v1.1 Review
```
