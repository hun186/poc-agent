# ARC A3b 深度報告統計 admission（尚無 ES transport）

深度報告的原生文件頻率分母以原始事件日期及必要實體 filter 為限，不包含一般 relevance should。它可能涵蓋未由 canonical 查詢取得的文件，因此原有 index/branch 存取權限不是統計授權。WorkerScopeBinding 新增獨立 check_frequency_scope(job, constraints)，預設 None；只有可信 Worker 明確授權此範圍才可申請。仍需重新查核 running Job、owner/index/branch policy；不從 LLM、環境變數或使用者 query 推導授權。

必須是同一 owner 預檢的 exact frozen plan、已 claim 的 execution token、同一 coordinator/round/constraints 的完整且已 take_complete_hits 的 RoundESPageFence，無 pending/failed。重用既有 build_deep_frequency_plan 的硬範圍驗證，不能把計數請求當 canonical page。獨立 optional admission 在 coordinator lock 內確認 active phase、round、token、PIT open + 完成頁數的必要 ES slots；原 request budget 限制每輪1次、全請求2次，保留至少2個 ES slots 及10秒 retrieval reserve。ARC 也須在相同 round 綁定並原子保留 es_calls=1；先保留 ARC，若後續主預算拒絕不退款，避免額外重試。拒絕本身不終止原本查詢；已取消/過期則不得開始 IO。

此 PR **只有 admission/policy gate 與 synthetic tests，尚未發出統計 ES 請求**。可信 adapter 後續仍須在必要頁鏈完成而 PIT 未關閉時，使用已授權相同 PIT，傳送固定 count-only DSL、限制 timeout、零重試、嚴格驗證 response 與最新 PIT id，依既有 cleanup contract 關閉；任何觀察值均不可提升 technical/semantic coverage 或改變正式 Evidence。需確認 owner 目前資料權限確實允許 broader root-doc counts，並取得實機 mapping/analyzer/負載驗收。既有 Worker 不傳入 frequency policy，預設不執行。
