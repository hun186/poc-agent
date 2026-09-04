# Architecture Decisions

## 2026-09-04 Phase 1B immutable SQL Requirement history

- SQL Server is the control-plane authority. Profiles, Requirement versions, observations, and snapshots are immutable; reviewed pointers are mutable.
- SQL API sources store named registry references only; filesystem sources are allow-root confined. Preview is side-effect free and activation is strict/atomic.
- Schema integers are not trusted alone: version 1 is accepted only after structural validation, and version 0 is upgraded with the marker written last in the same transaction. Named SQL security relies on reviewed registry entries plus a read-only database principal, not SQL text parsing.
- Constraint names alone are not schema evidence: canonical validation binds each required PK/UQ/FK to its schema/table and ordered columns. Legacy-v1 compatibility is deliberately limited to making diagnostic row numbers nullable; all other malformed-v1 structures fail closed.

## 2026-09-02 Scoped principals and signed browser capabilities

- Use distinct high-entropy service keys for OpenWebUI and future batch clients. User and service credentials share scope authorization without conflating their identity domains.
- Persist only complete-key SHA-256 digests under cross-process locking; return plaintext once.
- Preserve browser-clickable resources with bounded, exact HMAC capabilities. An invalid Authorization header is authoritative and cannot fall back to a capability.

## Current Summary

### 2026-08-27 連貫文本採「代理人參考文本」契約

- 使用「代理人參考文本」（agent reference text）指稱代理人理解前後文所用的連貫文本；它可以是原始全文或精煉詳文，但不取代可追溯、局部引用的 `evidence_snippets`。
- ES 欄位以 `SRA_REFERENCE_TEXT_FIELD` 在部署時選擇，預設 `rawInfo.content`。明確設定替代欄位後不得靜默退回雜亂原文，以避免同一次任務混合不同品質與語意的文本來源。
- 同一環境的 TXT→ES、SQL→ES writer/mapping 與 agent/API reader 必須共用此設定，避免只換讀取端而造成新文件無內容。Excel→SQL 不直接寫 ES dot path，其銜接點是 SQL→ES 的 `source.columns.content`。
- 人工檢核需要保留原始材料，因此全文 API 不把 raw 視為 reference 的 fallback alias，而以 `reference`、`raw`、`both` 三個明確層次輸出；單獨要求缺少的層次必須回 404，避免把精煉內容誤標成原文。
- Ingestion 對新文件保留 `rawInfo.content` 並 seed configured reference field，以支援舊版 reader 與人工稽核；精煉工作只能覆寫 reference。Reader 不做 raw→reference 靜默 fallback，舊文件需明確 backfill，避免把「尚未精煉」誤報為「精煉完成」。

### 2026-08-25 相對週期採明確週界線與不重疊語意

- 相對週不是只靠 reference timestamp 猜測：系統以週一至週日為完整週，並在 refiner system context 提供上一週與前兩個完整週的實際日期邊界。
- 「前 N 週」定義為目前週之前的連續 N 個完整週；「N 週前」是偏移 N 週的單一完整週；「過去 N 週」是包含 reference date 的滾動 N×7 天。明確區分三者可避免檢索區間因自然語言歧義漂移。

### 2026-08-25 相對年度換算須明示且可稽核

- 對 report refiner 而言，僅提供目前時間不足以保證模型正確換算「去年」；system prompt 必須明示由 request-time 推得的今年／去年，並把相對時間轉為明確檢索範圍列為「不得新增事實」規則的唯一合理例外。
- 實際 reference time、時區與推得的去年年份必須隨 Data Agent 記錄輸出，讓 OpenWebUI / Word 使用者可直接確認是否啟用時間上下文，不必只依部署端 warning log 猜測。

### 2026-08-25 影響輸出的隱性 context 必須可觀測

- 目前時間屬於不一定加入、但可能改變答案的 system context。啟用時必須留下包含 caller reason、timezone、實際 reference time 與風險標記的 warning log；不以額外 user message 提示，因為提示本身會改變對話與結構化輸入。

### 2026-08-25 目前時間採 opt-in，而非共用 caller 預設值

- System role 雖不會字串污染 user JSON，仍會改變模型可用的推論證據；對「文章沒有明確日期就輸出 null」的抽取契約而言，執行時間可能使模型把文章中的「上週」推算成日期，屬於語意污染。
- 因此 `call_llm()` 預設不得注入現在時間。只有明確處理「使用者現在問本週／上週」的 query refiner 與 PURE_LLM caller opt in；文章結構化、文件抽取與中間 JSON 階段維持無時鐘上下文。此決策取代下方同日「共用 caller 附加時間」的預設策略。

### 2026-08-25 時間上下文與結構化輸入隔離

- 相對日期需要單一可信的 request-time 參考，但不得把時間字串串接進 user prompt 或 JSON payload。共用 LLM caller 因此只將時間附加至 system role，並保留 `include_current_time=False` 作為嚴格隔離開關。
- 時區由 `LLM_CURRENT_TIMEZONE` 控制，預設 `Asia/Taipei`；設定無效時安全降級為 UTC。system 指示限制時間只用於相對日期解析，避免與日期無關的輸出受影響。

### 2026-08-13 執行模式 timeout 分離

- PURE_LLM 與 SRA_REPORT 是不同模型呼叫邊界，timeout 採 `PURE_LLM_TIMEOUT` 與 `REPORT_LLM_TIMEOUT` 分開設定，避免調整報告等待時間時對直接生成產生錯誤預期。

### 2026-08-13 裁切視圖限制於消費者邊界

- 路由器與關鍵字提取器各自建立局部、暫時的 bounded view，不覆寫共用 query 物件，避免目前或未來新增的檢索、同義詞、匯出與執行功能意外繼承裁切內容。
- 關鍵字提取結果依設計仍是同義詞與 ES query 的種子，因此裁切可能間接改變召回率；此風險與「將裁切字串直接傳入下游」分開揭露及測試。

### 2026-08-13 Router 與執行內容分離

- 任務分類器只需要辨識意圖、模式與 topic，不應為了分類先讀取使用者附上的完整大量資料。
- 路由視圖採固定字元上限並保留頭尾：開頭通常包含任務指示，尾端可保留使用者把要求寫在資料後方的情境；中間插入明確省略標記，避免分類模型誤認內容完整。
- 不修改原始 `user_msg` / `query_for_agent`，因此執行模型及 Word 匯出仍使用完整資料。此方案比先用另一個 LLM 摘要更省一次昂貴呼叫，也不會把路由 timeout 轉移到摘要階段。
- 上限採環境變數調整而非寫死單一部署值；目前問題與歷史問題分開配置，避免歷史大型 payload 再度膨脹路由 context。

### Stable project decisions

- API runtime source 使用 `sra_api/`，`api/` 僅為 compatibility layer；對外 import / endpoint contract 優先保持相容。
- Compatibility package 內部引用同層模組時採 relative import，避免同一實體檔案同時以 `api.*` 與 `sra_api.*` 兩個 module identity 載入；移除已公開 symbol 時先保留無副作用 compatibility shim，讓 rolling / 部分同步部署可啟動。
- Route、prompt 或大型服務拆分時保留原 facade，避免一次迫使 routes、tests 與外部使用者遷移。
- Editor 欄位結構以 Elasticsearch mapping metadata 為型別權威，form config 負責 UI layout；mapping 不可用時明確降級。
- Excel→SQL 任務由 db_operator 建立 pending 設定、superuser 審核啟用；來源資料工具限定啟用任務白名單，不提供 arbitrary SQL。
- SQL / ES 跨系統刪除不在 request 內同步硬刪，後續應採 lineage + outbox / tombstone / 補償流程。
- Mock preview 不能冒充正式成功；production-like 環境預設關閉免密入口，mock token 與資料邊界需明確標記。
- Bearer token 不放 URL；同源前端身份以 localStorage 承接，長期可評估 HttpOnly cookie + CSRF。
- Agent/OpenWebUI integration API 與 Editor 管理 API 是不同 trust boundary；不得直接把 `sra_editor_token` 強制套到 OpenWebUI 的 models/chat/docs/export contract。未來若需 agent API auth，應新增可選且可由 OpenWebUI 設定的 integration credential，並提供相容遷移。
- SQL 值一律參數化；無法參數化的 identifier 必須經結構驗證並使用 SQL Server bracket quoting。ES document ID 只允許 exact lookup，不以使用者輸入建立 wildcard fallback。
- Filename、config path、record ID 與其他可猜測 locator 只用來定位資源，不構成授權；所有寫入仍須在 service boundary 驗證 owner、role 或已啟用任務白名單，不能只依賴前端隱藏清單。
- 靜態 UI 子頁使用共用全域樹狀導航，不另建平行大按鈕導覽體系。

## Recent Changes

- 2026-09-01：長報告採 FastAPI lifespan 管理的單機 worker、SQLite persisted state 與 local atomic DOCX publication，不使用 request `BackgroundTasks` 或 internal HTTP。此版只保證 pollable resource；process crash 將 stale running 標記 interrupted，不承諾 HA、exactly-once 或 crash resume。Caller filename 僅作顯示，實體 basename 固定由 job ID 生成。

- 2026-09-01：同步 Word automation 與 Chat 共用單一 turn execution service，避免兩個 endpoint 各自拼裝 Agent inputs。新的 POST endpoint 必須直接 render service 回傳的本輪 structured result；snapshot persistence 只保留既有 GET 下載相容性，不可成為 POST 產檔的 read-after-write 依賴。Phase 2 維持 synchronous HTTP 與既有 integration trust boundary，不引入 Queue、Redis、PostgreSQL、Airflow 或排程元件。

- 2026-08-31：Report explicit core query 採限定 prefix 的 deterministic parser，以保留上游已確認詞並省去重複 topic extraction；不泛化到 Style structured query。共用 synonym LLM 僅負責完整 query context 下的等價／近等價名稱與合法 semantic-axis 合併，Python 僅接受原 core term 作 representative key；不新增 reviewer/judge LLM，也不讓關鍵詞處理介入 index routing。
- 2026-08-20：ES 多事件資料不做跨 nested context 的單一 multi-match；每種 child path 獨立查詢並由 outer nested 包覆，避免不同事件間欄位誤配，evidence 輸出保留 `event_ids` 供下游追溯。
- 2026-08-13：採用 bounded router view，完整資料延後到 execution model。
- 2026-07-01～07-04：SQL 來源工具採啟用任務白名單、audit 與全域樹狀導航。
- 2026-06-23～06-29：確立 Vercel mock hardening、schema-driven Editor、任務審核與模組 facade 拆分原則。

## Archived History

- `.codex/archive/decisions.md-20260813-000000.md`：濃縮前完整 decisions，包含所有已取代與仍有效決策的原始日期區塊。

### 2026-08-26 任務時間範圍優先於背景事件時間

- Query refiner 判定 ES 檢索區間時，使用者的任務指令是時間範圍的權威來源；背景說明內的月份或事件日期只代表重點時段，不得覆蓋較廣的任務範圍。
- 任務要求「去年」且沒有在指令中明確限縮月份時，一律解讀為去年 1 月 1 日至 12 月 31 日；只有「去年10月」、「僅限10月」等明確限制才縮窄為單月。

## 2026-09-02 Shared capability resolver

- Direct principal and browser-capability authorization use one resolver. A supplied invalid Authorization header is authoritative; capability fallback is only available when Authorization is absent. Exact query multiplicity and allowlisting are enforced only on the capability path before any resource access.

## 2026-09-03 Pre-request signing configuration failure audit channel

- Production signing-secret validation failures are process-start failures. The raised startup exception and service/process logs are the authoritative audit channel for this pre-request condition; the application audit store is not required to initialize merely to record a startup failure.
- Startup validation remains fail-closed for a missing or weak signing secret, and logs must never include the secret value.

## 2026-09-04 Batch Scheduler Phase 1 boundary

- Keep scheduling in a standalone process consuming only the existing Report Job HTTP API with a dedicated create/read/download key. Persist deterministic task idempotency keys before submission, treat remote failed/interrupted as terminal, and publish validated DOCX through a confined atomic local write. Do not add recurrence, queues, server UI, or internal server imports in Phase 1.
