# api/core/presenters/docx/data_agent_section.py
from typing import Optional, Any, List
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from api.core.presenters.text_sanitize import normalize_text_for_docx
from api.core.presenters.sections import DataAgentSection
from api.core.presenters.docx.config import DocxRenderConfig  # ★新增

def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"

def _get(d: Any, key: str, default: str = "") -> str:
    if d is None:
        return default
    if isinstance(d, dict):
        return str(d.get(key) or default)
    return str(getattr(d, key, default) or default)

def iter_style_refs(da_section: Any) -> List[Any]:
    """
    兼容不同命名：盡量從 da_section 找到「風格參考文本」列表。
    你可以在 data_agent 端固定成 style_refs，這裡先做兼容。
    """
    candidates = ["style_refs","style_docs","style_samples","style_evidence","full_docs","style_full_docs"]
    for name in candidates:
        v = getattr(da_section, name, None)
        if isinstance(v, list) and v:
            return v
    return []



def add_data_agent_section(
    doc: Document,
    da_section: Optional[DataAgentSection],
    *,
    cfg: Optional[DocxRenderConfig] = None,   # ★新增
) -> None:
    """
    將 extract_data_agent_section(out) 回傳的 da_section 寫入 Word。
    ★ 注意：只吃 da_section，不再解析 out
    """
    cfg = cfg or DocxRenderConfig()           # ★新增：保底預設
    if not da_section:
        return

    # ==== 標題 ====
    doc.add_page_break()
    doc.add_heading("資料整備紀錄（Data Agent）", level=2)

    mode = da_section.mode
    elapsed = da_section.elapsed_sec
    question_raw = da_section.question_raw

    stats = da_section.stats or {}
    dt_from = da_section.date_from
    dt_to = da_section.date_to

    core_terms = da_section.core_terms or []
    topic_terms = da_section.topic_terms or []
    style_terms = da_section.style_terms or []

    syn_terms = da_section.syn_terms or []
    effective_terms = da_section.effective_terms or []

    es_query = da_section.es_query

    # ✅ 新增：路由/索引資訊（有值才顯示）
    topic = getattr(da_section, "topic", None)
    indexes = getattr(da_section, "indexes", None) or []
    #index_hint = getattr(da_section, "index_hint", None)
    
    # ==== 基本資訊 ====
    if mode:
        p = doc.add_paragraph()
        p.add_run("模式：").bold = True
        p.add_run(normalize_text_for_docx(mode))

    if elapsed is not None:
        p = doc.add_paragraph()
        p.add_run("資料準備耗時：").bold = True
        #p.add_run(f"約 {elapsed} 秒")
        p.add_run(f"約 {elapsed:.2f} 秒" if isinstance(elapsed, (int, float)) else f"約 {elapsed} 秒")

    if question_raw:
        p = doc.add_paragraph()
        p.add_run("原始問題：").bold = True
        p.add_run(normalize_text_for_docx(question_raw))

    refined_question = getattr(da_section, "refined_question", None)
    if refined_question:
        p = doc.add_paragraph()
        p.add_run("精煉後問題（檢索用）：").bold = True
        p.add_run(normalize_text_for_docx(refined_question))

    # ==== 路由 / 檢索標的 ====
    if topic:
        p = doc.add_paragraph()
        p.add_run("主題（topic）：").bold = True
        p.add_run(normalize_text_for_docx(str(topic)))

    if indexes:
        p = doc.add_paragraph()
        p.add_run("檢索索引（indexes）：").bold = True
        p.add_run(normalize_text_for_docx("、".join([str(x) for x in indexes if str(x).strip()])))

    #if index_hint:
    #    p = doc.add_paragraph()
    #    p.add_run("索引提示（index_hint）：").bold = True
    #    p.add_run(normalize_text_for_docx(str(index_hint)))
        
    # ==== 時間範圍 ====
    if dt_from or dt_to:
        p = doc.add_paragraph()
        p.add_run("查詢時間範圍：").bold = True
        p.add_run(f"{normalize_text_for_docx(dt_from or 'N/A')} ～ {normalize_text_for_docx(dt_to or 'N/A')}")

    # ==== 統計資訊 ====
    if stats:
        doc_cnt = stats.get("doc_count")
        snip_cnt = stats.get("snippet_count")
        active_days = stats.get("active_days")
        full_doc_count = stats.get("full_doc_count")

        items = []
        if doc_cnt is not None:
            items.append(f"文件數：{doc_cnt}")
        if snip_cnt is not None:
            items.append(f"片段數：{snip_cnt}")
        if active_days is not None:
            items.append(f"有活動天數：{active_days}")
        if full_doc_count is not None:
            items.append(f"風格樣本文檔數：{full_doc_count}")

        if items:
            p = doc.add_paragraph()
            p.add_run("統計概況：").bold = True
            p.add_run("；".join(items))

    # ==== 關鍵字樣態（保留你原本格式）====
    mode_norm = (str(mode or "")).lower()

    if mode_norm in ("report", "sra_report"):
        if core_terms:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run("核心關鍵詞：").bold = True
            p.add_run(", ".join(core_terms))

    elif mode_norm in ("style", "sra_style"):
        if style_terms:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run("風格關鍵詞（style_terms）：").bold = True
            p.add_run(", ".join(style_terms))
        if topic_terms:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run("主題關鍵詞（topic_terms）：").bold = True
            p.add_run(", ".join(topic_terms))
        if core_terms:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run("檢索核心關鍵詞（style_terms + topic_terms）：").bold = True
            p.add_run(", ".join(core_terms))

    # ==== ES 查詢字串 ====
    if es_query:
        p = doc.add_paragraph()
        p.add_run("代理人 ES 文本查詢工具查詢字串：").bold = True
        p.add_run(normalize_text_for_docx(es_query))

    # ==== 同義詞 / effective_terms ====
    if syn_terms:
        syn_str = ", ".join(syn_terms)
        if len(syn_str) > 1000:
            syn_str = syn_str[:1000] + "…"
        p = doc.add_paragraph()
        p.add_run("同義／擴充關鍵詞：").bold = True
        p.add_run(normalize_text_for_docx(syn_str))

    if effective_terms:
        eff_str = ", ".join(effective_terms)
        if len(eff_str) > 1000:
            eff_str = eff_str[:1000] + "…"
        p = doc.add_paragraph()
        p.add_run("實際使用關鍵詞（effective terms）：").bold = True
        p.add_run(normalize_text_for_docx(eff_str))

    style_refs = iter_style_refs(da_section)
    if style_refs:
        doc.add_paragraph("")
        doc.add_heading("風格參考文本（Style References）", level=3)

        has_quote = any(s.name == "Intense Quote" and s.type == WD_STYLE_TYPE.PARAGRAPH for s in doc.styles)
        quote_style = "Intense Quote" if has_quote else None

        for idx, ref in enumerate(style_refs[:cfg.style_ref_max_docs], start=1):
            title = _get(ref, "title") or _get(ref, "article_title")
            date_iso = _get(ref, "date_iso") or _get(ref, "article_date_iso")
            uuid_ = _get(ref, "uuid") or _get(ref, "id") or _get(ref, "doc_id")
            text = (_get(ref, "text") or _get(ref, "fulltext") or _get(ref, "content") or _get(ref, "note") or _get(ref, "snippet"))

            p = doc.add_paragraph(style="List Bullet")
            p.add_run(f"參考 {idx}：").bold = True
            if title:
                p.add_run(normalize_text_for_docx(title))
            if date_iso:
                p.add_run(f"（{normalize_text_for_docx(date_iso)}）")

            if uuid_:
                p2 = doc.add_paragraph()
                p2.add_run("UUID：").bold = True
                p2.add_run(normalize_text_for_docx(uuid_))

            if text:
                body = normalize_text_for_docx(_truncate(text, cfg.style_ref_max_chars))
                p3 = doc.add_paragraph(style=quote_style) if quote_style else doc.add_paragraph()
                p3.add_run(body)

    model_usage = getattr(da_section, "model_usage", None) or []
    if model_usage:
        doc.add_paragraph("")
        doc.add_heading("各階段使用模型", level=3)
        for item in model_usage:
            stage = _get(item, "stage")
            model_id = _get(item, "model_id")
            if not stage or not model_id:
                continue
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(f"{normalize_text_for_docx(stage)}：").bold = True
            p.add_run(normalize_text_for_docx(model_id))
