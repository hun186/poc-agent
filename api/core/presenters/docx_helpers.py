# api/core/presenters/docx_helpers.py
import re
from typing import Optional
from docx import Document
from docx.table import Table
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from api.core.presenters.text_sanitize import normalize_hyphens_for_word
from api.core.presenters.text_sanitize import normalize_text_for_docx
from api.core.presenters.sections import DataAgentSection

#VMERGE_MARK = "\u2063"
_NO_MERGE_VALUES = {"", "—", "N/A", "未知"}

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
                    
def _split_row_escaped(line: str) -> list[str]:
    """
    分割 markdown 表格列，支援跳脫 \|。
    """
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]

    cells: list[str] = []
    buf: list[str] = []
    esc = False
    for ch in s:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if ch == "\\":
            esc = True
            buf.append(ch)
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf).strip())

    return cells

def _set_cell_text_with_markdown(cell, text: str) -> None:
    """
    將文字寫入 table cell：
    - 支援 **粗體** / *斜體*（沿用 _add_bold_italic_runs）
    - 支援 <br> 換行（用 Word line break）
    """
    text = text or ""
    # 把 markdown 的 <br> 轉成分行
    parts = str(text).replace("\r\n", "\n").replace("\r", "\n").split("<br>")

    # 清空原本內容
    cell.text = ""
    p = cell.paragraphs[0]

    for idx, part in enumerate(parts):
        part = part.strip()
        if idx > 0:
            p.add_run().add_break()  # Word 換行（同一格內）
        if part:
            _add_bold_italic_runs(p, part)


def _norm_merge_key(s: str) -> str:
    t = (s or "").strip()
    # 統一將所有類型的橫線轉為標準減號，確保比對一致
    t = t.replace("\u2011", "-").replace("—", "-").replace("–", "-")
    # 把多空白壓成 1 個，避免「看起來一樣」但其實多空白造成不合併
    t = re.sub(r"\s+", " ", t)
    return t

def merge_vertical_when_same_text(
    table: Table,
    col_idx: int,
    start_row: int = 1,   # 1 = 略過表頭
    min_run: int = 2,     # 至少連續 2 列才合併
) -> None:
    anchor_row = None
    anchor_key = None
    run_len = 0

    def _clear_cell(cell) -> None:
        # 這個最簡單也最穩：會清掉該 cell 所有段落/runs，避免 merge 後內容被拼上去
        cell.text = ""

    def _flush_run(end_row_exclusive: int):
        nonlocal anchor_row, run_len
        if anchor_row is None or run_len < min_run:
            return

        anchor_cell = table.cell(anchor_row, col_idx)

        for r in range(anchor_row + 1, end_row_exclusive):
            lower_cell = table.cell(r, col_idx)

            # ★ 先清空「被合併」的儲存格，避免 merge 後重複
            _clear_cell(lower_cell)

            anchor_cell.merge(lower_cell)

    for r in range(start_row, len(table.rows)):
        cell = table.cell(r, col_idx)
        key = _norm_merge_key(cell.text)

        # 禁止合併的值：未知 / 空 / — / N/A
        if key in _NO_MERGE_VALUES:
            _flush_run(r)
            anchor_row = None
            anchor_key = None
            run_len = 0
            continue

        if anchor_row is None:
            anchor_row = r
            anchor_key = key
            run_len = 1
            continue

        if key == anchor_key:
            run_len += 1
        else:
            _flush_run(r)
            anchor_row = r
            anchor_key = key
            run_len = 1

    _flush_run(len(table.rows))

def beautify_table_merge_repeated_cells(
    table: Table,
    start_row: int = 1,
) -> None:
    # 套用全部欄位
    for c in range(len(table.columns)):
        merge_vertical_when_same_text(table, c, start_row=start_row)
        
'''
def merge_vertical_all_columns_by_marker(table: Table, marker: str = VMERGE_MARK, start_row: int = 1) -> None:
    col_count = len(table.columns)
    for c in range(col_count):
        anchor_row: int | None = None
        for r in range(start_row, len(table.rows)):
            txt = (table.cell(r, c).text or "")
            txt_norm = txt.replace("\n", "").strip()

            # 看到 marker → 向上合併
            if txt_norm == marker:
                if anchor_row is not None:
                    table.cell(anchor_row, c).merge(table.cell(r, c))
                # 若沒有 anchor（第一列就 marker），就放著；marker 不可見
                continue

            # 非 marker 且有內容 → 更新 anchor
            if txt_norm:
                anchor_row = r
'''
                
'''
def merge_vertical_when_hidden_marker(table: Table, col_idx: int, marker: str = "<!--ROWSPAN-->", start_row: int = 1) -> None:
    anchor_row: int | None = None
    for r in range(start_row, len(table.rows)):
        cell = table.cell(r, col_idx)
        txt = (cell.text or "").strip()

        if txt and txt != marker:
            anchor_row = r
            continue

        if txt == marker and anchor_row is not None:
            table.cell(anchor_row, col_idx).merge(cell)
'''
'''
def merge_vertical_when_marker(table: Table, col_idx: int, marker: str = "〃", start_row: int = 1) -> None:
    anchor_row: int | None = None
    for r in range(start_row, len(table.rows)):
        cell = table.cell(r, col_idx)
        txt = (cell.text or "").strip()

        if txt and txt != marker:
            anchor_row = r
            continue

        if txt == marker and anchor_row is not None:
            table.cell(anchor_row, col_idx).merge(cell)
'''
'''
def merge_vertical_when_blank(table: Table, col_idx: int, start_row: int = 1) -> None:
    """
    將指定欄位 col_idx 中，連續的空白儲存格向上合併到最近一個非空白儲存格。
    start_row=1 代表略過表頭（第 0 列）。
    """
    anchor_row: int | None = None
    for r in range(start_row, len(table.rows)):
        cell = table.cell(r, col_idx)
        txt = (cell.text or "").strip()

        if txt:
            anchor_row = r
            continue

        if anchor_row is not None:
            table.cell(anchor_row, col_idx).merge(cell)
'''
def _add_markdown_table(doc, header_line: str, sep_line: str, body_lines: list[str]):
    """
    把 markdown 表格轉成 Word 表格。
    header_line / body_lines 形如：| 日期 | 事件概述 | 來源 |
    """
    headers = _split_row_escaped(header_line)
    rows = [_split_row_escaped(l) for l in body_lines if l.strip()]

    if not headers:
        return

    col_count = len(headers)

    # ★ 正規化每列欄位數：不足補空、過多合併到最後一欄（避免炸表）
    norm_rows: list[list[str]] = []
    for r in rows:
        if len(r) < col_count:
            r = r + [""] * (col_count - len(r))
        elif len(r) > col_count:
            r = r[:col_count - 1] + [" ".join([x for x in r[col_count - 1:] if x]).strip()]
        norm_rows.append(r)

    table = doc.add_table(rows=1 + len(norm_rows), cols=col_count)
    table.style = "Table Grid"

    # 表頭（支援 markdown，並加粗）
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        _set_cell_text_with_markdown(hdr_cells[i], h)
        # 表頭粗體：把該格全部 runs 設 bold（簡單作法）
        for run in hdr_cells[i].paragraphs[0].runs:
            run.bold = True

    # 內容（支援 markdown / <br>）
    for r_idx, row in enumerate(norm_rows, start=1):
        cells = table.rows[r_idx].cells
        for c_idx, cell_text in enumerate(row):
            _set_cell_text_with_markdown(cells[c_idx], cell_text)

    # ★ 關鍵：讓 Word 呈現「跨列合併」效果（以第 0 欄：日期 欄為例）
    #merge_vertical_when_blank(table, col_idx=0, start_row=1)
    #merge_vertical_when_marker(table, col_idx=0, start_row=1)
    #merge_vertical_when_hidden_marker(table, col_idx=0, marker="<!--ROWSPAN-->", start_row=1)
    #merge_vertical_all_columns_by_marker(table, marker=VMERGE_MARK, start_row=1)
    beautify_table_merge_repeated_cells(table, start_row=1)

    


def _add_markdown_table_1224(doc, header_line: str, sep_line: str, body_lines: list[str]):
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
