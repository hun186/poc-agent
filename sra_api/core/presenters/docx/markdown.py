# api/core/presenters/docx/markdown.py
from __future__ import annotations

import re
from typing import Optional

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

from api.core.presenters.text_sanitize import normalize_hyphens_for_word
from api.core.presenters.text_sanitize import normalize_text_for_docx  # 可能會用到，保留

from .table import add_markdown_table
from .config import DocxRenderConfig

from .inline import add_bold_italic_runs

def _has_paragraph_style(doc: Document, style_name: str) -> bool:
    # 小優化：只掃一次 doc.styles（O(n)）
    for s in doc.styles:
        if s.type == WD_STYLE_TYPE.PARAGRAPH and s.name == style_name:
            return True
    return False


def add_markdown_to_doc(doc: Document, text: str, cfg: Optional[DocxRenderConfig] = None) -> None:
    """
    把 answer 的 Markdown-ish 內容轉成 Word 排版（你原本 _add_markdown_to_doc 的拆出版）：
    - 標題行（**一、...**）→ Heading 2
    - #/##/### → Heading 1/2/3
    - > 引用 → Intense Quote（若存在）
    - - / * → List Bullet
    - 表格（| ... |）→ 交給 tables.add_markdown_table()
    - 其他 → 一般段落（支援 **粗體** / *斜體*）
    """
    cfg = cfg or DocxRenderConfig()

    text = normalize_hyphens_for_word(text or "")
    lines = text.split("\n")

    has_intense_quote_style = _has_paragraph_style(doc, "Intense Quote")

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            doc.add_paragraph("")
            i += 1
            continue

        # 1) Markdown 表格：連續含 '|' 的行 + 第二行是 --- 分隔
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*-", lines[i + 1]):
            header_line = line
            sep_line = lines[i + 1]
            body_lines: list[str] = []
            j = i + 2
            while j < len(lines) and "|" in lines[j]:
                body_lines.append(lines[j])
                j += 1

            add_markdown_table(doc, header_line, sep_line, body_lines, cfg=cfg)
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
            if has_intense_quote_style:
                p.style = "Intense Quote"
            add_bold_italic_runs(p, content)
            i += 1
            continue

        # 5) 項目符號行：- ... 或 * ...
        m_bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m_bullet:
            bullet_text = m_bullet.group(1)
            p = doc.add_paragraph(style="List Bullet")
            add_bold_italic_runs(p, bullet_text)
            i += 1
            continue

        # 6) 一般段落
        p = doc.add_paragraph()
        add_bold_italic_runs(p, line)
        i += 1
