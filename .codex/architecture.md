# System Architecture

## 2026-09-16 Runtime provenance generated-product boundary

- `shared/runtime_provenance.py` is the single path-policy authority for generator selection, operator-side reviewed-map reconstruction, deployment manifest validation, and generated dirty-product classification.
- `operator_e2e/output/**` and root-level `operator_e2e/*.docx` are generated evidence/report products and cannot become deployment runtime authority. The rest of `operator_e2e/` is not blanket-excluded: imported support/source-identity modules and harness configuration remain managed.
- `operator_e2e/requirement_e2e_profile_v1.json` and `operator_e2e/input/requirement_e2e_3items.xlsx` intentionally remain in the reviewed map as canonical operator fixture authority used by the harness, although they are not Linux service inputs. The XLSX retains its separate canonical source SHA-256 validation in addition to provenance byte authority.

## 2026-09-15 Requirement operator E2E harness

- `operator_e2e/test_requirement_schedule_e2e.py` is a thin deployment-host orchestrator: it uses authenticated HTTP Requirement/Schedule lifecycle calls, read-only launcher identity/process evidence, and read-only artifact verification. It never runs production workers or uses the manual Run route.
- `operator_e2e/requirement_e2e_support.py` owns environment validation, stage/result types, redaction, bounded diagnostics, process identity checks, automatic Batch identity validation, terminal checks, and DOCX/SHA verification. Production workflow logic remains in its existing modules.
- Correlation flows from Import Run and exact Snapshot to immutable Schedule Version, scheduled Batch, Run Items, durable remote Job IDs, and root-bound artifact evidence. Per-invocation evidence is isolated under `operator_e2e/output/requirement_e2e/<e2e_run_id>/`.

## 2026-09-16 Runtime provenance namespace and package preflight

- `shared.runtime_provenance` is the single policy for both provenance paths and import namespaces. Package roots define exact top-level Python namespaces; only `.py` entries in the explicit root-file policy define root module names. Shell and dependency files remain byte-managed but are never treated as Python modules.
- Deployment evidence walks `sys.modules.items()` and applies namespace policy before inspecting module paths. A qualifying namespace outside the project root is shadowing; a qualifying module inside the root but absent from provenance is unexpected active runtime; managed byte mismatches remain blocking.
- The provenance generator compares reviewed Git blob bytes with the exact working-tree runtime bytes destined for robocopy before manifest output, without normalization or source mutation.

## 2026-09-08 Shared SQL Server driver-resolution seam

- Generic SQL Server ODBC driver selection lives in `data_ingestion/sql_server.py`. Excel-to-SQL preserves its `sql_utils.detect_odbc_driver` import surface while Requirement's named registry uses the same helper.
- Excel-to-SQL task configuration and Requirement/Schedule named-registry configuration remain separate. Their inner DB key semantics align; `connections.requirement_control` continues to serve both `sra_requirement` and `sra_schedule`.

## 2026-09-04 Phase 1B legacy key-name compatibility

- Canonical fresh DDL continues to explicitly name every required PK/UQ/FK. Version-1 validation treats the PKs and `requirement_sets.source_id` UQ that PR #194 declared inline without names as structural identities: canonical schema/table, PK/UQ kind, exact ordered columns, and exactly one matching key are required, while the SQL Server-generated name is ignored.
- Keys and foreign keys explicitly named by PR #194 remain name-and-structure validated. Legacy acceptance does not rename or recreate keys and composes with the existing diagnostic-nullability repair before complete validation and commit.

## 2026-09-04 Phase 1B Requirement control plane

- `data_ingestion/requirements/` separates adapters, strict immutable mapping, deterministic hashes, analysis, and an explicit SQL Server schema/store.
- Manual upload, confined file path, and reviewed named SQL queries converge on one service. Commits atomically create immutable versions/snapshots; preview is read-only.
- The authenticated router initializes in the existing lifespan only when enabled and has no Agent, Elasticsearch, Report Job worker, Word, or Phase 1A SQLite dependency.
- SQL startup is a transactional 0→1 state machine: bootstrap the version container, migrate only version 0, structurally validate canonical v1 tables/columns/constraints/foreign keys, then write version 1. Unknown or malformed schemas roll back and fail closed.
- Commit-lock stale/anomaly detection rolls back the mutation transaction before a separate failed Import Run transaction records safe row diagnostics; active snapshot selection is not changed.
- Canonical-v1 startup validates each required named PK/UQ/FK against its owning/parent table and ordered local/referenced columns. The sole legacy-v1 repair changes `import_run_rows.source_row_number` from `NOT NULL` to nullable, then runs the complete validator in the same transaction.

## 2026-09-02 Unified API security boundary

- Canonical runtime imports remain `api.*`. Editor user authentication and service credentials resolve into transport-neutral principals only at the Agent/report boundary; service keys never satisfy Editor RBAC.
- The owner-aware Report Job schema is SQLite `user_version=1`; legacy version 0 is rebuilt in one `BEGIN IMMEDIATE` transaction before the owner-scoped partial unique index is installed.
- Browser document/Word access uses HMAC capabilities with exact action/representation binding rather than placing upstream credentials in URLs.

## Current Summary

### Unified operator launcher

- `run_sra_api.sh` is the foreground Linux supervisor for exactly three external runtime children: the API, Requirement Schedule Worker, and Requirement Handoff Worker. The API lifespan continues to own the Report Job Worker internally.
- A Linux `flock` prevents duplicate launcher instances. The launcher retains direct runtime PIDs, bootstraps project environment files in each Requirement worker process, applies separate approximately 10 MB runtime logs, and performs bounded TERM-then-KILL cleanup only for owned children.
- Port 9002 collision handling fails closed unless `/proc` command and deployment-directory evidence narrowly identify the listener as the expected SRA API; verified stale API shutdown is TERM-first and permanently audited.
- Deployment bootstrap's machine-readable, non-secret state-path result is the sole authority consumed by the launcher after dotenv loading; Bash does not independently derive or source the generated credential file. Normal restart requires one exact active canonical key, and deterministic SQL/signing configuration is checked before takeover.

### Runtime layout

- `app.py` 是 root ASGI entrypoint；`api/` 提供 compatibility import，實際 FastAPI app、routers、services、presenters 與 static assets 位於 `sra_api/`。
- `sra_api/routers/chat.py` 對同 package helper 使用 relative import，避免從 `api.routers.chat` 啟動時交叉載入第二份 `sra_api.routers.chat`；compatibility package 與 runtime package 不應在同一 import chain 混用絕對 namespace。
- `agent/agent.py::answer_with_routing()` 是對話主協調器；API 建立 history / memory / trace 後呼叫它，再保存 session 並產生 OpenAI-compatible response。
- `agent/routing.py` 以 LLM 將任務分類為 `SRA_REPORT`、`SRA_STYLE`、`DOC_FOLLOWUP`、`PURE_LLM`，topic 再映射到 Elasticsearch indexes。
- `agent/report_agent.py`、`style_agent.py`、`doc_followup_agent.py` 分別承接資料報告、風格改寫與既有文件追問；PURE_LLM 直接呼叫一般模型。
- `sra_api/core/presenters/` 將統一輸出轉成 Markdown / DOCX；Word 匯出不依賴任務必須走 RAG。

### Chat data flow and bounded routing

1. API 保留完整當輪 `user_msg`，並準備 history / memory / session context。
2. `build_router_input()` 只建立分類所需的瘦身視圖：目前問題預設最多 6000 字元、每筆歷史最多 1500 字元；超限保留頭 75% 與尾 25%。
3. Router 僅讀瘦身視圖以判斷 mode / topic，不讀完整大量資料。
4. 執行階段仍使用完整 `user_msg` 或既有 `query_for_agent`；PURE_LLM 的大量資料、回答內容及 Word 匯出資料不被截斷。
5. 上限可由 `ROUTER_CURRENT_MAX_CHARS`、`ROUTER_HISTORY_MAX_CHARS` 調整。
6. 檢索模式另在關鍵字提取 LLM 前建立獨立 bounded view（預設 6000 字元）；完整精煉查詢仍傳給人工詞比對、同義詞擴增及 Elasticsearch 搜尋。
7. PURE_LLM 直接生成不經 report agent，使用獨立 `PURE_LLM_TIMEOUT`；`REPORT_LLM_TIMEOUT` 只控制 SRA_REPORT 的報告模型呼叫。

### Data and administration boundaries

- Elasticsearch 是 agent retrieval 與 Editor 文件層；Excel→SQL 匯入、audit、來源資料編輯 / 統計位於 `data_ingestion/excel_to_sql/` 與 `sra_api/routers/excel_to_sql.py`。
- SQL 來源工具只能操作啟用任務設定內的 `destination.table`，並以 role、欄位白名單、reason、audit 限制修改。
- Dashboard、Excel upload/import 與單列/批次 SQL 修改共用同一份已啟用任務白名單；任務 JSON filename 不是授權憑證，overwrite 另以 `dashboard.created_by` 與 superuser 狀態檢查。
- Auth roles 為 `data_reader`、`data_editor`、`db_operator`、`superuser`；前端 session 使用同源 localStorage key `sra_editor_token`。
- Vercel mock runtime 與正式 ES / SQL 路徑分離，mock response 必須揭露其狀態。
- OpenWebUI 整合面 `/v1/chat/completions`、`/v1/models`、`/v1/docs/*`、`/v1/export/word` 維持既有無 Editor bearer token 的 contract；Editor/Auth 與 Excel→SQL/SQL 管理才使用 `sra_editor_token` role boundary。
- API app 保留既有 permissive CORS 相容性，供既有 OpenWebUI / 內網整合使用；若未來要保護 agent API，需設計不與 Editor token 混用的可選 integration credential。
- 「代理人參考文本」是提供連貫上下文的原始全文或精煉詳文，與可引用的零碎 `evidence_snippets` 分工；其 ES dot path 由 `SRA_REFERENCE_TEXT_FIELD` 設定（預設 `rawInfo.content`），TXT→ES / SQL→ES writer 與 mapping、搜尋、證據 fallback、單篇參考文本取得及 docs 下載共用同一契約。Excel→SQL 只負責 SQL 欄位映射，後續由 SQL→ES 的 `source.columns.content` 接入此契約。
- 全文 API 將「代理人參考文本」與固定 `rawInfo.content` 的「原始未處理文本」視為並列資料層；預設只回 reference，人工稽核可明確要求 raw 或 both，不改變代理人的預設消費欄位。
- TXT→ES / SQL→ES 在 reference field 不同於 raw 時採相容雙寫：raw 永久保留稽核材料，reference 初始以同一輸入 seed，之後由精煉 pipeline 單獨更新。這讓舊版 reader 可持續讀 raw，但既有舊文件仍需 backfill reference 後才能供新版 agent 使用。

## Recent Changes

### 2026-09-09 Phase 1C runtime process separation

- Phase 1C has two independent externally supervised process roles. The existing `handoff-worker` owns reconcile → prepare → submit. The implemented `schedule-worker` owns only validated startup, aware-UTC `ScheduleStore.claim_due()` polling, and graceful stop.
- The processes communicate only through SQL-authoritative Batch Run / Run Item state. The schedule process performs no HTTP, handoff, artifact, Phase 1A SQLite, Report Job worker, Agent, Elasticsearch, or Word work and is not hosted in FastAPI lifespan.
- The runtime-driver design completes a missing automation delta without superseding Phase 1C-A Design v5, Job Task Orchestration Boundary Design v1, or the corrected Phase 1C-B architecture. JT-1 and LangGraph remain future, unimplemented gates.

- 2026-09-01：新增 dual-mode Word report。FastAPI lifespan 依序初始化 Job SQLite、原子標記 stale `running` 為 `interrupted`、啟動唯一 thread worker；worker 直接呼叫 transport-neutral `execute_agent_turn(request=None, session_id=...)`。SQLite 每操作獨立 connection，`BEGIN IMMEDIATE` 保護 idempotent create 與 claim；DOCX 在 local reports root temp write/validation 後 atomic rename。

- 2026-09-01：新增 `sra_api/services/turn_execution.py` 作為 Chat 與同步 Word API 的共用非 META Agent turn 執行邊界；它統一準備 session/history/memory/reuse、呼叫 `answer_with_routing()`、補齊 turn identifiers 並保留既有 snapshot 相容副作用。`POST /v1/report/word` 直接把 service 回傳的本輪 structured result 交給 `ExportWordService`，不從 `state.json` 讀回；Chat 則沿用相同 service，再完成 Markdown response、session/memory 與 API state persistence。

- 2026-08-31：Report Data Agent 產生的 `核心關鍵詞組如下：...` 在 `compute_effective_terms()` 由 deterministic parser 直接接收，不再進行第二次 topic extraction；自然語言與 Style 的 `風格仿寫關鍵詞組如下：...` 維持原路徑。synonym、人工詞與簡繁變體仍在 ES Tool 層處理，router/topic/index_hint 軸未改動。

- 2026-08-25：opt-in 目前時間 context 是可觀測的 LLM 邊界事件；實際注入時以 warning 輸出 reason code、timezone、reference time 與輸出可能改變標記，未注入則不記錄，且不將 debug 提示送入 user message。

- 2026-08-25（更正）：LLM 呼叫邊界預設不附加目前時間；僅 query refiner 與 PURE_LLM 這兩個以使用者當下問題為語意的 caller 明確 opt in。結構化文章抽取及其他 machine-to-machine JSON 流程維持既有 system/user message，避免把執行時間誤當文章事件時間。

- 2026-08-25：LLM 呼叫邊界在 system role 附加可關閉的時區化目前時間，不改寫 user role payload；agent 完成時將 trace 內各階段 model ID 正規化至 `data_agent.model_usage`，供 presentation extractor 與 DOCX renderer 顯示。

- 2026-08-20：結構化事件檢索採 `multidim_event_json` outer nested + Event / Timeline / Person / Party / evidence child nested 兩層查詢；`event_id/event_ids` 為跨事件子結構的關聯鍵。
- 2026-08-13：關鍵字提取裁切限制於 extractor 呼叫邊界，不改寫下游共用查詢。
- 2026-08-13：Chat router 新增 bounded head/tail input view，大型資料只在執行階段交給模型。
- 2026-07-01～07-04：SQL 來源編輯 / 統計與 Excel 匯入全域樹狀導航完成。
- 2026-06-25～06-29：Chat helpers、data-agent prompts、auth flows、task config builder 拆分並保留 facade contracts。

## Archived History

- `.codex/archive/architecture.md-20260813-000000.md`：濃縮前完整 architecture，含 Vercel、auth、Editor、Excel→SQL 與資料流歷史細節。

- 2026-08-26：`answer_with_routing()` 在 LLM 邊界 trace 之上產生精簡且可輸出的 `llm_execution` 稽核資料；presentation extractor 僅保留允許欄位，DOCX renderer 將執行情況置於文件最後，避免輸出完整 prompt 或 raw response。

## 2026-09-02 Phase 0 hardening follow-up

- `bootstrap_env()` runs before `sra_api.main` imports configuration-backed routers/security globals; CLI bootstraps before constructing `ServiceKeyStore`.
- Document detail/fulltext and legacy Word share `require_principal_or_capability`; capability validation is transport-only and precedes resource lookup.
- Report Job schema initialization validates both fresh and reopened version-1 databases; version-0 migration operations remain in the approved transactional order and are individually injectable for rollback regressions.

## 2026-09-03 Unified security audit boundary

- `sra_api/security/principal.py` 在 unified authentication/scope boundary 記錄 denied audit；Service Key admin router記錄 create/revoke，Report Job router記錄 admin cross-owner read/download。事件只保存 action、reason、principal/key/job識別及 scopes，不保存 credential或 digest。

## 2026-09-04 Standalone Batch Scheduler boundary

`CSV/XLSX/JSON -> batch_scheduler process -> dedicated scoped Service Key -> Report Job HTTP API -> existing server worker/Router/Elasticsearch/Agent -> HTTP DOCX -> local atomic publication`. The scheduler owns a separate user-version-1 SQLite database and never imports server execution components or accesses the server Report Job database.

## 2026-09-04 Phase 1C planned architecture (not implemented)

- The authoritative Design v1 places scheduling control-plane state in separately versioned SQL Server schema `sra_schedule` and code in a focused future `requirement_scheduler/` package. It reads exact active Phase 1B snapshots but cannot mutate immutable Requirement history.
- Immutable schedule versions and Batch Run/Run Item history feed a narrow Phase 1A programmatic import seam. Phase 1C may not access Phase 1A SQLite directly or import Agent, Elasticsearch execution, ReportJobWorker, or Word renderer code.
- Recurring work belongs to `python -m requirement_scheduler worker`, formally one active process in v1, never a FastAPI lifespan thread. SQL locking/unique identities and deterministic Phase 1A identities protect restarts.
- Phase 1C references, rather than copies or renders, Phase 1A-published DOCX artifacts under one shared confined output root.

## 2026-09-04 Phase 1C Design v2 correction (not implemented)

- Phase 1C Design v1 / Plan v1 / Prompts v1 are superseded by v2 after Design Review v1. Run Items will bind RequirementVersion ID plus monotonic per-Requirement number; checkpoints will carry matched seen/success ID-number evidence and reject older success completions.
- Operator pause clears `next_run_at` and starts a fresh recurrence window on re-enable; continuously enabled worker downtime alone uses `coalesce_latest`. Version activation recalculates from its transaction time.
- Configuration hashes remain comparison evidence rather than version identity, allowing immutable A→B→A reversion. Batch Runs will persist a non-secret Phase 1A output-root fingerprint and fail closed if the configured root changes before resume/reconciliation/history serving.

## 2026-09-04 Phase 1C-A control plane

- `requirement_scheduler/` is the SQL Server-backed scheduling control-plane boundary: frozen recurrence/domain evidence, transactional schema/store operations, pure selection policy, and lifecycle orchestration.
- `sra_schedule` remains independently versioned from immutable Phase 1B history. Scheduled claims lock authority rows, coalesce enabled downtime, bind the active snapshot and exact RequirementVersion ID/number, persist selection evidence/checkpoint seen state, and advance recurrence atomically.
- `sra_api/routers/requirement_schedules.py` exposes control-plane CRUD/version approval only. FastAPI initializes the store only when configured and starts no scheduling thread; Gate A has no Phase 1A bridge or outbound execution.

## 2026-09-04 Phase 1C-A review corrections

- Canonical v1 validation now treats columns (type, byte length/MAX, nullability, ordinal), filtered unique indexes, keys, and cross-schema FKs as exact catalog evidence. Internal FK identities derive from the configured schedule schema; Phase 1B references derive independently from the configured Requirement schema.
- Run materialization joins immutable RequirementVersion evidence to `requirements.external_item_id`; selected items persist that external identity as their future Phase 1A task identity and runs persist `reqrun-<batch_run_id>`.
- A narrowly recognized SQL Server 2601/2627 violation naming the scheduled filtered index rolls back and rereads the winner; all other database errors remain failures.

## 2026-09-05 Phase 1C Design v3 architecture (not implemented)

- Design v3 supersedes Design v2. Canonical Phase 1C SQL becomes schema version 2: fresh stores create v2 directly; allowlisted PR #200/#201 version-1 shapes migrate in one transaction with marker 2 last; malformed/future states fail closed.
- Canonical Run Item `phase1a_task_id` is nullable `NVARCHAR(240)` and preserves the exact Phase 1B `external_item_id`. Composite `(schedule_id,schedule_version_id)` relationships enforce same-schedule active pointers and Batch Run bindings without cascades.
- Successful lifecycle mutations and `requirement_schedule_audit_outbox` events share one SQL transaction. Existing Editor JSONL is an at-least-once projection through `append_audit_event()` with stable `audit_event_id`; authorization denials without SQL mutation retain the direct canonical denial path.
- This architecture is a pending Phase 1C-A v3 closure, not implemented behavior. Phase 1C-B remains not started and blocked pending merge plus explicit post-merge PASS.

## 2026-09-05 Phase 1C Design v4 compatibility correction

- Design v4 supersedes v3 without redesigning schema v2 or the transactional audit outbox. Exact PR #200/PR #201 whole-catalog descriptors classify v1 before mutation; only recognized PR #200 may transactionally repair its exact `phase1c-`/internal-Requirement handoff placeholders after proving Gate-B evidence absent. PR #201 canonical identity is never rewritten.
- Migration validates active/approved persisted configuration under current canonical rules. JSONL lifecycle `ts` derives from immutable outbox `created_at`; delivery success/failure updates compare-and-set only pending rows so delivered metadata cannot regress.
- These contracts await Phase 1C-A v4 closure implementation and post-merge review; Gate B remains not started.

## 2026-09-05 Phase 1C-A schema v2 and audit projection

- `sra_schedule` now has canonical schema version 2. Fresh initialization creates v2 directly; exact reviewed v1 shapes migrate in one transaction with the version marker updated last. Composite schedule/version ownership prevents cross-schedule active pointers and Run bindings.
- Successful lifecycle mutations and immutable audit-outbox rows share the SQL transaction. `requirement_scheduler.audit_delivery` performs bounded, at-least-once projection to the existing audit sink outside that transaction; immutable creation time supplies the lifecycle timestamp and pending-row CAS keeps delivery metadata monotonic.

## 2026-09-05 Phase 1C Design v5 source correction (pending implementation)

- Design v5 preserves the schema-v2/outbox architecture but corrects the source baseline: PR #200 and PR #201 share the reviewed vocabulary/state widths and differ primarily in internal FK additions. Canonical v2 preserves those widths and widens only nullable `phase1a_task_id` to 240 characters.
- Production classification must query complete SQL Server catalog evidence through ordinary DB-API methods. Fresh v2 uses explicit canonical DDL; recognized v1 shapes have distinct transactional migration programs; marker authority is exactly one row and is written last/re-read.
- The authoritative outbox retains `safe_payload_json`, non-null lifecycle `schedule_id`, reserved `batch_run_id`, and the non-unique `(delivered_at,created_at,audit_event_id)` pending index. Bounded startup and post-commit drains make projection live without a FastAPI scheduler thread.
- These are corrective requirements, not runtime claims. Phase 1C-A remains NOT PASS pending implementation/review; Phase 1C-B remains NOT STARTED.

## 2026-09-05 Phase 1C-A v5 closure implementation

- Phase 1C schema classification now reads complete columns, keys, filtered indexes (including uniqueness), and FK bindings through parameterized SQL Server `sys.*` queries and ordinary DB-API methods. Fresh v2 DDL is explicit; exact PR #200/#201 shapes use separate transactional migration programs and complete canonical postvalidation.
- Canonical audit outbox uses the v5 field/index contract. Scheduler initialization and committed lifecycle mutations trigger bounded best-effort projection to the existing JSONL sink, with no FastAPI scheduling thread; SQL outbox remains authoritative when projection fails.

### 2026-09-05 Phase 1C-A v5 post-merge catalog hardening

- Schedule schema authority now includes normalized filtered predicates, FK delete/update NO ACTION evidence, and the narrowly required audit-outbox default/check constraints. PR #200 migration widens `phase1a_task_id` before copying external identity, within the same transaction.

## 2026-09-07 Requirement execution compatibility bridge

- `requirement_scheduler` now contains a framework-neutral execution boundary, an HTTP-only legacy Report Job gateway, durable SQL lease/schema contracts, and an independently supervised coordinator entry point. HTTP and filesystem effects occur outside SQL transactions.

## 2026-09-07 Phase 1C-B closure runtime flow

- The external `handoff-worker` initializes schema v3, acquires/renews a SQL-fenced coordinator lease, reconciles unfinished immutable submissions before preparing bounded new work, and stops authoritative mutation on lease failure. FastAPI owns no handoff loop.
- Prepare and acknowledge are separate SQL transactions around the Report Job HTTP call. Reconciliation translates only neutral gateway states, verifies the frozen server-owned root, publishes a validated deterministic DOCX, then atomically closes item/counters/checkpoint/audit.

## 2026-09-10 SRA launcher stale-runtime identity boundary

- `sra_api/main.py` invokes `sra_api/core/proctitle.py::init_proctitle()` during module import, before FastAPI construction. When `setproctitle` is installed it replaces argv/cmdline and the comm name with `SRA-API | port=<PUBLIC_API_BASE port or 9002> | [<MODEL_ID prefix> | ]pid=<os.getpid()> | <socket.gethostname()>` (the kernel comm view is truncated). Both PID and hostname therefore use the launcher's current/container namespace and hostname.
- `run_sra_api.sh` discovers only TCP LISTEN owners, then requires exact deployment cwd, effective UID, live listener ownership, and either original uvicorn argv, the exact rewritten-title grammar, or a matching launcher-owned PID/start-time/port record. The record supplements rather than replaces live `/proc` and listener proof.
- Takeover captures `/proc/<pid>/stat` field 22, sends TERM first, and permits KILL only after the same PID/start time remains a verified listener. It performs no Docker/host PID translation.

## 2026-09-10 Self-bootstrapping deployment boundary

- `config/deployment_bootstrap.py` is a one-shot provisioning/preflight component invoked by `run_sra_api.sh`; it does not become a runtime role and does not alter `config.bootstrap` environment-loading responsibilities.
- `.sra_runtime/requirement_handoff.env` is strict owner-only generated state, while the existing shared `ServiceKeyStore` remains the sole digest-only key authority. The canonical Handoff principal has exactly create/read/download Report Job scopes.
- Startup order is bootstrap and strict state import, verified orphan/takeover handling, API listener readiness, Schedule Worker, then Handoff Worker. Only the supervisor retains flock FD 9; all three children and log consumers close it.

## 2026-09-10 Credential-repair transaction recovery

- An owner-only repair journal binds each rotation to exactly one validated old key ID and one newly created key ID before generated state replacement. Recovery accepts only the journal-selected replacement credential and the exact recorded active identity set; it never infers transaction ownership from same-name/same-scope keys.
- A state-write exception is not treated as proof that replacement failed. Protected state is re-read: exact old state permits replacement rollback, while exact replacement or unreadable/other state retains both credentials and the journal for fail-closed explicit recovery.
- State-absent explicit recovery is limited to one exact-scope canonical key created by `deployment-bootstrap`. It creates and persists a replacement through the same journaled rotation before revoking the unrecoverable orphan; ordinary bootstrap remains non-destructive.

## 2026-09-10 Pre-creation repair intent

- Repair journal schema v2 binds the exact old/replacement IDs to either `credential_rotation` with prior state or `first_run_orphan_recovery` without prior state. The repair layer preselects the replacement ID and durably journals it before `ServiceKeyStore.create`, closing the store committed-before-response boundary.
- Journal-proven first-run recovery rolls back only its exact replacement when state is still absent, then retries from the uniquely retained original orphan. Missing state for a normal rotation and any active-ID set beyond the exact journal evidence remain fail-closed.

## 2026-09-10 Deployment bootstrap transaction serialization and store durability

- A state-directory deployment-bootstrap lock serializes the entire Python bootstrap or explicit repair decision/mutation sequence across credential state, repair journal, and ServiceKeyStore. Recursive journal recovery stays inside the already-held transaction rather than reacquiring the lock.
- ServiceKeyStore atomic writes now fsync the containing directory after replacement and final owner-only mode enforcement. A successful create/revoke return is therefore a durable store commit point for the repair protocol; an uncertain directory commit raises before journal removal.

## 2026-09-10 Safe launcher takeover

- Runtime flock remains the single-launcher authority. A separate owner-only atomic launcher identity record binds PID, process start time, effective UID, resolved deployment cwd, and resolved launcher path; current `/proc` cmdline evidence must resolve to that launcher.
- A restart contender bootstraps first, validates and revalidates the existing launcher, signals only that launcher, and relies on its existing direct-child cleanup. A narrow takeover flock serializes concurrent contenders through replacement worker startup; invocation start time prevents an older contender from targeting a newer replacement.
- Handoff process signals are translated to its coordinator stop event, preserving the coordinator's existing `finally`-owned lease release and fencing protocol.

## 2026-09-15 SD-1 release/deployment identity

- Release identity flows as `explicit source commit -> Git-object runtime equivalence -> exact staged-package validation -> canonical DEPLOYMENT_MANIFEST.json -> external manifest SHA-256 receipt -> Linux no-Git byte verification`.
- `tools/deployment_manifest_policy.json` defines runtime-managed roots/files and separately classified release tooling. Runtime equivalence compares path set, blob identity, and Git mode to the reviewed runtime commit; release-tool and documentation changes may coexist without moving that baseline.
- Package verification trusts an independently retained manifest SHA-256, rejects symlinks/missing or mutated managed files/unexpected runtime code, and ignores historical deployed `.git`. The runbook hashes both the manifest and deployed verifier before executing project code.

## 2026-09-15 SD-1 manifest trust chain v1.1

- Release construction uses two independent Git authorities: `reviewed_runtime_commit` fixes runtime path/blob/mode identity, while `reviewed_manifest_commit` fixes exact policy bytes/mode and release-tool path/blob/mode identity. Both must be ancestors of the candidate source commit.
- The reviewed policy permits no unmanaged runtime extras. Staged-package and deployed managed-file reads use a package-root directory descriptor and `O_NOFOLLOW` for every parent and final component.
- Manifest Git modes are executable-semantics authority: `100755` requires an executable bit and `100644` prohibits executable bits. The external manifest SHA-256 remains the package-mode trust anchor.

## 2026-09-15 Requirement operator harness identity recovery

- `enabled_schedule_id` is cleanup ownership only. Once the automatic Batch is observed, its durable `schedule_id` plus `batch_run_id` is the immutable polling route even after the Schedule is disabled and cleanup ownership is cleared.
- Before Import Commit, the harness enumerates the complete Snapshot ID set across Requirement Sets belonging to the exact E2E Source. Ambiguous-write rereads subtract that durable baseline before applying source-SHA/profile-version matching.
- A valid `E2EConfig.output_dir` is the single root for the invocation lock, copied artifacts, and result/summary/diagnostic evidence; only pre-config failure evidence uses the safe fallback destination.

## 2026-09-16 Requirement operator E2E Harness v2

- One shared `Harness` retains the complete functional Golden Path; local and remote providers differ only in deployment-evidence and artifact-byte acquisition.
- Local mode preserves Linux `/proc`, launcher identity, clean Git, configured root fingerprint, and direct filesystem DOCX checks. Remote mode uses the superuser-only read-only runtime-evidence API and existing Report Job download API, then independently checks downloaded DOCX/SHA bytes.
- Runtime evidence returns bounded source/worker/fingerprint facts only. Result evidence is `requirement_e2e_result_v2` and distinguishes operator source from deployment source.

## 2026-09-16 Harness v2 authoritative remote artifact correction

- Remote artifact proof now uses a superuser-only operator route keyed solely by immutable Batch Run and Run Item IDs. `ScheduleStore` joins those identities and returns existing durable Handoff metadata; no client path is accepted.
- The server resolves the durable path only under configured `REQUIREMENT_HANDOFF_OUTPUT_ROOT`, verifies root fingerprint, confinement, non-symlink file, DOCX ZIP safety/integrity, and durable SHA before returning bytes. The remote provider independently repeats DOCX/SHA validation and retains the verified bytes.
- Report Job `/word` remains a product API but is no longer Remote PASS artifact authority. This supersedes that portion of the preceding Harness v2 entry without DB schema or Schedule/Handoff/Report Job execution changes.

## 2026-09-16 Harness runtime identity modes

- Operator source identity is exact or a reviewed-equivalent Git descendant after path-role classification.
- Deployment evidence supports Git worktrees and incremental packages. `REQUIREMENT_E2E_PROVENANCE.json` enumerates deterministic reviewed runtime hashes; the API verifies deployed bytes and bounded active module paths, while the operator reconstructs the expected map from the externally reviewed Git object.
- Worker positive identity still uses launcher PID/start-time/UID/cwd/cmdline checks; provenance binds the worker entrypoint/runtime tree. Residual files are not directory-cleanliness authority.

## 2026-09-16 Shared runtime provenance path policy

- `shared/runtime_provenance.py` is the single bounded selector for incremental-package byte authority. `RUNTIME_ROOTS` contains runtime source/config trees; `RUNTIME_FILES` enumerates only materially active root files; `RUNTIME_PATHS` is the Git pathspec authority used by both package generation and external reviewed-map reconstruction.
- Root classification is explicit: `python_compat.py` and `telemetry.py` are imported runtime modules; `app.py` is the Vercel application entrypoint; `run_sra_api.sh` supervises API/Schedule/Handoff startup and process identity; and `requirements.txt` controls runtime dependency installation. The empty root `__init__.py` has no current import/launch role, while README/TODO and repository metadata are documentation/tooling rather than runtime inputs.
- Deployment evidence accepts provenance entries only inside the shared policy, hashes all declared authoritative bytes (including the launcher even though it is not a Python module), and separately requires every discovered active project module to appear in reviewed provenance. Inactive unmanaged historical Python residue remains warning-only.
