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

## 2026-10-24 OFF-1 Engineering Decisions (Current)
- Separate operator diagnostics from production SQL registries, credentials, Worker processes and background jobs. ES diagnostics use strictly bounded selectors, read-only GET and CA; unknown IP SAN in warning-only mode cannot yield validated peer identity and must not trigger sensitive credential challenges.
- Model inventory is not inference; explicit local-only inference requires verified Ollama listener executable, socket inode, environment OLLAMA_NO_CLOUD=1 and supporting version before even one POST. Neither proves Agent/Word.
- SQL Server diagnostic uses operator-supplied least-privilege connection via private IPv4/ODBC18 strict TLS. `ApplicationIntent=ReadOnly` is only a routing hint, never an authorization proof; no DML/DDL or business-data reads.
- OFF-1H process verification reuses canonical `verify_worker_identity`, rejects symlink/FIFO/path races with fd-bound reads and exact argv PID-start/UID/cwd verification. Process existence alone is not useful work.
- OFF-1I one SQL lease snapshot does not prove local owner. OFF-1J requires an extra FOURTH operator flag for two fixed, separate-connection SQL Server snapshots 15s apart; compare fencing generation and strictly increased heartbeat-at marker. Returns only redacted partial evidence. Because `REQUIREMENT_HANDOFF_OWNER_ID` may be custom, guessing local `handoff-<pid>` ownership is forbidden; true association and Schedule claim cycle still pending.
- All merges require GitHub current exact HEAD CI success + formal Codex CLEAN + all review threads resolved + explicit user `merge`. No CI mocks may be passed off as actual offline/airgap acceptance.

## Archived History — 2026-10-24
- `.codex/archive/decisions.md-20261024-180500.md` — full 15,630-character original active decisions verified byte-for-byte with identical Git blob SHA before compaction. Prior decision archives remain discoverable through `.codex/archive/decisions.md-20261021-165000.md`.

## Compaction Record — 2026-10-24
- Preserved unresolved Product/security/SQL/ES/Worker boundaries and their full review chronology, including earlier review and architecture decisions, in named immutable archive.

## 2026-10-24 OFF-1K explicit birth-env owner binding decision

- Do not assume owner=`handoff-<pid>` because `build_coordinator_from_env` may receive `REQUIREMENT_HANDOFF_OWNER_ID` from post-exec `bootstrap_env` dotenv. Only accept a unique bounded printable ASCII owner from canonical verified Handoff PID's **initial** Linux /proc environment, for which bootstrap guarantees OS values take precedence. Avoid printing owner/env; SQL computes exact UTF16 binary owner comparison against a parameter after all six flags plus prior worker/lease-renewal evidence. Revalidate PID/start/env after DB. This is at most point-in-time ownership correlation; real DB renewal on the same generation, job progress, Report Job and DOCX remain distinct gates.

## 2026-10-25 OFF-1L non-invasive monitoring decision

- Never trigger claim_due() or alter live schedules for a readiness check. Read only one operator-selected canonical schedule's COUNT_BIG twice in isolated bounded SQL connections; observe a run's actor label without claiming process ownership or completion. Require actual SQL DBA permissions and explicit operator opt-in.

## 2026-10-25 OFF-1M incremental read-only linkage decision

- To improve beyond OFF-1L's bare actor-labelled count increment without new production writes or unsafe identity assertions, use one extra explicitly authorized, read-only SQL SELECT returning only three server-computed predicates for current Schedule active version, latest run version and later next-run. Require prior SCHEDULE-CLAIM PASS, never attach a PID identity to created_by or claim the observed row was necessarily created in that 15-second window. Leave future authenticated per-process attribution to separate reviewed work.

## 2026-10-25 OFF-1N operator-only Handoff ack decision

- After positive SCHEDULE-LINK and six explicit opt-ins, read one SQL predicate-only snapshot of the latest scheduled run's persisted Handoff submission/remote-job reference, not the semantic manifest, remote job content, or real API. Treat positive database acknowledgement as partial; do not start production jobs to force success, assume that created_by proves worker PID identity, or downgrade strict TLS/SQL DB privileges.

## 2026-10-25 OFF-1O observe same-item Report Job checkpoint, not remote success

- Prioritize an additional opt-in, read-only SQL checkpoint using the *same item* for Handoff/report submission/remote-completed/artifact metadata, to avoid cross-item false attribution. Keep remote Report Job API calls, authenticated identifier binding, actual DOCX content validation, and runtime PID evidence as separate acceptance gates. Never label SQL-only observations FULL_LIVE or assume a hash string proves a real artifact.

## 2026-10-25 OFF-1P bounded real published DOCX byte proof

- Extend SQL-only OFF-1O incrementally with separately opted-in **local file inspection**, not new Report Job APIs or active scheduling. Use frozen output-root fingerprint plus strict publisher path, fd-relative nofollow regular-file reads, capped file/ZIP resource costs and direct SHA256 comparison against SQL. Never print secret-bearing SQL row, path, hash or DOCX contents. Treat only actual byte/hash/structure match as partial PASS; keep remote Report Job / full E2E pending.

## 2026-10-25 OFF-1P root-file TOCTOU and ZIP corruption resolution

- Do not consider final-component O_NOFOLLOW sufficient if an ancestor can be renamed during an ODBC round trip. Open and pin the output root by per-component O_NOFOLLOW traversal **before** SQL; use only retained dirfd for item/file traversal after SQL. Treat zlib/EOF compressed-stream corruption as explicit artifact structure FAIL when the persisted checksum matches. Avoid showing paths/digests or claiming remote HTTP/full acceptance.

## 2026-10-27 OFF-1Q minimal independent remote Report Job GET

- Restrict first live Report Job diagnostic to explicit on-host authenticated read-only GET to a numeric 127.0.0.1 port, no caller-controlled URL, no DNS/proxy/redirect, bounded JSON and short timeout, no retries/job creation. Validate both remote job ID and original report_v1 Handoff submission metadata from same SQL selected item; do not accept HTTP 200 or completed alone as proof. Use owner-allowed REPORT_JOB_READ credential, never expose it or IDs in JSON; leave runtime listener PID trust, atomic SQL-to-file identity and physical airgap as separate future acceptance gates.

## 2026-10-27 OFF-1Q Codex P2 whole-call deadline

- Replace high-level streaming Requests with a reviewed minimal HTTP/1.1 numeric-IPv4 loopback client that applies one monotonic 3s total deadline across every network operation. Keep strict fixed route and regex-checked job IDs, bounded headers/body, Content-Length framing only and immediate socket teardown. Refuse redirects, chunked/compressed responses and unverified content; slower than 3s cannot PASS. No public hostname/proxy/real production acceptance.

## 2026-10-27 OFF-1R single-item SQL reference instead of independent latest selections

- Correct OFF-1P/OFF-1Q evidence mismatch possibility by adding one separately opted-in operator probe rather than retroactively equating earlier PASS observations. Select seven SQL columns from the same joined schedule batch/item/handoff; read file with existing pinned-root OFF-1P protections; authenticate same job/submission via OFF-1Q bounded loopback GET; re-read the SQL tuple and SKIP if changed. Preserve partial-only status; do not claim SQL read-write serializability, API listener/PID authenticity, signed provenance or complete isolated E2E.

## 2026-10-27 OFF-1S credential-safe listener check

- Reject treating 127.0.0.1 as process authentication. Use existing launcher identity record, bounded Linux proc state and listening socket inode proof; do not accept arbitrary PID/host/URL, do not spawn/signals/mutate. Crucially, require repeat attestation immediately after TCP connection and BEFORE bearer transmission, with post-body recheck and a safe SKIP if state changes. Keep OFF-1S separately opt-in and preserve legacy flags; do not overstate process attestation as cryptographic security or airgap acceptance.

## 2026-10-28 OFF-1S nested procfs mount policy

- Prefer fail-closed validation of the complete bounded `/proc/self/mountinfo` mountpoint set, not only the `/proc` root. Forbid any descendant overlay of numeric PID directories, self/thread-self or net inspection paths, even when an otherwise legitimate `hidepid=0` procfs root is present. Permit unrelated normal procfs support mounts such as /proc/sys and /proc/bus. Reject ambiguous mountpoint encodings and revalidate before and after fd enumeration; do not send owner-scoped HTTP bearer on any unverifiable view. This remains non-cryptographic, host/PID-namespace-scoped partial evidence.


## 2026-10-29 OFF-1S thread-level FD scanning security decision

For opt-in bearer GET listener corroboration, do not accept leader-only
`/proc/<PID>/fd` checks: Linux `CLOSE_RANGE_UNSHARE` can create a separate
FD table in a worker thread. Inspect each `/proc/<PID>/task/<TID>/fd`
under conservative global/process/thread/resource bounds. Reject unknown or
unavailable task views rather than assume they are harmless. Retain existing
mountinfo and pre-send fail-closed gates, and document that this is not
strong authenticated peer identity; protected UDS/mTLS remains future work.

## 2026-10-29 OFF-1T standalone design

- Reuse merged OFF-1S hardening in a standalone offline CLI rather than merge overlapping PR #315 verifier code. Retain full per-thread descriptor-owner validation, process/mount checks and conservative SKIP. The CLI makes no HTTP call and sends no bearer. Do not equate a local process snapshot with authenticated peer identity, SQL/ES/LLM/report execution or network isolation. PR #315 remains open pending final overlap decision.


## 2026-10-29 E2E preflight versus ordinary SRAF Readiness (PR #319)

- Ordinary FastAPI lifespan, Report Job Worker.start and real production inference must not run E2E live model probes or create/seed a private acceptance ES index. Keep mode *syntax* validated at startup, and freeze the complete capability plan only during an explicit superuser-protected operator runtime-evidence preflight.
- Verified E2E marker/provenance without a frozen plan must fail closed rather than using real or mock backends without accepted authority. Once prepared, preserve immutable live/auto/offline E2E plan selection and production/semantic-mock scope isolation. A healthy API listener is not equivalent to FULL_LIVE E2E acceptance.
- When Field Selector fails, preserve rule-based evidence and mark the model stage as degraded `fallback` with a sanitized failure category, not unqualified full success.

## 2026-10-29 E2E-only Data Agent probe timeout policy

- The explicit superuser-triggered Requirement E2E `Reply with READY.` Data Agent boundary must use LiteLLM's documented per-request `timeout=30`, `num_retries=0` to avoid default 600s budget and automatic client retry during model contention. This is deliberately scoped to `resolve_environment_plan`; do not impose the same short request budget on ordinary production Data Agent inference or silently switch E2E live to semantic mocks. Preserve E2E live fail-closed and auto classification. Continue to treat operator HTTP and complete ES/model preflight as separately unbounded pending an end-to-end deadline/async design.

- 2026-10-30 Operator E2E re-entry boundary: use a process-local nonblocking guard for the existing authenticated runtime-evidence handler and expose redacted superuser status, not a second Scheduler/Job Worker and not a fictitious terminated state after client disconnect. 409 on concurrent requests without entering resolver. Do not misuse this as an absolute deadline or cross-process lock; true total-limit requires explicit cooperative service/ES/LLM budget or durable job design.

- 2026-10-30 E2E server timeout: choose 540s *cooperative* monotonic operator-only budget, shorter than the separately proposed 600s Linux client bound. Cap each Ollama/LiteLLM/ES request using remaining time, turn off ES automatic retries, do not freeze a backend plan after expiry, and never assert that an in-progress SDK was canceled. Retain partially created dedicated ES fixtures for ownership/dataset revalidation rather than unsafe automatic delete. Preserve normal SRAF production timeouts.


- 2026-10-30 Operator E2E partial-fixture design: require ownership Mapping plus count and exact `_index/_id/_source` checks before writes, create only missing IDs using `op_type=create` and recheck; reject any unexpected/modified/aliased entry, never rewrite. Linux operator concurrency uses private UID-owned no-follow file `flock` with nonblocking admission, not daemon threads or duplicate Scheduler/Job queue. Expose only busy observation across processes; fail closed on corrupt/unsafe lock path. Document that Windows and separate hosts retain old scope.


- 2026-10-30: Do not globally expose a newly prepared E2E BackendPlan until **all** authenticated runtime evidence is constructed and the operator's cooperative deadline has not expired. Use request-only ContextVar provisional state and an explicit under-lock publication step; preserve immutability, independent Request Job fail-closed semantics and direct legacy `frozen_plan` callers. Do not introduce untrusted shared JSON plan files or silently adopt another process's hybrid/mock selection.


- 2026-10-30: Existing process-local E2E plan is an immutable prior decision, **not** a timeless current acceptance receipt. At operator runtime-evidence recheck entry, suspend its authority for newly entering verified E2E jobs and re-run actual source/LLM/ES evidence. Only fully successful same-plan revalidation under the preflight deadline restores local admission. Drift/failure/timeout leaves it suspended; do not silently replace a previously published live backend with fallback or permit ordinary `install_plan` to bypass suspension. In-flight E2E jobs already holding a plan are not preempted. Keep ordinary production report behaviour unchanged.


- 2026-10-30 Codex P2 resolution: operator revalidation suspends only new verified E2E Report Job admissions; the ReportJobWorker pins the exact plan after successful provenance+admission, and bound per-job tools transmit it to worker threads rather than re-reading suspended process authority. Preserve immutable job behavior through mode/recheck drift; no cancellation or implicit cross-host admission.
