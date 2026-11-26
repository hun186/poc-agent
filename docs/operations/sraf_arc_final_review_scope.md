# A8c-1 最終 Evidence 來源綁定（本地觀察）

獨立旗標 SRAF_ARC_REVIEW_SCOPE=shadow，預設關閉；並要求 SRAF_ARC_REVIEW_VERIFIED_INDEX 單一具體索引。普通報告私有 ARC scope、原始問題、明確雙端 ISO 日期、非 manual、非 Requirement acceptance、非 ordinary scope capture。safe_search 首次非 retry 的實際 Elasticsearch client 成功路徑建立私有 receipt；mock、partial、timeout、remote cluster、gte、索引不符、重複 _id、回應未完整返回或 >128 hits 均略過。此為窄範圍 pilot，不代表所有報告均適用。

日期 refill 最終選定來源與 Evidence 後，核對同一 query body / response 物件、raw hit 順序與身分、具體索引與 _id、單頁且無 scan/admission 截斷。僅針對實際留下來源之首64筆 Evidence，保留 strict、structured_time_context=true 且有 canonical matched_event_time_candidates 的完整正文；非結構日期 fallback 不用於此 pilot。不得以 UUID 代替 hit ordinal。先保留 ARC 共享預算 1 slice / 128 hits / 64 rows / 96000 chars，再準備 A8 批次；最多8筆不同來源、每筆<=1500 chars，沿用 A8a 契約。最終選擇與原輸出不變。只記固定狀態、batch/prefix/skipped counts，立即丟棄私有批次；不呼叫 A8b transport、不傳送正文、不新增 ES/LLM 呼叫。不得據此宣稱模型複查已執行。

receipt 只證明受限的程式內資料流，不證明 ES 連線的 TLS 主機身分（目前普通 ES client 的 hostname 驗證設定需另外驗收）、授權的 owner/document scope、端點資料保留或出境核准。真正接入 A8b 之前仍須可信來源及 owner/ACL/端點授權、deadline 與 LLM 預算分配 gate；不以 operator index 設定或 budget 取代授權。實機 A/B 尚未驗收。
