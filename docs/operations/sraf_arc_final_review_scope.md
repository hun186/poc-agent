# A8c-1 最終 Evidence 來源綁定（本地觀察）

獨立旗標 SRAF_ARC_REVIEW_SCOPE=shadow，預設關閉；並要求 SRAF_ARC_REVIEW_VERIFIED_INDEX 單一具體索引。普通報告私有 ARC scope、原始問題、明確雙端 ISO 日期、非 manual、非 Requirement acceptance、非 ordinary scope capture。safe_search 首次非 retry 的實際 Elasticsearch client 成功路徑建立私有 receipt；mock、partial、timeout、remote cluster、gte、索引不符、重複 _id、回應未完整返回或 >128 hits 均略過。此為窄範圍 pilot，不代表所有報告均適用。

日期 refill 最終選定來源與 Evidence 後，核對同一 query body / response 物件、raw hit 順序與身分、具體索引與 _id、單頁且無 scan/admission 截斷。僅針對實際留下來源之首64筆 Evidence，保留 strict、structured_time_context=true 且有 canonical matched_event_time_candidates 的完整正文；非結構日期 fallback 不用於此 pilot。不得以 UUID 代替 hit ordinal。先保留 ARC 共享預算 1 slice / 128 hits / 64 rows / 96000 chars，再準備 A8 批次；最多8筆不同來源、每筆<=1500 chars，沿用 A8a 契約。最終選擇與原輸出不變。只記固定狀態、batch/prefix/skipped counts，立即丟棄私有批次；不呼叫 A8b transport、不傳送正文、不新增 ES/LLM 呼叫。不得據此宣稱模型複查已執行。

receipt 只證明受限的程式內資料流，不證明 ES 連線的 TLS 主機身分（目前普通 ES client 的 hostname 驗證設定需另外驗收）、授權的 owner/document scope、端點資料保留或出境核准。真正接入 A8b 之前仍須可信來源及 owner/ACL/端點授權、deadline 與 LLM 預算分配 gate；不以 operator index 設定或 budget 取代授權。實機 A/B 尚未驗收。


## A8c-2 明確授權的普通報告接入候選

既有 `agent.tools_es.date_refill.refill_date_filtered_evidence` 私有 Python 入口
新增可選的 `_arc_review_policy`、`_arc_review_deadline_monotonic`。
未注入 callback 時仍只記錄本地 scope；一般 ESSearchNews/Report Job/HTTP
呼叫者目前沒有傳入這兩個參數，也沒有新增 env 開關。

在既有來源綁定、完整首頁、明確日期、structured strict Evidence 與掃描
預算條件上，額外要求至少 40 筆最終保留片段、4 筆不同來源的有效批次及
弱/混合/metadata 歧義。可信 callback 必須獨立核准原問題、不可變語意群組、
日期、實際具體索引、首 64 筆可進入取樣的所有 ES _id（保守超集合）、
專用 HTTPS endpoint/model/CA 及 owner/document/data egress 政策。
不得由 LLM、公用參數或環境開關授予此能力。

deadline 為可信呼叫者使用 monotonic clock、已扣除後續報告生成保留時間的
截止點；呼叫前後與 policy 前後至少保留 25 秒，重查 ARC 旗標、端點配置及
共享 budget scope；沿用 A8 transport 的原子、不可退款單次模型 reservation。
不重試，不改報告輸出，不保留/公開逐筆 verdict。拒絕、撤銷、逾期、
模型失敗均不影響原有檢索結果。讀取 timeout 並非硬取消；撤銷後無法
收回已傳送的內容。尚未有可信普通報告 owner/ACL policy、正式 caller 或
A2/A7/A8 統一分配接線，因此不代表已開放正式普通語意複查或完成實機驗收。
