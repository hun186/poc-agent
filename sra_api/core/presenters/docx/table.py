# api/core/presenters/docx/tables.py
from __future__ import annotations

#import re
from typing import Optional

from docx import Document
from docx.table import Table

from .config import DocxRenderConfig
from .inline import add_bold_italic_runs  # 用來渲染 cell 內的粗斜體
from .merge_policy import should_merge_table, merge_vertical_when_same_text

def split_row_escaped(line: str) -> list[str]:
    """
    分割 markdown 表格列，支援跳脫 \|。（沿用你原本 _split_row_escaped）
    """
    s = (line or "").strip()
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


def set_cell_text_with_markdown(cell, text: str) -> None:
    """
    將文字寫入 table cell：
    - 支援 **粗體** / *斜體*
    - 支援 <br> 換行（用 Word line break）
    """
    text = text or ""
    parts = str(text).replace("\r\n", "\n").replace("\r", "\n").split("<br>")

    cell.text = ""
    p = cell.paragraphs[0]

    for idx, part in enumerate(parts):
        part = part.strip()
        if idx > 0:
            p.add_run().add_break()
        if part:
            add_bold_italic_runs(p, part)


def _normalize_rows(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
    """
    ★ 正規化每列欄位數：
    - 不足補空
    - 過多合併到最後一欄
    """
    col_count = len(headers)
    norm_rows: list[list[str]] = []

    for r in rows:
        if len(r) < col_count:
            r = r + [""] * (col_count - len(r))
        elif len(r) > col_count:
            r = r[: col_count - 1] + [" ".join([x for x in r[col_count - 1 :] if x]).strip()]
        norm_rows.append(r)

    return norm_rows


def beautify_table_merge_repeated_cells(table: Table, start_row: int = 1, cols: Optional[list[int]] = None) -> None:
    """
    只做合併動作（策略判斷在 add_markdown_table 內）
    """
    if cols is None:
        cols = list(range(len(table.columns)))
    for c in cols:
        merge_vertical_when_same_text(table, c, start_row=start_row)


def add_markdown_table(
    doc: Document,
    header_line: str,
    sep_line: str,   # 保留參數以維持介面；目前不使用
    body_lines: list[str],
    *,
    cfg: Optional[DocxRenderConfig] = None,
) -> None:
    """
    把 markdown 表格轉成 Word 表格。
    header_line / body_lines 形如：| 日期 | 事件概述 | 來源 |
    """
    cfg = cfg or DocxRenderConfig()

    headers = split_row_escaped(header_line)
    rows = [split_row_escaped(l) for l in body_lines if l.strip()]

    if not headers:
        return

    col_count = len(headers)
    norm_rows = _normalize_rows(headers, rows)

    table = doc.add_table(rows=1 + len(norm_rows), cols=col_count)
    table.style = "Table Grid"

    # 表頭（支援 markdown，並加粗）
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        set_cell_text_with_markdown(hdr_cells[i], h)
        for run in hdr_cells[i].paragraphs[0].runs:
            run.bold = True

    # 內容（支援 markdown / <br>）
    for r_idx, row in enumerate(norm_rows, start=1):
        cells = table.rows[r_idx].cells
        for c_idx, cell_text in enumerate(row):
            set_cell_text_with_markdown(cells[c_idx], cell_text)

    # ✅ 合併前先判斷風險（策略交給 merge_policy）
    if should_merge_table(doc, headers, norm_rows, cfg=cfg):
        safe_cols = [c for c in cfg.merge_safe_cols if c < len(headers)]
        if safe_cols:
            beautify_table_merge_repeated_cells(table, start_row=1, cols=safe_cols)
