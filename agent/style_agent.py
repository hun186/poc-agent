#agent/style_agent.py
from typing import Any, Dict, Optional
import json
import os
import time
# ★ 依你原本的位置調整 import
from .data_agent import _run_data_agent         # 如果 _run_data_agent 還在 agent.py
from agent.utils_citations import (
    build_citations_from_ev,
    compress_evidence,
    build_refno_uuid_map,   # ★ 新增：如果之後要 ref_no → uuid 映射
)
#from agent.utils_citations import _build_citations_from_payload
from agent.utils_citations import build_citations_from_ev
from agent.utils_citations import compress_evidence
from .llm_utils.ollama_client import call_llm           # 若 call_llm 在別的 util 模組

MAX_STYLE_DOCS = int(os.getenv("STYLE_MAX_DOCS", "8"))
MAX_STYLE_DOC_CHARS = int(os.getenv("STYLE_MAX_DOC_CHARS", "4000"))

STYLE_MODEL_ID = (
    os.getenv("STYLE_MODEL_ID")   # 若有指定就用這個
    or os.getenv("MODEL_ID")      # 否則沿用主 MODEL_ID
    or "gpt-oss:120b-32k"         # 最後給一個預設
)

STYLE_SYSTEM_PROMPT = """
你是一個「風格模仿寫作助手」，主要任務是：

- 觀察資料庫中既有文本（style_samples, style_docs）的語氣、格式與用詞；
- 但是「所有事實內容」只能來自使用者提供的 source_article；
- 依照 instruction 的要求，把 source_article 重新寫成指定風格的新聞或公文。

你會收到一個 JSON 物件 payload，格式大致如下：

{
  "instruction": "使用者的要求（例如：以聯合國新聞的風格改寫下列新聞⋯）",
  "source_article": "要改寫的原始新聞全文（包含標題、內文等）",
  "style_samples": [
    {
      "d": "YYYY-MM-DD",
      "title": "資料庫原文標題",
      "note": "資料庫原文片段（聯合國新聞 / WHO 新聞等）"
    }
  ],
  "style_docs": [
    {
      "uuid": "...",
      "article_title": "...",
      "full_text": "資料庫中的完整聯合國/WHO 新聞內文"
    }
  ]
}

請嚴格遵守以下規則：

1. 【事實來源限制】
   - 只能把 source_article 中出現的事實（人物、時間、地點、數字、事件內容）重新表達。
   - 不可以把 style_samples 或 style_docs 裡面的事件（例如「全球每年700萬人死於癌症」、「2030年1310萬」）當成新文章的事實搬過來。
   - 如果 source_article 沒提到，就不要自己補充全球統計數字、歷史背景或其他機構研究結果。

2. 【風格來源】
   - 風格只從 style_samples / style_docs 學習：
     - 標題寫法：是否用「世衛組織：⋯」「聯合國呼籲：⋯」這類句型。
     - 段落結構：是否先講背景，再講現在的重點，再講政策建議或呼籲。
     - 用詞與語氣：偏正式、客觀、中性，避免煽情或主觀評論。
   - 你可以模仿聯合國新聞常用的句型，但內容必須仍然在描述 source_article 裡的事件（例如 PFAS 食品包材與健康風險）。

3. 【寫作任務】
   - 讀取 instruction，理解使用者想要的輸出形式（例如：新聞稿、簡報式摘要、公文通知）。
   - 把 source_article 重新整理成一篇完整、條理清楚的文章，風格接近聯合國新聞／WHO 新聞。
   - 可以：
     - 重寫標題，使之符合聯合國新聞常見風格；
     - 重組段落順序（例如先講 PFAS 是什麼，再講研究發現與健康風險，再講呼籲與建議）；
     - 合理濃縮或展開原文內容，但不得捏造新事實。

4. 【禁止事項】
   - 不要輸出 JSON 或多篇新聞的列表。
   - 不要列出資料庫中「被參考的文件清單」，那是系統用的，不是讀者要看的。
   - 不要用簡體中文，全部使用繁體中文。

5. 【輸出格式】
   - 直接輸出一篇可閱讀的完整文章：
     - 可以有一行標題；
     - 下面 2〜6 個段落的內文；
     - 如有需要，可加上一句簡短的背景說明或提醒，但必須能在 source_article 的內容合理推得。
"""

# 依你實際 index 命名改
DEFAULT_STYLE_INDEX_HINT = "mil_reports-01"


def ask_with_style(
    question: str,
    trace: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    SRA_STYLE 模式：
    - 用 SRA_STYLE 資料代理人準備風格樣本與原文，
    - 再交給 STYLE_SYSTEM_PROMPT 做風格改寫。
    """
    if trace is None:
        trace = {}
    # 1) 用 SRA_STYLE 專用資料代理人拿「風格語料 payload」
    payload = _run_data_agent(question, mode="style", trace=trace)

    # 2) 壓成風格樣本，避免 context 被塞爆
    #ev = payload.get("evidence_snippets") or []
    #raw_style_docs = payload.get("style_docs") or []
    ev_full = payload.get("evidence_snippets") or []
    # ★ 用 compress_evidence 產生「有 ref_no 的精簡 ev」
    #style_samples = compress_evidence(ev, max_samples=50)
    style_samples = compress_evidence(ev_full, max_samples=50)
    ev_compact = style_samples         # ★ 之後 citations / LLM 都用這一批

    raw_style_docs = payload.get("style_docs") or []

    # ★ 新增：限制「篇數」與「每篇長度」
    trimmed_style_docs = []
    for d in raw_style_docs[:MAX_STYLE_DOCS]:
        text = (d.get("full_text") or "")
        if len(text) > MAX_STYLE_DOC_CHARS:
            text = text[:MAX_STYLE_DOC_CHARS]
        nd = dict(d)          # 複製一份，避免改到原 payload
        nd["full_text"] = text
        trimmed_style_docs.append(nd)

    style_docs = trimmed_style_docs
    
    # ★ 拆出「指令」與「要改寫的原始新聞」
    instruction = payload.get("question") or question
    source_article = payload.get("original_article") or ""

    # ★ 傳給 LLM 的 payload：帶上 ev_compact（有 ref_no）
    payload_for_llm = {
        "instruction": instruction,
        "source_article": source_article,
        "style_samples": style_samples, # = ev_compact
        "style_docs": style_docs,  # 讓風格 LLM 可以看到部分全文參考
        # 如果你想讓 LLM 顯式知道 ev/ref_no，可以加：
        # "ev": ev_compact,
    }

    user_prompt = json.dumps(
        payload_for_llm,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    # 3) 交給風格生成 LLM
    t0 = time.perf_counter()  # ★ 新增：計時開始
    style_text = call_llm(
        user_prompt,
        system_prompt=STYLE_SYSTEM_PROMPT,
        extra_params={"options": {}},
        timeout=180.0,
        model=STYLE_MODEL_ID,  # ★ 新增：這次仿寫實際用的模型
    )
    t1 = time.perf_counter()  # ★ 新增：計時結束

    # ★ 新增：把這次風格 LLM 呼叫寫到 trace["llm"]["style"]
    llm_root = trace.setdefault("llm", {})
    style_logs: list[Dict[str, Any]] = llm_root.setdefault("style", [])
    style_logs.append({
        "system": "STYLE_SYSTEM_PROMPT",
        "user": user_prompt,
        "answer_preview": (
            style_text[:200] if isinstance(style_text, str)
            else str(style_text)[:200]
        ),
        "elapsed_sec": round(t1 - t0, 3),
        "model_id": STYLE_MODEL_ID,  # ★ 這次仿寫用的 model id
    })

    # 4) 引用 / reasoning
    #citations = _build_citations_from_payload(payload)
    # ★ citations：直接用 ev_compact
    #citations = build_citations_from_ev(ev)
    citations = build_citations_from_ev(ev_compact)   # ★ 跟 report_agent 一樣
    refno_uuid_map = build_refno_uuid_map(ev_compact) # ★ 有需要可以一併回傳
    reasoning = (
        "本回答參考資料庫中既有文本的語氣與格式，"
        "但所有事實僅來自使用者提供的原始文章內容，"
        "資料庫中的既有事件並未被當成新事實引用。"
    )

   # === 5) 組「風格參考原文」區塊，改成較好閱讀的 Markdown ===

    def _to_blockquote(text: str) -> str:
        """把多行文字轉成 Markdown blockquote。"""
        lines = (text or "").splitlines()
        # 保留空白行，但空白行也加一個 ">" 讓區塊感一致
        return "\n".join("> " + (ln.rstrip() or "") for ln in lines if ln.strip() or ln == "")

    ref_sections: list[str] = []
    for i, d in enumerate(style_docs, 1):
        title = (d.get("article_title") or "").strip() or f"樣本 {i}"
        uuid = (d.get("uuid") or "").strip()
        full_text = (d.get("full_text") or "").strip()
        if not full_text:
            continue

        # 小標題：用 ### 當次級標題，比現在的中括弧更清楚
        if uuid:
            header = f"### 風格參考樣本 {i}：{title}（uuid: {uuid}）"
        else:
            header = f"### 風格參考樣本 {i}：{title}"

        # 內文整段改成 blockquote，避免一大坨文字難以分段辨識
        body_block = _to_blockquote(full_text)

        # 每個樣本中間用一行空白隔開
        ref_sections.append(f"{header}\n\n{body_block}")

    if ref_sections:
        style_text_with_refs = (
            style_text
            + "\n\n---\n"
            + "以下為本次風格仿寫所參考的資料庫原文內容（已截斷），供對照與檢核風格：\n\n"
            + "\n\n\n".join(ref_sections)
        )
    else:
        style_text_with_refs = style_text

    # ★ 新增：整理本輪可供後續操作的 uuid（順序照 style_docs）
    used_uuids: list[str] = []
    for d in style_docs:
        u = (d.get("uuid") or "").strip()
        if u and u not in used_uuids:
            used_uuids.append(u)

    return {
        "answer": style_text_with_refs,
        "citations": citations,
        "reasoning": reasoning,
        "style_references": style_docs,
        "used_uuids": used_uuids,       # 保留你原本給前端 reuse_uuids 的用途
        "refno_uuid_map": refno_uuid_map,  # ★ 新增（若前端要用 ref_no → uuid）
    }
