# Project Memory

## Current Summary

- This repository is a FastAPI + Elasticsearch RAG/agent system. Runtime API source is `sra_api/`; `api/` is the compatibility namespace. Agent/retrieval is in `agent/`, ingestion in `data_ingestion/`, and tests in `tests/`.
- Requirement import authority is SQL Server with immutable Requirement Version/Snapshot history. Requirement recurrence/execution authority is the separately versioned `sra_schedule` schema. Report Jobs own real Agent/LLM/Elasticsearch execution and DOCX production.
- Requirement scheduling uses external Schedule/Handoff workers; Report Job execution remains downstream. Product orchestration must compose those authorities rather than create a second scheduler, queue, worker, auth store, or execution path.
- Formal live Requirement deployment acceptance remains blocked by the unresolved Elasticsearch `mapping_incompatible` condition. Repository review/checks do not clear that live blocker.
- Requirement Product Design/Plan v1 is the active implementation roadmap. P1.0 schema v4, P1.0A authority identities, P1.1 presenters/identities, P1.2 preview, P1.3 one-time create, and P1.4 recurring create are merged through PR #283 at `main@2c22df0bf7fa9a973f374849ebd0de82f2ca6946`.
- Product P1.5 Task updates/draft proposals merged in PR #284, P1.5A draft activation in #285 and P1.6 low-level ownership fences in #286 according to earlier review records. Product P1.7 input replacement was developed as a separate slice; its merge and live acceptance require verification. P2.1 public Task/Run read and preview remain under review on PR #288; later Product HTTP mutations, P2.2, UI/browser and authorized SQL Server E2E remain independent gates.

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

- The repository is **PUBLIC** as confirmed by GitHub Connector. Earlier PRIVATE-account GitHub Actions jobs were blocked before starting by a billing/spending-limit annotation; those historical `Failure` statuses are **NOT_EXECUTED**, not pytest failures or an active billing blocker.
- PR #295 had real Hosted Actions **#39551740910** SUCCESS on historical exact head `e587fcda9404bb18e6ac6a7753687629eac77944` with **539 pytest PASS in 1.17s**, **OFF0_CONTRACT 19 schema-only PASS**, compilation/dependency/config-only checks successful. Earlier real Hosted green runs include #39547153892 (539/19), #39543476662 (527/19), #39538097852 (513/19), #39534484218 (513/19), and rerun #39533967611 (513/19). These observations are SHA-specific history; **always query GitHub current HEAD, checks and Codex state live** rather than treating this file as real-time dashboard.
- PR #295 is not merged and no Linux update was performed. Hosted tests and OFF-0 contract checks are not live SQL Server, ES Mapping, LLM, worker or DOCX verification. The on-host `mapping_incompatible` blocker remains unresolved pending authorized operator-run evidence.
- Current-HEAD Merge gates: fresh **real Hosted CI success on that exact SHA**, completed clean exact-head Codex with no outstanding P1/P2 or open Review Threads, and explicit user `merge` approval. Do not Merge on assumed/old statuses.

## Recent Changes

- 2026-10-21: Thirteenth Codex exact-head review on `e587fcda9404bb18e6ac6a7753687629eac77944` completed with **1 P1**: `.codex/known_issues.md` and `.codex/backlog.md` crossed 40KB without mandatory archive/compaction. Inspection also found `.codex/decisions.md` above 40KB, and other active memory records exceeding 20 dated work blocks. All six `.codex` active files were archived **in full first**, re-fetched and compared byte-for-byte at their named archive paths, then compressed into current actionable summaries. User history, review chronology and original text are preserved in archives.
- 2026-10-21: The OFF-1B ES diagnostic in PR #295 enforces private numeric IPv4 HTTPS, fixed CA and IP SAN TLS identity, strict bounded read-only root/protected-auth/Mapping GETs, redacted output and partial-only classification. Up to three GETs normally; with operator-authorized `--verify-credentials`, up to four including one intentionally invalid Basic password request that can generate failed-login audit/lockout signals.
- 2026-10-21: Identity/auth semantics: a positive protected principal observation alone does not prove the Basic password if a proxy may substitute it; default remains `auth=NOT_VERIFIED`. For opt-in negative challenge, HTTP 401 proves the deliberately invalid password rejected; authenticated HTTP 200 matching the same enabled principal proves control ineffective (FAIL). 403/429/5xx, redirects and unattested success remain incomplete; false negative/positive auth proof must not be emitted. Independent later TLS certificate failure forces exit 1. Nested or top-level malformed Mapping becomes redacted invalid failure, never traceback.
- 2026-10-20: OFF-1B configured TCP preflight and separate API HTTP health slices were merged as PRs #293/#294, but cannot attest actual service identity or Linux end-to-end dependencies.
- 2026-10-16: OFF-0 19-check schema-only contract/validator does not perform live services checks and must never claim fabricated PASS/FAIL/WARN. OFF-1/2/3/4/5 are separate bounded-probe, packaging, report, and isolation acceptance phases.
- 2026-10-12: Requirement Product P1.5/P1.5A/P1.6 ownership and activation progressed through merged PRs #284–286; Product P2.1 PR #288 read/preview remains subject to separate source/CI/SQL Server validation. No cross-Task result sharing/dedup without separate security review.

## Archived History

- `.codex/archive/memory.md-20261021-165000.md` — full 30,781-character previous active Project Memory, including Product P1 implementation, PR #292–295 exact-head Codex review and Hosted CI chronology; pre-compaction archive content verified byte-for-byte.
- `.codex/archive/known_issues.md-20261021-165000.md` — full 45,639-character previous issues history.
- `.codex/archive/backlog.md-20261021-165000.md` — full 40,879-character previous backlog, with Product P2.1 and OFF milestones.
- `.codex/archive/decisions.md-20261021-165000.md` — full 47,371-character previous engineering decisions.
- `.codex/archive/architecture.md-20261021-165000.md` — full 29,940-character previous system architecture.
- `.codex/archive/api_contract.md-20261021-165000.md` — full 36,169-character previous API contract.
- Earlier compaction archives linked inside those complete preserved source files remain available, including `memory.md-20261008-113100.md`, `known_issues.md-20261006-153400.md`, `backlog.md-20261006-153400.md`.

## Compaction Record

- 2026-10-21: Mandatory AGENTS.md §Memory Compaction, triggered by >40 KB, >20 dated work records, and redundant superseded review logs. Each of six exact full pre-compaction contents was **created under `.codex/archive/` and re-fetched/verified identical BEFORE overwriting any active text**. Each active file then re-fetched and compared against its condensed contents. Unresolved live mapping, SQL/Worker, Product/airgap backlog, security, API contracts and trust decisions remain in the active summaries. Archives retain exact original details. Newest PR head must undergo fresh Hosted CI and Codex review; no merge or live deployment was performed.


- 2026-10-22 PR #296 OPEN on feat/off1b-es-san-warning-diagnostic, after merged PR #295. Background: real Docker ES host IP moved; CA_CHAIN_VALID YES, two IP SAN and two DNS SAN entries, ES_IP_MATCHES_SAN False, OpenSSL verify code 64. New explicit --warn-only-ip-san option retains fixed CA and private numeric IPv4 but deliberately relaxes IP identity **only** for partial diagnosis; warns via tls_validation/Mapping WARN, exit 2, never official acceptance. This carries real credential exposure risk: the configured Basic username/password still goes to a CA-signed IP-identity-unverified peer; use only on independently trusted routed Docker networks and never by default. No deliberate negative credential check while in warning mode. First Hosted run #39710545333 on intermediate head 74b072b8 ran and FAILED three new tests because the dummy CA fixture cannot create SSLContext (547 PASS, OFF-0 19 PASS); tests were corrected, exact-head CI and formal Codex review still needed. No merge or Linux change.

- 2026-10-22 PR #296 operator request: choose warning-only as the default *Quick/Diagnose CLI behavior* to avoid blocking read-only Mapping observations after moving a Docker ES private IP. `--strict-ip-san` explicitly restores full CA + leaf IP SAN verification; `--verify-credentials` implicitly uses strict mode, and explicit --warn-only-ip-san remains compatibility alias. In Quick the existing Basic password can go to a CA-signed IP-identity-unverified peer (real credential-capture risk even offline), and non-matching IP SAN always forces tls_validation/mapping WARN and CLI exit 2, NOT formal PASS. Four new regression areas added. Codex found a P2 on earlier head `d741bef...`: mismatched SAN observed before Basic was lost when HTTP response failed. Fixed by preserving mismatch through transport/response failure reason and propagating identity_warning even on root, protected-auth and Mapping error branches. Actual Hosted Actions #39712503345 on `fda02f3939fd0682013c0d5457a062b411d76ca5` SUCCESS with 560 pytest PASS and OFF-0 19 schema-only PASS. Latest-head review/CI needed after docs; PR remains unmerged, Linux unchanged.

- 2026-10-22 PR #296 latest exact-head Codex identified P2: existing `identity_warning=true` and `tls_validation=WARN` from an earlier HTTPS GET were overwritten with NOT_VERIFIED when a later auth/Mapping connection failed before observing a new peer SAN. Corrected `_later_tls_failure` to preserve WARN on later inconclusive transport failure while promoting to FAIL for independently verified `es_tls_identity_unverified`. Added parameterized negative/positive cases for auth vs mapping and ordinary connection loss vs cert-chain failure, with no secret leakage. Requires fresh Hosted CI + final exact-head Codex before authorized Merge; operator expressly requested Merge after fixing newly surfaced issues. Actual Docker/Linux deployment and ES mapping acceptance are not yet verified.

- 2026-10-22 PR #297 OPEN (branch fix/off1b-es-chunked-mapping): real air-gapped Linux operator after merged PR #296 reported HTTPS root PASS, TLS WARN for Docker IP SAN mismatch, auth NOT_VERIFIED, Mapping FAIL/es_https_transport_unavailable_ip_san_mismatch. Independent read-only ES Mapping header probe returned HTTP 200, no numeric Content-Length, Transfer-Encoding CHUNKED, Content-Encoding IDENTITY. This confirms a transport framing compatibility problem, **not** verified mapping_incompatible. New operator-only bounded chunked decoder, 2MiB Mapping limit (root/auth remain 64KiB), explicit identity encoding, strict CL+TE ambiguity refusal, 3s total deadline and redaction; fixtures/rejection tests added. No change to runtime ES TLS or real Docker. Needs exact-head Hosted CI/Codex then user-authorized merge; Linux Mapping and FULL_LIVE still not tested after change.

- 2026-10-22 PR #297 verification checkpoint: Hosted Actions run #39737814902 on intermediate head 6398116a... executed and FAILED 23 new tests (565 PASS, OFF0_CONTRACT 19 PASS) because the test helper constructed `asyncio.StreamReader` outside an active asyncio loop. Fixed the synthetic reader helper to prefeed bytes + EOF within `asyncio.run`, preserving decoder functionality. Re-run #39738238839 on exact code head 309f858b4cd7cdd2022a4a90fc3c9f03cd1251d9 completed SUCCESS: 588 pytest PASS in 1.63 seconds, OFF0_CONTRACT 19 PASS, compile/dependency/config-only green. Runbook old paragraph about "rejects chunked" corrected on later documentation commit. Final exact-HEAD CI + Codex Review still required after documentation commits; PR remains OPEN/unmerged and Docker/Linux unchanged.

- 2026-10-22 PR #297 Codex review on intermediate HEAD 6398116a identified 1 P1 + 3 P2: pytest fake StreamReader initialization outside event loop, HTTP/1.0 illegally accepting chunked, forbidden Content-Length/Transfer-Encoding/auth/routing trailer names, and stale runbook/memory describing deliberate chunked refusal. P1 tests fixed and actual Hosted #39738238839 at 309f858b returned 588 pytest PASS/19 OFF0 PASS; docs and .codex then updated and former runbook contradiction replaced. P2 HTTP/1.0 now explicitly rejected for TE:chunked (version passed through); forbidden trailer check reuses existing audited OFF-1 `_TRAILER_HEADER_ONLY_FIELDS`/prefix policy and rejects Proxy-Status absent attestation. Added >10 negative tests. Latest exact-HEAD CI and fresh Codex pending; no merge or Linux runtime change.

- 2026-10-22 PR #297 second Codex review on head 00cb19a0 found P2 `Reject non-identity response encodings`: the decoder could accept JSON bytes with a contradictory `Content-Encoding: gzip`, leading to false Mapping success. Fixed by validating at most one `Content-Encoding`, strictly `identity` case-insensitively, or no content encoding; reject gzip/deflate/br/stacked/duplicate before reading bodies. Added 18 pytest cases spanning fixed-length + chunked content and regression acceptance of identity/absent. The user's actual live Mapping header said `Content-Encoding: IDENTITY`. Need new exact-head Hosted CI and formal Codex re-review; PR not merged.

- 2026-10-22 PR #297 Codex latest exact-head review at 37125ae12fcbcec28a15c71f5bde1621ad8f9b54 completed with one new P2: chunk-extension acceptance only required printable ASCII, so malformed `1;foo==bar` could be parsed and allow false Mapping PASS. Fixed by reusing the audited `_CHUNK_HEAD` RFC-token subset from OFF-1 while retaining a stricter 8-hex-digit chunk-size cap. Added 9 invalid and 7 valid token/zero-chunk extension tests; exact-head Hosted CI/official re-review still required; PR remains unmerged.


## 2026-10-22 OFF-1B configured index discovery (in review)

- New branch `feat/sraf-off1b-es-index-discovery` starts from merged PR #297 main. It introduces operator-only `tools/sraf_airgap_off1b_es_index_discovery.py` with bounded selected-runtime ES targets, differentiated default/topic/E2E roles, safe mapping-only partial diagnostics, per-index continuation and redacted JSON. Existing single-index OFF-1B behavior is unchanged; its preflight gained opt-in `skip_mapping` reuse. No Linux deployment, ES mutation, or FULL_LIVE acceptance is claimed.
- Runtime `agent/es/es_client.py` aggregates `ES_INDEX` and `INDEX_CONFIG.topic_index_map`; index_loader merges selected index YAMLs additively by topic and honors `default_indexes`, not legacy singular `default_index`. Operator discovery deliberately leaves unspecified runtime's hardcoded development fallback UNRESOLVED and does not assume any development index is present in production.
- Hosted CI and exact-head Codex Review of this branch remain pending and must be checked against current HEAD before merge; Linux evidence remains separate.

## 2026-10-23 PR #298 exact-head Codex findings and remediation (pending verification)

- Formal Codex review completed for `1d8beaa52dbab672ecffb361045cad1a110633f8` with one P1 (late SAN warning bypassed by fixture-conflict early exit) and two P2 (identity-unverified negative Mapping incorrectly FAIL; YAML numeric index selectors dropped). Prior four P2 threads had been resolved; these three are newly raised.
- OFF-1B discovery now records SAN mismatches immediately after each Mapping request, downgrades response-derived positive and negative Mapping verdicts to advisory WARN when peer identity is unverified, and mirrors runtime scalar-to-string YAML selector normalization without loading or printing secret-prone runtime config. Added regression tests for late SAN/fixture conflict, base/late warning with negative Mapping evidence, independent continuation, CLI partial exit and numeric YAML selectors.
- Hosted CI on the remediation branch and fresh exact-head Codex re-review remain pending until verified. This is operator-only PARTIAL_ONLY_NOT_ACCEPTANCE; no Linux or ES changes and no merge authorized.

## 2026-10-23 PR #298 later exact-head review — external deployment index config

- Codex completed review on `7f35d4555a224e4b32cb92f38502b89567121be8` and identified one new P2: discovery rejected explicitly selected `INDEXES_CONFIG`/`INDEX_CONFIG`/`INDEXES_CONFIGS` YAML files outside the repository, despite the runtime accepting their resolved paths.
- Corrected selected-file reading policy: implicit defaults must stay checkout-local; *explicitly* selected external YAMLs may be read under the unchanged 8-file/256-KiB/read-only bounded policy, and are flagged `external_index_config_not_release_attested`. No external file or selector names are included in default logs; deployment provenance still requires separate attestation.
- Added regressions for all three explicit selector keys, external multi-file order/topic additive merge, oversized YAML and implicit symlink escape. Hosted CI and formal exact-head Codex re-review of these latest edits remain pending. PR #298 remains unmerged; no Linux/full-live claims.

## 2026-10-23 PR #298 ninth Finding (pending final review)

- Codex completed formal review of `412b1be26dd8eee1b13e68ad08aea110ec2c1e02` and found one new P2: a later nonempty scalar/list YAML root invalidates the runtime's index loader but operator discovery continued using stale selectors from earlier files, potentially issuing authenticated Mapping GET.
- Discovery now treats truthy non-object roots and YAML syntax parse errors as fatal `INVALID_CONFIG`: zero discovered selectors, zero network probes (even with explicit `ES_INDEX`/E2E selector), redacted notes, exit code 1. Falsy/empty YAML roots retain runtime's `safe_load(...) or {}` fallback. Regression tests include later invalid YAML/root, explicit external override, no network, no leaked names, and CLI exit.
- Latest exact-head Hosted CI and formal Codex re-review are separate required gates; do not treat any test pass as live ES/RAG acceptance. No merge or Linux changes authorized.

## 2026-10-23 OFF-1B review follow-up

- Latest PR #298 Codex review of 9f01bed found two P2 problems: index lists defined as scalar values, and unreadable selected YAML, could cause stale configured targets to be diagnosed. Both are addressed in the discovery tool and tested; latest Hosted CI and formal review are still required.
- No merge and no live deployment performed.

## 2026-10-23 PR #298 formal Codex review of 297870df

- Review completed with two P2: literal overlap between a production selector and REQUIREMENT_E2E_ES_INDEX was noted but not made fatal; integer YAML topic keys were dropped though the runtime loader retained them.
- PR branch remediation makes a literal fixture collision INVALID_CONFIG/exit 1 with zero network access; non-string hashable topic keys now retain their index values without exposing keys. Regression tests cover no network, redaction, CLI failure, numeric/boolean keys and additive merge. Hosted CI and fresh exact-head formal review are pending. No merge or Linux deployment.

## 2026-10-23 PR #298 default-fixture and recursive-YAML findings

- Formal Codex review on `912059cd` completed with two new P2 findings: default Requirement E2E fixture (when no environment override) was not protected from literal/alias production collisions, and YAML recursion depth failures reached the generic incomplete exit instead of invalid configuration.
- The discovery tool now uses the same built-in default E2E fixture constant as the Runtime with the effective deployment config override, protects both literal and resolved alias conflicts, and does not issue extra probes to an unconfigured fixture. Recursive YAML parse failures are classified as invalid config, clear all stale selector targets, block ES network, and exit 1.
- Regression cases cover all production selection sources, default fixture alias, no extra implicit network probes, forced and deep YAML recursion, status and redaction. Current Hosted CI and new formal exact-HEAD Codex review are separate pending gates. PR not merged; no on-host production acceptance.

## 2026-10-23 PR #298 E2E fixture naming parity follow-up

- Codex review completed on `35407f23bba2a27a3b5cdab3abc731c759012c05`, raising one P2: selected E2E fixture names could be syntactically safe for Elasticsearch but invalid under the runtime's `requirement_e2e_[a-z0-9._-]{1,238}` contract.
- The runtime and operator diagnostic now share a compiled E2E index regex pattern from `agent.external_capabilities`. An invalid effective E2E fixture name blocks discovery and all Elasticsearch network probes, yields redacted `e2e_selector_invalid` / `INVALID_CONFIG` and CLI exit 1. Existing valid fixture tests were migrated to runtime-valid names; regression cases verify invalid variants, no secret leakage, no network and runtime parity.
- Hosted CI and fresh formal Codex review on latest HEAD are distinct required gates. The PR remains unmerged; no Linux or real Elasticsearch acceptance was run.

## 2026-10-23 OFF-1C bounded zero-hit search preflight (work in progress)

- PR #298 was merged into `main` at merge commit `f0a57fc910655990db2be426ca067f5dbd816776`, after Codex CLEAN on exact HEAD `ea53992f`, 16/16 resolved threads, and Hosted 707 pytest/19 OFF-0 PASS. No Linux rollout was performed.
- Next independent OFF-1C branch `feat/sraf-off1c-readonly-search-preflight` extends the existing operator-only index diagnostics with `--check-readonly-search --strict-ip-san`. The optional request is a single fixed-size-zero, no-hit Elasticsearch GET on the first required literal selected index after Mapping checks, with strict CA+IP SAN identity and existing fixed private-IP transport. Without explicit flags, old behavior is unchanged. Never log hits/credentials or imply full RAG/LLM/SQL/Word acceptance.
- Regression tests added for opt-in, wrong/valid data formats, status codes, no additional request in unsafe modes, CLI exit handling and redaction. Latest Hosted CI, formal review and actual operator Linux evidence remain **not yet verified**. No merge authorized for this new branch.

## 2026-10-23 PR #299 first formal Codex review remediation

- Formal Codex reviewed initial OFF-1C HEAD `8ba930831971` and raised two P2 findings: strict search 401/403 was incorrectly NOT_VERIFIED/exit 2; malformed/over-limit HTTP response bytes were collapsed into a generic transport-unavailable reason rather than failure.
- Updated strict search classification to FAIL on HTTP 401/403 without claiming separate credentials outcome. Introduced a fixed response-framing exception and redacted response-invalid code for the optional strict search GET, retaining legacy Mapping/root semantics and NOT_VERIFIED for actual transport failures. Added raw HTTP framing tests, transport classification, CLI exit 1, no-leak and timeout regressions.
- Current HEAD Hosted CI and fresh exact-head formal Codex review remain pending; do not claim CLEAN or merge. Air-gapped Linux execution remains untested.

## 2026-10-24 OFF-1D bounded readiness matrix (review pending)

- After PR #299 was merged to main at `dcdc8aa332e2fd9f74dd38f2a225fa2fab7d13a3` (Codex CLEAN; 742 pytest and 19 OFF-0 contract checks on the PR head), started `feat/sraf-off1d-readiness-matrix` as the next independent operator-only slice.
- New `tools/sraf_airgap_off1d_readiness_matrix.py` reuses reviewed host disk / fixed ODBC library-file observations, configured API/ES/LLM private-IP TCP probes and bounded anonymous API /healthz, forming a fixed redacted dependency matrix. It is no-network by default; `--probe-network` explicitly opts in to a maximum of three TCP connects and one loopback HTTP health check, with independent checks continuing after unrelated failures.
- SQL read, ES authenticated Mapping (existing separate tool only), model inventory/inference, real workers, Word outputs and air-gap isolation are explicitly NOT_TESTED and prevent any FULL_LIVE conclusion; matrix exits 1 for actual observed failures and 2 for incomplete (never 0). No private Linux acceptance, credentials, SQL mutation or production deployment.
- Deterministic regression tests, workflow integration and operator runbook were added. Current exact-head Hosted CI / formal Codex Review must be verified before merge and are not yet attested here.

## 2026-10-24 PR #300 formal Codex review: 3 new P2 findings

- Formal reviewed HEAD `3f35791f4c8a58dcf45aaafa30ee30a5adb0ebd3` completed with three P2 findings: API /healthz nested provider contradictory PASS, unknown FAIL reason incorrectly demoted to SKIP, and invalid APP_ENV profile wrongly returning incomplete exit 2.
- Remediation in the OFF-1D readiness matrix requires a resolved configuration, integer 200, correct reason/method/path before reporting health PASS. Explicit invalid config or non-200 HTTP responses become FAIL. A reported FAIL retains failure severity even when its reason is redacted. Invalid APP_ENV profiles return redacted `runtime_profile_invalid` with ISSUES_FOUND/exit 1; unknown loader failures still exit 2.
- Regression cases cover inconsistent provider statuses, non-200 and bool HTTP status, unknown FAIL codes from disk/ODBC/TCP/API, CLI exit and actual bootstrap APP_ENV input. Hosted CI, precise HEAD review and thread resolution are separate gates; PR still OPEN and no live Linux acceptance claimed.
