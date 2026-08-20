# Architecture Decisions

## Current Summary

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

- 2026-08-20：ES 多事件資料不做跨 nested context 的單一 multi-match；每種 child path 獨立查詢並由 outer nested 包覆，避免不同事件間欄位誤配，evidence 輸出保留 `event_ids` 供下游追溯。
- 2026-08-13：採用 bounded router view，完整資料延後到 execution model。
- 2026-07-01～07-04：SQL 來源工具採啟用任務白名單、audit 與全域樹狀導航。
- 2026-06-23～06-29：確立 Vercel mock hardening、schema-driven Editor、任務審核與模組 facade 拆分原則。

## Archived History

- `.codex/archive/decisions.md-20260813-000000.md`：濃縮前完整 decisions，包含所有已取代與仍有效決策的原始日期區塊。
