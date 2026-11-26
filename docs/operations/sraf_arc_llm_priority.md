# ARC LLM 優先分配（第一階段）

SRAF_ARC_LLM_PRIORITY=shadow，預設關閉。普通報告不再於首批 ES 回應後立即執行 A2b，而在既有 final Evidence selection/refill 後，重用同次首批 A5/A6 的 A7 route。A2/A7 各自開關仍有效，A5/A6 診斷亦需分別開啟，不自動增設觀察。A2 優先於尚未解決且無截斷的低量語意/alias 評估；缺明確必要主體、多種可行收緊策略等由 A7 處理；無適用選項、精確零、日期/來源問題、已有放寬候選、一般量、多頁或不完整查詢則不分配額外模型。精確零未自動擴詞，保留查詢範圍診斷。A7 可繼續記錄確定性路由或 deferred_by_priority。相同 Data Agent 的多工具共享每輪最多1次 ARC LLM reservation，仍由既有 atomic budget 控制，不回退/重試、不退款；跨工具先後順序仍可能影響分配，非全報告最佳化。計數/路由僅為觀察，無正式查詢或 Evidence 改變。

A8 本地 scope / 專用 HTTPS transport 已有各自契約，但未有已授權 production caller，因此此階段不分配 A8、不傳送 Evidence。深度 PIT 統計及實機 A/B 仍待整合。flag 關閉維持既有 A2/A7 呼叫順序。所有門檻及效益尚待真實私有資料驗收。
