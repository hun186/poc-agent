# Architecture and Engineering Decisions

## Current Summary

### Runtime and execution boundaries

- Keep runtime API code in `sra_api/` with `api/` as compatibility namespace. Preserve established Auth/RBAC, signed-capability, audit, and owner-isolation boundaries.
- Keep Phase 1A Batch Scheduler separate from Requirement Scheduler and keep Report Job Worker ownership in API lifespan.
- Keep Requirement import authority in SQL Server with immutable Requirement Version/Snapshot history and exact catalog validation.
- Keep Requirement recurrence/execution control in separately versioned `sra_schedule`, driven by external Schedule/Handoff workers rather than FastAPI background loops.
- Keep HTTP/filesystem effects outside SQL authority transactions. SQL lifecycle state/fencing/audit mutations commit atomically; JSONL/audit projections are not transaction authority.
- Preserve production Report Job execution through real Agent/LLM/Elasticsearch. Verified E2E semantic mocks are job-scoped test authority only and must never leak to ordinary production jobs.
- Job Task JT-1, generic Task/Attempt/Event infrastructure, Workflow Registry, and LangGraph integration remain future work and are NOT STARTED.

### Deployment and provenance

- Requirement SQL registry selection is deployment-local privileged authority and is excluded from release-provenance evidence; do not expose registry bytes, digest, resolved path, credentials, or query text.
- Runtime provenance uses explicit shared bounded selectors. Generated artifacts and deployment-local mutable/secrets state do not become release authority merely by directory location.
- Functional verification may make only reviewed runtime byte drift advisory; security/discovery/module-shadow/worker/artifact integrity checks remain fail closed. Release verification remains the strict default.
- Operator E2E is a stimulus/observer of deployed public APIs/workers, not a second executor. Live acceptance claims require actual authorized deployment evidence.

### Requirement Product API + Task Center

- The first implementation slice is intentionally limited to Schedule schema v4 Product control-plane persistence and exact migration/catalog validation; Product service/router/create saga/UI remain separate later PRs.
- Integrate Requirement automation into the existing SRA operations console. Reuse existing navigation, Auth/RBAC, audit, service-key system, Requirement Import, Schedule/Handoff, Report Job, and artifact authorities; do not build parallel infrastructure.
- Persist Product Task identity/kind/state and Product idempotency in Schedule schema v4 using only `requirement_product_tasks` and `requirement_product_requests` in v1.
- New Product Task/source provisioning remains superuser-only. Service-key automation is limited to already provisioned Tasks.
- Preallocate cross-authority Product saga IDs before authority commit. Requirement import and Schedule Version authorities accept optional caller-supplied IDs with same-ID/same-semantics recovery.
- Product-owned low-level Schedule/source HTTP mutation is fenced transactionally; reads remain available and non-Product mutation remains backward compatible.
- Hide/inhibit Product Tasks while `provisioning`. Release one-time initial Run or recurring enablement only inside the atomic Product create finalizer that also publishes Task visibility and create success.
- Input replacement persists `base_snapshot_id` and uses locked CAS. Same-ID committed import recovery occurs before `_prepare()`.
- Schedule-affecting Product PATCH creates a draft only. A separate superuser-only `task_version_activate` operation approves/activates the exact draft. Low-level Product-owned approval stays fenced.
- Product Task revision represents active semantic state: successful in-place metadata/state PATCH and successful activation each increment once; draft-only proposal and input replacement do not.
- Reject mixed in-place + schedule-proposal PATCH before durable reservation with `requirement_task_patch_mixed_modes`.
- Recurring Product `product_state` mirrors Schedule enablement atomically: active/true and disabled/false. One-time Tasks remain active in v1.
- First manual `run_trigger` admission serializes with recurring disable on the Product Task lock. Disable affects new admissions only.
- For an existing same principal/operation/idempotency key, compare canonical hash and dispatch every persisted ledger state before lifecycle checks: recoverable states resume, success replays success, terminal failure replays the same safe terminal result.
- Canonical Product request hashes bind operation + every path/target resource identity + semantic payload/input digest. Task-scoped operations include `task_id`; draft activation includes `task_id + schedule_version_id`; empty-body Run trigger still hashes `task_id`. Reusing one key on another resource yields `requirement_idempotency_conflict`.
- Product v1 does not persist retry parent/child ancestry; “Run again” creates an independent Run.

## Recent Decisions

### 2026-10-06 Preserve quoted literals during SQL catalog normalization

- Catalog normalization may remove SQL Server-owned brackets/parentheses/spacing and normalize unquoted syntax only; it must never rewrite characters inside quoted SQL literals.
- Hash/fingerprint CHECK patterns therefore retain the exact `[^0-9a-f]` character class so structural drift cannot be normalized into equivalence.


### 2026-10-06 Implement Product schema v4 as the first isolated slice

- Start implementation with P1.0 only: Schedule schema v4, Product Task/request catalog descriptors, transactional v3→v4 migration/fresh bootstrap, and focused persistence tests.
- Do not introduce Product router, UI, create saga, activation, input replacement, or Run trigger in this slice; later gates build on the reviewed persistence authority.
- Keep `requirement_product_requests` reservation refs intentionally non-FK while `requirement_product_tasks.schedule_id/source_id` are real FKs to existing Schedule/Requirement authorities.
- Persist Product Task `revision` and request-ledger `base_task_revision` / `result_task_revision` as SQL Server BIGINT, matching the approved monotonic revision authority before schema v4 is released.


### 2026-10-06 Canonical idempotency hash binds target resources

- Ledger namespace remains principal + operation + idempotency key, so `request_sha256` must distinguish the target resource.
- Cross-Task or cross-Version reuse of the same key cannot replay an earlier resource even when request bodies are identical or empty.

### 2026-10-06 Persisted run-trigger state precedes lifecycle admission

- Current disabled/provisioning state is a rule for truly new `run_trigger` admission only.
- Existing same-key requests are resolved by request hash and persisted ledger state first. `failed_recoverable` remains resumable after disable; `failed_terminal` remains the same terminal result.

### 2026-10-06 Serialize manual Run admission with recurring disable

- The Product Task lock is the serialization point between first `run_trigger` reservation and recurring enable/disable.
- Disable-first rejects without a request row; trigger-first creates one durable admitted request. Later disable does not revoke it.

### 2026-10-06 Product state/revision rules

- `product_state=disabled` is reachable only for recurring Tasks and atomically mirrors Schedule `enabled=false`; re-enable mirrors active/true.
- Draft proposal creation does not change Product Task revision or `result_task_revision`. In-place Product mutations and successful activation each advance revision exactly once.
- Mixed in-place + schedule-proposal PATCH is rejected instead of defining a coupled two-phase transaction in v1.

### 2026-10-05 Separate Schedule proposal from activation

- `db_operator` may propose immutable Schedule drafts but cannot activate them. Superuser activation is a distinct idempotent Product operation using the proposal's original `base_task_revision` CAS anchor.
- Durable retry ancestry is outside Product v1.

### 2026-10-02 Product concurrency and recovery

- Product ownership fencing is transactional with low-level writes and recognizes task-create reservations before the Product Task row exists.
- Input replacement uses `base_snapshot_id` CAS; committed same-ID import replay must be recovered before preparation/diagnostics.
- Product create finalization is the atomic execution-release and visibility boundary.

### 2026-09-30 E2E isolation

- Verified E2E authority is carried on per-Agent tool instances and re-opened in worker threads; no process-global fallback may make mocks visible to production jobs.

### 2026-09-23 Verification/provenance

- Keep release verification strict by default. Functional verification does not bypass runtime discovery, active-module, worker identity, or artifact integrity.
- Port semantic-input corrections without weakening deployment capability/worker/artifact architecture.

## Archived History

- `.codex/archive/decisions.md-20261006-143100.md` — full active decision history immediately before this compaction, including all dated Product-review decisions through 2026-10-06.
- `.codex/archive/decisions.md-20260907-120000.md` — earlier complete pre-compaction history through PR #214.
- `.codex/archive/decisions.md-20260813-000000.md` — earlier retained decision history.
- Historical details not repeated here remain authoritative for traceability only when not superseded by the current summary.


### 2026-10-07 One-time Product create uses persisted preallocation + atomic release

- Reserve every cross-authority identity in `requirement_product_requests` before creating Source/Import/Snapshot/Schedule/Task/Version rows.
- Exact-ID Source and Schedule creation must replay only when semantics match; unique-key or same-ID drift is never treated as success.
- The one-time initial Batch Run is created only inside the Product finalizer, using the existing locked Schedule materializer and a stable request-derived manual trigger. Product visibility (`active`) and request success commit in that same transaction.
- The selected preview profile must still be the active approved profile at create time so Requirement commit cannot silently normalize under a different profile version.


### 2026-10-07 Product preview profile identity must be transactionally bound at import

- A Product create pre-check of the active Requirement profile is insufficient because another superuser can activate a different profile version before the import transaction begins.
- Product create therefore passes the previewed `profile_version_id + profile_sha256` into Requirement Import authority. Preparation uses that exact version; a new import locks/validates the active profile binding inside the mutation transaction; terminal exact-ID replay verifies persisted import/snapshot profile identity without requiring the profile to remain currently active after success.


### 2026-10-07 Product create recovery precedes current-active profile admission

- Historical exact-ID import recovery is authoritative once the persisted import/snapshot is bound to the expected profile identity. A later profile activation change must not prevent recovery/finalization of that already-committed Product request.
- Therefore Product orchestration must not independently reject the current active profile before calling Requirement Import recovery. The Requirement Import transaction enforces active-profile equality only for a genuinely new write.
- One-time Product create requires at least one accepted Requirement row. Empty direct JSON/header-only uploads fail terminal before durable domain objects or an initial Batch Run are created.


### 2026-10-07 Product create selection time is part of durable request semantics

- One-time Product create eligibility must not drift across retries. The selection/expiry evaluation time is the Product request's persisted `created_at`, established when the idempotency reservation is first committed.
- Retries may occur after Requirement rows expire; if those rows were eligible at the original request time, recovery/finalization continues using that same evaluation instant rather than converting the request to terminal failure.


### 2026-10-07 Product one-time finalization separates selection time from audit time

- `_materialize_locked()` accepts an optional semantic `selection_time`; existing scheduler/manual paths default it to `now_utc`.
- Product one-time finalization passes the reserved Product request `created_at` as `selection_time` so retries select the same rows as the original request.
- Audit/materialization timestamps continue using current `now_utc`; only eligibility evaluation and item `evaluated_at` use the durable selection instant.


### 2026-10-07 Recurring Product create releases only recurrence, not an initial Run

- Reuse the existing Phase 1C recurrence calculation and scheduler worker rather than copying scheduler logic into Product service.
- The recurring finalizer computes `next_run_at` with `next_occurrence()` and enables the Schedule in the same transaction that makes the Product Task visible and marks the owning request succeeded.
- Do not create a manual/initial Batch Run for recurring Product create. The scheduler remains the sole authority for scheduled occurrence materialization.
- Persist the first computed due time in bounded request result metadata so same-key replay returns original create evidence even after the scheduler advances the live Schedule.


### 2026-10-07 Recurring create uses separate reservation and release clocks

- Product request `created_at` remains the durable semantic time for preview/replay identity; it is not the authority for recurrence release after potentially long provisioning.
- Immediately before recurring finalization, the service obtains a fresh UTC release time. The finalizer computes `next_run_at` from that release time using existing Phase 1C recurrence logic.
- The exact first due is also the authoritative first-run expiry gate. The finalizer must prove the committed snapshot contains at least one row with no expiry or `expires_at > initial_next_run_at` before it can enable recurrence.
- If no row can participate in the first occurrence, the create request is terminalized while Schedule remains disabled and Product Task remains provisioning; no zero-selected scheduled Run is released.


### 2026-10-07 Scheduled Requirement selection is evaluated at scheduled_for

- For scheduled runs, `scheduled_for` is the semantic selection/evaluation time. Worker claim time is operational/audit time only.
- Delayed scheduler claims therefore do not change expiry-based membership for the occurrence being materialized.
- This reuses the existing materializer's explicit `selection_time` mechanism; manual/Product one-time paths retain their own reviewed selection-time semantics.


### 2026-10-08 Zero-selection Requirement Runs complete at materialization

- A materialized Batch Run with `selected_count == 0` has no downstream handoff work and must not be persisted as `handoff_pending`.
- Reuse `_terminal_run_recompute()` inside the same materialization transaction after item evidence/checkpoint writes. With no selected items, the canonical terminal state is `completed` with zero success/failure counts and a completion timestamp.
- This is a scheduler invariant rather than a Product-only special case, so delayed/coalesced scheduled occurrences and manual paths cannot strand empty runs.


### 2026-10-08 Product Task PATCH is split into two durable mutation modes

- Classify Task PATCH before reservation. In-place metadata/state and Schedule-version proposal semantics must never share one durable request because they have different revision and privilege behavior.
- In-place success increments Product Task revision exactly once. Schedule-proposal success creates only an immutable draft and leaves Task revision / active Schedule semantics untouched.
- Persist the originating Task revision in every `task_update` request; it is the in-place CAS anchor and the future P1.5A activation CAS anchor.

### 2026-10-08 Recover exact Product draft before rebuilding proposal config

- A crash may occur after the preallocated Schedule Version draft commits but before the Product request is marked succeeded.
- Retry therefore checks the exact request-owned `schedule_version_id` first. If present, it reuses that persisted draft and proceeds to request completion instead of recomputing from a possibly newer active Schedule config.
- This preserves idempotent draft identity and avoids digest drift after unrelated active-version movement.

### 2026-10-08 Same enabled state must not reschedule recurrence

- An in-place PATCH that repeats the current recurring enabled state may still complete as one Task revision update, but it must preserve the current `next_run_at`.
- Only an actual disabled→enabled transition recomputes `next_run_at` from the active approved Schedule Version. Active→disabled clears it.


### 2026-10-08 Product draft activation uses proposal-origin revision, never current revision

- `task_version_activate` must resolve the exact successful schedule-proposal `task_update` that created the draft and copy its persisted `base_task_revision`.
- Activation CAS is evaluated against that immutable origin revision. This guarantees that two drafts created from one Task revision cannot both become active after either activation or another in-place Task update advances the revision.
- Lost-response replay is governed by the activation ledger result; successful replay never re-runs approval or increments Task revision again.

### 2026-10-08 Schedule approval logic is shared through a locked helper

- Low-level Schedule approval and Product activation must not maintain separate recurrence/version-transition implementations.
- `_approve_version_locked()` is the single SQL-transaction helper for retiring the previous approved version, approving the exact draft, updating active version / next-run state, and emitting Schedule approval audit evidence.
- Product activation performs Product provenance/CAS checks before calling the helper and commits Product revision/request state in the same transaction.

### 2026-10-08 P1.5A low-level Product approval guard is intentionally interim

- The low-level Schedule approval endpoint must stop being a supported bypass once Product activation exists, so P1.5A adds a Product-ownership read/precheck and stable 409 response.
- This precheck is not treated as the final concurrency boundary. P1.6 must move ownership/reservation checks into the same transaction/locks as each low-level mutation and cover the documented TOCTOU races.


### 2026-10-08 Product activation requires atomic Product-level audit

- Schedule-version approval audit alone is insufficient when activation also mutates Product Task semantics.
- Successful `task_version_activate` must enqueue `requirement.task.updated` in the same transaction as approval, Task revision increment, and request success.
- The Product audit payload is explicitly bounded to `task_id`, committed `revision`, and `operation`; Schedule/version identity remains in the existing audit envelope.

### 2026-10-11 Product ownership survives request terminalization

- A `task_create` request's preallocated `schedule_id` / `source_id` is an ownership reservation as soon as it is durable. Low-level mutation fences therefore match the reservation by operation + identity without filtering request state.
- This is intentional: after a recoverable or terminal provisioning failure, a partially created Schedule/source may still exist and must not become mutable through the legacy low-level API.
- Once `requirement_product_tasks` exists it is the steady-state ownership authority; checking both authorities closes the provisioning gap.
- Public mutation code uses explicit guarded methods rather than a generic bypass parameter. Product-internal orchestration retains the existing authority methods.

## 2026-10-12 P1.7 Product input replacement

- Reuse schema v4's `input_replace` operation and optional `base_snapshot_id`/`import_run_id`/`snapshot_id`; no new schema migration.
- Keep input-replacement CAS inside Requirement Import's existing SQL transaction and record conflict terminally in the Product request ledger. Never recompute the CAS anchor or assign fresh import/snapshot IDs on retries.
- The Product finalizer verifies preallocated committed import identity rather than the currently active snapshot, because later successful replacements legitimately advance the active snapshot.
- Preserve the P1.6 public guarded source-import path; Product internal orchestration calls the existing authority-bound `commit()` with preallocated IDs and base snapshot.

- 2026-10-12 P2.1 PR #288 deliberately exposes only Product Task/Run read APIs and side-effect-free Product input preview. P2 mutation endpoints cannot be advertised until durable Run-trigger admission and remaining authorization/error-contract gates are reviewed. Cross-Task semantic dedup/result reuse remains deferred, not implicitly enabled.

### 2026-10-15 SRAF air-gap OFF-0 inspection/mutation boundary

- Issue #290 is a separate release/operability gate parallel to Product P2.2, not a new reporting core or Product schema/API subsystem. Preserve existing launcher, Operator E2E, Release Provenance and external capabilities ownership; one future offline runner may orchestrate their **approved, mode-safe** entry points, never duplicate their domain authorities.
- Default `quick` and explicit `diagnose` must be logically read-only; notably API login can write audit state, schema `initialize()` can change SQL, and E2E Elasticsearch fixture setup creates/indexes data. Only an explicitly selected authorized `acceptance` phase may mutate controlled fixtures or run real jobs; mock/offline tests do not satisfy FULL_LIVE external dependency proof. Use stable check IDs and dependency-aware FAIL/SKIP separation.

### 2026-10-15 OFF-0 fail-closed safe report construction

- A report is constructed from reviewed inventory-defined static summary/remediation only, bounded numeric/bool/hash/classification evidence keys, approved per-check or system error codes, and no unstructured exception data. The registry must carry the explicit fail-closed policy and reject any extra top-level weakening fields. Future OFF-3/4 report runners must use `make_report_record` instead of serializing probe results or arbitrary log text. Worker Runtime Evidence requires valid package provenance as well as API availability; missing provenance must cause dependent Worker SKIP rather than misleading FAIL.

### 2026-10-15 OFF-0 report copy validation and JSON parsing isolation

- Report-emitted `title` and `remediation` must be short, single-line, and reject obvious URL, credential/authorization, traceback and absolute-path text; `component` and `error_code` must match bounded machine-code formats. No raw probe exception or other untrusted text is permitted in report records. The report-message validator is defense-in-depth atop PR review of the static inventory. JSON parser's `ValueError` is normalized to a fixed CLI code in its own block so it does not mask the `ContractError` validator boundary. Hosted focused pytest now installs project dependencies first, per AGENTS.md.

### 2026-10-15 OFF-0 reviewed copy and bounded registry bytes

- Any text emitted as report title or remediation is required to equal an in-code reviewed per-check allowlist in addition to regex/Unicode/length checks. A registry-only change cannot introduce unreviewed report strings. The JSON registry CLI reads only opened regular, non-symlink files with an effective 256KiB+1 byte cap and nonblocking open; malformed deeply nested JSON maps to bounded `contract_json_invalid`. No runtime SQL/ES/LLM interaction is added by these defenses.

### 2026-10-16 OFF-0 check inventory and error semantics

- OFF-0 contract PASS requires the complete reviewed 19 check IDs, never a nonempty subset. FAIL must carry only its check-specific real error code; SKIP may carry only a bounded allowed skip reason; PASS has no error code; WARN may have its specific code or none. JSON parsing uses a deterministic preparse structural nesting limit of 128, ignoring brackets in quoted JSON strings, so acceptance does not depend on CPython recursion depth.

### 2026-10-16 OFF-0 planned-check result invariant

- A check whose readiness is `planned` has no executable proof and may only be represented as `SKIP(check_not_implemented)`. It must never be a PASS/FAIL/WARN or use any alternate skip reason. This applies in the safe report-record constructor and must be retained by any future unified offline Runner. Existing/reviewed checks retain check-specific failure codes when actually executed.

### 2026-10-16 OFF-0 reviewed readiness authority

- Probe readiness is an implementation fact, not user-editable configuration. Bind every OFF-0 check ID to a reviewed in-code readiness value and reject any JSON-only promotion or relabeling. Future OFF-1 work must update this authority only when a real probe and its tests have been reviewed; no planned check may produce operational PASS/FAIL/WARN.

### 2026-10-16 OFF-0 execution and failure attribution authority

- Each check ID has code-owned reviewed `minimum_mode`, `effect`, `depends_on`, `component`, and `error_code`. Registry JSON is a declared contract to validate, not an authority capable of changing execution permissions, dependency fences, or fault categories. A mismatch must fail closed before future runners can consume the values. Any change to this code-owned mapping needs corresponding reviewed implementation and regression tests.

### 2026-10-16 OFF-0 success proof boundary

- An implemented/reusable component indicator or caller-provided `http_status=200`/`sha256` is **not** authoritative evidence of probe execution. OFF-0 supplies only a contract validator, not live probes; its report-record constructor cannot emit any per-check PASS. The static schema validator can still print `OFF0_CONTRACT=PASS (schema-only)`. OFF-1 must add trustworthy per-check execution provenance and deterministic success evidence validation before allowing live PASS, without introducing a JSON-only bypass.

### 2026-10-16 OFF-0 runtime outcome proof requirement

- No business check result `PASS`, `FAIL` or `WARN` may be generated by the OFF-0 contract-only recorder absent a reviewed, execution-bound probe. The validator's `OFF0_CONTRACT=PASS` is strictly schema-only. Future OFF-1 must introduce a provenance-aware evidence pathway for each new live outcome, instead of trusting a `status` or `evidence` dict provided by arbitrary callers. `SKIP` remains possible with constrained reason codes.

### 2026-10-16 OFF-0 skipped-check evidence boundary

- A contract-only OFF-0 SKIP denotes non-execution and therefore must not expose caller-supplied positive or negative service observations. Its `evidence` must be empty; even structurally valid HTTP/status/classification/hash data is unsafe without an audited execution path. OFF-1 can define reason-specific trusted evidence only after integrating genuine probe execution and versioned tests.

### 2026-10-16 OFF-0 SKIP reason honesty

- OFF-0 has no runtime execution or verified dependency, auth, or mode context. Each of its report records is constrained to SKIP(check_not_implemented) with empty evidence: this means the OFF-0 probe is not implemented, NOT that a reusable SRAF component is missing. Future real OFF-1/3 probes must add trustworthy check-specific evidence and verified mode/dependency paths before any richer skip reason can be emitted.

### 2026-10-16 OFF-0 non-execution timing and remediation

- OFF-0 emits only `SKIP(check_not_implemented)` with empty evidence, zero duration, and no failure remediation. Displaying elapsed probe time or a subsystem troubleshooting instruction for a check that never ran is an unsupported operational claim. The reviewed failure remediation remains in the inventory for future evidence-bound OFF-1/3 probes, but OFF-0 records set it to null.

### 2026-10-16 OFF-0 nullable remediation policy

- The validated JSON contract specifies `report_policy.remediation_source=verified_fail_warn_inventory_remediation_else_null`: only an actual, verified failure/warning probe in future OFF-1/3 may use reviewed inventory operational remediation; unexecuted SKIP and non-failure outcomes must have null remediation. The static report builder's only supported result in OFF-0 remains SKIP(check_not_implemented), no evidence, zero duration, and null remediation. The validator must reject the legacy always-inventory policy.

## 2026-10-17 OFF-1A first-probe trust decision

- Integrate in small, single-check, read-only slices before the OFF-3 runner. The first batch uses zero secrets and loopback-only GET with timeout=3s, max body=64KiB+1, no proxy/redirect, and fixed reason codes; riskier read-only SQL auth, ES mapping, and remote TLS are designed separately with explicit environment authorization.
- OFF-1A returns explicit PARTIAL_ONLY_NOT_ACCEPTANCE observations; no unreviewed adapter to OFF-0 formal report. The OFF-0 make_report_record no-execution safeguards remain unchanged. True parent PASS/FAIL requires reviewed full-scope probe outcomes, trusted execution source, mode/identity/side-effect guards, and dependency-aware report generation, not arbitrary caller values.

### 2026-10-17 OFF-1A wall-clock deadline security invariant

- Every anonymous localhost HTTP probe must obey a single 3-second monotonic deadline for connect, send, response header and response body, NOT a 3-second inactivity interval reset after each recv. Standard http.client HTTP parser remains in use; a socket subclass used by socket.SocketIO recomputes remaining time before recv_into/recv and sendall, returning static error classification on expiry. The absolute deadline must be backed by slow-drip socket regressions.

- 2026-10-17 Python http.client portability detail: HTTPConnection.__init__ assigns _create_connection as an *instance* attribute, so a subclass method with that name is silently overridden. OFF-1A must explicitly rebind the factory after super().__init__ to create _DeadlineSocket; preserve the integration regression on a connected real loopback socket in addition to timeout tests.

- 2026-10-17 OFF-1A ODBC: never run implicit ldconfig/compiler helper discovery in bounded read-only probes. Use a fixed candidate list on Unix, no arbitrary paths, dynamic loader, or subprocesses; missing path WARN is not proof the driver is absent. Functional SQL driver/connection diagnosis remains OFF-1B.

- 2026-10-17 OFF-1A HTTP response integrity: a 200 with parsable JSON is insufficient if Content-Length declares unreceived bytes; bounded reads must compare original advertised length to bytes received before allowing any subprobe PASS. ES root identity fields must be nonblank strings. These remain partial, not full service attestation.

- 2026-10-17 OFF-1A framing safety: response.length=None may mean either no length header or an invalid header. Read parsed headers to distinguish them; when present require exactly one decimal-only Content-Length, reject duplicate framing and any Transfer-Encoding ambiguity, and validate actual received body size. This is mandatory before partial ES/LLM PASS.

- 2026-10-17 OFF-1A strict parser policy: successful loopback HTTP identity requires both zero email.parser header defects and valid checked framing. Parsed Content-Length absence alone is insufficient because syntactically invalid raw header lines may be discarded by the parser. Fail closed on defects; preserve legitimate close-delimited responses with no malformed header.

- 2026-10-17 OFF-1A HTTP framing compatibility: only a single exact case-insensitive Transfer-Encoding: chunked is accepted without any Content-Length and only if http.client verified chunked decoding. Multiple/unsupported codings, conflicting Content-Length, header parser defects, truncated stream, oversized body and deadline exceedance continue to fail closed. This preserves real local service interoperability without accepting arbitrary framing.

- 2026-10-17 OFF-1A strict chunk decoding: CPython 3.11 http.client response.chunked=True is only a parser-mode flag, NOT proof of wire-format integrity. For valid HTTP/1.1 and unique standalone Transfer-Encoding: chunked, read buffered socket stream with deadline-bound strict chunk-size/CRLF/trailer validation and explicit byte/fragment/trailer caps; disallow HTTP/1.0 chunked. Keep formal OFF-0 probe record fail-closed and disallow production acceptance from narrow results.

- 2026-10-17 OFF-1A HTTP version trust: do not use http.client normalized HTTPResponse.version to certify version when receiving Transfer-Encoding chunked. Preserve _read_status() literal version via HTTPResponse subclass and require exactly 'HTTP/1.1'. Real local TCP regressions must reject HTTP/1.2 and HTTP/1.X even if CPython normalizes version to 11.

- 2026-10-18 OFF-1A raw HTTP parsing: trusting http.client/email parser defect reporting alone is insufficient for strict wire-format validation. Wrap response.fp only during response.begin with _StrictHeaderLineReader enforcing CRLF for every status and header line, then restore the original buffered reader before any body read. Applies to 100 interim status headers, chunked transfer and Content-Length bodies while maintaining absolute 3s deadline.

- 2026-10-18 strict OFF-1A HTTP protocol validation: raw CRLF is necessary but not sufficient. Before permissive stdlib parser sees final or interim 100 response, require every raw header line to have token field-name, colon, and value containing only HTTP visible ASCII/HTAB/obs-text; reject NUL, control bytes, whitespace field names, obsolete folds and malformed lines. Accept only literal HTTP/1.0 or HTTP/1.1 for all response body framings; chunked requires exact HTTP/1.1. Keep OFF-0 acceptance fail-closed.

- 2026-10-18 OFF-1A raw status-line trust: validate every wire status line before http.client text parsing, including interim 100s. Only HTTP/1.0 and HTTP/1.1, three ASCII-digit status code and reason characters limited to HTAB/visible ASCII/obs-text (not NUL/other C0/DEL) may proceed. Continue using strict header field validation and total socket deadline.

- 2026-10-18 strict OFF-1A raw status syntax requires exact HTTP/1.0 or 1.1, SP, 3 ASCII decimal status digits, mandatory SP, then optional safe reason bytes. Absence of second SP is malformed even if Python HTTPResponse accepts it. Validate all final and interim raw status lines.

- 2026-10-18 OFF-1A HTTP interim framing rule: reject Content-Length or Transfer-Encoding headers on every 100 Continue status block prior to stdlib http.client discarding interim headers, regardless of value/case. Stateful strict raw-line reader tracks current 100 header block, resets at the blank line and continues validating subsequent final response. Preserve valid custom interim headers and strict final HTTP framing checks.

- 2026-10-18 OFF-1A chunk trailers: although syntactically legal field lines can appear after zero-size chunk, message-framing fields (Content-Length, Transfer-Encoding) are never allowed to modify/declare framing after body. Explicitly reject both names case-insensitively in strict bounded trailer parser. Ordinary safe metadata trailers remain allowed. No full-live SRAF acceptance implied.

- 2026-10-18 OFF-1A trailer policy: validate trailer lines using same raw field-line grammar as final/interim HTTP headers (visible+HTAB+obs-text 0x80–0xFF, never NUL/control). Reject known header-only standard fields (framing/authentication/routing/content-format/response-control/cache/security) case-insensitively and sensitive standard field prefixes; allow custom metadata and explicitly trailer-compatible digest/integrity fields. Trailer content is never interpreted as credentials or identity. Keep body/deadline limits and fail-closed semantics.

- 2026-10-19 OFF-1A HTTP trailers: Keep a bounded, strict wire parser plus an explicit case-insensitive set of known header-only controls; do not blanket-ban every standard field or accept request controls in response trailers. RFC 9110 explicitly permits ETag (§8.8.3) and Accept-Ranges (§14.3) after streamed content. Trailer data is not used to override HTTP framing, authorization, routing, or JSON identity. Hosted CI and Codex still required; this remains partial-only and unauthenticated loopback GET.
- 2026-10-19 OFF-1A Trailer policy: RFC 8470 prohibits response Early-Data; RFC 9209 permits Proxy-Status trailer only if the matching intermediary member appeared in the same response's Proxy-Status header. Reject other proxy-* prefixes and do not derive authentication, identity, or routing authority from trailer diagnostics.

- 2026-10-19 PR #292 Codex exact-head 816a0297ed review completed after 863 passed (run 39206507074). Two new P2: malformed Proxy-Status parameter suffix (e.g. '; =broken') falsely accepted; legal RFC 8941 sf-token characters (e.g. '+') falsely rejected. Replaced prefix-only parsing with full RFC 8941 Item/Parameter matcher (all token tchar, key/bare item grammar and decoded Base64 validation). Added live TCP four-path valid/invalid regression matrix; new exact-head Hosted CI and Codex review pending. No full SRAF airgap deployment acceptance or merge authorization.

- 2026-10-19 PR #292 Codex exact-head aa8ed6f3df review completed at 2026-10-19T07:25:47Z (previous Hosted run 39211543915: 1003 PASS, OFF-0 19 schema-only PASS). New P2s: parser accepted known Proxy-Status fields using wrong types (e.g. received-status quoted string or error boolean) and incorrectly normalized illegal initial HTAB around RFC 8941 List items. Followup patch validates RFC 9209 and 9532 registered field types including next-protocol as Token OR Byte Sequence, and preserves RFC 8941 legal OWS around commas while rejecting HTAB at list start/end. Raw header guard rejects leading Tab before http.client strips it; strict trailer decoder no longer strips original field data. Four-endpoint live loopback regression vectors added. New exact-head Hosted CI and Codex re-review required; no merged/live acceptance claim.


## 2026-10-19 OFF-1B configuration source of truth and safety boundary (proposed)

- Avoid duplicate dotenv precedence logic in diagnostic scripts. Invoke config.bootstrap.bootstrap_env() within a dedicated operator subprocess from the repository root; suppress bootstrap path-bearing stdout. Honor OS process environment priority and reject unsafe APP_ENV selector values before loading.
- The first automated diagnostic accepts only configured root-path http/https origins and numeric RFC1918/loopback IPv4 TCP endpoints, with a two-second timeout and one connection per service. It does not interpret a reachable TCP port as authenticated Elasticsearch/LLM/API service acceptance, never prints host/URL/model/secret, and never makes authenticated network requests or mutates state. Remote TLS/certificate pinning, credential authority, allowlists and mapping/model metadata require a separate reviewed implementation.

- 2026-10-19 OFF-1B review resolution: only actual network clients can supply target addresses. API TCP observes loopback bind with launcher shell PORT, which must be captured before Python dotenv bootstrap and defaults to 9002; PUBLIC_API_BASE remains a separate external URL. Actual topic term extraction uses MODEL_BASE_URL while TOPIC_LLM_URL is a truthy enablement flag: never connect to TOPIC_LLM_URL. Accept runtime LLMClient's /api/chat and /api/generate suffixes while emitting only classified scheme and port, no path. Default all excludes topic flag; explicit topic check is skip-only.

- 2026-10-19 OFF-1B followup: Runtime LLMClient.rstrip('/') accepts trailing slash(es) after /api/chat and /api/generate; preflight path validity must compare normalized path, while preserving strict rejection of unknown paths, query, userinfo and unsafe endpoint scope. Stale architecture target documentation contradicting feature-flag-only Topic LLM is a P2 and must be corrected alongside code. Python compile gate must pass before test evidence counts.

- 2026-10-20 OFF-1B boundary refinement: URL suffix normalization must be opt-in for LLM (whose real LLMClient.rstrip('/') accepts it) rather than generic. Elasticsearch must accept only exact path '' or '/', reject '//' and all extra path suffixes, and never connect to malformed endpoints. Regression suite explicitly verifies both cases.

- 2026-10-20 OFF-1B configured probe URL decision: the real LLMClient accepts prefix paths (such as /ollama or /gateway/ollama/api/chat), which do not alter TCP destination. Accept safe ordinary path segments and trailing slash normalization only on MODEL_BASE_URL, without DNS/HTTP/credentials or path logging. ES_URL remains restricted to exact path '' or '/' and never borrows the LLM rule. Reject ambiguous path traversal, percent escapes, doubled interior slashes and query/fragment/userinfo.

- 2026-10-20 OFF-1B strict parsing: detect any literal '?' or '#' in the raw URL (including empty delimiters), since urlsplit cannot distinguish absent and empty query/fragment components; reject before connecting. Verify len(url.path) <= 512 before any LLM trailing-slash normalization, so excessive suffix characters cannot bypass bounds. Keep no arbitrary host/port overrides, no SSRF, and never promote TCP-only observations.

## 2026-10-20 OFF-1B deployment cadence and API HTTP boundary

- Following operator preference, continue developing independently reviewable OFF-1B slices but defer Linux package updates until API /healthz, vetted ES HTTPS identity/mapping and real LLM inventory can run as one useful diagnosis. For configured API HTTP, reuse existing OFF-1A hardened loopback GET and OFF-1B bootstrap instead of reimplementing HTTP or discovering public hosts. Return only a bounded diagnostic partial observation; do not assert FULL_LIVE/worker readiness, follow redirects, or access remote endpoints/credentials.

## 2026-10-20 OFF-1B ES trust boundary

- Never reuse the runtime ES connection's ssl_assert_hostname=False for a security diagnostic; instead build verification-enabled TLS with fixed repo http_ca.crt and numeric IP SAN checking, direct socket.AF_INET connect and no DNS/proxy. Do not send Basic auth until TLS handshake completes. Support GET / ES identity plus one literal GET /{index}/_mapping, with a single 3s monotonic async timeout per request, limited response header/body, no redirects/HTTP writes/search, and stable redacted error classifications. Reuse the existing Requirement mapping_compatibility comparator and refuse ambiguous alias expansion; these narrow successes cannot certify production retrieval, service ownership or FULL_LIVE. Plan Linux deployment only when ES and LLM reviews join the already merged API diagnostics.

- 2026-10-20 PR #295 auth gate: never mark Elasticsearch Basic credentials verified from HTTP 200 root or mapping. After TLS validated root ES identity, use protected GET /_security/_authenticate, require enabled username matching configured Basic principal and realm type, and only then request mapping. Fail closed on malformed/mismatched/absent security API; report redacted fixed reasons and never substitute partial verification for full deployment readiness.

- 2026-10-20 OFF-1B ES auth and TLS decision: read-only anonymous/Basic GET to ES does not prove configured password effective through intermediaries. Avoid implicit failed-password attempts in operator defaults; report auth NOT_VERIFIED and incomplete exit 2. An explicitly selected --verify-credentials performs one randomized wrong-password control against /_security/_authenticate; only matching enabled Basic principal + rejection of the invalid control allow auth PASS. Warn failed login can create audit/lockout events. All independent HTTPS connections must collectively retain TLS verification or overall TLS PASS must be revoked. Still PARTIAL_ONLY_NOT_ACCEPTANCE.

- 2026-10-20 OFF-1B ES CLI evidence priority: any aggregate TLS certificate identity FAIL, including from later auth/control/mapping handshakes, mandates exit code 1; must not collapse a proven certificate failure to exit 2 merely because another probe is SKIP or NOT_VERIFIED. Keep transport uncertainty separate from attested cert failure.
