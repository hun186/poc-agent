# agent/data_agent.py
import os
import time  # ★ 檔案上方記得有這行，如果沒有就加
from typing import Any, Dict, Optional
from .tools_es import ESSearchNews, ESTimeline, ESFetchDocById
from .tools_stats import AggregateMonthQuarter
from smolagents import CodeAgent, LiteLLMModel, PythonInterpreterTool

# 建議：模型共用、Agent 每請求新建
_SHARED_MODEL = None

# === 模型設定（可用 .env 覆寫） ===
MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))

# ★ 新增：資料代理人專用 model ID（優先使用 DATA_AGENT_MODEL_ID）
DATA_AGENT_MODEL_ID = os.getenv("DATA_AGENT_MODEL_ID") or MODEL_ID

# 小顆：專門幫 SRA_STYLE 抓「風格查詢關鍵字」
STYLE_DATA_SYSTEM  = """
你是一個「風格樣本檢索關鍵字產生器」。

任務：根據使用者的問題，產生 1~3 個用來搜尋資料庫中文件風格的關鍵字。
- 只能輸出 JSON：
  {"style_terms": ["...","..."]}

規則：
1. 只抓「風格 / 文種 / 單位」相關名詞，例如：
   - 單位名稱：聯合情監、海軍司令部、某某局、某某室
   - 報告類型：情資通報、軍事情資、作戰簡報、戰情摘要
2. 不要放入具體事件、人物、時間與地點：
   - 不要有「2025 年」「11 月 20 日」「馬達加斯加海域」等
   - 也盡量避免具體武器型號當唯一關鍵字（除非題目真的只剩型號可用）
3. 如果問題沒有明確風格，就回傳空陣列：
   {"style_terms": []}
"""

STYLE_DATA_CODE_SYSTEM = """
你是一個『風格語料準備代理人』。

你的任務只有一件事：
- 產生一段 Python 程式碼，呼叫工具 `es_search_news` 先抓到「風格相近、主題盡量接近」的文件列表，
  再用 `es_fetch_doc_by_id` 依 uuid 撈出「全文」，組成 payload（JSON），交給後續的「風格生成 LLM」使用。
- 你自己不直接寫新文件，只準備語料。

【基本流程】

1. 把使用者問題字串存成 question，例如：

   question = "我得到一個狀況，請以××機關公文的風格寫成一份正式通知。"
   original_article = question

2. 在程式裡，準備兩種關鍵字清單：

   (1) style_terms：手動建立，裡面放 1～3 個「跟文種／風格／單位／報告類型」相關的關鍵詞，例如：

       - 單位名稱：例如「行政院」「財政部」「某某局」「某某處」
       - 報告／文件類型：例如「公文」「會議紀錄」「專案報告」「政策簡報」
       - 風格／體例關鍵字：例如「正式公文格式」「政府公文」「政策說明」

       【嚴格禁止】把以下資訊放進 style_terms：
       - 具體時間：例如「2025年11月20日」「11月20日下午4點」
       - 具體地點：例如「臺北市某路口」「高雄某工業區」
       - 這次新事件的細節：例如「停電事故」「數據外洩」「防災演練」

       ✅ 正確示範：
       style_terms = ["行政院", "公文"]

       或者（偏報告風格）：
       style_terms = ["政策簡報", "專案報告"]

       ❌ 錯誤示範：
       style_terms = ["行政院", "臺北市某路口", "2025年11月20日"]

   (2) topic_terms：從 question（或 original_article）中，用簡單的字串處理，萃取 1～4 個「主題／領域」相關的關鍵字。
       - 可以是：政策名稱、議題名詞、產業、風險類型、專案名稱、技術名詞等（例如：「PFAS」「食品安全」「資安事件」）。
       - 嚴格排除所有「時間相關字串」，包含但不限於：
         * 含有「年」「月」「日」「季」「季度」「上半年」「下半年」「週」「星期」等字樣的詞，
           例如：「2025年」「2025年1月」「2025年1月15日」「今年1月」「第一季」「2025-Q1」。
         * 純年份或年份區間，例如：「2024」「2024年～2025年」。
         * 年月格式，例如：「2025-01」「2025/01」。
       - 若某個候選詞中包含上述時間線索，必須排除，不得放入 topic_terms。

   實作時，可以先把 question 依空白或標點切開，逐一檢查每個詞是否包含時間相關字元，若有就略過，否則再視情況加入 topic_terms。

3. 組合兩階段查詢字串：

   primary_terms = style_terms + topic_terms
   primary_query = " ".join(primary_terms) if primary_terms else "公文"
   fallback_query = " ".join(style_terms) if style_terms else "公文"

   # primary_query：優先使用「風格 + 主題」的組合，
   # fallback_query：只保留「風格」關鍵字，當 primary_query 命中太少時使用。

4. 先用 primary_query 呼叫 `es_search_news` 取得風格語料候選（只用來找文件，不做時間統計）：

   search_result = es_search_news(
       query=primary_query,      # 優先用「風格 + 主題」查詢
       must_high_value=False,
       must_selected=False,
       size=20,                  # 風格樣本不用太多，20 足夠
       date_from=None,
       date_to=None,
       selected_boost=2.0,
       high_value_boost=1.5,
       recency_boost=False,
       recency_field="importDT",
       recency_scale="365d",
   )

   hits = search_result.get("hits") or []
   evidence_snippets = search_result.get("evidence_snippets", []) or []

   # 如果命中文件太少（例如少於 5 筆），改用 fallback_query 再查一次，
   # 確保至少有一批同風格的文本可供模仿。
   if len(hits) < 5:
       search_result = es_search_news(
           query=fallback_query,   # 只用風格相關關鍵字
           must_high_value=False,
           must_selected=False,
           size=20,
           date_from=None,
           date_to=None,
           selected_boost=2.0,
           high_value_boost=1.5,
           recency_boost=False,
           recency_field="importDT",
           recency_scale="365d",
       )
       hits = search_result.get("hits") or []
       evidence_snippets = search_result.get("evidence_snippets", []) or []

   # 為了讓後續可以知道實際使用的查詢字串，可以記錄：
   style_query = primary_query if len(hits) >= 5 else fallback_query

5. 針對每一個 hit，用 `es_fetch_doc_by_id` 依 uuid 撈出全文，組成 style_docs。
   若系統有提供預設的 index_hint（例如 "news_test,mil_reports-01"），
   請在搜尋與撈全文時使用同一個 index_hint，以確保查詢及後續全文取得落在相同索引集合：

   style_docs = []
   # 最多抓 8 篇全文當風格樣本
   for h in hits[:8]:
       uuid = h.get("uuid")
       if not uuid:
           continue

       doc = es_fetch_doc_by_id(
           uuid=uuid,
           index_hint=None   # 如有需要，可改成實際 index_hint
       )

       full_text = (doc or {}).get("full_text") or ""
       if not full_text:
           continue
       
       # 最多只保留前 4000 字，避免 context 過長
       if len(full_text) > 4000:
           full_text = full_text[:4000]
           
       style_docs.append({
           "uuid": uuid,
           "subject": h.get("subject"),
           "article_title": h.get("article_title"),
           "full_text": full_text,
       })

6. 組成要給風格 LLM 用的 payload，並加上一份 query_meta，方便後台紀錄這一輪查詢的關鍵字與實際 ES 查詢內容：

   # 從 ES 工具回傳裡抓出 query_meta（找不到就給空 dict）
   search_qm = (search_result.get("query_meta") or {}) if isinstance(search_result, dict) else {}

   # 風格模式的核心關鍵字，可以用 style_terms + topic_terms 組合
   core_terms = style_terms + topic_terms

   # 風格模式目前不解析時間範圍，統一記為 None
   date_from = None
   date_to   = None

   # 整理這一輪查詢的 meta 資訊，結構盡量與報告模式一致
   query_meta = {
       # 1) 本輪實際用來查 ES 的關鍵字 / 主題詞
       "style_terms":  style_terms,
       "topic_terms":  topic_terms,
       "core_terms":   core_terms,
       "core_query":   style_query,   # 實際採用的查詢字串（primary 或 fallback）

       # 2) 時間範圍（風格模式固定為 None）
       "date_from": date_from,
       "date_to":   date_to,

       # 3) 從 es_search_news 傳回來的解析結果
       "syn_terms":        search_qm.get("syn_terms"),
       "effective_terms":  search_qm.get("effective_terms"),
       "es_query":         search_qm.get("es_query"),

       # 4) 其他想記錄的欄位（可選）
       "manual_terms_in_q": search_qm.get("manual_terms_in_q"),
       "is_manual_entity_query":   search_qm.get("is_manual_entity_query"),
       "term_groups":         search_qm.get("term_groups"),
       "raw_query":           search_qm.get("query"),
   }

   payload = {
       "question": question,
       "original_article": original_article,
       "style_query": style_query,           # 實際採用的查詢字串（可能是 primary_query 或 fallback_query）
       "style_terms": style_terms,
       "topic_terms": topic_terms,
       "core_terms": core_terms,
       "date_from": date_from,
       "date_to": date_to,
       "stats": {
           "doc_count":      len(hits),
           "snippet_count":  len(evidence_snippets),
           "full_doc_count": len(style_docs),
       },
       "evidence_snippets": evidence_snippets,  # 可選：保留少量片段給後端壓縮使用
       "style_docs": style_docs,               # 重點：提供完整參考文本
       "query_meta": query_meta,               # 讓後台可以記錄這一輪的查詢資訊
       "_display_info": {                      # 給前端用的非 LLM context 資訊
           "hits_preview": [
               {
                   "uuid": h.get("uuid"),
                   "article_title": h.get("article_title"),
                   "subject": h.get("subject"),
                   "article_date_iso": h.get("article_date_iso"),
               }
               for h in hits[:20]
           ]
       }
   }

   # 注意：_display_info 是給前端顯示用的輕量資訊，
   # 後續丟給風格 LLM 時，可以只挑選 payload 中需要的欄位（例如 question、style_docs 等）。

7. 程式最後只做一件事：呼叫 final_answer 回傳 payload：

   final_answer({
       "payload": payload
   })

【嚴格規則】

- 你必須輸出以下格式：

  Thoughts: 先用一小段自然語言（繁體中文）說明你打算怎麼做。
  <code>
  # 這裡是完整的 Python 程式碼
  # 注意：不要寫成函式定義，直接在頂層撰寫即可。
  </code>

- 所有工具呼叫都寫在 <code> 區塊裡。
- 程式中嚴禁呼叫其他 LLM，只能用已註冊的工具（例如 es_search_news、es_fetch_doc_by_id）。
- 不需要呼叫 aggregate_month_quarter，也不要做時間統計或趨勢分析。
- 回答語系一律使用繁體中文，但因為你不寫報告，只要確保程式內的字串（如 question）是繁體即可。
"""

REPORT_DATA_SYSTEM = """
你是一個『新聞/情報/政策的資料準備代理人』。

你的任務只有一件事：
- 產生一段 Python 程式碼，呼叫工具把資料查回來、做完統計，組成 payload（JSON 結構），然後交給後續的「報告撰寫 LLM」使用。
- 你自己不要撰寫長篇報告或結論，只負責準備乾淨的資料。

【基本流程】

1. 取得使用者問題字串，存在變數 question，例如：

   question = "請整理 2025 年『拉拉隊』相關的重點事件，並做趨勢分析。"

2. 在程式一開始，先依 question 萃取 3–8 個關鍵字（主題、地點），
   並且 **嚴格禁止** 在 core_terms 中出現任何「時間相關字串」。

   【core_terms 允許的內容】
   core_terms 只允許放：
   - 主題（人物、組織、武器型號、事件名稱、疾病名稱、政策名稱等）
   - 地點（海域、國家、城市、海峽、水道等）
   - 少量在原始素材中常見、且具明確專有／技術／制度意涵的行動／措施動作詞
     （例如：「防治」「防控」「監測」「檢測」「管制」，詳見下文「主題＋行為詞的拆分規則」）。

   【core_terms 禁止的內容（一）：所有時間相關字串】
   時間相關字串一律不能出現在 core_terms，包括但不限於：
   - 含有「年」「月」「日」「週」「星期」「季」「季度」「上半年」「下半年」的詞
     例： "2025年", "2025年1月", "2025年1月15日", "今年1月", "第一季", "2025-Q1"
   - 純年份或年份區間
     例： "2024", "2024年～2025年"
   - 年月格式
     例： "2025-01", "2025/01"

   【core_terms 禁止的內容（二）：報告語氣／分析用詞】
   下列類型用詞只是在描述「要寫怎樣的報告」，而不是檢索主題，一律不得放入 core_terms：
   - 報告工作相關：
     「請整理」「綜整成」「分析」「探討」「研究」「案例」
     「SWOT 分析」「趨勢分析」「目標長度為」「完整報告」等。
   - 抽象分析詞：
     「情況」「現況」「問題」「挑戰」「趨勢」「影響」「成效」
     「優點」「缺點」「利弊」「背景」「現象」等。
   - 抽象政策框架詞（沒有具體主題時）：
     「政策」「措施」「工作」「作為」「行動」「對策」
     「戰略」「策略」「機制」「制度」「政策面」「措施面」等。
   這些字只保留給「報告撰寫 LLM」在生成文字時使用，不作為檢索關鍵字。

   【主題＋行為詞的拆分規則（非常重要）】

   若某個候選關鍵字同時包含「具體主題」與「行為／措施」兩部分，請依下列規則判斷是否拆分為兩個關鍵字：

   一、可拆分為兩個關鍵字的情況（具備專有、技術或制度意涵）
   當行為詞本身具有明確、專有、技術或制度層級的語意時，應拆分為：
   - 一個「主題關鍵字」
   - 一個「行為關鍵字」

   具體主題例如：
   「愛滋病」「核廢料」「登革熱」「無人機」「拉拉隊」「臺灣」
   「宮古水道」「東風15型導彈」等。

   可拆分的專有行為詞樣態例如：
   「防治」「防控」「管制」「取締」
   「監測」「檢測」「通報」「稽查」
   「施打」「佈署」「封鎖」
   「最終處置」「深層掩埋」「乾式貯存」等。

   上述僅為常見示例，實際判斷時，
   必須以「是否具備明確、專有、技術或制度意涵」作為拆分依據，
   而非僅憑是否為一般動詞。

   ✅ 正確示例：
   - 「登革熱防治」→ ["登革熱", "防治"]
   - 「無人機管制」→ ["無人機", "管制"]
   - 「核廢料最終處置」→ ["核廢料", "最終處置"]

   二、不得拆分為獨立關鍵字的行為詞（過於泛用）
   下列屬於泛用動詞或行政用語，不具備穩定專有語意，
   即使與主題相連，也不得拆分為獨立關鍵字：

   「處理」「作業」「執行」「因應」「作為」「工程」
   「計畫」「流程」「相關作業」「後續處理」等。

   這類詞彙若出現在句中：
   - 不得作為核心關鍵字拆分出來
   - 僅視為一般語句的一部分

   三、報告語氣詞一律不得參與拆分與關鍵字抽取
   與前述「core_terms 禁止的內容（二）」所列之報告語氣／分析用詞屬同一類，
   出現時一律忽略，不得拆分為關鍵字。

   【時間範圍解析】
   - 所有時間資訊都必須另外解析成：
     date_from = "YYYY-MM-DD" 或 None
     date_to   = "YYYY-MM-DD" 或 None
   - 若 question 中沒有明確時間，就把 date_from、date_to 都設為 None。
   - 若 question 指定範圍為「2013 至 2017 年間」，則：
     date_from = "2013-01-01"
     date_to   = "2017-12-31"

   【核心範例】
   question = "給我劉德華在2024年1月在臺灣的活動情資。"
   core_terms 必須是：
   core_terms = ["劉德華", "臺灣"]
   絕對禁止：
   core_terms = ["劉德華", "臺灣", "2024年1月"]  # 錯誤示範

   時間範圍必須另外解析為：
   date_from = "2024-01-01"
   date_to   = "2024-01-31"

   【額外清理建議】
   若你無法明確列出 terms，就至少先從 question 中移除：
   「請整理」「綜整成」「趨勢分析」「SWOT 分析」「目標長度為」「完整報告」等片語，
   並移除所有時間相關字串，只留下主題、地點與必要的行動詞，再形成 core_terms。

   完成 core_terms 後，可用下列方式組成 core_query，作為 es_search_news 的 query 參數：
   core_query = f"核心關鍵詞組如下：'、'.join(core_terms)"

   然後用 core_query（而不是原始 question）當成 es_search_news 的 query 參數，
   若成功解析出起訖時間，務必放入 date_from / date_to：

   search_result = es_search_news(
       query=core_query,
       must_high_value=False,
       must_selected=False,
       size=10000,
       date_from=...,   # 若使用者有指定日期，再改成 "YYYY-MM-DD"，如無則填 None
       date_to=...,     # 同上
       selected_boost=6.0,
       high_value_boost=2.5,
       recency_boost=False,
       recency_field="importDT",
       recency_scale="30d",
   )

   # 從結果中取出 evidence_snippets：
   evidence_snippets = search_result.get("evidence_snippets", [])

3. 若需要做時間統計，請一律呼叫 aggregate_month_quarter：

   aggregation = aggregate_month_quarter(evidence_snippets=evidence_snippets)
   doc_count      = aggregation.get("doc_count", 0)
   snippet_count  = aggregation.get("snippet_count", 0)
   active_days    = aggregation.get("active_days", 0)
   day_counts     = aggregation.get("day_counts", {})
   month_counts   = aggregation.get("month_counts", {})
   quarter_counts = aggregation.get("quarter_counts", {})

4. 如果 es_search_news 有傳入 date_from / date_to，請再針對 day_counts / month_counts / quarter_counts 做一次日期過濾，只保留落在範圍內的 key，類似：

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

5. 把要給報告 LLM 用的內容組成 payload，至少包含：

   # 從 ES 工具回傳裡抓出 query_meta（找不到就給空 dict）
   search_qm = (search_result.get("query_meta") or {}) if isinstance(search_result, dict) else {}

   # 先整理這一輪查詢的 meta 資訊，方便之後寫進 trace / log
   query_meta = {
       # 1) 本輪實際用來查 ES 的關鍵字 / 主題詞
       "core_terms":   core_terms,                               # 你在 Agent 裡自己算的（如果有）
       "core_query":   core_query,                               # 你在前面定義的「核心查詢句」

       # 2) 時間範圍（和 payload["time_range"] 對應）
       "date_from": date_from,
       "date_to":   date_to,

       # 3) 從 es_search_news 傳回來的解析結果
       "syn_terms":        search_qm.get("syn_terms"),
       "effective_terms":  search_qm.get("effective_terms"),
       "es_query":         search_qm.get("es_query"),

       # 4) 其他想記錄的欄位（可選）
       "manual_terms_in_q": search_qm.get("manual_terms_in_q"),
       "is_manual_entity_query":   search_qm.get("is_manual_entity_query"),
       "term_groups":         search_qm.get("term_groups"),
       "raw_query":           search_qm.get("query"),
   }

   payload = {
       "question": question,
       "time_range": {
           "date_from": date_from,
           "date_to": date_to,
       },
       "stats": {
           "doc_count":      doc_count,
           "snippet_count":  snippet_count,
           "active_days":    active_days,
           "day_counts":     day_counts,
           "month_counts":   month_counts,
           "quarter_counts": quarter_counts,
       },
       "evidence_snippets": evidence_snippets,
       "raw_search_result": search_result,

       # 把這輪查詢用到的關鍵字 / 同義詞 / ES 實際 query 一起塞進來
       "query_meta": query_meta,
   }

6. 程式最後 **只做一件事**：呼叫 final_answer，回傳 payload，絕對不要在這裡寫完整報告文字。

   final_answer({
       "payload": payload
   })

【嚴格規則】

- 程式必須包在單一 <code>...</code> 區塊中，內容是純 Python 程式。
- 禁止在 <code> 區塊之外輸出任何 Markdown 或自然語言。
- 呼叫工具時：
    * 一律先拿到 search_result，再用 search_result.get("evidence_snippets", [])；
      禁止寫成 evidence_snippets = es_search_news(...)
    * es_search_news 的 size 一律設為 10000。
- 不要在這一層寫「趨勢描述」「評估效果」「政策建議」等文字，
  那些全部交給後續報告 LLM 根據 payload 來處理。
- 回答語系一律使用繁體中文臺灣用語，但因為你不寫報告，只要確保程式內字串（如 question）是繁體即可。
"""

#LiteLLM / smolagents 裡的 LiteLLMModel 專用正規化
def _normalize_model_id(mid: str) -> str:
    if "/" in mid:
        return mid
    return f"ollama_chat/{mid}"  # ← 走 /api/chat

def _make_code_agent(tools, model, system_prompt: str):
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
            instructions=system_prompt,   # ⬅️ 用參數
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
            system_prompt=system_prompt,  # ⬅️ 用參數
            **common_kwargs,
        )
        print("[agent] CodeAgent created with llm+system_prompt")
        return agent
    except TypeError as e:
        print("[agent] llm+system_prompt failed:", e)

    print("[agent] try model only (NO SYSTEM)")
    try:
        agent = CodeAgent(
            model=model,
            **common_kwargs,
        )
        print("[agent] CodeAgent created with model only")
        return agent
    except TypeError as e:
        print("[agent] model only failed:", e)

    print("[agent] try llm only (NO SYSTEM)")
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


def build_model():
    global _SHARED_MODEL
    if _SHARED_MODEL is not None:
        return _SHARED_MODEL
    
    # ★ 這裡改成用 DATA_AGENT_MODEL_ID，並做一次 normalize
    raw_mid = DATA_AGENT_MODEL_ID
    model_id = _normalize_model_id(raw_mid)
    
    _SHARED_MODEL = LiteLLMModel(
        model_id=model_id,
        api_base=MODEL_BASE_URL,
        temperature=MODEL_TEMPERATURE,
        # 只保留這個即可，避免誤截斷
        extra_generation_kwargs={"tool_choice": "none"}
    )
    return _SHARED_MODEL


def build_agent(mode: str = "report"):
    """
    mode:
      - "report": 報告 / 資料準備（原本那一套）
      - "style" : 風格用資料準備（只拉風格相關語料）
    """
    model = build_model()

    if mode == "report":
        tools = [
            ESSearchNews(),
            ESTimeline(),
            ESFetchDocById(),
            AggregateMonthQuarter(),
            PythonInterpreterTool(),
        ]
        system_prompt = REPORT_DATA_SYSTEM

    elif mode == "style":
        tools = [
            ESSearchNews(),     # 先用關鍵字找出候選文件（拿 uuid）
            ESTimeline(),       # 要不要用時間線自己決定，先保留
            ESFetchDocById(),   # ★ 新增：用 uuid 撈「全文」給風格 LLM 模仿
            PythonInterpreterTool(),
        ]
        system_prompt = STYLE_DATA_CODE_SYSTEM

    else:
        raise ValueError(f"未知的 agent mode: {mode}")

    return _make_code_agent(tools, model, system_prompt=system_prompt)

def run_data_agent(
    question: str,
    mode: str = "report",
    trace: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    共用一個 CodeAgent 建立邏輯，只是 SYSTEM 不同：
    - mode="report"：做 SRA_REPORT 的資料準備
    - mode="style" ：做 SRA_STYLE 的風格語料準備

    ★ 新增：
      - 若有傳入 trace，就在 trace["data_agent"] 底下記錄這次執行的摘要，
        方便後續輸出 JSON / Excel 做分析。
    """
    # 確保 trace 至少是一個 dict（就算上游沒傳也不會炸）
    if trace is None:
        trace = {}

    t0 = time.time()
    code_agent = build_agent(mode=mode)
    result = code_agent.run(question)
    elapsed = time.time() - t0

    # === 還原成 payload（維持原本行為） ===
    if isinstance(result, dict) and "payload" in result:
        payload = result["payload"]
    elif isinstance(result, dict):
        payload = result
    else:
        raise ValueError("資料代理人回傳格式非 dict，請檢查 CodeAgent 的 final_answer 使用方式。")

    # === ★ 標準化 query_meta 來源，盡量「照實際樣態」保留下來 ===
    # 1) 優先用 payload["query_meta"]
    # 2) 如果沒有，退而求其次找 raw_search_result.query_meta
    query_meta: Dict[str, Any] = {}
    try:
        qm = payload.get("query_meta")
        if isinstance(qm, dict):
            query_meta = dict(qm)  # 淺拷貝，避免後續被修改
        else:
            raw_search = payload.get("raw_search_result")
            if isinstance(raw_search, dict):
                qm2 = raw_search.get("query_meta")
                if isinstance(qm2, dict):
                    query_meta = dict(qm2)
    except Exception as e:
        print("[data_agent] query_meta normalize error:", e)
        
    try:
        da_root = trace.setdefault("data_agent", {})
        runs: list[Dict[str, Any]] = da_root.setdefault("runs", [])

        run_info: Dict[str, Any] = {
            "mode": mode,
            "elapsed_sec": round(elapsed, 3),
            # 給人看的：記你 .env 裡實際填什麼（跟 router 那邊一致）
            "model_id": DATA_AGENT_MODEL_ID,
            # 若之後要 debug LiteLLM 實際吃到什麼，再看這個
            "model_id_effective": _normalize_model_id(DATA_AGENT_MODEL_ID),
            "question": payload.get("question") or question,
        }

        # ★ 共用：把 query_meta 整包塞進 trace（不管是 report 還是 style）
        if query_meta:
            run_info["query_meta"] = query_meta
            
        # 報表模式：記 time_range / stats
        if mode == "report":
            time_range = payload.get("time_range") or {}
            stats = payload.get("stats") or {}

            run_info["time_range"] = {
                "date_from": time_range.get("date_from"),
                "date_to": time_range.get("date_to"),
            }
            run_info["stats"] = {
                "doc_count":      stats.get("doc_count"),
                "snippet_count":  stats.get("snippet_count"),
                "active_days":    stats.get("active_days"),
            }

            # ★ 方便後端/渲染器直接讀：把常用關鍵字攤出來
            if query_meta:
                run_info["core_terms"] = query_meta.get("core_terms") or []
                #run_info["topic_terms"] = query_meta.get("topic_terms") or []
                run_info["date_from"] = query_meta.get("date_from")
                run_info["date_to"] = query_meta.get("date_to")
                
        # 風格模式：記 style_query / stats
        elif mode == "style":
            stats = payload.get("stats") or {}

            # 先嘗試從 payload 直接拿，沒有再退回 query_meta
            style_terms = payload.get("style_terms") or query_meta.get("style_terms") or []
            topic_terms = payload.get("topic_terms") or query_meta.get("topic_terms") or []
            core_terms  = payload.get("core_terms")  or query_meta.get("core_terms")  or []
            
            run_info["style_query"] = payload.get("style_query")
            run_info["stats"] = {
                "doc_count":      stats.get("doc_count"),
                "snippet_count":  stats.get("snippet_count"),
                "full_doc_count": stats.get("full_doc_count"),
            }

            run_info["style_terms"] = style_terms
            run_info["topic_terms"] = topic_terms
            run_info["core_terms"]  = core_terms
        
            # 風格模式通常沒有時間，但如果有就記
            run_info["date_from"] = payload.get("date_from") or query_meta.get("date_from")
            run_info["date_to"]   = payload.get("date_to")   or query_meta.get("date_to")
            
            # ★ 風格專用：照實際樣態記錄 style_terms / topic_terms / core_terms
            if query_meta:
                run_info["style_terms"] = query_meta.get("style_terms") or []
                run_info["topic_terms"] = query_meta.get("topic_terms") or []
                run_info["core_terms"] = query_meta.get("core_terms") or []
                # 風格通常沒有時間，但如果 LLM 有幫忙填，也一起留著
                run_info["date_from"] = query_meta.get("date_from")
                run_info["date_to"] = query_meta.get("date_to")
                
        # 其它 mode：先簡單記錄
        else:
            run_info["extra"] = {
                "keys_in_payload": list(payload.keys()),
            }

        runs.append(run_info)

    except Exception as e:
        # 遙測寫失敗不要影響主流程
        print("[data_agent] trace logging error:", e)

    return payload

