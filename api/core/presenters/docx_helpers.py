# api/core/presenters/docx_helpers.py
import re
import os
from typing import Optional
from docx import Document
from docx.table import Table
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from api.core.presenters.text_sanitize import normalize_hyphens_for_word
from api.core.presenters.text_sanitize import normalize_text_for_docx
from api.core.presenters.sections import DataAgentSection

import math
import statistics

#VMERGE_MARK = "\u2063"
_NO_MERGE_VALUES = {"", "—", "N/A", "未知"}

def _parse_merge_cols(s: str) -> list[int]:
    out: list[int] = []
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            pass
    return out

'''
def _apply_table_merge_policy(table: Table, headers: list[str], *, start_row: int = 1) -> None:
    """
    DOCX_TABLE_MERGE_MODE:
      - none : 不合併（建議統計表用這個）
      - first: 只合併第 0 欄（常見：日期/項目）
      - first2: 合併第 0,1 欄（常見：類別+項目）
      - cols : 依 DOCX_TABLE_MERGE_COLS 指定欄位，如 "0,1"
      - auto : 欄位太多(>=6)就不合併，否則只合併第0欄
    """
    mode = (os.getenv("DOCX_TABLE_MERGE_MODE", "none") or "none").lower().strip()

    if mode == "none":
        return

    col_count = len(table.columns)
    if col_count <= 0:
        return

    if mode == "auto":
        if len(headers) >= 6:
            return
        cols = [0]
    elif mode == "first":
        cols = [0]
    elif mode == "first2":
        cols = [0, 1] if col_count >= 2 else [0]
    elif mode == "cols":
        cols = _parse_merge_cols(os.getenv("DOCX_TABLE_MERGE_COLS", "0"))
    else:
        # 不認得就當 none
        return

    # 邊界保護
    cols = [c for c in cols if isinstance(c, int) and 0 <= c < col_count]
    if not cols:
        return

    for c in cols:
        merge_vertical_when_same_text(table, c, start_row=start_row)
'''
        
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

_NUMERIC_RE = re.compile(
    r"""^\s*
    [+-]?
    (?:\d{1,3}(?:,\d{3})+|\d+)      # 123 or 1,234
    (?:\.\d+)?                      # .45
    (?:%|‰)?                        # % / ‰
    \s*$""",
    re.VERBOSE,
)

_CURRENCY_RE = re.compile(r"^\s*(?:NT\$|\$|USD|TWD|EUR|JPY|RMB|¥|€)\s*[\d,]+(?:\.\d+)?\s*$", re.IGNORECASE)

def _looks_like_numeric_cell(text: str) -> bool:
    if text is None:
        return False
    t = str(text).strip()
    if not t:
        return False
    # 常見統計值：3、1,234、12.5、80%、$1,000
    return bool(_NUMERIC_RE.match(t) or _CURRENCY_RE.match(t))

def _is_forbidden_column_by_header(table: Table, col_idx: int) -> bool:
    # 以表頭判斷更穩：Count / 數值 / 件數 / 次數 / 比例 等欄位通常不應合併
    h = (table.cell(0, col_idx).text or "").strip().lower()
    if not h:
        return False
    forbidden_keys = [
        "count", "value", "num", "number", "total", "sum", "avg", "mean", "rate", "ratio", "percent", "%",
        "數值", "件數", "次數", "總計", "合計", "平均", "比率", "比例", "百分比",
    ]
    return any(k in h for k in forbidden_keys)

def merge_vertical_when_same_text(
    table: Table,
    col_idx: int,
    start_row: int = 1,   # 1 = 略過表頭
    min_run: int = 2,     # 至少連續 2 列才合併
) -> None:
    
    if _is_forbidden_column_by_header(table, col_idx):
        return
    
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
        raw_text = cell.text or ""
        key = _norm_merge_key(cell.text)
        # ✅ 2) 數據型（統計值）一律不合併：遇到就先結束前一段 run，並重置
        if _looks_like_numeric_cell(raw_text):
            _flush_run(r)
            anchor_row = None
            anchor_key = None
            run_len = 0
            continue
        
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

def _estimate_wrap_width(col_count: int) -> int:
    # 欄越多，每格越窄，越容易自動換行 → 列高越不一致
    if col_count <= 4:
        return 42
    if col_count <= 6:
        return 28
    if col_count <= 8:
        return 18
    return 12

def _estimate_cell_lines(txt: str, wrap_width: int) -> int:
    txt = (txt or "").strip()
    if not txt:
        return 1
    # 以「換行 + 粗估自動換行」估算行數
    parts = txt.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = 0
    for p in parts:
        p = p.strip()
        if not p:
            lines += 1
            continue
        lines += max(1, math.ceil(len(p) / max(1, wrap_width)))
    return max(1, lines)

def _estimate_lines_per_page(doc) -> int:
    # 盡量用 section 尺寸估算一頁可容納的「行數」
    # 12pt 字體約 0.17 inch/行，加上表格內距與框線，保守抓 0.22 inch/行
    try:
        sec = doc.sections[-1]
        page_h = sec.page_height.inches
        usable = page_h - sec.top_margin.inches - sec.bottom_margin.inches
        return max(20, int(usable / 0.22))
    except Exception:
        return 40  # fallback

def _table_sparsity_ratio(text_rows: list[list[str]]) -> float:
    # 計算空白/0/—/N/A 比例，越高表示「空白大片」越嚴重
    if not text_rows:
        return 1.0
    total = 0
    empty = 0
    for row in text_rows:
        for v in row:
            total += 1
            t = (v or "").strip()
            if (t == "") or (t == "0") or (t in _NO_MERGE_VALUES):
                empty += 1
    return empty / max(1, total)

def _should_merge_table(doc, headers: list[str], body_rows: list[list[str]]) -> bool:
    col_count = len(headers)
    row_count = len(body_rows)

    # 0) 太寬或太長：先直接判高風險（你也可改成「只合併前1欄」）
    if col_count >= 9:
        return False

    wrap_w = _estimate_wrap_width(col_count)

    # 1) 估算每列高度（用該列中「最長的格」的行數代表列高）
    row_line_heights: list[int] = []
    for r in body_rows:
        est = 1
        for cell in r:
            est = max(est, _estimate_cell_lines(cell, wrap_w))
        row_line_heights.append(est)

    # 2) 跨頁風險：估算總行數 vs 一頁可容納行數
    lines_per_page = _estimate_lines_per_page(doc)
    total_lines = sum(row_line_heights) + 2  # +表頭/間距保守加
    likely_spans_pages = total_lines > lines_per_page

    # 3) 列高不一致：用變異係數（std/mean）判斷
    mean_h = statistics.mean(row_line_heights) if row_line_heights else 1
    stdev_h = statistics.pstdev(row_line_heights) if len(row_line_heights) >= 2 else 0
    cv = (stdev_h / mean_h) if mean_h else 0
    row_height_very_uneven = cv >= 0.60   # 門檻可調：越小越保守

    # 4) 空白大片：稀疏度過高 → 合併後更像巨大空白塊
    sparsity = _table_sparsity_ratio(body_rows)
    very_sparse = sparsity >= 0.72

    # 只要任一高風險成立，就不要合併（保守策略）
    if likely_spans_pages or row_height_very_uneven or very_sparse:
        return False

    return True

def beautify_table_merge_repeated_cells(
    table: Table,
    start_row: int = 1,
    cols: list[int] | None = None,
) -> None:
    if cols is None:
        cols = list(range(len(table.columns)))
    for c in cols:
        merge_vertical_when_same_text(table, c, start_row=start_row)
   
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
    #beautify_table_merge_repeated_cells(table, start_row=1)
    #_apply_table_merge_policy(table, headers, start_row=1)

    # ✅ 合併前先判斷風險
    #if _should_merge_table(doc, headers, norm_rows):
        # 建議最多只合併前 1~2 欄，降低框線/跨頁風險
        #beautify_table_merge_repeated_cells(table, start_row=1, cols=[0, 1])
    if _should_merge_table(doc, headers, norm_rows):
        safe_cols = [c for c in (0, 1) if c < len(headers)]
        if safe_cols:
            beautify_table_merge_repeated_cells(table, start_row=1, cols=safe_cols)
    else:
        # 不合併就維持原樣（可選：做底色分組/加粗第一欄等）
        pass


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

    refined_question = getattr(da_section, "refined_question", None)
    if refined_question:
        p = doc.add_paragraph()
        p.add_run("精煉後問題（檢索用）：").bold = True
        p.add_run(normalize_text_for_docx(refined_question))

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

    def _iter_style_refs(da_section):
        """
        兼容不同命名：盡量從 da_section 找到「風格參考文本」列表。
        你可以在 data_agent 端固定成 style_refs，這裡先做兼容。
        """
        candidates = [
            "style_refs",
            "style_docs",
            "style_samples",
            "style_evidence",
            "full_docs",          # 你 stats 裡有 full_doc_count，常見會配 full_docs
            "style_full_docs",
        ]
        for name in candidates:
            v = getattr(da_section, name, None)
            if isinstance(v, list) and v:
                return v
        return []
    
    def _style_ref_get(d, key: str, default: str = "") -> str:
        # 支援 dict / pydantic model / object
        if d is None:
            return default
        if isinstance(d, dict):
            return str(d.get(key) or default)
        return str(getattr(d, key, default) or default)
    
    def _truncate_text(s: str, n: int) -> str:
        s = (s or "").strip()
        return s if len(s) <= n else (s[:n] + "…")
    
    # ====== 風格仿寫：把參考的風格文本寫進 Word ======
    # 可用環境變數控制長度，避免 Word 爆肥
    max_docs = int(os.getenv("DOCX_STYLE_REF_MAX_DOCS", "5"))
    max_chars = int(os.getenv("DOCX_STYLE_REF_MAX_CHARS", "2000"))
    
    style_refs = _iter_style_refs(da_section)
    if style_refs:
        doc.add_paragraph("")  # 空行
        doc.add_heading("風格參考文本（Style References）", level=3)
    
        for idx, ref in enumerate(style_refs[:max_docs], start=1):
            title = _style_ref_get(ref, "title") or _style_ref_get(ref, "article_title")
            date_iso = _style_ref_get(ref, "date_iso") or _style_ref_get(ref, "article_date_iso")
            uuid_ = _style_ref_get(ref, "uuid") or _style_ref_get(ref, "id") or _style_ref_get(ref, "doc_id")
            text = (
                _style_ref_get(ref, "text")
                or _style_ref_get(ref, "fulltext")
                or _style_ref_get(ref, "content")
                or _style_ref_get(ref, "note")
                or _style_ref_get(ref, "snippet")
            )
    
            # 標頭（第幾則 + 基本資訊）
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(f"參考 {idx}：").bold = True
            if title:
                p.add_run(normalize_text_for_docx(title))
            if date_iso:
                p.add_run("  ")
                p.add_run(f"（{normalize_text_for_docx(date_iso)}）")
            if uuid_:
                p2 = doc.add_paragraph()
                p2.add_run("UUID：").bold = True
                p2.add_run(normalize_text_for_docx(uuid_))
    
            # 內容（截斷 + 正規化）
            if text:
                body = _truncate_text(text, max_chars)
                body = normalize_text_for_docx(body)
    
                # 用引用樣式（如果有）更好看；沒有就用一般段落
                quote_style = "Intense Quote" if "Intense Quote" in [s.name for s in doc.styles if s.type == WD_STYLE_TYPE.PARAGRAPH] else None
                p3 = doc.add_paragraph(style=quote_style) if quote_style else doc.add_paragraph()
                p3.add_run(body)