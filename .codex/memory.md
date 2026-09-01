# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；實際 API source 在 `sra_api/`，`api/` 為 compatibility package，agent / retrieval / evidence 在 `agent/`，ETL 在 `data_ingestion/`。
- Chat completion 由 `sra_api/routers/chat.py` 呼叫 `agent.agent.answer_with_routing()`，分成 `SRA_REPORT`、`SRA_STYLE`、`DOC_FOLLOWUP`、`PURE_LLM`。
- Report query refiner 以 request-time 與設定時區解析相對日期；時間 context 採 caller opt-in，並在 trace / Word 中保留可稽核基準。
- 相對週以週一至週日為完整週；「前 N 週」、「N 週前」及「過去 N 週」採不同且明確的區間語意。
- Editor / Excel→SQL 共用 `sra_editor_token` localStorage 身份；SQL 資料工具限定已啟用任務目的表白名單，不提供任意 SQL。
- Vercel mock 僅供 preview / 唯讀用途，須標示 `mock_mode` 與 warnings；正式服務不得以 mock 冒充成功。
- 環境 package index 偶爾因 proxy 403 無法更新套件，但既有 requirements 可用；缺少 Playwright / browser runtime 時以靜態測試替代 UI 截圖。

## Recent Changes

### 2026-08-31 Report explicit terms 與 contextual synonym contract

- Report core-term prompt 移除最低數量要求，補上人工關鍵詞控制、受控一階語義擴充、明示案例／模型聯想案例區分與背景議題跳躍限制，並將相關 prompt 範例泛化以避免驗測提示污染。
- `核心關鍵詞組如下：...` 改由限定 Report prefix 的 deterministic parser 依序清理與去重，跳過第二次 topic extraction；自然語言與 Style structured prefix 保持既有行為，Style 的 `< 5` style-only fallback 與 index_hint 傳遞未改。
- synonym LLM 改為完整 query context 下的等價／近等價名稱擴充，收斂跨領域義項與 semantic-axis 合併；Python 拒絕非原 core term 的 representative key，簡繁與 manual synonym 架構維持 deterministic。
- 驗證：`python -m compileall agent` 通過（僅有既有 `markdown_tables.py` invalid escape SyntaxWarning）；`PYTHONPATH=. pytest -q tests/test_query_terms_contract.py tests/test_keyword_extraction_input.py tests/test_routing_input.py tests/test_nested_event_mapping.py` 為 23 passed；`git diff --check` 通過。
- 相依套件 preflight 已執行；requirements 皆已安裝。package index 經 proxy 查詢 pip 更新時仍出現既有 403 retry，但未阻礙測試。

### 2026-08-27 Word 文件改以 Base64 文字保存

- 因 PR 工具無法提交 binary，移除 tracked `.docx`，改提交 `docs/SRA代理人參考文本與多層全文下載技術說明.docx.b64` 與 `docs/restore_docx.py`；restore script 會先驗證內建 SHA-256，成功後才寫出 DOCX。
- 原始與還原檔 SHA-256 均為 `ea08d8bef0498e003c0b6133379234fa10e97f8233767914c87d4560d252f2bc`，`cmp --silent` 確認 byte-for-byte 完全相同，還原檔 `unzip -t`、script `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 代理人參考文本技術介紹 Word

- 新增 `docs/SRA代理人參考文本與多層全文下載技術說明.docx`，以非開發者也能理解的方式整理更新背景、目標、核心名詞、資料流、OpenWebUI/API 行為、相容性、部署步驟、測試範圍、效益與 30 秒介紹話術。
- 文件包含資料流圖示表、相容性矩陣、下載層次表與主要技術元件附錄，可直接用於內部說明或對外簡報前的技術附件。
- 驗證：`unzip -t docs/SRA代理人參考文本與多層全文下載技術說明.docx` 通過；以 `python-docx` 重新開啟並確認 55 個 paragraphs、12 個 tables、必要章節與文件 metadata 均存在；`git diff --check` 通過。

### 2026-08-27 OpenWebUI 全文下載入口分層

- Citation 原本的單一「下載全文」連結改為參考文本、原始文本與雙層比對三個明確入口，JSON link 也直接顯示 both 層次。
- 舊文件若沒有 `agent_context`，下載參考文本會明確 404，但下載原始文本與雙層比對仍能取得 `rawInfo.content`，不再讓單一按鈕造成使用者無法判斷下載內容或只有錯誤頁。
- 新增 citation URL 與 Markdown label 測試；`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_export_word_service.py tests/test_api_security_boundaries.py -q`（49 tests passed）、presenter `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 舊文件相容性與 ingestion 雙寫測試

- 未設定 reference env 時，只有 `rawInfo.content` 的舊文件維持完整相容；切換到新欄位但尚未 backfill 時，reference 明確 404，而 raw / both 仍可供人工檢核。
- TXT→ES / SQL→ES 新資料改為保留 raw 並 seed configured reference field，使舊版 reader、新版 agent 與後續精煉 pipeline 能平順共存。
- 新增舊文件 default／切換後行為、雙層 ingestion 與 API layer 回歸測試；`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_sql_to_es_odbc_driver.py tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py tests/test_doc_followup_fetcher.py tests/test_api_security_boundaries.py -q`（57 tests passed）、相關模組 `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 全文下載多層次文本

- `/v1/docs/{doc_id}/fulltext` 新增 `text_layer=reference|raw|both`，讓預設代理人參考文本與固定 `rawInfo.content` 原始材料可分別取得或並列比對。
- JSON 回傳層次可用性、欄位與長度，both 模式包含兩份文本；TXT both 使用清楚的層次／欄位標題，下載檔名含 layer suffix。
- 驗證：`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_multidim_shape_normalization.py tests/test_api_security_boundaries.py -q`（43 tests passed）、docs router `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 代理人參考文本 ingestion 串接

- 補齊 TXT→ES 與 SQL→ES 寫入端及新 index mapping，使其與 agent/API 共用 `SRA_REFERENCE_TEXT_FIELD`，避免替換讀取欄位後新匯入文件斷流。
- 確認 Excel→SQL 不直接建立 ES `_source`；其 destination 內容欄由 SQL→ES `source.columns.content` 選取後，寫入設定的代理人參考文本欄位。
- 驗證：`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_sql_to_es_odbc_driver.py tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py tests/test_doc_followup_fetcher.py tests/test_api_security_boundaries.py -q`（53 tests passed）、ingestion `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 代理人參考文本欄位模組化

- 將具前後文的原始全文或精煉詳文命名為「代理人參考文本」，明確與局部、可追溯的 `evidence_snippets` 分工。
- 新增 `SRA_REFERENCE_TEXT_FIELD`，預設 `rawInfo.content`；搜尋、證據 fallback、依 ID 取得參考文本與 docs 下載改用共用 accessor，無效欄位設定安全退回預設值。
- 驗證：`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py tests/test_doc_followup_fetcher.py tests/test_api_security_boundaries.py -q`（47 tests passed）與 `git diff --check` 通過。

### 2026-08-26 SRA Elasticsearch 原文欄位契約盤點

- 確認 `rawInfo.content` 並非全域可設定欄位，而是在搜尋加分與 fallback、證據日期 fallback、全文／風格文件取得及 Editor 設定中直接引用。
- 結構化主搜尋主要依賴 `multidim_event_json` 與 `communication.subject`；保留完整結構化欄位時，原文改名未必使所有報告立即報錯，但會降低召回並破壞或降級全文相關功能。
- 新增 `docs/es_source_field_contract.md`，記錄安全遷移方式與需同步修改的邊界。
- 驗證：`PYTHONPATH=. pytest tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py -q` 與 `git diff --check` 通過。

### 2026-08-26 問題精煉 timeout 預設延長

- 將 report query refiner 的通用 timeout 預設由 20 秒延長為 60 秒，並同步 report refiner 設定載入器與 `.env.example`。
- 盤點 agent/API/ingestion Python 路徑的 timeout：其餘 LLM 預設皆為 60 秒以上；較短者僅 Elasticsearch request timeout 30 秒，屬資料庫 I/O 而非生成式 LLM 呼叫，未調整。
- 驗證：`PYTHONPATH=. pytest tests/test_query_refiner_time_context.py -q` 與 `git diff --check` 通過。

### 2026-08-26 時間優先序 prompt 範例去除驗測月份

- 將「任務時間範圍優先於背景事件時間」規則中的示例月份由 10 月改為 3 月，避免 system prompt 直接包含高難度驗測案例的 10 月線索而影響效能評估。
- 回歸測試明確確認 system prompt 不含「10月」，實際驗測問題仍可在 user prompt 保留原始 10 月背景。

### 2026-08-26 去年全年範圍與背景月份優先序

- Query refiner 明定任務指令的時間範圍優先於背景事件時間；「請蒐集去年」預設換算為去年 1 月 1 日至 12 月 31 日，背景中的「10月間」只能保留為重點時段。
- 只有任務指令本身明確要求「去年10月」、「僅限10月」或同等限制時，才可縮窄至單月。
- 驗證：`PYTHONPATH=. pytest tests/test_query_refiner_time_context.py tests/test_ollama_client_config.py tests/test_export_word_service.py tests/test_routing_input.py -q`，16 tests passed；`git diff --check` 通過。

### 2026-08-25 相對週期語意與週界線補強

- Refiner 支援通用日／週／月／季／年與帶數量相對時間；週以週一至週日為界。
- 明確區分「前 N 週」（目前週之前連續 N 個完整週）、「N 週前」（往前偏移 N 週的單一完整週）與「過去 N 週」（截至 reference date 的滾動 N×7 天）。

### 2026-08-25 「去年」解析、時間 context 與模型稽核

- Refiner 明示今年／去年並要求把相對時間換成明確日期，不得依模型知識截止日猜測；reference time、時區與去年年份寫入 Data Agent payload 並顯示於 Markdown / Word。
- `call_llm()` 的目前時間採 opt-in，只有 query refiner 與 PURE_LLM 明確啟用；啟用時記錄 reason、timezone、reference time 與 output risk warning。
- Word 匯出會列出任務路由、問題精煉、資料整備及報告／風格生成階段的實際模型 ID。

### 2026-08-21 靜態 UI 導航與 Dashboard 分頁

- 代理人資料流程頁及匯入管理子頁沿用共用全域樹狀導航與延遲收合互動。
- Excel→SQL dashboard 移除重複的載入筆數欄位，以 pager「每頁顯示」作為唯一 server-side `limit` 來源，預設 2000。

### 2026-08-20 API 相容、安全與 ES nested evidence

- 修復 `api.*` / `sra_api.*` mixed-version import recursion，並保留 rolling deployment 所需 compatibility shim。
- OpenWebUI models/chat/docs/export 維持既有公開 integration contract，不誤套 Editor bearer token；Editor、Excel 與 SQL 管理端仍保留 role、owner、allowlist、identifier 及 path traversal 防護。
- ES 多事件資料按 child path 分別建立 nested query，避免跨事件欄位誤配，evidence 保留 `event_ids` 追溯。

### 2026-08-13 大型輸入路由與 timeout

- Router 與關鍵字提取使用局部 bounded view，不覆寫下游完整 query；保留頭尾並以省略標記取代中段。
- PURE_LLM 與 SRA_REPORT 使用獨立 timeout 設定，避免調整其中一條路徑影響另一條。

### 2026-07-01～2026-07-04 SQL 來源工具與全域導航

- SQL source rows / stats、排序、篩選與 audit 均受已啟用任務白名單及欄位驗證保護；靜態子頁統一使用全域樹狀導航。

### 2026-06-23～2026-06-29 Auth、Editor schema 與任務審核

- Editor 採 ES mapping metadata 作欄位型別權威；Excel→SQL 任務由 db_operator 建立 pending 設定並由 superuser 審核。
- SQL / ES 跨系統刪除保留 lineage / outbox 後續設計，不在 dashboard request 內同步硬刪 ES。

## Archived History

- `.codex/archive/memory.md-20260813-000000.md`：2026-06-11 至 2026-08-13 的完整歷史。
- `.codex/archive/memory.md-20260826-043925.md`：2026-08-26 濃縮前全文，涵蓋 2026-06-11 至 2026-08-25 的工作紀錄；因 active memory 已累積超過 20 個工作區塊而濃縮。

### 2026-08-26 Word 附加 LLM 階段埋行稽核

- Agent 將任務路由、問題精煉、資料整備、證據欄位選擇、報告／風格／一般回答生成的成功、錯誤或 fallback 狀態整理為 `llm_execution`，包含實際模型、耗時與截短後錯誤訊息。
- Word 報告在所有既有內容之後新增「附錄：LLM 各階段執行情況」，方便確認正常回傳與糾錯；錯誤回應也保留已收集的執行軌跡。
- 驗證：`PYTHONPATH=. pytest tests/test_export_word_service.py -q`，8 tests passed；`git diff --check` 通過。依賴安裝完成，pip index 查詢仍出現既有 proxy 403 retry，但 requirements 均已安裝。

### 2026-08-27 Word 模型清單整合執行狀態與耗時

- Word 最後的「各階段使用模型」清單改為在每個階段的模型 ID 後直接顯示執行狀態與耗時，不再另建內容重複的 LLM 執行情況附錄；fallback / error 仍保留安全截短的錯誤備註。
- 舊 session 若只有 `data_agent.model_usage`，仍在文件最後輸出既有模型清單，不虛構無法取得的狀態或耗時。
- 驗證：`PYTHONPATH=. pytest tests/test_export_word_service.py -q`，8 tests passed；相關模組 `py_compile` 與 `git diff --check` 通過。依賴確認成功，pip index 查詢出現既有 proxy 403 retry，但 requirements 均已安裝。

### 2026-08-27 Word 模型執行階段依資料處理流排序

- 「各階段使用模型」固定依任務路由、問題精煉、資料整備、證據欄位選擇、報告生成及後續生成階段排列；Word 匯出也會穩定排序舊 session 或外部傳入的未排序執行紀錄，未知階段保留在已知階段之後。
- 驗證：`PYTHONPATH=. pytest tests/test_export_word_service.py -q`（10 tests passed）、相關模組 `py_compile` 與 `git diff --check` 通過。
