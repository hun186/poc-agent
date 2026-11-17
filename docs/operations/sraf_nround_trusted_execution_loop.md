# SRAF：N 輪受控檢索執行循環（尚未接正式背景 Job）

本 PR 將已合併的以下模組接成**可由可信上層實際呼叫**的一個循環：

- 凍結的單輪 canonical ES PIT 查詢計畫（#460）
- 只保留通過 Event／Timeline 日期、主題及來源驗證之私有 Evidence 的語意橋接（#461）
- 整輪 Evidence 覆蓋度與協調器、下一輪 LLM 策略安全准入（#457／#458）
- 既有 request-local 30 分鐘檢索、10 分鐘報告保留時間、ES／Planner 呼叫次數預算與停止條件

`run_trusted_nround` 現可在受信任 Worker 明確注入
**已授權的 ES client、固定 QueryConstraints、可信語意驗證回呼、
完整整輪查詢範圍驗證回呼**後，執行：

1. 一輪唯一 canonical ES PIT 查詢，取得完整分頁鏈，使用排他執行權杖防止
   其他查詢插入。ES opening/search/closing 的逾時與額度仍由既有 adapter 控制。
2. 信任的 `attest_whole_query_scope` 回呼**明確確認**這次查詢確實涵蓋
   此問題原本應執行的所有分支（此階段只支援固定的一條主查詢）。
   不回傳真正 `True` 就立即 fail closed；不能憑 PIT 200 或文件命中數自動通過。
3. 使用同一原始問題／Event 日期／主題條件，擷取合格 canonical
   Evidence 私有原文，交由可信 `semantic_assessor` 逐面向產生合法 witness。
   只有通過 source+Evidence digest 配對檢查者可進入覆蓋度 ledger。
4. `coordinator.complete_round()` 再用原有 canonical parser 驗證同一批 ES
   hit，並使用可信 Witness Grant 提供的回呼與 witness；
   這個二次解析的身份必須與第一次一致，不可只相信 LLM 的文字宣稱。
5. 若證據仍不足，由獨立策略 Planner 在既有額度內產生新召回策略，開始
   下一輪；若充分或預算安全停止則終止，並回傳**私有**各輪檢索結果、
   不含全文／事件私密內容的計數型 `safe_audit`。

## 關鍵安全限制

此 helper 雖然**具備實際 ES client 執行能力**，但目前：
- **不連接正式 API、Report Job Worker、OpenWebUI 或 Word**；
  因此使用者不能從現有 SRAF API 發起新的 N 輪 Job。
- 本身無法證明外部傳入的 client 具備合法 RBAC 權限；
  也無法驗證 `attest_whole_query_scope` 的回覆是真實正確。
  可信 Worker 需要真正建置可審計的 query-plan manifest 與跨索引／
  子題清單，不能僅將回呼設為 `lambda: True`。
- 語意 `semantic_assessor` 必須由可信服務實作，並依每次請求預算限制
  provider timeout／token 數；目前只控制最大驗證次數，
  **不具備**對長時間執行中的模型 SDK 真正取消的能力。
- 已有的 `QueryConstraints` 固定欄位／獨立分析日期硬條件仍不支援時
  由 ES adapter 拒絕；不能為啟用功能自動放寬。
- 整個 30 分鐘檢索截止條件必須在取回 ES、scope attestor、語意驗證
  返回之後重新檢查，避免長回呼過期後還被判為報告可接受。
- 返回的 `TrustedNroundExecutionResult` **不是 Word**，
  safe_audit 明確顯示 `report_job=NOT_INTEGRATED`、
  `word_generated=False`、`live_acceptance=NOT_TESTED`。

## CI 與 Linux 離線驗收

```bash
cd /mntCZJ/TopicClassification/poc-agent

PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_trusted_execution_loop.py \
  tests/test_sraf_nround_round_query_execution.py \
  tests/test_sraf_nround_private_semantic_binding.py \
  tests/test_sraf_nround_coverage_coordinator_bridge.py
```

測試透過偽 ES client／偽 Planner／偽語意驗證器（**合成環境才允許
模擬 scope attestor True**）驗證從第 1 輪取證、缺口判斷、策略規劃、
第 2 輪補證到滿足停止的完整循環；也測試查詢範圍未證明、ES
分頁失敗、語意驗證例外、失效的 provider／逾時預算、取消及隱私。

成功仍不等於私人 ES／LLM／Report Job 端到端上線。
接下來必須完成可信實體授權映射與真正的 query-branch manifest，
再接入報告 Job 持久化、單輪回覆與背景 N 輪 Word 載點。
