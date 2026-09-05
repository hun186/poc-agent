# System Architecture

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
