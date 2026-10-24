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

- Product Schedule schema v4, P1.3/P1.4 create saga, P1.5 Task updates, P1.5A draft activation, and P1.6 low-level ownership fences were implemented in separate earlier slices (merged through PR #286 as documented in earlier commits). P2.1 public Task/Run read and preview is a separate review branch PR #288; do not claim Product UI/P2.2 or live operator acceptance is complete.
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

- 2026-10-21: PR #295 ES credential-control truthfulness: only deliberate wrong-password HTTP 401 attests rejection. Protected HTTP 200 returning the same enabled Basic realm principal despite the wrong password proves the control ineffective (FAIL). HTTP 403/429/5xx, redirects and unattested success cannot show acceptance or rejection and must remain NOT_VERIFIED/INCOMPLETE with no Mapping GET.
- 2026-10-21: PR #295 reports the real configuration/evidence boundary: `PARTIAL_ONLY_NOT_ACCEPTANCE`; root/positive-auth/Mapping GET maximum 3 by default, or 4 with one explicitly authorized failed-login control (`--verify-credentials`), which may create audit events and lockout risk. No default failed login. A distinct TLS identity/cert failure forces failure; independent transport uncertainty remains incomplete.
- 2026-10-21: ES Mapping JSON may parse while its root/nested field containers have invalid types. Validate bounded `properties`/`fields` dict shape first, reuse application mapping-compatibility predicate only for valid structures, and return a fixed redacted error without stack traces.
- 2026-10-21: Public Hosted CI became available after repository visibility switched from private; historical billing/spending-limit failures were never started. A successful 539-pytest/19 OFF0-contract run #39551740910 is prior-SHA evidence only, not actual private Linux ES Mapping acceptance. Current-HEAD CI and Codex review must be queried, not inferred from static memory.
- 2026-10-21: Repository AGENTS.md triggers archival + compaction for active files above 40 KB or >20 dated blocks. All pre-compaction full files archived before summaries. Release gate/explicit merge requirement and live acceptance limitations stay actionable in memory.
- 2026-10-20: OFF-1B TCP and API HTTP slices intentionally report bounded partial observations; never assert worker, actual ES auth/Mapping, LLM inference, SQL access, artifact or air-gap readiness from TCP connect or `/healthz` alone.
- 2026-10-16: OFF-0's 19-check schema contract cannot generate unsupported runtime PASS/FAIL/WARN. Unimplemented checks remain honest SKIP and require reviewed OFF-1 probe evidence for promotion.
- 2026-10-12: Product P2.1 input/HTTP safety boundaries require bounded JSON/CSV/XLSX predecode work, consistent SQL Read Task/Schedule locks, pagination and no cross-Task result sharing. SQL Server concurrency and operator E2E remain separate acceptance gates.
- 2026-10-08: Product Task PATCH separates in-place CAS from immutable Schedule draft proposals, with privileged draft activation and ownership fences. Do not build a second scheduler/auth store or bypass existing SQL control-plane authority.

## Archived History

- `.codex/archive/decisions.md-20261021-165000.md` — exact full pre-compaction active decisions (47,371 characters), complete Product, OFF-0/1, security, authentication, redaction and deployment chronology, verified identical before summary rewrite.
- Earlier archive references and pre-compaction decision details are preserved verbatim in that file.

## Compaction Record

- 2026-10-21: Mandatory >40 KB and repeated dated work-block compaction. Archive first, then preserve active runtime, provenance, Product and operator trust decisions above. Current GitHub SHA/CI/Codex status must be checked live; no merge or Linux deployment authorized.


- 2026-10-22 PR #296 portability policy: keep strict TLS CA-chain + IP SAN as the default; allow only explicit operator --warn-only-ip-san for **partial non-authoritative** Docker ES IP-move troubleshooting. Even when CA chain passes, identity mismatch raises TLS/Mapping WARN and exit 2. Supplied Basic password can be exposed to an impersonating CA-signed peer, so warn mode requires independent routing/CA provenance assurance, is not production acceptance and cannot run --verify-credentials. Prefer leaf IP SAN renewal or reviewed stable verified DNS name for final acceptance. Do not merge without explicit user authorization.

- 2026-10-22 PR #296 revised operator profile decision: default standalone OFF-1B CLI **Quick/Diagnose WARN** uses trusted CA but permits stale IP SAN, marking TLS/Mapping non-authoritative WARN/exit 2; --strict-ip-san and --verify-credentials explicitly enforce full IP SAN chain identity. Existing runtime ES trust settings unchanged. Real configured Basic credentials may be sent to a CA-signed but misidentified peer even in default Quick, so this tradeoff must be clear in operator docs and must never be equated with FULL_LIVE acceptance. Observed SAN mismatch must remain visible even if subsequent HTTP/transport parsing fails; don't suppress separate hard CA errors.

- 2026-10-22 PR #297: observed Elasticsearch Mapping uses standards-compliant HTTP chunked response, so extend bounded read-only operator diagnostic rather than change ES server/proxy or disable TLS. Permit single Transfer-Encoding: chunked with bounded trailers and cumulative decoded Mapping <=2MiB; root/auth retain 64KiB, same 3-second absolute deadline and strict refusal of CL+TE ambiguity. Mapping compatibility remains separate from HTTP framing and IP SAN warnings; no LIVE acceptance or runtime ES client changes.


## 2026-10-22 ES discovery security and compatibility decision

- Preserve existing single-index OFF-1B API/CLI and introduce a separate operator-only configured-selector CLI. Share vetted CA/private IPv4/Basic principal preflight through opt-in `skip_mapping`; never import runtime `agent.es.es_client` to use its TLS-hostname-bypassing client for diagnostics.
- Use only operator-selected loader inputs and exact literal configured selectors; do not enumerate `_cat/indices`, expand wildcards, fetch document bodies or classify unused remote indices as legacy from their names. E2E fixture and optional topic Mapping rules are not imposed on unrelated production indexes. Default WARN_ONLY IP SAN evidence cannot certify identity or FULL_LIVE.

## 2026-10-23 OFF-1B per-request identity evidence

- Capture every Mapping-request IP SAN mismatch before any selector-specific early exit; preserve the warning in the aggregate TLS status. Treat both positive and negative response-derived Mapping verdicts as advisory WARN whenever the intended peer identity is unverified. Keep genuinely strict certificate identity failures and independent local auth/configuration problems distinct and blocking. Match runtime index_loader's YAML scalar stringification while continuing to reject unsafe wildcard/invalid literal selectors.

## 2026-10-23 OFF-1C query diagnostic design

- The optional single read-only search must use verified TLS/IP SAN and an explicitly selected required production index with Mapping compatibility. Reject the request in WARN_ONLY mode. Size zero prevents document hits; responses remain redacted and do not attest RAG or full live readiness.

## 2026-10-24 OFF-1E decision: do not infer inference from inventory

- Reuse audited localhost-only bounded HTTP rather than connecting to arbitrary configured hosts or sending tokens. An explicit operator pair of flags and credible LLM TCP are prerequisites for exactly one GET /api/tags, which cannot execute a model. Never print model names, source URLs, credentials or remote JSON; do not accept an inconsistent nested provider PASS or promote OFF-0/FULL_LIVE from an inventory observation.

## 2026-10-24 OFF-1F model-generation safety decision

- Model inference has CPU/GPU/memory side effects. Therefore require a *third* explicit operator flag, plus positive actual model inventory on exact numeric 127.0.0.1 HTTP. Use a fixed small non-user-supplied prompt, 8 generated-token cap, 20s total client deadline, 64KiB strict HTTP response cap and one request/no retry. Do not assume a timed-out connection cancels server work, do not forcibly unload a model, and do not label a nominal positive generation response as E2E acceptance.
