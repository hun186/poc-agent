# A9 語意複查離線成對標註驗收

`agent/es/evidence_core/arc_semantic_eval.py::evaluate_semantic_cases` 是純離線統計介面，不呼叫模型/ES，不更改任何正式 Evidence。輸入為 operator 私下已配對、同一候選集合上的人工標註與模型預測；每 case 為 list，row 僅含 ordinal、source（同 case 的本地序號）、gold、predicted（relevant/uncertain/unrelated）、direct_anchor、strong。最多32 cases、每 case 256 rows、總4096 rows；拒絕缺項、重複序號、未知標籤、額外欄位與不合法型別。不得從目前 count-only A8 生產觀察重建個別模型預測；真實人工標註及私有成對模型測試仍需另行授權、於本地隔離環境取得。

對照 keep-all 與假設只移除 model-unrelated（不移除 uncertain），計算 3x3 confusion matrix、人工已確定標籤的 precision、相對於同批人工 relevant 的保留率及誤淘汰率、人工 unrelated 移除率、人工 uncertain 誤刪疑慮、必要主體/strong 的 relevant 誤淘汰率，以及按 case 彙總來源保留與相關來源喪失。即使來源仍有無關片段，不算保留該來源的 relevant coverage。所有比例提供 numerator/denominator，分母0時 value=null；不將人工 uncertain 當真/假，不隱藏其數量。輸出僅聚合數字，不輸出序號、文字或 per-row verdict。未驗證抽樣是否具代表性，非全資料庫 recall 或安全啟用證明。資料量、模型推論效能、人工一致性及不同議題/日期切片仍需實機驗收。本功能不提供正式自動刪除權限。
