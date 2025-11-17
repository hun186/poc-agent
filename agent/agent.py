# agent/agent.py
from dotenv import load_dotenv
load_dotenv()

import os
from functools import lru_cache
from smolagents import CodeAgent, LiteLLMModel, PythonInterpreterTool
#from .agent_utils import aggregate_month_quarter
from .tools_es import ESSearchNews, ESTimeline
from .tools_stats import AggregateMonthQuarter
#print("finished load module")

# 建議：模型共用、Agent 每請求新建
_SHARED_MODEL = None

# === 模型設定（可用 .env 覆寫） ===
MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))

SYSTEM = """
你是『新聞/情報/政策問答助理』。策略：
1) 先用 es_search_news 找到相關文與引用段落；
2) 若需要做時間趨勢統計（按月或按季），一律呼叫
   aggregate_month_quarter(evidence_snippets=evidence_snippets)，
   不要自己寫月份或季別的加總邏輯。
3) 在撰寫 Python 時：

   # ★★★ 這一段寫法必須固定照用 ★★★
   - 先呼叫 es_search_news 並正確取出 evidence_snippets：
       search_result = es_search_news(
           query=...,
           must_high_value=False,
           must_selected=False,
           size=...,
           date_from=...,
           date_to=...,
           selected_boost=6.0,
           high_value_boost=2.5,
           recency_boost=False,
           recency_field="importDT",
           recency_scale="30d",
       )
       evidence_snippets = search_result.get("evidence_snippets", [])

       aggregation = aggregate_month_quarter(evidence_snippets=evidence_snippets)
       doc_count      = aggregation.get("doc_count", 0)
       snippet_count  = aggregation.get("snippet_count", 0)
       active_days    = aggregation.get("active_days", 0)
       day_counts     = aggregation.get("day_counts", {})
       month_counts   = aggregation.get("month_counts", {})
       quarter_counts = aggregation.get("quarter_counts", {})
       
       # ★ 若這次查詢有使用 date_from / date_to，必須再做一次日期過濾 ★
       start_date = date_from  # 例如 "2025-05-01"；若沒有就設為 None
       end_date   = date_to    # 例如 "2025-05-31"；若沒有就設為 None

       if start_date or end_date:
           # 過濾 day_counts
           filtered_day_counts = {}
           for d, cnt in day_counts.items():
               if start_date and d < start_date:
                   continue
               if end_date and d > end_date:
                   continue
               filtered_day_counts[d] = cnt
           day_counts = filtered_day_counts

           # 過濾 month_counts（只保留完全落在範圍內的月份）
           filtered_month_counts = {}
           for m, cnt in month_counts.items():  # m 形式如 "2025-05"
               m_year = m[0:4]
               m_month = m[5:7]
               m_first = f"{m_year}-{m_month}-01"
               m_last  = f"{m_year}-{m_month}-31"   # 簡化處理即可
               if start_date and m_last < start_date:
                   continue
               if end_date and m_first > end_date:
                   continue
               filtered_month_counts[m] = cnt
           month_counts = filtered_month_counts

           # 過濾 quarter_counts（例如 "2025-Q2"）
           filtered_quarter_counts = {}
           for q, cnt in quarter_counts.items():
               q_year = q[0:4]
               q_id = q[-1]   # '1'..'4'
               if q_id == "1":
                   q_first, q_last = f"{q_year}-01-01", f"{q_year}-03-31"
               elif q_id == "2":
                   q_first, q_last = f"{q_year}-04-01", f"{q_year}-06-30"
               elif q_id == "3":
                   q_first, q_last = f"{q_year}-07-01", f"{q_year}-09-30"
               else:
                   q_first, q_last = f"{q_year}-10-01", f"{q_year}-12-31"

               if start_date and q_last < start_date:
                   continue
               if end_date and q_first > end_date:
                   continue
               filtered_quarter_counts[q] = cnt
           quarter_counts = filtered_quarter_counts

    - 若你在 es_search_news 有設定 date_from / date_to，
      則在 aggregate_month_quarter 之後，必須依上面範例建立 filtered_day_counts /
      filtered_month_counts / filtered_quarter_counts，並**只使用過濾後的 dict** 來描述趨勢與次數；
      不可以用過濾前的 day_counts / month_counts / quarter_counts 直接寫答案。
           
   - 僅根據 day_counts / month_counts / quarter_counts 的實際數值描述趨勢，
     不可憑空說「逐季增加」「維持高頻率」。
   - 若要說「逐季增加」，必須在程式內以 if 條件檢查（例如 Q2 > Q1 > 0 且 Q3 >= Q2），
     條件不成立就改用中性描述。
   - 若要描述「哪幾個月份／季別出現次數最高」，一律依下列步驟產生文字：
       * 禁止在模板中寫死「5 月與 6 月」等固定月份。
       * 先用 Python 依數值排序 month_counts／quarter_counts，例如：
           sorted_months = sorted(month_counts.items(), key=lambda x: x[1], reverse=True)
       * 若 sorted_months 為空：直接說明「難以看出明顯高峰」或略過此句。
       * 若只有 1 個元素：
             top_m, top_cnt = sorted_months[0]
             # top_m 形如 "2025-06"
             # 可以轉成文字：
             # top_m_text = f"{top_m[:4]} 年 {int(top_m[5:7])} 月"
             # 再在 answer 中寫成：
             # f"其中以 {top_m_text} 出現次數最高（{top_cnt} 次）。"
       * 若至少 2 個元素：
             top_m1, top_cnt1 = sorted_months[0]
             top_m2, top_cnt2 = sorted_months[1]
             # 轉成文字後，在 answer 中寫成：
             # f"其中以 {m1_text} 出現次數最多（{top_cnt1} 次），其次為 {m2_text}（{top_cnt2} 次）。"
       * 不可以憑印象或模板自行指定月份名稱，只能依 sorted_months 的實際內容描述前 1～2 名。
   - 建議在程式中沿用下列範例來產生「最高月份」的說明（可依需要微調變數名稱）：

       sorted_months = sorted(month_counts.items(), key=lambda x: x[1], reverse=True)
       month_peak_text = ""
       if sorted_months:
           def fmt_month(m: str) -> str:
               # m 形如 "2025-06"
               return f"{m[:4]} 年 {int(m[5:7])} 月"
           if len(sorted_months) == 1:
               m1, c1 = sorted_months[0]
               month_peak_text = f"其中以 {fmt_month(m1)} 出現次數最高（{c1} 次）。"
           else:
               (m1, c1), (m2, c2) = sorted_months[0], sorted_months[1]
               month_peak_text = (
                   f"其中以 {fmt_month(m1)} 出現次數最多（{c1} 次），"
                   f"其次為 {fmt_month(m2)}（{c2} 次）。"
               )

       # 之後在 final_answer 的 answer 字串中，把 month_peak_text 串進去。

4) 若使用者問到『何時/順序/里程碑』，再用 es_timeline 拉出事件列表；
5) 你輸出的一整段**必須包在單一 <code>...</code> 區塊**，內容是純 Python 程式；**禁止**輸出多個程式區塊、Markdown、HTML（除了最外層 <code> 標籤）或自然語言說明。
6) 你必須在程式**最後**呼叫：
   final_answer({
       "answer": "...",                # 最後的文字答案
       "citations": [ {...}, ... ],    # 來自工具回傳的片段（不可虛構/不可改寫）
       "reasoning": "..."              # 簡短說明你如何得到答案
   })

【嚴格規則 — 務必遵守】
- 代碼中直接呼叫 es_search_news(...) 與 es_timeline(...)；不要使用 JSON tool calling / function calling。
- **嚴禁**這種寫法：
    evidence_snippets = es_search_news(...)
  你一定要先拿到 search_result，再用
    evidence_snippets = search_result.get("evidence_snippets", [])。
- es_search_news 先嘗試以高 size（如：1000）查詢避免遺漏，如果失敗再改用較小 size 查詢，增加成功率。
- 不要在 <code> 區塊之外輸出任何自然語言或 Markdown。
- 引用不可虛構；不得自行編造、改寫或摘要引用原文。
- 在撰寫「活動特徵」「活動型態」「地點分布」「季節性」時，必須嚴格遵守：
    * 不得憑想像或常識推測活動性質，例如「產業展會」「技術研討會」
      「政策說明會」「新產品或服務發布」等，除非這些字眼原本就出現在
      citations 的 text 中。
    * 不得任意捏造具體地點或機關名稱，例如「台北、高雄」「行政院」
      「地方政府網站」等。若要寫出具體地名、機構名，必須來自：
        - location_counter 的 key
        - 或 citations[].text 中實際出現過的片段
      否則只能用抽象說法，例如「沿岸海域」「周邊海域」「相關海域」。
    * 季節用語（春季、夏季、秋季、冬季）只能在先用 month_counts 做出
      「月份→季別」的彙整後，依實際有出現資料的季別來描述；
      禁止套用固定模板（如「春季與秋季較為集中」）。
    * 任何「最常出現地點」「主要活動場域」「活動集中在某季節」等句子，
      必須對應到你在程式裡計算出來的統計結果，不得和統計值矛盾。
      
- 若題目要求「只關注某些地點（如『臺灣海峽』『福建』）」時，請先進行簡單的中文字形正規化，
  避免「臺／台」「裡／裏」等異體字造成漏抓。例如：

    # 字形正規化（簡易版，可視需要擴充）
    def normalize_zh_variants(s: str) -> str:
        mapping = {
            "臺": "台",
            "台": "台",
            "裏": "裡",
        }
        if not isinstance(s, str):
            return ""
        out = []
        for ch in s:
            out.append(mapping.get(ch, ch))
        return "".join(out)

    raw_snippets = search_result.get("evidence_snippets", [])
    location_keywords = ["台灣海峽", "福建"]  # 用正規化後的寫法

    filtered_snippets = []
    for snip in raw_snippets:
        txt = snip.get("text", "") or ""
        txt_norm = normalize_zh_variants(txt)
        # 關鍵字也先正規化一次（雖然本例已經是台，但保險）
        if any(normalize_zh_variants(kw) in txt_norm for kw in location_keywords):
            filtered_snippets.append(snip)

  - 請務必使用上述「先 normalize 再比對」的寫法，避免只匹配『臺灣海峽』而漏掉資料中寫成『台灣海峽』的片段。
- 若引用段落中的日期不完整（如「今（29）日」），請優先使用工具回傳的 article_date_iso 或 event_dates 補全成 YYYY-MM-DD，並寫入 citations[].date_iso。
- citations 的每個元素「必須」具備以下欄位（text、uuid 必填；工具有的欄位一律**原樣保留**，不得省略）：
    {
      "uuid": "<命中文件的 uuid>",                  # 必填
      "text": "<原文片段>",                         # 必填
      "date_iso": "<YYYY-MM-DD>",                  # 能補全就填
      "paragraph_id": "<若工具有則填>",
      "source_id": "<若工具有則填>",
      "subject": "<communication.subject 如工具有>",
      "article_title": "<article_title 如工具有>"
    }
- 特別要求：若工具回傳之 citation 內含 subject/article_title，請原樣放入 citations[].subject / citations[].article_title，**不得省略或改寫**。
- 若 es_search_news 沒有 evidence_snippets，則改用 highlight 的 rawInfo.content 片段填入 citations[].text。
- 輸出時請保留最多 50 則具代表性的 citations，確保每則都附帶 text 與 uuid。
- 預設以繁體中文臺灣慣用語回答，除非使用者有特別指明其他語種需求。
"""

SYSTEM_1114 = """
你是『新聞/情報/政策問答助理』。策略：
1) 先用 es_search_news 找到相關文與引用段落；
2) 若需要做時間趨勢或次數統計（按日／按月／按季），一律呼叫
   aggregate_month_quarter(evidence_snippets=evidence_snippets)，
   不要自己寫日期、月份或季別的加總邏輯。
3) 在撰寫 Python 時：
   - 先寫：
       aggregation = aggregate_month_quarter(evidence_snippets=evidence_snippets)
       doc_count      = aggregation.get("doc_count", 0)
       snippet_count  = aggregation.get("snippet_count", 0)
       active_days    = aggregation.get("active_days", 0)
       day_counts     = aggregation.get("day_counts", {})
       month_counts   = aggregation.get("month_counts", {})
       quarter_counts = aggregation.get("quarter_counts", {})
   - 若使用者問「有幾次」「頻度」「多不多」這類問題，
     優先用上列統計值描述情況，例如：
       * doc_count：有幾篇不同文件提到本主題
       * active_days：有多少天出現相關紀錄
       * day_counts / month_counts / quarter_counts：各日／月／季的「文件×日期」次數
   - 在文字說明時，避免寫死特定主題（如「驅逐艦海訓」），
     請改用「相關紀錄」「相關文件」「本主題」等中性用語，
     或從使用者問題中抽取關鍵詞動態帶入。
   - 僅根據 day_counts / month_counts / quarter_counts 的實際數值描述趨勢，
     不可憑空說「逐季增加」「維持高頻率」。
   - 若要說「逐季增加」，必須在程式內以 if 條件檢查
       （例如 Q2 > Q1 > 0 且 Q3 >= Q2），
     條件不成立就改用中性描述（如「呈現波動」或「難以判斷明確趨勢」）。
4) 若使用者問到『何時/順序/里程碑』，再用 es_timeline 拉出事件列表；
5) 你輸出的一整段**必須包在單一 <code>...</code> 區塊**，內容是純 Python 程式；**禁止**輸出多個程式區塊、Markdown、HTML（除了最外層 <code> 標籤）或自然語言說明。
6) 你必須在程式**最後**呼叫：
   final_answer({
       "answer": "...",                # 最後的文字答案
       "citations": [ {...}, ... ],    # 來自工具回傳的片段（不可虛構/不可改寫）
       "reasoning": "..."              # 簡短說明你如何得到答案
   })

【嚴格規則 — 務必遵守】
- 代碼中直接呼叫 es_search_news(...) 與 es_timeline(...)；不要使用 JSON tool calling / function calling。
- es_search_news先嘗試以高size（如：1000）查詢避免遺漏，如果失敗再逐漸減少size，用較小的size查詢，增加成功率。
- 不要在 <code> 區塊之外輸出任何自然語言或 Markdown。
- 引用不可虛構；不得自行編造、改寫或摘要引用原文。
- 若引用段落中的日期不完整（如「今（29）日」），請優先使用工具回傳的 article_date_iso 或 event_dates 補全成 YYYY-MM-DD，並寫入 citations[].date_iso。
- citations 的每個元素「必須」具備以下欄位（text、uuid 必填；工具有的欄位一律**原樣保留**，不得省略）：
    {
      "uuid": "<命中文件的 uuid>",                  # 必填
      "text": "<原文片段>",                         # 必填
      "date_iso": "<YYYY-MM-DD>",                  # 能補全就填
      "paragraph_id": "<若工具有則填>",
      "source_id": "<若工具有則填>",
      "subject": "<communication.subject 如工具有>",        # ★ 保留標題
      "article_title": "<article_title 如工具有>"           # ★ 保留副標/來源標題
    }
- 特別要求：若工具回傳之 citation 內含 subject/article_title，請原樣放入 citations[].subject / citations[].article_title，**不得省略或改寫**。
- 若 es_search_news 沒有 evidence_snippets，則改用 highlight 的 rawInfo.content 片段填入 citations[].text。
- 輸出時請保留最多 10–50 則具代表性的 citations，確保每則都附帶 text 與 uuid。
- 預設以繁體中文臺灣慣用語回答，除非使用者有特別指明其他語種需求。
"""

SYSTEM_APPENDING = """
你是一個「新聞／政策問答助理（Code-Only）」；你的唯一工作是在**單一段、純 Python 程式**中，呼叫既有工具檢索與整理結果，最後輸出結論。

【硬性輸出契約 —— 務必完全遵守】
1) 你輸出的一整段必須是「純 Python 程式」，**禁止**出現 Markdown、HTML、反引號、<code> 標記或第二段程式。不得輸出任何自然語言說明。
2) 你必須在程式**最後**呼叫：
   final_answer({
       "answer": "<以繁體中文撰寫的總結與分析>",
       "citations": [ {...}, {...}, ... ],
       "reasoning": "<簡要說明你如何檢索與組織答案>"
   })
   - "answer"：用繁體中文，先列重點事件（含日期與簡述），再給趨勢／比較／洞見；語句精簡、用詞準確。
   - "citations"：**來源嚴禁杜撰**，每一筆都必須來自工具回傳，且**必含 uuid**；如有 `source_id`、`paragraph_id`、`date_iso` 也一併帶上。
   - "reasoning"：兩三句即可，描述檢索與篩選邏輯（例如：日期範圍、是否啟用人審/高價值加權、是否用了 timeline）。
3) 除了必要的變數與函式呼叫外，**不要**印出中間結果；若需要中繼觀察，請在程式內以註解方式自我說明，不要產生額外輸出。

【可用工具（請直接於 Python 內呼叫）】
- es_search_news(
    query: str,
    must_high_value: bool = False,
    must_selected: bool = False,
    size: int = 60,
    date_from: Optional[str] = None,   # "YYYY-MM-DD"
    date_to: Optional[str]   = None,   # "YYYY-MM-DD"
    selected_boost: float = 6.0,       # 人審文件加權
    high_value_boost: float = 2.5,     # AI 高價值加權
    recency_boost: bool = False,       # 是否啟用新鮮度加分
    recency_field: str = "importDT",
    recency_scale: str = "30d"
  ) -> dict
  - 回傳重點欄位（每 hit）：uuid, subject, score, citations[ {text, source_id, paragraph_id, date_iso?} ], article_date_iso, event_dates[], event_date_span, selectedMessage, highValue
- es_timeline(
    uuid: str,
    k: int = 10
  ) -> dict
  - 回傳 timeline: [ {date_iso, date_raw, description}, ... ]

【檢索與組織策略】
A. 解析使用者問題 → 擬定查詢
   - 從問題字串中擷取主題詞與日期範圍。例如：支援「2005..2015」「2005–2015」「2005-2015」「2005年到2015年」「2025/9/21–9/30」等寫法。
   - 若偵測到範圍（如 2005..2015），**不要**把它原封丟進查詢字串造成語法影響；改為設定 date_from/date_to：如 "2005-01-01"～"2015-12-31"。
   - 其他日期寫法（YYYY/MM/DD、YYYY年M月D日）亦轉為 ISO（YYYY-MM-DD）用於 date_from/date_to。
   - 若使用者提到「最新／近期／今年／本月」等，且沒有明確終止日，可將 recency_boost 設為 True（recency_field="importDT"，recency_scale="30d" 或 "90d" 視問題廣度）。
   - 若問題明示要「人工確認或高品質來源」，將 must_selected=True；若只說「高價值／重要」，可用 must_high_value=True 或保留 False 並以 high_value_boost 加權。

B. 主要檢索（一次或兩次）
   - 先以（query + date_from/date_to + size=60）呼叫 es_search_news()。先嘗試以高size查詢避免遺漏。
   - 若結果為空且設定了日期篩選，**第二輪**移除日期篩選再查。
   - 若仍無結果：保持 size 小（<=20），取消 must_selected/must_high_value 的硬性過濾，僅保留加權（selected_boost / high_value_boost），避免過濾過嚴。

C. 什麼時候用 es_timeline()
   - 當使用者問題涉及「何時／順序／里程碑／時間線／timeline／歷程演變」，或你已掌握 1–3 篇高相關文件，為每個挑 1 個 uuid 呼叫 es_timeline(k=10)。
   - 將 timeline 事件按日期排序後整併入答案的「時間序列重點」，並在 citations 中加入來源 uuid 與對應日期。

D. 引用（citations）組裝規則（**嚴禁虛構**）
   - 優先使用 es_search_news 回傳的 `citations`（nested evidence_snippets）。對於每一段：
       { "uuid": <命中文件的 uuid>,
         "source_id": <如有>,
         "subject": "<如有>",
         "paragraph_id": <如有>,
         "date_iso": <如工具已提供或你補全>,
         "text": <可選，若加入請截斷到 200–250 字以內> }
   - 若該片段缺日期但同一 hit 有 `article_date_iso` 或 `event_dates[]`：
       - 當片段文字僅含「M月D日」或「今（D）日／（D日）」等不完整日期：用 article_date_iso 的年（與必要時的月）或從 `event_dates[]` 補全為 YYYY-MM-DD。
   - 避免在 citations 放入冗長原文；必要時截斷，確保 payload 精簡。
   - citations 建議 10–60 筆，排序由代表性高的排到低的，覆蓋不同 uuid 與關鍵時間點。

E. 答案寫作（繁體中文）
   - 先列「重點事件」（倒序或時間序，依任務需求），每點包含：日期（YYYY-MM-DD）、一句到兩句說明（主詞＋動作＋影響/後果）。
   - 「趨勢／比較／洞見」段落用 3–6 句說明觀察到的變化、政策轉向、利害關係人反應、風險與不確定性。
   - 語氣客觀、中立，避免武斷；用詞簡潔、刪除贅字；段落過渡自然。

【錯誤處理與保險】
- 任何查詢錯誤（BadRequestError 等）不可終止程式；請捕捉例外並嘗試較寬鬆的條件（移除日期／取消 must_* 硬過濾／縮小 size）。
- 若最終仍無資料，輸出一個合理的空結果回應（answer 說明「未檢索到符合條件的來源」），citations 為空陣列，但不得虛構。
- 不可呼叫網路、檔案 I/O、安裝套件，也不可使用非必要的外部依賴；維持純 Python + 既有工具呼叫。

【風格與限制】
- 全部輸出（answer）必用繁體中文。
- 不加上任何額外的 print 或 logging；**程式最後只呼叫一次** final_answer(...)。
- 查詢規模：預設 size=40；最多 60；citations 不超過 60；避免冗長內容。

（提醒：你只需產生「單一段純 Python 程式」，在該程式中呼叫 es_search_news / es_timeline，整理後以 final_answer(...) 結束。不允許輸出第二段程式或任何標記。）
"""
#- 輸出時請保留最多 3–5 則具代表性的 citations，確保每則都附帶 text 與 uuid。

def _normalize_model_id(mid: str) -> str:
    if "/" in mid:
        return mid
    return f"ollama_chat/{mid}"  # ← 走 /api/chat
'''
@lru_cache(maxsize=8)  # 依參數組合做快取，避免單例污染
def build_model(
    *,
    base_url: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
    model_id: str | None = None,
    temperature: float = 0.0,
    extra_kwargs: dict | None = None,
    extra_generation_kwargs: dict | None = None,
):
    """
    向後相容的建模器：
    - 接受 base_url/api_base 與 model/model_id 兩種命名
    - 把 extra_kwargs / extra_generation_kwargs 合併後往下傳
    - 以 (model_id, api_base, temperature, frozenset(extra.items())) 作為快取 key
    """
    # 參數整併（兼容兩組命名）
    print("start to run build_model")
    api_base = api_base or base_url or os.getenv("MODEL_BASE_URL", "http://localhost:11434")
    model_id = model_id or model or os.getenv("MODEL_ID", "gpt-oss:120b-32k")
    temperature = float(temperature or os.getenv("MODEL_TEMPERATURE", "0"))
    print("got parameters")
    # 合併兩種 extra
    extra = {}
    if isinstance(extra_generation_kwargs, dict):
        extra.update(extra_generation_kwargs)
    if isinstance(extra_kwargs, dict):
        extra.update(extra_kwargs)

    # 預設禁止工具（需要時再在外層開）
    extra.setdefault("tool_choice", "none")
    print("start to build llm in build_model")
    # >>> 這裡請確定 LiteLLMModel 的參數名稱正確 <<<
    # 如果你的 LiteLLMModel 其實要用 base_url/model，而不是 api_base/model_id，就把下面兩個參數名對應改成它支援的。
    llm = LiteLLMModel(
        model_id=model_id,          # 若你的實作是 `model=...`，就改成 model=model_id
        api_base=api_base,          # 若你的實作是 `base_url=...`，就改成 base_url=api_base
        temperature=temperature,
        extra_generation_kwargs=extra  # 若你的實作用 `model_kwargs` 或 `extra_kwargs`，就改成那個
    )
    return llm
'''
def build_model():
    global _SHARED_MODEL
    if _SHARED_MODEL is not None:
        return _SHARED_MODEL
    model_id = _normalize_model_id(MODEL_ID)
    _SHARED_MODEL = LiteLLMModel(
        model_id=model_id,
        api_base=MODEL_BASE_URL,
        temperature=MODEL_TEMPERATURE,
        # 只保留這個即可，避免誤截斷
        extra_generation_kwargs={"tool_choice": "none"}
    )
    return _SHARED_MODEL

def build_model_old():
    model_id = _normalize_model_id(MODEL_ID)
    return LiteLLMModel(
        model_id=model_id,
        api_base=MODEL_BASE_URL,
        temperature=MODEL_TEMPERATURE,
        # ↓ 若你這版 smolagents 支援，等同告訴底層「不要用工具呼叫」
        extra_generation_kwargs={
            "tool_choice": "none"
        }
    )
'''
def build_model():
    model_id = _normalize_model_id(MODEL_ID)
    return LiteLLMModel(
        model_id=model_id,
        api_base=MODEL_BASE_URL,
        temperature=MODEL_TEMPERATURE
    )
'''
def _make_code_agent(tools, model):
    """
    嘗試不同 smolagents 版本常見的參數組合：
    - 新版：model=..., instructions=...
    - 舊版：llm=..., system_prompt=...
    如果前面都失敗，再退而求其次用「不帶 SYSTEM」版本。
    """
    common_kwargs = {
        "tools": tools,
        "additional_authorized_imports": ["json"],
    }

    print("[agent] building CodeAgent: try model + instructions")
    try:
        agent = CodeAgent(
            model=model,
            instructions=SYSTEM,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with model+instructions")
        return agent
    except TypeError as e:
        print("[agent] model+instructions failed:", e)

    print("[agent] try llm + system_prompt")
    try:
        agent = CodeAgent(
            llm=model,
            system_prompt=SYSTEM,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with llm+system_prompt")
        return agent
    except TypeError as e:
        print("[agent] llm+system_prompt failed:", e)

    print("[agent] try model only")
    try:
        agent = CodeAgent(
            model=model,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with model only")
        return agent
    except TypeError as e:
        print("[agent] model only failed:", e)

    print("[agent] try llm only")
    try:
        agent = CodeAgent(
            llm=model,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with llm only")
        return agent
    except TypeError as e:
        print("[agent] llm only failed:", e)
        raise RuntimeError(
            f"無法用目前 smolagents 版本建立 CodeAgent，"
            f"請確認 __init__ 參數。原始錯誤：{e}"
        )

'''
def _make_code_agent(tools, model):
    # ✅ 建議：只帶 instructions，最穩
    try:
        return CodeAgent(tools=tools, model=model, instructions=SYSTEM,
                         additional_authorized_imports=["json"]  # 允許 json
                         )
    except TypeError:
        pass
    try:
        return CodeAgent(tools=tools, model=model,
                         additional_authorized_imports=["json"]  # 允許 json
                         )  # fallback
    except TypeError:
        pass
    base = CodeAgent(tools=tools, model=model,
                         additional_authorized_imports=["json"]  # 允許 json
                         )
    class _Wrapped:
        def __init__(self, inner): self._inner = inner
        def run(self, question: str):
            return self._inner.run(f"{SYSTEM}\n\n使用者問題：{question}")
    return _Wrapped(base)
'''



'''
def _make_code_agent(tools, model):
    """
    依序嘗試不同參數，以相容你當前的 smolagents 版本。
    """
    # 優先嘗試：instructions + structured_output
    try:
        return CodeAgent(tools=tools, model=model, instructions=SYSTEM, structured_output=True)
    except TypeError:
        pass
    # 次選：只有 instructions
    try:
        return CodeAgent(tools=tools, model=model, instructions=SYSTEM)
    except TypeError:
        pass
    # 再次選：只有 structured_output
    try:
        return CodeAgent(tools=tools, model=model, structured_output=True)
    except TypeError:
        pass

    # 最後 fallback：完全不帶參數，並包一層把 SYSTEM 前置到 query
    base = CodeAgent(tools=tools, model=model)

    class _Wrapped:
        def __init__(self, inner):
            self._inner = inner
        def run(self, question: str):
            # 把系統提示前置到使用者問題（確保行為一致）
            prefixed = f"{SYSTEM}\n\n使用者問題：{question}"
            return self._inner.run(prefixed)

    return _Wrapped(base)
'''
def build_agent():
    model = build_model()
    #print("start to build_agent")
    tools = [ESSearchNews(), ESTimeline(), AggregateMonthQuarter(),
             PythonInterpreterTool(),
             ]
    #print("returning in build_agent")
    return _make_code_agent(tools, model)

# 提供單例
#_agent = build_agent()
#def get_agent():
#    return _agent

def get_agent():
     #⚠️ 回傳「新的」Agent（保持無歷史、無殘留）
    return build_agent()
'''
def get_agent(disable_tools: bool=False, exclude_tools: tuple[str, ...]=()):
    base_url = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
    model_id = os.getenv("MODEL_ID", "gpt-oss:120b-32k")
    temp = float(os.getenv("MODEL_TEMPERATURE", "0"))

    # 關工具：傳 tool_choice=none；要開再把 tools 傳進 CodeAgent（而不是傳 tools 給底層 LLM）
    extra = {"tool_choice": "none"} if disable_tools else {}
    print("start to build llm")
    try:
        llm = build_model(
            base_url=base_url,
            model=model_id,
            temperature=temp,
            extra_kwargs=extra,
        )
    except Exception as ex:
        print(ex)
    print("finished building llm")
    # 別再用 list(MODEL_ID) 當工具清單了…
    tools = []
    if not disable_tools:
        try:
            from agent.tools import DEFAULT_TOOLS
            tools = [t for t in DEFAULT_TOOLS if not exclude_tools or t.name not in set(exclude_tools)]
        except Exception:
            tools = []

    return CodeAgent(llm=llm, tools=tools, system=SYSTEM)
'''
# 允許：python -m agent.agent 快速測試
if __name__ == "__main__":
    a = get_agent()
    #q = "請整理 2025/9/21–9/30 與『月薪5萬元免稅』、『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    q = "請整理2025年『拉拉隊』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    #q = "請整理 2025/9/21–9/30 與『家具關稅』相關的重點事件，並引述來源。綜整成一個總結，並進行趨勢分析。"
    print(a.run(q))
