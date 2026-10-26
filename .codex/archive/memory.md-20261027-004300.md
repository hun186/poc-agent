# Project Memory

## Current Summary

- SRAF is the core report-writing/report-creation system; automated Requirement scheduling is an additional application. This FastAPI + Elasticsearch/Agent system uses `sra_api/` (with `api/` compatibility), `agent/`, `data_ingestion/` and `requirement_scheduler/`.
- SQL Server is the authority for immutable Requirement Version/Snapshot; the separately versioned `sra_schedule` schema is authority for recurring schedules, coordinator leases and Handoff. Report Jobs execute real Agent/LLM/ES and create DOCX. Do not create parallel auth, scheduler or report execution paths.
- Requirement Product Task/Create/Update authority, durable request idempotency, and ownership fences described below remain architectural contracts; verify the **current Hosted** state of Product PR #288 and later slices rather than inferring their merge from old work logs.
- OFF-1B through OFF-1H operator diagnostic slices are now merged through PR #304 (`main` merge `8d891e72acdc17981c1498377ceaffaee74ec28a`). These are **partial operator observations**, not actual Linux acceptance.
- Current OFF-1I branch `feat/sraf-off1i-handoff-lease-snapshot` (PR #305) adds a separate, explicitly gated HANDOFF-LEASE snapshot. Its query can only certify one active database lease row at the SQL server's clock instant, not the current local Worker owner or actual schedule progress.
- Deployment-authoritative real ES Mapping remains unresolved (historic `mapping_incompatible` and relocated Docker IP SAN warning). Real SQL, LLM, Worker/Report Job, DOCX, and physical network-isolation acceptance have **not** been established by Github Hosted CI.

## Requirement Product — Current Contract

- Product v1 integrates into the existing SRA management shell/Auth/RBAC. There is no second login or separate execution subsystem.
- Product Task lifecycle is `provisioning|active|disabled`. One-time Tasks remain active after provisioning; recurring Task state mirrors Schedule enablement: active/true and disabled/false.
- Product create is superuser-only. Preview remains side-effect free. Product presenters suppress Report Job native states/IDs, credentials, absolute paths, E2E markers, and trigger-request internals.
- Durable Product mutations use `requirement_product_requests` with principal + operation + idempotency key + canonical request hash. Cross-resource identities are included in hashes so one key cannot replay another Task/version.
- P1.3 one-time create preallocates cross-authority IDs, commits Requirement import/Snapshot and Schedule authorities, then atomically materializes the initial manual Run while making the Product Task visible. One-time selection semantics are anchored to the durable request `created_at`; audit/materialization timestamps use actual finalization time.
- P1.4 recurring create approves the initial Schedule Version while keeping recurrence disabled during provisioning. Its finalizer atomically enables the Schedule, computes the first due through existing Phase 1C recurrence logic, marks the Task active, and marks the request succeeded. It does not create an initial manual Run.
- Scheduled occurrence selection is evaluated at canonical `scheduled_for`, not later worker claim time. Runs with `selected_count == 0` terminalize to `completed` in the materialization transaction so empty Runs cannot remain stranded.
- P1.5 classifies Task PATCH semantics before durable reservation:
  - in-place mode: `name` and/or recurring `enabled`;
  - schedule-proposal mode: `timezone`, `recurrence`, `run_policy`, and/or `model`;
  - mixed modes are rejected before any request reservation.
- P1.5 reservation locks the Product Task, rejects provisioning, persists `base_task_revision`, and preallocates `schedule_version_id` only for schedule proposals.
- P1.5 in-place finalization locks request/Task/Schedule, enforces revision CAS, allows name changes for normal Product operators, requires superuser for recurring enable/disable, atomically mirrors recurring Task/Schedule state, increments Task revision exactly once, stores `result_task_revision`, audit metadata, bounded result, and request success.
- A same-state `enabled=true|false` in-place PATCH does not recompute or shift `next_run_at`; only a real disabled→enabled transition calculates a fresh due. One-time Tasks do not support enabled-state transitions in v1.
- P1.5 schedule-proposal updates create exactly one immutable request-owned draft and never approve/activate it, change active Schedule Version, change `next_run_at`, change enabled state, or increment Product Task revision. Successful proposal requests keep `result_task_revision=NULL`.
- Schedule-proposal retry first recovers the exact preallocated draft identity if it already exists; it does not rebuild the draft from a newer active config after a crash. Draft activation remains a separate P1.5A superuser-only operation using the proposal's persisted `base_task_revision` CAS anchor.
- P1.6 transactional low-level Product ownership fences were implemented and merged through PR #286; P1.7 Snapshot CAS and its exact Hosted merge/deployment state must be checked independently. Do not rewrite old unverified Product work as deployed acceptance.

## Verification and Acceptance

- Never treat Hosted CI, 19 OFF-0 schema-only checks, stubbed SQL/network tests, or a Worker PID/DB lease snapshot as FULL_LIVE; no live deployment is modified via these PRs.
- Before Merge: verify exact current PR HEAD, Hosted CI success on that HEAD, completed formal Codex Review with zero open P1/P2 and zero unresolved Review Threads, plus the user's explicit `merge` command. Do not use stale snapshots.
- OFF-1F local Ollama generation requires actual same-listener PID, server `OLLAMA_NO_CLOUD=1` and compatible version; loopback/inventory alone cannot disprove cloud forwarding. OFF-1G SQL uses a separately granted readonly diagnostic account, strict TLS peer identity and constant SELECT, not a proof of actual SQL principal read-only authority.
- OFF-1H reads bounded launcher Schedule/Handoff identity files and matches trusted /proc start/uid/cwd/exact argv; no progress/SQL lease proof. The canonical verifier now rejects symlink/FIFO races and arbitrary appended role strings.
- OFF-1I only under `--probe-network --probe-sql-read --probe-worker-lease`, requiring OFF-1G success, reads one parametrized TOP(2) lease predicate query. No SQL mutation, owner/token exposure, local owner association or Schedule worker heartbeat. Feature acceptance remains NOT_TESTED.

## Recent Changes

- 2026-10-24 PR #304: merged after exact-head Codex CLEAN; Host CI 1,047 OFF-1H-focused tests, 2 existing E2E Worker tests and 19 OFF-0 checks PASS. Shared Worker verifier hardened and old E2E tests updated. No Linux rollout.
- 2026-10-24 PR #303: OFF-1G SQL Server fixed-query diagnostic merged; 1,008 pytest and OFF-0 19 PASS. SQL read access and TLS still need operator validation.
- 2026-10-24 PR #302: OFF-1F controlled local Ollama generation merged after fixing cloud-forwarding P1; 956 focused pytest, 1,131 OFF-1A and OFF-0 19 PASS on exact reviewed head.
- 2026-10-24 PRs #298–301: partial ES selector/mapping/search, matrix, LLM inventory slices merged after their own review gates; prior per-commit details are fully archived.
- 2026-10-24 PR #305: OFF-1I Handoff lease snapshot initial Hosted CI run #40080725404 passed 1,079 focused pytest, 2 legacy E2E tests and 19 OFF-0; first Codex review raised P1 about mandatory memory compaction, **not yet CLEAN**. Exact new HEAD re-review required after this archival/compaction.
- 2026-10-24: mandatory AGENTS.md §Memory Compaction triggered (>20 dated work records). Full unchanged active memory and backlog were copied to the timestamped archives below and re-fetched byte-identical before condensing. Unresolved Product, ES, SQL, Worker and OFF-1I work kept here and in `.codex/backlog.md`.

## Archived History

- `.codex/archive/memory.md-20261024-170825.md` — byte-identical 38,469-character active Project Memory before this 2026-10-24 compaction, including all 2026-10-22 through OFF-1I detailed review chronology.
- `.codex/archive/backlog.md-20261024-170825.md` — byte-identical 20,489-character active backlog before this compaction, preserving every historical open/closed task statement.
- `.codex/archive/memory.md-20261021-165000.md` and `.codex/archive/backlog.md-20261021-165000.md` — earlier full histories; follow their archive chains for legacy Product and OFF records.
- Other active `.codex/architecture.md`, `api_contract.md`, `decisions.md`, and `known_issues.md` remain separate project context; do not replace their authority with this summary.

## Compaction Record

- 2026-10-24: archived both source files first, re-fetched each and verified identical full text and Git blob SHA. Then condensed active records below the 20-block/200-line target. This compaction changes **only documentation**, not any acceptance claim. Verify the new exact PR HEAD with real Hosted tests and formal Codex review before merge.

## 2026-10-24 OFF-1J lease renewal — active work

- PR #305 OFF-1I merged to main as `de698c086977b64c8168a868eda5eb2bb21067a6`, after exact-head Hosted 1,079 focused + 2 legacy E2E + 19 OFF-0 PASS and formal Codex CLEAN. This is NOT real Linux SQL Server acceptance.
- New `feat/sraf-off1j-handoff-lease-renewal` implements opt-in `HANDOFF-RENEWAL`. Only all four explicit flags `--probe-network --probe-sql-read --probe-worker-lease --probe-lease-renewal` and verified OFF-1I lease-snapshot PASS allow two fixed SQL Server SELECTs in separate bounded TLS ODBC connections 15 seconds apart. SQL computes safety flags and heartbeat epoch milliseconds internally; client compares constant fencing generation and strictly increasing heartbeat marker; no token or owner id fetched, no numeric marker output. An observation of renewal is **not** local worker ownership/Report Job/actual job progress or FULL_LIVE. Real deployment, Hosted CI, Codex review and merge are independent pending gates.

## 2026-10-24 OFF-1J mandatory memory compaction verified

- First Codex review for PR #306 reported P1: active `.codex/architecture.md`, `api_contract.md`, `decisions.md` and `known_issues.md` surpassed AGENTS.md's 20 dated/work record limit. Each pre-compaction FULL text was created first at its matching `.codex/archive/<name>.md-20261024-180500.md` path and re-fetched byte-for-byte identical with the SAME Git blob SHA before rewriting any active document. Preserved sizes and blob identities: architecture 15,245 chars (`9d746757c94c05c67bc74e45e68d8ad41e061b0c`); api_contract 14,199 (`a92e140d6dc5aa0a6c9665fb58d00d25336b40c8`); decisions 15,630 (`f72d558bac5db9a41fd500523ba076a98267bc3e`); known_issues 17,224 (`c92178e7ff09d6d8c6e0a369ae711b1d45526598`). Active records condensed to 63, 49, 82 and 96 lines, maintaining live unresolved Product, ES, SQL, Worker, LLM and DOCX constraints; earlier 2026-10-21 archives remain linked. None of this is a real Linux acceptance; final exact HEAD Hosted CI and Codex re-review are required. No Merge.

## 2026-10-24 OFF-1K local Handoff inherited-owner attestation

- PR #306 OFF-1J merged to main at `807bf96cc51bfbbbc7878ca2ab7186f0fb840b63` after exact-head Codex CLEAN, Hosted 1,109 pytest + 2 Worker E2E + 19 OFF-0 PASS; no private SQL deployment acceptance.
- OFF-1K branch `feat/sraf-off1k-handoff-owner-binding` adds an independent optional `HANDOFF-OWNER` matrix row. All SIX operator flags are mandatory: network, sql-read, worker-lease, lease-renewal (15s), worker-identities and handoff-owner, plus actual previous WORKERS/HANDOFF-RENEWAL PASS. It binds only an explicitly **inherited-at-exec** `REQUIREMENT_HANDOFF_OWNER_ID` obtained from the canonical verified local Handoff PID's bounded NUL-framed Linux /proc environ. The existing `config.bootstrap.bootstrap_env` does not override already-set OS env values; late dotenv-only owner and default `handoff-<pid>` are NOT inferred. One fixed TLS-verified SQL SELECT computes byte-exact lease owner equality without returning owner/token; PID/start/owner evidence is repeated after query. Positive means point-in-time local inherited owner equals active DB owner, NOT actual renewal by this PID, handoff work, Report Job or FULL_LIVE. Hosted CI, formal Codex review and real operator Linux SQL evidence separately pending. No merge without user authorization.

## 2026-10-24 P2.1 URL-encoded Preview regression — PR #289 refresh

- On 2026-10-15 the deployment host yielded 64 PASS / 1 FAIL because it expected HTTP 400 but URL-encoded >1MiB Preview input returned Product's HTTP 422 `requirement_preview_input_invalid`. After restoring old PR #289 onto current `main`, Hosted run #40090472110 reproduced 64 PASS / 1 FAIL in the *opposite* direction: FastAPI 0.162.0 / Starlette 1.9.0 rejects the same oversized URL-encoded form with HTTP 400 before Product input parsing. Neither result invoked Preview. Revised the test to admit only framework-size 400 (bounded error) or Product 422 (exact safe code), require no large request echo and no Preview call. Dependency ranges are unpinned; both safety boundaries are real, but exact response status is version-dependent. Rerun exact-HEAD Hosted Product pytest and Codex review; no live SQL or deployment acceptance, no Merge.

## 2026-10-24 P2.1 exact-head Hosted test evidence (PR #289)

- GitHub Actions `SRAF P2.1 Requirement Product API tests` run #40090472110 on `da30d571f38d46ffc292b3e0b2d2a1602eed688e` **FAILED** with 64 pass/1 fail; FastAPI 0.162.0 + Starlette 1.9.0 returned safe parser HTTP 400 where older deployment-host Starlette 0.50 returned Product HTTP 422. Subsequent run #40090730685 at `e49acffda9109ea5ae2eceddb53d809ecfad2f1a` **PASSED 65/65** (2 existing deprecation warnings) in 3.59s, after making the regression require bounded size-related HTTP 400 or canonical HTTP 422, no Preview calls and no large echo. These are synthetic Hosted API tests only, not real SQL/airgap acceptance. Subsequent documentation-only test-comment commit requires its own exact-head CI verification before formal Codex review; no merge authority granted.


## 2026-10-24 Hosted main integration for OFF-1K PR #307

- PR #289 merged on main at `40b8bb9f1122090f8e025c1054b9b319ab4f92aa` after exact-head Hosted P2.1 65/65 PASS and formal Codex CLEAN. This OFF-1K integration brings forward the P2.1 regression test, dedicated CI workflow, and both original P2.1 memory/known-issues appendices without discarding the OFF-1K operator diagnostics. The older P2.1 notes document contemporaneous pending gates; the current PR #289 state is MERGED. PR #307 prior CLEAN and Hosted tests were at old head `c050de9dc8f7dc5b4fd02de81bd07048b9df7f9c`, not this integration commit. Revalidate exact new OFF-1K PR HEAD with Hosted CI and fresh formal Codex; no Linux acceptance, no implicit merge.

## 2026-10-24 OFF-1K main sync and current Hosted verification

- Preserved both OFF-1K and merged Product PR #289 history with non-force, two-parent merge `d455853eb805fd9594c46fbc9a20bbb7fba1cd8c` (parents OFF-1K `c050de9dc8f7dc5b4fd02de81bd07048b9df7f9c` and main `40b8bb9f1122090f8e025c1054b9b319ab4f92aa`). PR #307 conflicts resolved, now GitHub mergeable; separate user authorization still required for actual merge.
- On that merge commit Hosted workflow run [#40096081791](https://github.com/hun186/poc-agent/actions/runs/40096081791) returned SUCCESS: 1,154 focused unit regressions, 2 legacy E2E Worker identity tests, OFF-0 schema-only 19 checks PASS; config-only non-network probes remain partial. Vercel deployment status is a separate free-tier quota failure, not an OFF-1 runtime test result. This entry is an additional documentation commit, so fresh exact-final-HEAD Hosted CI and formal Codex review must run before merge. No private Linux SQL or physical air-gap acceptance performed.

## 2026-10-25 OFF-1L Schedule actor-labelled run observation — current work

- OFF-1K PR #307 merged to main `0702f2be4d9107c1e43f50d1aae7181dded7c9d0` after Hosted 1,154 + 2 Worker E2E + 19 OFF-0 PASS and Codex CLEAN; actual private SQL/Linux acceptance remains pending.
- OFF-1L `feat/sraf-off1l-schedule-claim-ledger` adds default-off read-only SQL actor-labelled ledger growth observation under four explicit flags: network/sql-read/worker-identities/schedule-claim and prior SQL-READ/WORKERS PASS. Two separate strict ODBC18 private IPv4/TLS SQL COUNT_BIG snapshots scoped to one canonical SRAF_OFF1L_SCHEDULE_ID, 15 seconds apart. Never triggers claim_due or reports run counts, ID or credentials. Growing actor-labelled ledger **does not prove local PID work, Handoff, report or full E2E**. Negative tests, CI workflow and operations guide added. Hosted CI, formal Codex Review and user-authorized merge are pending.

## 2026-10-25 OFF-1L first Hosted verification — PR #308

- GitHub Actions run #40165593763 on exact feature-and-docs HEAD `1578a4c17e11fdcd32b5d59d25f84c0c85495c8e` **SUCCESS**, inspected Hosted job log: OFF-0 schema-only 19 PASS, 1,179 focused pytest PASS (including OFF-1L strict flags/redaction/SQL-count negatives), and 2 legacy Worker E2E PASS. This is only CI mock ODBC, not live SQL Server, Schedule PID attribution or actual airgap acceptance. This memory evidence update itself produces a new commit requiring fresh exact-HEAD Hosted run and Codex review; no Merge.

## 2026-10-25 OFF-1L Codex P2 response — schema override

- Codex automatic first-review P2 identified that the matrix loaded SRAF_OFF1I_SQL_SCHEMA only for Handoff lease flags and not the independent four-flag Schedule-only check. Now include --probe-schedule-claim in the existing schema-reading condition (still requires network+sql-read) and add direct CLI regression verifying the custom schema flows to the SQL probe without any Handoff opt-in. Existing default and partial/no-network semantics preserved. New HEAD must pass Hosted CI and get fresh exact-head Codex review; no actual private SQL or user merge authorization.

## 2026-10-25 OFF-1M current Schedule→run read-only linkage work

- OFF-1L PR #308 merged on main `ee2ec7c985efc2c3ddb01cf4ed24d90dce71ad78`, after exact-head 1,180 focused tests + 2 Worker E2E + 19 OFF-0 PASS and formal Codex CLEAN. This did not certify live SQL or any actual Schedule PID activity.
- OFF-1M branch `feat/sraf-off1m-schedule-run-link` adds a separately operator-opted `SCHEDULE-LINK` row; needs 5 flags (network/sql-read/worker-identities/schedule-claim/schedule-link) and prior SCHEDULE-CLAIM PASS. Fixed single parameterized read-only SQL SELECT computes enabled + approved active schedule version, latest application-actor-labelled scheduled run's version equality, and persisted next_run_at after latest scheduled_for. The only returned evidence is three boolean predicates; missing/mismatched rows SKIP, no IDs or time values in output. SQL Server's normal transaction isolation does not attest an atomic distributed or even serializable cross-table snapshot. No process PID ownership, exactly which new run was claimed, job completion or FULL_LIVE inferred. Hosted CI and formal Codex Review pending; no user-authorized merge or actual private Linux test.

## 2026-10-25 OFF-1M first exact-HEAD Hosted verification (PR #309)

- GitHub Actions [#40167408415](https://github.com/hun186/poc-agent/actions/runs/40167408415) for code/docs HEAD `539c989c4c400ded27bf5f9195d87bc91d0026ee` completed SUCCESS: actual Hosted log confirmed 1,200 focused pytest PASS, 2 legacy Worker E2E PASS and OFF-0 19 schema-only checks PASS. No live SQL Server, authentic Schedule PID attribution, Report Job or private airgap acceptance is implied. Recording this evidence creates a new documentation-only HEAD that requires its own Hosted CI and a fresh exact-head formal Codex review before any user-authorized merge.

## 2026-10-25 OFF-1N read-only Handoff SQL acknowledgement — current work

- OFF-1M PR #309 is merged on main at `8b03ffd807f7a34d32f88e2fd8748f160afcbde5`, after exact-head 1,200 focused tests, 2 Worker E2E, 19 OFF-0 contracts PASS and formal Codex CLEAN. No real private SQL/Linux acceptance.
- OFF-1N adds `tools/sraf_airgap_off1n_handoff_ack.py` and new `HANDOFF-ACK` row with six explicit flags (network/sql-read/worker-identities/schedule-claim/schedule-link/handoff-ack), plus prior SQL-READ/WORKERS/SCHEDULE-CLAIM/SCHEDULE-LINK PASS. One more parameterized, bounded read-only SQL SELECT on the latest actor-labelled scheduled batch, requiring a selected item, persisted Handoff start/handed-off timestamps, joined workflow_id=report_v1 submission row, remote_job_id and dispatched_at. Returns only two server-computed flags, no run/job/submission IDs, timestamps, credentials or payloads. SQL row proves persisted *acknowledgement*, NOT actual remote Report Job progress, current local PID identity, DOCX, or fully sealed network. SQL normal isolation may see independent state changes; latest run can differ from OFF-1L's counted new record. New negative tests, Hosted CI wiring and operator guide; exact-head review, CI and user merge authorization pending.

## 2026-10-25 OFF-1N first Hosted verification — PR #310

- Exact-head Hosted workflow [#40189059867](https://github.com/hun186/poc-agent/actions/runs/40189059867) at `3e5d6d0b774266d32c4ca47ada502fe0d9cd6c84` completed SUCCESS. Inspected job log: 1,219 focused pytest PASS, 2 legacy Worker E2E PASS and OFF-0 19 schema-only contract checks PASS. Automatic Codex summary for this SHA reported completed with no findings. These are simulated ODBC and process-unit tests, NOT operator-authorized real private SQL/Report Job/DOCX or physical airgap acceptance. This evidence record is a further commit; final-HEAD Hosted CI and formal Codex review are still required before any explicitly authorized merge.

## 2026-10-25 OFF-1O read-only persisted Report Job checkpoint — current work

- OFF-1N PR #310 merged to main at `c0e37d04aa1e2326ef96fb113d1ac8e4eab0a6de`, after exact-HEAD 1,219 focused + 2 Worker E2E + 19 OFF-0 PASS and formal Codex CLEAN; no operator-authorized real SQL/Linux E2E acceptance. OFF-1O `feat/sraf-off1o-report-checkpoint` adds default-off `REPORT-CHECKPOINT`, requiring 7 explicit operator flags and preceding HANDOFF-ACK PASS. Reuses restricted OFF-1G TLS/private IP ODBC and canonical OFF-1L schedule selector; one new fixed, parameterized SELECT returns just two flags: latest actor-labelled run Handoff/reconciled times; and one SAME selected run item has report_v1 submission, persisted remote_job_state=completed, execution_state=completed, remote_completed_at/completed_at/artifact_reconciled_at, nonempty recorded artifact_relative_path, and 64-char lowercase hex artifact_sha256. No remote GET, DOCX bytes, SHA256 recompute or PID identity proof. A positive SQL checkpoint is not Report Job independent success, full batch success or FULL_LIVE. Tests, workflow and operator guide included; exact-head Hosted and formal Codex review not yet verified; no Merge without explicit user authorization.

## 2026-10-25 OFF-1O first Hosted verification — PR #311

- On code/docs HEAD `df923f8507a6f645df88f0bea4fe348afaee8677`, GitHub Actions [#40191149108](https://github.com/hun186/poc-agent/actions/runs/40191149108) returned SUCCESS. Independently inspected Hosted job log: 1,238 focused pytest PASS, 2 legacy Worker E2E PASS and OFF-0 schema-only 19 checks PASS. The test suite uses mock ODBC and cannot claim real Linux/SQL/Report Job HTTP/DOCX/airgap acceptance. This project-memory verification append itself creates another HEAD, requiring a new exact-HEAD Hosted CI and formal Codex review before any user-authorized Merge.

## 2026-10-25 OFF-1P local DOCX byte integrity — current work

- OFF-1O PR #311 merged to main at `aeae06963a7b1412ae2e46172e93f8884e47ebe1` after exact-head 1,238 focused + 2 Worker E2E + 19 OFF-0 PASS and formal Codex CLEAN. Real private SQL/Linux and DOCX bytes remained unverified.
- OFF-1P `feat/sraf-off1p-docx-integrity` introduces `tools/sraf_airgap_off1p_docx_integrity.py`, `DOCX-BYTES` row gated by all eight explicit operator flags, SQL-READ and the real previous REPORT-CHECKPOINT PASS, one canonical schedule ID, and independently configured absolute SRAF_OFF1P_ARTIFACT_ROOT. Additional fixed, parameterized SQL SELECT returns one latest-scheduled-run completed item's stored run-item ID, relative DOCX path, SHA-256 and frozen output-root fingerprint only **into memory**, never JSON. Root fingerprint must match canonical local root; Linux fd-relative O_NOFOLLOW opens publisher-style item folder and file, caps file at 16MiB, bounds ZIP member count/uncompressed bytes, validates basic DOCX structure and compares actual bytes SHA-256 to SQL. Digest or DOCX corruption FAIL; missing/path or SQL ambiguity SKIP. No writes, HTTP Report Job call, content echo, PID binding, remote execution or FULL_LIVE attestation. New tests/CI/doc/operator safety evidence; latest Hosted CI/review and user Merge remain pending.

## 2026-10-25 OFF-1P initial Hosted CI evidence

- On PR #312 commit `3b5af4692f5d3500bb29f9760122124b90e16961`, Actions run #40206818095 completed SUCCESS: 1,257 focused unit PASS, 2 Worker E2E PASS, and OFF-0 19 schema-only checks PASS. Mock ODBC and temporary local DOCX tests are not live Linux SQL/remote Report Job or physical airgap acceptance. Revalidate final HEAD before merging.

## 2026-10-25 OFF-1P formal Codex P2 remediation

- Formal Codex at HEAD `b07b1e07fe23e128c32355cb1411318cd9768197` reported two P2: a mutable ancestor of the configured artifact root could be symlink-swapped during SQL and pass using external data, and `zlib.error` from corrupt ZIP compressed bytes escaped to SKIP. Updated OFF-1P to pin the root descriptor by component-wise nofollow traversal **before** `_read_reference()`, and retain it through SQL and fd-relative read; ZIP validator now treats `zlib.error` / EOF corruption as invalid structure. Two specific reproductions added; Actions #40207552259 at `b290783089098208e587be37f39c600aa0006ab1` **SUCCESS**, Hosted log **1,259 focused + 2 Worker E2E + 19 OFF-0**. The final documentation/FD exception close commit needs fresh exact-head Hosted CI and formal Codex review. No merge and no real deployment acceptance.

## 2026-10-27 OFF-1Q authenticated Report Job GET — current development

- OFF-1P PR #312 formally Codex CLEAN at exact `d1d0b52a411e0756b9cabb3b6dcfe4c00ff8bebc` after two P2 corrections and Hosted 1,259 focused + 2 Worker E2E + 19 OFF-0 PASS, user-authorized merge to main `ff5ac56ec18a58c812deeca30381aea5b1151f70`. No private Linux/SQL/DOCX or physical airgap acceptance was established.
- OFF-1Q adds a ninth opt-in `REPORT-LIVE` row after actual `DOCX-BYTES: PASS`. New `tools/sraf_airgap_off1q_remote_report_job.py` uses a fixed parameterized SQL TOP(2), same latest-scheduled batch and same selected item ordering as OFF-1P, joins report_v1 submission and retrieves only local in-process `rpt_<32hex>` and `rhsub_<48hex>`, then one authorized HTTP GET to exact 127.0.0.1:<port>/v1/report/jobs/{id} using a separate REPORT_JOB_READ bearer token with no proxy, redirects or retries, bounded time/body. API must return matching job_id and metadata submission_id/workflow_id and completed state to PASS. No report-job create/download, no data/IDs/tokens/SQL-native errors in JSON. SQL and HTTP/ZIP evidence are successive observations, NOT atomic proof of the same DOCX/artifact job; API listener process identity, Agent/LLM/ES and airgap remain pending. Tests/CI/docs included, Hosted exact head CI/review and merge pending.
