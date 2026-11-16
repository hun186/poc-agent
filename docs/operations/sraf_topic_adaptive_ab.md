# SRAF P0：單輪 Topic Match 低證據量自適應（受控 3→2）

## 為什麼需要這個機制

既有主題語意群組規則：1 組須命中 1，2 組須命中 2，3 組須命中 3，4 組以上至少命中 3。原設計避免大量低相關 Evidence，實際報告中常出現已由 ES 找到適當文章、但該文章部分 Evidence 僅符合 2/5 群組而被排除。既有 zero-only relaxed fallback 不會在仍有 1–2 筆嚴格片段時自動重新評估。

本功能不取消嚴格規則，而是先產生安全候選，再在樣本足夠、精確率/誤收率經人工驗收後決定是否讓正式報告採納。與之前的 Topic Shadow 相容；**不是第二輪 ES 搜尋、不是 N-round LLM planner、不是檢索完整性證明**。

## 開關、先決條件、失敗保底

環境變數 SRAF_TOPIC_MATCH_ADAPTIVE：off（預設）、shadow、on。

- off：保留現有結果，無額外候選、無適應性審核成本。
- shadow：以同一批已解析 ES hits 計算新候選，但不加入輸出。輸出固定格式的 count-only audit，適合真實 ES A/B。
- on：只有嚴格 Evidence 非零且不足 3 筆、term_groups 至少 4 軸、從**原始提問**明確且唯一辨識必要主題、片段本體至少命中兩個獨立主題語意軸時，才可加入最多 2 段弱證據，使總數達最多 3 段。現有日期、Event/Timeline 驗證不放寬。

此版所謂「可信必要主題」僅支援使用者第一個非空行明確標記，例如：

主題：加薩
請分析 2025 年加薩停火、醫療及人道援助。

標記主體須恰好對應一組已提供的語意軸，而且沒有歧義或排除指令。一般自然語言如「分析加薩停火」尚不能穩健地自動推斷必要實體，這類問題會安全地不啟用新增 3→2；後續需完善命名實體、否定與比較條件辨識。**絕不可直接拿 LLM 重寫的關鍵詞當成可信必要主體**。

若候選本段直接提及必要主題，允許作為候選；若不直接提及，只在已由同一個原始 ES hit、同一個結構化區塊及同一 Event ID 的獨立強證據建立必要主題上下文時，才允許作為 contextual 候選。只有文章標題、metadata、相同 UUID、相同發文日期或跨 Event 文字，均不足以讓無直接主題證據放行。每個候選仍須通過 build_evidence_snippet 的 canonical 日期關聯。

每 builder slice 僅檢視至多 256 條已解析片段，每段最長 4096 字元、總文字 262144 字元；此階段不增加 ES/LLM 呼叫。高風險語意判斷在真實資料品質驗收前**不得將 on 設為部署預設**。

## 必須留下、又不外洩資料的 Audit

當使用者明確選 shadow 或 on，日誌會包含固定前綴 SRAF_TOPIC_ADAPTIVE，並用固定 schema 枚舉／整數記錄 mode、status、strict、inspected、date_eligible、two_text_axes、direct_subject、same_event、blocked_meta_only、blocked_unanchored、uninspected_by_cap、proposed、selected。若也有 SRAF_EVIDENCE_TRACE=1，沿用既有單次 Builder Trace 裡的 adaptive_3to2.* count-only 指標。

**不記錄原始問句、主體、日期、來源 UUID、Event ID、片段、路徑或 LLM 輸入**。它是單輪／單批解析器統計，不代表 Request 全域或真正的 Recall。需透過同一資料快照 A/B 加上人工判斷方可計算 precision/recall。

## 在部署機做同一批資料的唯讀離線 A/B

已提供 tools/sraf_topic_adaptive_ab_offline.py，可讀一份由受信操作員以原有讀取權限取得的 ES 查詢結果快照，不會對 ES、SQL、LLM、API 發出連線或寫入。使用者必須自行在私人主機建立快照；此工具不提供權限提升或任何匯出密鑰功能。

Snapshot JSON 欄位：
- es_hits：原始 ES hits 陣列；每個元素必須是 Search API 返回的 _index、_id、_source、inner_hits 等必要內容（不要只傳計數）。
- date_from、date_to：同一案例的固定日期條件。
- term_groups：多個語意群組，每組字串陣列，含必須的主要主題名稱。
- effective_terms：本輪原本的核心與相關詞清單（與報告來源一致）。
- original_question：原始提問，若要受控 3→2 必須有第一行明確必要主題。
- query_for_snippet：供既有解析器挑選片段的固定查詢詞。

快照可能包含內部正文與敏感 ID；只能在你控制的 Linux 主機私人目錄保存，所有者須是執行使用者、權限 0600、上限 8MiB、不能是 symlink。**不要貼到 GitHub、ChatGPT 或 Word**，對外只提供工具的固定計數摘要即可。

使用既有 Windows→Linux 增量部署後在主機操作：

~~~bash
cd /mntCZJ/TopicClassification/poc-agent
python -m tools.sraf_topic_adaptive_ab_offline /path/to/private_sraf_news_test_snapshot.json
~~~

這會用完全相同的輸入，分別計算 off／shadow／on 版本的片段數、增補數與來源數。固定摘要會標示 live_es_query=NOT_TESTED、report_docx=NOT_TESTED、human_precision_assessment=REQUIRED；**不會假裝已通過真實 ES、召回率或 Word E2E**。

推薦案例：2025 加薩停火／蘇丹假相關（比較 5/10 與 25/40 同快照）、2023-08-24 古特雷斯 Event-only 日期、Timeline 為空或日期 null。每次都必須固定 ES 索引、日期、檢索詞與原始問題；人工標記可信真陽性／假陽性與誤刪。光看新增幾段不能等同品質改善。

## 與 Report LLM Evidence Review 的先後與實機要求

單輪流程：ES 候選 → 日期安全檢查 → 嚴格 Topic Match → 有界／受控弱證據補救 → LLM Evidence Relevance Review（另以 SRAF_REPORT_EVIDENCE_REVIEW=shadow|on 控制）→ 報告生成／Citation／DOCX。

兩層目標不同：Topic Match 主要改善低證據量的召回，而 LLM 只作為另行評估的相關性覆核，不能回寫 Evidence、也不得掩蓋 Topic Match 誤收。兩者都應先跑 shadow 並獨立觀察，不應一次把兩個 on 都打開，否則無法定位品質變化。

真實 L3-A Report Job + DOCX、L3-B 自動排程、N-round Adaptive Job、SQL L2/ES TLS、Token 模型容量、跨頁完整召回均另列驗收；此 PR 不替代以上工作。
