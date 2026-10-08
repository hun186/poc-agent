# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval is in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Phase 0 security, Phase 1A Batch Scheduler, Phase 1B Requirement import, Phase 1C Schedule/Handoff, and the Report Job execution bridge are implemented. Job Task JT-1 and LangGraph remain NOT STARTED.
- Requirement scheduling uses external `schedule-worker` and `handoff-worker` processes supervised with the API by `run_sra_api.sh`; Report Job Worker remains API-lifespan owned.
- Requirement import authority is SQL Server with immutable Requirement Version/Snapshot history. Requirement recurrence/execution control is the separately versioned `sra_schedule` schema. Report Jobs own real Agent/LLM/Elasticsearch execution and DOCX production.
- Production jobs must never enter Requirement E2E semantic mocks. Verified E2E mock authority is job-scoped and isolated across tool threads.
- Operator E2E remains a deployment/technical observer. Repository tests or documentation review are not fresh live deployment acceptance.
- Formal Requirement deployment acceptance is still blocked by the unresolved live Elasticsearch `mapping_incompatible` condition identified during capability probing; repository/offline tests do not clear that blocker. Re-run authorized live mapping/capability acceptance after it is corrected.
- Requirement Product API + integrated Task Center Design/Plan v1 is approved. P1.0 schema v4, P1.0A authority IDs, and P1.1 Product presenters/identities are merged through PR #280. P1.2 side-effect-free Product preview is merged in PR #281. P1.3 one-time Product create orchestration is in progress; Product HTTP routes, recurring create, update/run orchestration, and UI are not implemented yet.

## Requirement Product API + Task Center — Current Contract

- Product v1 integrates into the existing SRA management shell/Auth/RBAC; no second login, scheduler, queue, Report Job worker, or browser-owned execution path.
- Schedule schema v4 adds only `requirement_product_tasks` and `requirement_product_requests`.
- Product Task lifecycle is `provisioning|active|disabled`. One-time Tasks remain active after provisioning. Recurring Task `product_state` atomically mirrors Schedule `enabled`: active/true and disabled/false.
- New Task/source provisioning remains superuser-only. `db_operator` may preview, replace input on active Tasks, create prospective Schedule drafts, and trigger permitted Runs, but cannot approve/activate drafts or enable recurring automation.
- Schedule-affecting Task PATCH creates an immutable draft only. Product draft activation is a separate superuser-only `task_version_activate` operation. Low-level approval remains fenced for Product-owned Schedules.
- Product Task revision advances exactly once for successful in-place metadata/state PATCH and exactly once for successful draft activation. Draft-only proposal PATCH and input replacement do not increment Task revision; proposal `result_task_revision` remains NULL.
- Mixed in-place + schedule-proposal PATCH payloads are rejected before durable request reservation with `requirement_task_patch_mixed_modes`.
- Product-owned low-level Schedule/source mutation routes are fenced transactionally; reads remain available and non-Product resources retain existing mutation behavior.
- Product create finalization atomically releases initial execution and visibility: one-time initial Run is materialized inside the finalizer; recurring Schedule enablement/next-run calculation occurs inside the same finalizer; rollback leaves provisioning hidden/inoperable.
- Input replacement uses `base_snapshot_id` CAS. Same-ID committed import recovery occurs before `_prepare()`, so delayed replay cannot be reclassified against newer Requirement state.
- Product v1 does not persist `parent_run_id` retry ancestry. “Run again” creates an independent Run.
- Recurring disable and first manual Run admission serialize on the Product Task lock. Disable blocks new admissions but does not change replay semantics of already accepted `run_trigger` requests.
- Existing same-key/same-hash `run_trigger` requests are resolved by persisted ledger state before lifecycle checks: `reserved|in_progress|failed_recoverable` resume, `succeeded` replays success, and `failed_terminal` replays the same terminal error.
- Canonical Product request hashes bind operation plus all route/path target identities and semantic payload/input digest. At minimum Task-scoped operations include `task_id`; activation includes `task_id + schedule_version_id`; empty-body Run trigger still hashes `task_id`. Cross-resource reuse of one principal/operation/idempotency key must conflict, never replay another resource.

## Recent Changes

- 2026-10-06: Codex review on pre-fix head `40d7a5fff0ca4f2c7dde4f6658dc49dbc9f9efeb` found disabled/untrusted SQL Server CHECK/FK constraints were not rejected. Catalog reads and per-constraint validation now require active, trusted CHECK/FK enforcement; focused Product FK/hash-check regressions cover both `is_disabled` and `is_not_trusted`.
- 2026-10-06: P1.0 re-review found the historical v1 Schedule catalog classifier inherited v3-only `artifact_sha256` plus Handoff tables/keys from current `REQUIRED_*` descriptors. Restored the exact historical v1 shape and added regressions proving v1/v2 upgrade paths execute v3→v4 statements exactly once.
- 2026-10-06: Started Product implementation from merged hosted main `155db8bb5568e04118481080840aad378026af44` on `feat/requirement-product-schema-v4`: Schedule schema v4 now adds only `requirement_product_tasks` and `requirement_product_requests`, v3→v4/fresh-v4 migration flow, exact catalog descriptors, Product Task FKs/uniqueness/checks, request-ledger uniqueness/checks, and filtered `schedule_id`/`source_id` ownership indexes; Product service/router/create saga/UI are not part of this slice.
- 2026-10-06: Bound canonical Product idempotency hashes to path/target resource identities and added cross-Task / cross-version same-key conflict regressions to Design/Plan v1.
- 2026-10-06: Completed run-trigger admission/replay design: first admission is atomic with lifecycle state, and all persisted request states are resolved before new-admission checks.
- 2026-10-06: Defined recurring Product disabled-state mirroring and superuser-only draft activation, with revision/CAS and idempotency semantics.
- 2026-10-05: Split Schedule draft proposal from privileged activation; removed Product v1 durable retry-ancestry guarantee.
- 2026-10-02: Added Product provisioning visibility/execution gate, atomic ownership fences, input replacement snapshot CAS, and same-ID committed import recovery before preparation.
- 2026-10-06: Started Product implementation with P1.0 Schedule schema v4: two reviewed Product control-plane tables, catalog descriptors, v3→v4 migration/fresh bootstrap, and focused migration tests. Product service/API/UI remain unimplemented.
- 2026-10-06: PR #278 opening review found two P1 migration issues: whole-catalog checks/defaults were not normalized like SQL Server catalog evidence, and legacy Schedule migration/stateful tests still encoded v3 marker/index/default assumptions. Both were corrected; all Requirement Schedule test files were rescanned for remaining hard-coded v3/final-index assumptions before exact-head re-review.
- 2026-10-06: A subsequent review of the pre-fix head also confirmed Product default normalization and found the approved BIGINT revision contract was implemented as INT. `requirement_product_tasks.revision` plus request-ledger `base_task_revision` / `result_task_revision` are now BIGINT in DDL, catalog descriptors, tests, and Design/Plan.
- 2026-10-06: Review of the next pre-fix head found `normalize_sql_predicate()` removed brackets/whitespace inside quoted literals, weakening hex-character-class CHECK evidence. The shared normalizer now transforms only unquoted SQL syntax; quoted literal bytes/text are preserved, existing artifact/fingerprint descriptors retain `[^0-9a-f]`, and Product request-hash regressions reject the weakened `%^0-9a-f%` form.
- 2026-10-01: Added docs-only Requirement Product API + Task Center Design/Plan v1; PR #277 later merged and became implementation authority.
- 2026-10-01: Requirement Operator E2E CLI now follows deployed external mode by default when the operator omits the option.
- 2026-09-30: Isolated Requirement E2E semantic mocks from ordinary production jobs and propagated verified E2E authority safely into tool worker threads.

- 2026-10-06: P1.0A authority-identity compatibility is implemented in PR #279: Phase 1B accepts/replays preallocated import/snapshot IDs before preparation, input replacement enforces locked base-snapshot CAS, Schedule Version accepts/replays a preallocated version ID, and Manual Run keeps its existing trigger-request identity. An initial Codex review found that candidate diagnostics could bypass replacement CAS; the current branch fixes that ordering and adds a regression. Product service/router/create saga/UI remain unimplemented.

## Verification Summary

- PR #277 Design/Plan and PR #278 P1.0 schema v4 are merged. P1.0A authority-level caller-supplied identity support is implemented on open PR #279; Product service/API/UI and later saga gates remain not implemented.
- P1.0A regression coverage on PR #279 includes terminal import replay before `_prepare()`, exact preallocated import/snapshot IDs, base-snapshot CAS before both normal writes and failed-import recording, failed-import same-ID replay, and Schedule Version exact-ID create/replay/mismatch behavior. A local pytest PASS is not claimed: direct Git transport still fails with `Could not resolve host: github.com`, so the hosted branch cannot be cloned into the execution container. Hosted Vercel/check status and a fresh exact-head Codex review are required before merge.
- No fresh live Requirement E2E, private SQL Server, Elasticsearch, LLM, Agent, deployment bootstrap, or DOCX acceptance was executed for this documentation task.
- Exact-head Codex review and hosted status checks are required for PR #279 before merge; the completed review of older head `ef9fdd1` is not acceptance for the current head.
- Compaction verification: the 2026-10-06 memory and decisions archives have blob SHAs identical to the pre-compaction files at hosted head `364db0b1d04029570c2ff6a34b05269956751d3d`; active memory/decisions are 59/89 lines respectively, and all six required active `.codex/*.md` context files are below the AGENTS.md mandatory size/line/date-block thresholds.
- Historical test and deployment evidence is preserved in the archived memory files and should not be restated as fresh acceptance.

## Archived History

- `.codex/archive/memory.md-20261006-143100.md` — full active memory immediately before this compaction; includes all dated Product-review corrections and prior Requirement/E2E verification records through 2026-10-06.
- `.codex/archive/memory.md-20260915-170533.md` — earlier full pre-hardening history.
- Earlier archives referenced by those files remain under `.codex/archive/`.

## Compaction Record

- 2026-10-06: Compacted `.codex/memory.md`, `.codex/decisions.md`, `.codex/backlog.md`, and `.codex/known_issues.md` after robust AGENTS.md date/work-block counting. Full originals were archived first at `.codex/archive/memory.md-20261006-143100.md`, `.codex/archive/decisions.md-20261006-143100.md`, `.codex/archive/backlog.md-20261006-153400.md`, and `.codex/archive/known_issues.md-20261006-153400.md`.
- Verification: memory, decisions, backlog, and known-issues archives were created from complete hosted branch contents before active-file rewrites; archive blob SHAs exactly match the corresponding pre-compaction blobs. Recounting all six required active `.codex/*.md` files with both dated headings and dated work bullets leaves every file below the >40 KB, >400-line, and >20-work-block mandatory compaction triggers. Active files retain current Product/architecture contracts, unresolved acceptance blockers (including Elasticsearch `mapping_incompatible`), live backlog, and archive pointers.

## 2026-10-06 Requirement Product P1.1 presenters

- Started P1.1 from hosted `main@a6e81e55ec1d70b4b8e8c07be9440a4e335cab8c` on `feat/requirement-product-presenters-p1-1`.
- Added `sra_api/services/requirement_product_service.py` as a pure Product façade presenter layer. Product Task identity is taken from the `requirement_product_tasks` authority row; Task and Run presenters whitelist output instead of forwarding Schedule/Handoff/Report Job dictionaries.
- Product Run presentation exposes immutable `schedule_id + schedule_version_id + snapshot_id` binding and Requirement Version identity, maps backend lifecycle into neutral Product status, emits only relative API links, and does not expose Report Job native state/IDs, artifact filesystem paths, output-root fingerprints, trigger-request identity, credentials, or E2E markers.
- Provisioning Task/Run presenters fail closed as unavailable; one-time `disabled` identity is rejected as an invalid Product invariant.
- Added focused `tests/test_requirement_product_service.py` coverage for Product identity authority, neutral status mapping, safe links, provisioning visibility, cross-schedule identity rejection, and sensitive/backend-field non-disclosure.
- No Product HTTP route, preview orchestration, create saga, activation, input replacement, or Run admission is implemented by this slice.
- Local pytest PASS is not claimed in this connector-only pass; exact-head Codex review/check evidence is required before merge.


## 2026-10-07 Requirement Product P1.2 preview

- Started P1.2 from hosted `main@5ea1530bfd687546d8b97458871258f184a5f1ca` on `feat/requirement-product-preview-p1-2` after PR #280 merged.
- `RequirementProductService.preview_input()` accepts exactly one input mode: uploaded bytes + filename, or direct Requirement JSON, plus an explicitly selected approved import-profile version.
- Preview remains side-effect-free: it reads the selected profile version and reuses existing Requirement `acquire_source()` + `normalize_rows()` authority through an ephemeral manual-upload descriptor; it creates no source, import run, snapshot, schedule, Product Task, or Run.
- Product preview returns source SHA, row/accepted/rejected counts, normalized canonical rows, separated row errors/warnings, and profile/version identity. Raw source columns, row hashes, execution hashes, and durable internal identities are not exposed.
- Focused tests cover direct JSON normalization, CSV upload parsing, exact-one input mode, approved-profile enforcement, format mismatch, and mutation traps.
- Local pytest PASS is not claimed: `git ls-remote https://github.com/hun186/poc-agent.git HEAD` still fails with `Could not resolve host: github.com`; Hosted exact-head review/check evidence is required.


## 2026-10-07 Requirement Product P1.3 one-time create

- Started P1.3 from hosted `main@b5c8046cdcc4c82727317d3933a775dd874cab6b` on `feat/requirement-product-create-once-p1-3` after PR #281 merged.
- Added durable `task_create` request reservation in Schedule SQL authority. The reservation persists preallocated Task/Source/Import/Snapshot/Schedule/Schedule-Version IDs before external authority writes and replays same-key/same-hash requests; concurrent first-reservation unique-key races re-read the winner.
- Added replay-safe exact-ID Requirement Source and Schedule creation. Same ID + same semantics replays; semantic drift fails closed.
- Added provisioning Product Task persistence and one-time Product create finalizer. The finalizer locks request/Task/Schedule/Version/Snapshot authority in one Schedule transaction, requires the Schedule remain recurrence-disabled, materializes exactly one manual Run through the existing locked materializer, transitions the Task to active, stores bounded safe result metadata, and marks the request succeeded atomically.
- `RequirementProductService.create_one_time_task()` enforces an internal superuser gate, reserves before preview, requires the selected approved profile to remain active, creates/enables a task-owned manual-upload source, commits exact preallocated import/snapshot IDs, creates exact Schedule/Version identities, approves the initial version while disabled, and invokes the atomic finalizer. It never calls Report Job/Handoff directly.
- Focused regressions cover lower-role rejection before reservation, exact authority binding, one-time-vs-disabled-recurring identity, lost-response success replay without duplicate import/version/run, same-key changed-payload conflict, replay-safe source identity, and replay-safe Schedule identity.
- Local pytest PASS is not claimed: direct Git transport still fails with `Could not resolve host: github.com`. Hosted exact-head Codex review/check evidence remains required.


- 2026-10-07 P1.3 review correction: exact-head Codex review found a TOCTOU gap between Product preview/profile pre-check and Requirement commit. The fix threads the expected `profile_version_id + profile_sha256` into `RequirementImportService.commit()`, prepares with that exact version, validates terminal replay against persisted import/snapshot profile identity, and locks the source/profile/profile-version rows with `UPDLOCK,HOLDLOCK` before a new import write so active-profile switching cannot change normalization semantics between preview and snapshot commit.


- 2026-10-07 P1.3 second review corrections: Product create no longer performs a separate active-profile pre-check before import authority. This preserves recovery when an exact-ID import already committed and the profile later changes; genuinely new imports still enforce the previewed profile binding transactionally inside Requirement Import. One-time create also terminal-rejects zero accepted rows before Source/Import/Schedule/Run mutation so empty snapshots cannot create permanently queued runs.


- 2026-10-07 P1.3 third review corrections: fixed a Product preview refactor regression where `preview_input()` referenced normalized locals before assignment; raw upload arguments now enter `_input_bytes()` and only normalized bytes/name reach `acquire_source()`. One-time create also rejects previews whose accepted rows are all expired at the create evaluation time, preventing initial Batch Runs with zero selectable items from remaining queued indefinitely.


- 2026-10-07 P1.3 fourth review corrections: the exact `preview_input()` block now passes raw `upload_bytes/upload_filename` into `_input_bytes()` and passes only normalized bytes/name to `acquire_source()`. Product create eligibility is evaluated against the durable request's original persisted `created_at`, not the retry wall clock, so a crash/retry after rows later expire can still recover and finalize the same idempotent request.


- 2026-10-07 P1.3 fifth review correction: the one-time finalizer now separates semantic selection time from audit/materialization time. Product retry materialization evaluates Requirement eligibility at the durable request `created_at`, while Batch Run/item created/updated timestamps remain the current finalization time. This closes the remaining expiry drift between service preview admission and Schedule-store item selection.


## 2026-10-07 Requirement Product P1.4 recurring create

- P1.3 one-time Product create merged in PR #282 at `main@c51a10655616354d7a52c3548c363cfec2a3747e`.
- P1.4 is implemented on `feat/requirement-product-recurring-create-p1-4` as an internal service/store slice only; Product HTTP router/UI/P1.5 updates/P1.6 low-level ownership fences remain out of scope.
- Added `RequirementProductService.create_recurring_task()` by preserving the reviewed P1.3 durable reservation/preview/profile-binding/source/import/Schedule/Version saga and changing only Product execution kind + finalization behavior.
- The initial Schedule Version is approved while the Schedule stays `enabled=0,next_run_at=NULL`; the Product Task stays `provisioning` until finalization.
- Added `ScheduleStore.finalize_recurring_product_task_create()`. In one Schedule SQL transaction it locks the owning request, Product Task, Schedule, approved active version, and exact active Requirement Snapshot; validates persisted recurrence config through existing Phase 1C authority; calculates `next_run_at` with the existing `next_occurrence()`; enables recurrence; transitions the Product Task active; persists bounded safe create evidence; and marks the same request succeeded.
- Recurring finalization does not create an initial Batch Run. Scheduler visibility is released only by the atomic `enabled=1 + next_run_at` commit; the existing scheduler query considers only enabled schedules.
- The durable create result stores the initial `next_run_at` as immutable replay evidence. Replaying a successful create may present the Task's current Schedule state while still returning the original create-time next-run evidence, so later scheduler advancement or future Task disable/version activation does not invalidate create idempotency.
- Existing Product presenters already hide provisioning Tasks/Runs, and ScheduleStore direct Product Task reads exclude provisioning by default. No Product mutation/run/service-key routes exist yet in this gate; those lifecycle admission checks remain P1.5/P2 work.
- Focused regressions cover superuser admission, atomic enable-only finalization, no initial Run, lost-response replay without duplicate enable/recalculation, once-vs-recurring idempotency conflict, and store-level use of existing recurrence calculation.
- Local pytest PASS is not claimed because direct Git transport remains unavailable in the execution environment; exact-head Hosted Codex review and Hosted checks are required before merge.


- 2026-10-07 P1.4 review correction: recurring Product finalization must emit the existing empty-payload `requirement_schedule.enabled` audit event shape. Passing Product-specific metadata in that audit payload violates the Schedule audit schema and rolls back the entire finalizer. The unsupported payload was removed and focused regression now asserts the emitted enable event has an empty payload.


- 2026-10-07 P1.4 second review corrections: recurring create now separates durable request time from recurrence-release time. The service refreshes UTC immediately before finalization (with an explicit deterministic test override), while request `created_at` remains the input/replay semantic anchor. The recurring finalizer computes the first due from that fresh release time and, before enabling the Schedule, locks/queries the exact snapshot to require at least one Requirement whose expiry extends beyond that first due. If none can participate, it atomically marks the owning create request `failed_terminal` with `requirement_product_no_selectable_first_run` while leaving the Schedule disabled and Product Task provisioning/invisible.


- 2026-10-07 P1.4 third review correction: scheduled occurrence materialization now evaluates Requirement selection at the occurrence's canonical `scheduled_for` instant, not the later worker claim time. `claim_due()` passes `selection_time=latest` into the existing materializer, while run/item created/materialized/updated timestamps continue using the actual claim time. This keeps Product first-due validation and scheduler selection on the same semantic clock and prevents delayed claims from turning an otherwise valid occurrence into a zero-selected queued run.


- 2026-10-08 P1.4 fourth review correction: zero-selection materialization is now terminalized inside the same Schedule transaction. After snapshot items are evaluated and evidence rows/checkpoints are written, `_materialize_locked()` calls the existing `_terminal_run_recompute()` when `selected_count == 0`, so the Batch Run becomes `completed` with `completed_at` before commit instead of remaining `handoff_pending` with no selected item capable of driving recomputation. This closes delayed/coalesced recurrence cases and also hardens any other materialization path that legitimately selects nothing.
