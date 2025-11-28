# agent/data_agent.py
import os
from typing import Any, Dict
from .tools_es import ESSearchNews, ESTimeline, ESFetchDocById
from .tools_stats import AggregateMonthQuarter
from smolagents import CodeAgent, LiteLLMModel, PythonInterpreterTool

# 建議：模型共用、Agent 每請求新建
_SHARED_MODEL = None

# === 模型設定（可用 .env 覆寫） ===
MODEL_ID = os.getenv("MODEL_ID", "ollama_chat/llama3.1:8b")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:11434")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0"))


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

'''
def _extract_style_terms_via_llm(question: str) -> list[str]:
    """
    用一顆很小的 LLM，把 question 轉成風格檢索用的 style_terms。
    回傳 list[str]，失敗就給空陣列，後面再 fallback。
    """
    try:
        raw = call_llm(
            question,
            system_prompt=STYLE_DATA_SYSTEM,
            extra_params={"options": {}},
            timeout=30.0,
        )
        # 預期 raw 是 JSON 字串
        data = json.loads(raw)
        terms = data.get("style_terms") or []
        # 簡單清洗：去空白、去空字串、去重複
        cleaned = []
        for t in terms:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if not t:
                continue
            if t not in cleaned:
                cleaned.append(t)
        return cleaned
    except Exception:
        # 任何錯誤都回空，讓上層決定 fallback
        return []
'''

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

6. 組成要給風格 LLM 用的 payload（不要塞 raw_search_result，只保留必要欄位），並另外加上前端可用的顯示資訊：

   payload = {
       "question": question,
       "original_article": original_article,
       "style_query": style_query,           # 實際採用的查詢字串（可能是 primary_query 或 fallback_query）
       "stats": {
           "doc_count": len(hits),
           "snippet_count": len(evidence_snippets),
           "full_doc_count": len(style_docs),
       },
       "evidence_snippets": evidence_snippets,  # 可選：保留少量片段給後端壓縮使用
       "style_docs": style_docs,               # 重點：提供完整參考文本
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

STYLE_DATA_CODE_SYSTEM_1127 = """
你是一個『風格語料準備代理人』。

你的任務只有一件事：
- 產生一段 Python 程式碼，呼叫工具 `es_search_news` 先抓到「風格相近的文件列表」，
  再用 `es_fetch_doc_by_id` 依 uuid 撈出「全文」，組成 payload（JSON），交給後續的「風格生成 LLM」使用。
- 你自己不直接寫新文件，只準備語料。

【基本流程】

1. 把使用者問題字串存成 question，例如：

   question = "我得到一個狀況，請以××機關公文的風格寫成一份正式通知。"
   original_article = question

2. 在程式裡，手動建立一個 style_terms list，裡面放 1～3 個「跟文種／風格／單位／報告類型」相關的關鍵詞，例如：

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

   然後用空白把這些詞串起來：

   style_query = " ".join(style_terms) if style_terms else "公文"

3. 呼叫 `es_search_news` 取得風格語料（只用來找候選文件，不做時間統計）：

   search_result = es_search_news(
       query=style_query,      # 用 style_query 而不是原始 question
       must_high_value=False,
       must_selected=False,
       size=20,               # 風格樣本不用太多，20 足夠
       date_from=None,
       date_to=None,
       selected_boost=2.0,
       high_value_boost=1.5,
       recency_boost=False,
       recency_field="importDT",
       recency_scale="365d",
   )

   hits = search_result.get("hits") or []
   evidence_snippets = search_result.get("evidence_snippets", [])

4. 針對每一個 hit，用 `es_fetch_doc_by_id` 依 uuid 撈出全文，組成 style_docs，若系統有提供預設的 index_hint（例如 "news_test,mil_reports-01"），請在搜尋與撈全文時使用同一個 index_hint，以確保查詢及後續全文取得落在相同索引集合。：

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

5. 組成要給風格 LLM 用的 payload（不要塞 raw_search_result，只保留必要欄位），並另外加上前端可用的顯示資訊：

   payload = {
       "question": question,
       "original_article": original_article,
       "style_query": style_query,
       "stats": {
           "doc_count": len(hits),
           "snippet_count": len(evidence_snippets),
           "full_doc_count": len(style_docs),
       },
       "evidence_snippets": evidence_snippets,  # 可選：保留少量片段給後端壓縮使用
       "style_docs": style_docs,               # 重點：提供完整參考文本
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

6. 程式最後只做一件事：呼叫 final_answer 回傳 payload：

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

   core_terms 只允許放：
   - 主題（人物、組織、武器型號、事件名稱…）
   - 地點（海域、國家、城市、海峽、水道…）

   時間相關字串一律不能出現在 core_terms，包括但不限於：
   - 含有「年」「月」「日」「週」「星期」「季」「季度」「上半年」「下半年」的詞
     例： "2025年", "2025年1月", "2025年1月15日", "今年1月", "第一季", "2025-Q1"
   - 純年份或年份區間
     例： "2024", "2024年～2025年"
   - 年月格式
     例： "2025-01", "2025/01"

   ✅ 範例：
   question = "給我劉德華在2024年1月在臺灣的活動情資。"

   核心關鍵字（core_terms）必須是：
   core_terms = ["劉德華", "臺灣"]

   絕對禁止：
   core_terms = ["劉德華", "臺灣", "2024年1月"]  # 這是錯誤示範

   時間範圍必須另外解析為：
   date_from = "2024-01-01"
   date_to   = "2024-01-31"
   
   若你無法明確列出 terms，就至少把 question 中的「請整理」「綜整成」「趨勢分析」
   「SWOT 分析」「目標長度為」「完整報告」等片語去掉，只留下主題與地點。
   所有時間相關字串（含「年」「月」「日」「季」「2025-01」等）一律不得放入 core_terms，
   只能用來推算 date_from / date_to。

   如果你發現某個候選關鍵字裡包含「年」「月」「日」「季」或年份／年月格式，
   必須視為時間資訊，從 core_terms 中移除；否則就違反規則。
   
   然後用 core_query 當成 es_search_news 的 query 參數，而不是原始 question，如果解析出起迄時間，務必放入query參數：

   search_result = es_search_news(
       query=core_query,
       must_high_value=False,
       must_selected=False,
       size=10000,
       date_from=...,   # 若使用者有指定日期，再改成 "YYYY-MM-DD"，如無則填None
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

   payload = {
       "question": question,
       "time_range": {
           "date_from": date_from,
           "date_to": date_to,
       },
       "stats": {
           "doc_count": doc_count,
           "snippet_count": snippet_count,
           "active_days": active_days,
           "day_counts": day_counts,
           "month_counts": month_counts,
           "quarter_counts": quarter_counts,
       },
       "evidence_snippets": evidence_snippets,
       "raw_search_result": search_result,
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
    model_id = _normalize_model_id(MODEL_ID)
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


def _run_data_agent(question: str, mode: str = "report") -> Dict[str, Any]:
    """
    共用一個 CodeAgent 建立邏輯，只是 SYSTEM 不同：
    - mode="report"：做 SRA_REPORT 的資料準備
    - mode="style" ：做 SRA_STYLE 的風格語料準備
    """
    code_agent = build_agent(mode=mode)
    result = code_agent.run(question)

    # 預期 final_answer({"payload": payload})
    if isinstance(result, dict) and "payload" in result:
        return result["payload"]

    if isinstance(result, dict):
        return result

    raise ValueError("資料代理人回傳格式非 dict，請檢查 CodeAgent 的 final_answer 使用方式。")
    