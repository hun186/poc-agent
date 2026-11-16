# SRAF 第 2～N 輪檢索：Planner 執行前的資源預算閘門（離線契約）

## 背景

現有 `AdaptiveRetrievalPlanner` 可根據可信的 `RoundEvidenceSummary` 判斷下一輪應 stop／search／date_recheck，但實際 LLM 呼叫和 `RequestAdmissionBudget` 屬不同組件。若開發者不先取得資源准入就直接呼叫 Planner，日後接到正式 N-round Job 時有超額 LLM 呼叫風險。

本 PR 引入 `agent/adaptive_retrieval/next_round_gate.py`，**只建立安全的「下一輪策略授權」物件**，不產生 ES DSL，不執行 ES、LLM 端點或報告 Job。

## 控制順序

1. 上層可信協調器對第一次檢索**先執行 `budget.admit("round")` 與每次 ES 請求前的 `budget.admit("es")`**。原有 Request Budget 設定：全部 2400 秒，預留生成 600 秒，故檢索新增操作預設 1800 秒（30 分鐘）上限；最多 8 rounds、24 ES calls、6 Planner calls。
2. 第一次及每次完整搜尋後，可信 Parser 與 Request-wide Evidence Ledger 回傳已去重、日期／事件／主題已驗證的 `RoundEvidenceSummary`。**不可信任單頁數量作 request_wide=true**；complete／coverage_sufficient 需上層資料完整性與研究品質契約負責。
3. `propose_budgeted_next_round` 先拒絕無資料、無可信 request-wide 評估、尚未完成頁面、Coverage 已足夠、使用者鎖定關鍵字、達輪數或兩輪無增量的情況；不會額外消耗 Planner Token。
4. 當確實需要重新思考且仍有預算時，從 `RequestAdmissionBudget.snapshot()` 取得呼叫前預算參考，接著**立即執行原子 `claim_next_strategy(completed_rounds)`**：在同一個請求的鎖內同時確定這輪尚未被其他執行緒認領、下一輪 round 額度仍有空間，以及 planner/ES 額度與時間均合法，並不可退回地扣除一次 Planner 額度。成功才呼叫既有 Planner。此順序確保只剩最後一次 Planner quota 仍可合法呼叫；若 Planner 回傳異常 JSON、越權日期/index/權限或沒有新策略，保守停止。
5. Planner 產生合法 `search` 策略後，透過原 `bind_next_round_plan` 再驗證 immutable QueryConstraints，**再一次 `admit("round")`**，確認沒有在 Planner 執行期間錯過 30 分鐘檢索截止，最後才回傳 `BoundNextRoundPlan`。
6. 本 PR **沒有**自動呼叫 ES。後續可信 ES adapter 仍必須於每次真正 ES 請求之前執行 `budget.admit("es")`，並在傳輸層加上 timeout、索引授權、不可變日期與欄位限制。不能把取到 BoundNextRoundPlan 誤當成已授權實際查詢、取消超時 SDK 或通過生產部署驗收。

## 隱私與檢查

`NextRoundAdmission.safe_audit()` 只輸出固定原因碼、輪次與是否准入，不包含原始問題、日期、ES index、來源 ID、可選關鍵字或模型回覆。固定原因碼包括資源不足、歷程過期、日期仍不完整、使用者鎖詞、Coverage 已足夠、Planner 異常、已准入等。

離線回歸測試涵蓋：
- 原始日期／索引／必要實體保持不變。
- 只有一個 Planner 配額時依然能在額度用盡前允許最後一次合法呼叫。
- LLM 函式執行時可觀察到已先扣除 Planner quota。
- 不完整／未經 request-wide 驗證、stale history、無增量、鎖定關鍵字都不呼叫 LLM。
- 30 分鐘檢索截止／10 分鐘生成保留區間不允許下一輪。
- Planner 執行後若時間已超過檢索截止，即使模型提出新的關鍵字也不能再 admit 新 round。
- 多執行緒爭用，即使同時還有多個 Planner 與 Round 額度，**同一份 completed history 只能被認領一次**，不能重複付費或產生兩張 Round 2 策略。
- Request Budget 的 max_rounds 已滿時，**LLM 呼叫前**拒絕下一輪；模型最大 32 輪停止時輸出的 audit round 也保持合法範圍。
- Planner JSON 錯誤／模型失敗後，同一份歷程的認領不退款，不會自動重試消耗更多模型額度。

本 PR 仍屬**離線策略准入基礎**，不代表已接進正式 Report Job、多輪 ES 查詢或 OpenWebUI 長時間等待流程，也不等同正式 L3-A/L3-B。
