# SRAF N 輪｜Report Job 所有者及查詢範圍綁定（隔離接口）

**階段：尚未接正式 ReportJobWorker、API、ES、LLM 或 Word。**

目前在 Linux 上，先前 71/71 與新一組 74/74 的合成測試都通過。
但原先的 `run_trusted_nround` 只透過
`attest_whole_query_scope(plan, receipt) -> bool`
向呼叫端要求「整題查詢已完成」；若最終 Worker 寫成
`lambda ...: True`，就可能將沒有授權或缺少重要查詢分支的
結果錯誤放行。

## 新接口

`WorkerScopeBinding` 綁定**已認領且為 running 狀態**的
既有 `ReportJob` 物件、Job 所有者（`owner_kind,owner_id`）、
`session_id`、原始 Job prompt 與**相同物件的**
`QueryConstraints`、`AdaptiveRequestCoordinator` 和授權 index 清單。

只有當上層可信 Worker 提供下列兩種真實 policy 回呼才能建立並執行：
- `check_index_access(job,index)`：對每一個擬查詢 index 判定目前 Job
  所有者是否有讀取權；需回傳真正的 `True`。
- `check_single_branch_coverage(job,constraints,("CANONICAL_MAIN",))`：
  獨立確認原始問題所有必要查詢分支，確實能由目前**唯一支援**
  的 canonical 主查詢完成，且未漏掉固定欄位／分析日期等硬性條件。
  如果需要多查詢分支或驗證器不具備該能力，必須拒絕。

`run_trusted_nround(job_scope_binding=...,attest_whole_query_scope=None)`
在每輪 ES PIT **開啟前**執行 `preflight()`，驗證所有者及索引權限。
完整分頁鏈取得後再執行 `attest()`，重新檢查權限、問題分支及正確的
round／索引／來源／頁數。若其中一個拒絕或丟錯，立即 fail closed，
不送到語意覆蓋度／下一輪。每個 round 只能 attested 一次；
跨不同 coordinator／owner 的 binding 不得混用。執行權杖
（`_execution_token`）同時綁定 PIT 開啟、各分頁與完整回執；
Owner binding 另外持有專屬的不公開 `_owner_binding_token`。
`preflight` 會記住**同一個 frozen plan 物件**，`attest` 必須
證明該 plan 曾成功排他認領、至少預算承認 PIT 與分頁的兩次 ES IO、
收到帶同一執行權杖的真實查詢回執，且所有 hit 的 index 在原始授權
範圍內。沒有執行過查詢就手工建造回執、用另一個 owner 的
plan、相同輪次的另一份 plan 或重複使用同一回執，都會拒絕。

此外 preflight 經授權政策確認後，會在**協調器自身**登記
`(round, owner_binding_token, execution_token)`；
只有這組身分已在任何 ES IO **發生前**記錄，該 round 才能領取
PIT 的執行 claim。若在 preflight 前試著跑帶 owner token 的 ES
executor，必須沒有 PIT IO；若已經透過未授權的舊路徑執行過 ES，
事後 preflight 必須失敗，絕不可追認。preflight 與 claim 的空檔若
有其他舊路徑發起 ES 亦應立即取消該輪，不能繼續當作合法完成。
隔離測試用的舊回呼模式仍保留，但不可與 binding 同時指定，
以免用 `lambda: True` 覆寫 binding 決策。

## 尚未完成的生產安全與功能

- 本模組**無法獨立證明**傳入的 ReportJob 確實由資料庫認領、
  Job owner 沒被冒用、回呼有真正查詢現行權限，或問題確實只需要
  一條 canonical 查詢。未來 Worker 必須從持久化 Store 讀取實際
  running Job，核對 owner 及 session，並注入正式 RBAC／完整需求政策。
  即使 binding 已實作，不能提前宣稱可以正式接受使用者 N 輪請求。
- 檢索開始前及完成後都會查權限，但遠端 ES 呼叫期間權限可能被撤銷，
  已在途的呼叫無法透過本 Python 模組強制中斷；正式 Worker 需有
  能撤銷的 Session／ES credentials，並避免把非必要原文持久化。
- 固定欄位 `fixed_fields` 與獨立分析日期 `analysis_date` 等
  尚未在 ES 查詢介面支援的硬條件，仍由既有 ES adapter fail closed。
- 現有 Report Job 為單輪 Word，尚未建立第二份 N 輪 Word 的獨立
  持久化執行及可授權下載路由。**沒有變更 SQLite schema 或現有
  正式 API；也沒有更動正式部署開關。**
- `safe_audit()` 只輸出固定狀態碼與數量，不會輸出 Job ID、
  所有者、session、原始問題、證據、PIT ID 或索引名。

## Linux 離線驗證（更新 main 後）

```bash
cd /mntCZJ/TopicClassification/poc-agent
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_worker_scope_binding.py \
  tests/test_sraf_nround_trusted_execution_loop.py \
  tests/test_sraf_nround_round_query_execution.py \
  tests/test_sraf_nround_private_semantic_binding.py
```

此命令不呼叫真實 ES、LLM、SQL 或 Word，不代表完整 N 輪上線驗收。


## N 輪語意／LLM 證據逐筆授權重驗（2026-11-18 隔離階段）

PIT 前後通過的 Job/Owner/索引與原始問題授權不代表整輪
語意處理期間永遠有效。現在只有在 `WorkerScopeBinding.attest()`
核對同一個不可偽造的已執行 PIT plan 後，
`recheck_semantic_authorization(plan)` 才允許使用；
每次可信語意驗證器（可能花費 LLM 時間／費用）**呼叫前和回傳後**
都重新讀取真實已認領的 ReportJob 並執行當下的 owner/index
與整題單一分支政策。若 Job 失效、權限撤銷、callback 異常或
同一輪執行計畫遭到更換，就 fail closed，不再對剩餘片段呼叫模型。

這只適用明確注入 owner-bound 的隔離式 `run_trusted_nround`
路徑，既有無 binding 的離線 helper 行為不變，正式單輪
ReportJobWorker/Word/API 未修改。無法撤銷已經送出的 ES/LLM
請求，也不取代真實可信 RBAC、跨主機租約或終止後報告生成
前的獨立授權 CAS。

離線回歸：`tests/test_sraf_nround_persisted_claimed_job_scope.py`
使用臨時 SQLite 與假 ES／語意 assessor，在第一筆 LLM
回呼期間撤銷 owner-index、整題 query branch 或 Job，
三種情況都不能開始第二筆模型回呼；沒有實機驗測。
