# api/core/presenters/docx_helpers.py
import re
from typing import Optional
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from api.core.presenters.text_sanitize import normalize_hyphens_for_word
from api.core.presenters.text_sanitize import normalize_text_for_docx
from api.core.presenters.sections import DataAgentSection

def _add_bold_italic_runs(paragraph, text: str):
    """
    處理 **粗體** / *斜體* 的簡單情況。
    """
    # 先處理粗體，再處理斜體
    # 分段：保留 **...** 作為 token
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            inner = part[2:-2]
            run = paragraph.add_run(inner)
            run.bold = True
        else:
            # 再細拆 *斜體*
            sub_parts = re.split(r"(\*.*?\*)", part)
            for s in sub_parts:
                if not s:
                    continue
                if s.startswith("*") and s.endswith("*") and len(s) > 2:
                    inner_i = s[1:-1]
                    run = paragraph.add_run(inner_i)
                    run.italic = True
                else:
                    paragraph.add_run(s)

def _add_markdown_table(doc, header_line: str, sep_line: str, body_lines: list[str]):
    """
    把 markdown 表格轉成 Word 表格。
    header_line / body_lines 形如：| 日期 | 宮古水道 | ...
    """
    def _split_row(line: str) -> list[str]:
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [cell.strip() for cell in line.split("|")]

    headers = _split_row(header_line)
    rows = [_split_row(l) for l in body_lines if l.strip()]

    if not headers:
        return

    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"

    # 表頭
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h

    # 內容
    for r_idx, row in enumerate(rows, start=1):
        cells = table.rows[r_idx].cells
        for c_idx, cell_text in enumerate(row):
            cells[c_idx].text = cell_text


def _add_markdown_to_doc(doc: Document, text: str):
    """
    把 answer 的 Markdown-ish 內容轉成較漂亮的 Word 排版：
    - 標題行（**一、...**）→ Heading 2
    - - 開頭 → 項目符號
    - 表格（| ... |）→ Word 表格
    - 其餘當一般段落，支援 **粗體** / *斜體*
    """
    text = normalize_hyphens_for_word(text)
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            # 空行 → 加一個空段落作為間距
            doc.add_paragraph("")
            i += 1
            continue

        # 1) Markdown 表格：連續含 '|' 的行 + 第二行是 --- 分隔
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*-", lines[i+1]):
            header_line = line
            sep_line = lines[i+1]
            body_lines = []
            j = i + 2
            while j < len(lines) and "|" in lines[j]:
                body_lines.append(lines[j])
                j += 1
            _add_markdown_table(doc, header_line, sep_line, body_lines)
            i = j
            continue

        # 2) 粗體標題行：例如 **一、資料概況**
        m_heading = re.match(r"^\s*\*\*(.+?)\*\*\s*$", line)
        if m_heading:
            title_text = m_heading.group(1).strip()
            p = doc.add_paragraph()
            p.style = "Heading 2"
            p.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
            p.add_run(title_text)
            i += 1
            continue

        # 3) 一般 Markdown 標題：## 標題 / # 標題
        m_md_h = re.match(r"^\s*(#{1,3})\s+(.*)$", line)
        if m_md_h:
            level = len(m_md_h.group(1))
            title_text = m_md_h.group(2).strip()
            style_name = "Heading 1" if level == 1 else "Heading 2" if level == 2 else "Heading 3"
            p = doc.add_paragraph()
            p.style = style_name
            p.add_run(title_text)
            i += 1
            continue

        # 4) 引用（> 開頭）
        if line.lstrip().startswith(">"):
            content = line.lstrip()[1:].strip()
            p = doc.add_paragraph()
            p.style = "Intense Quote" if "Intense Quote" in [s.name for s in doc.styles if s.type == WD_STYLE_TYPE.PARAGRAPH] else None
            _add_bold_italic_runs(p, content)
            i += 1
            continue

        # 5) 項目符號行：- ... 或 * ...
        m_bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m_bullet:
            bullet_text = m_bullet.group(1)
            p = doc.add_paragraph(style="List Bullet")
            _add_bold_italic_runs(p, bullet_text)
            i += 1
            continue

        # 6) 一般段落
        p = doc.add_paragraph()
        _add_bold_italic_runs(p, line)
        i += 1
        
def add_data_agent_section(doc: Document, da_section: Optional[DataAgentSection]) -> None:
    """
    將 extract_data_agent_section(out) 回傳的 da_section 寫入 Word。
    ★ 注意：只吃 da_section，不再解析 out
    """
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

    # ==== 基本資訊 ====
    if mode:
        p = doc.add_paragraph()
        p.add_run("模式：").bold = True
        p.add_run(normalize_text_for_docx(mode))

    if elapsed is not None:
        p = doc.add_paragraph()
        p.add_run("資料準備耗時：").bold = True
        p.add_run(f"約 {elapsed} 秒")

    if question_raw:
        p = doc.add_paragraph()
        p.add_run("原始問題：").bold = True
        p.add_run(normalize_text_for_docx(question_raw))

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
        if len(syn_str) > 120:
            syn_str = syn_str[:120] + "…"
        p = doc.add_paragraph()
        p.add_run("同義／擴充關鍵詞：").bold = True
        p.add_run(normalize_text_for_docx(syn_str))

    if effective_terms:
        eff_str = ", ".join(effective_terms)
        if len(eff_str) > 120:
            eff_str = eff_str[:120] + "…"
        p = doc.add_paragraph()
        p.add_run("實際使用關鍵詞（effective terms）：").bold = True
        p.add_run(normalize_text_for_docx(eff_str))
