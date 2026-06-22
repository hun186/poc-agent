# api/core/presenters/docx/inline.py
import re

def add_bold_italic_runs(paragraph, text: str) -> None:
    """
    處理 **粗體** / *斜體* 的簡單情況（沿用你原本邏輯）。
    """
    parts = re.split(r"(\*\*.*?\*\*)", text or "")
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            inner = part[2:-2]
            run = paragraph.add_run(inner)
            run.bold = True
        else:
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
