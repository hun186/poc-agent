# agent/utils/markdown_tables.py
from __future__ import annotations

import re
from typing import List

_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")
#ROWSPAN_MARKER = "〃"
#ROWSPAN_HIDDEN = "\u2063"  # INVISIBLE SEPARATOR：幾乎不可見，但字串仍存在

def _split_row_preserve_escaped_pipes(row: str) -> List[str]:
    """
    Split a markdown table row into cells, treating '\|' as literal pipe.
    """
    # normalize: remove leading/trailing pipe (optional)
    s = row.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]

    cells = []
    buf = []
    esc = False
    for ch in s:
        if esc:
            buf.append(ch)   # keep literal after backslash
            esc = False
            continue
        if ch == "\\":
            esc = True
            buf.append(ch)   # keep backslash for now; we'll normalize later
            continue
        if ch == "|":
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf))
    return cells

def _escape_cell(text: str) -> str:
    if text is None:
        return ""
    t = str(text)

    # real newlines break pipe tables → convert
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")

    # ★ 小強化：連續 <br>（通常來自空白行/多段落）壓成單一 <br>
    #t = re.sub(r"(?:<br>\s*){2,}", "<br>", t)
    #如果你遇過模型輸出的是 <br/> 或 <br />，可以改成「同時支援三種 br 寫法」：
    t = re.sub(r"(?:(?:<br\s*/?>)\s*){2,}", "<br>", t, flags=re.IGNORECASE)

    # unescaped pipes break columns → escape
    # keep already escaped \| as-is
    t = re.sub(r"(?<!\\)\|", r"\\|", t)

    # trim but keep meaningful spaces
    return t.strip()

def _normalize_row_cells(cells: List[str], col_count: int) -> List[str]:
    cells = [_escape_cell(c) for c in cells]
    if len(cells) < col_count:
        cells += [""] * (col_count - len(cells))
    elif len(cells) > col_count:
        # merge extras into last col to prevent table corruption
        head = cells[:col_count - 1]
        tail = cells[col_count - 1:]
        merged_last = " ".join([c for c in tail if c != ""]).strip()
        head.append(merged_last)
        cells = head
    return cells

def _rebuild_table(header_cells: List[str], rows_cells: List[List[str]]) -> str:
    col_count = len(header_cells)
    header = "| " + " | ".join(header_cells) + " |\n"
    sep = "| " + " | ".join(["---"] * col_count) + " |\n"
    body = "".join("| " + " | ".join(r) + " |\n" for r in rows_cells)
    return header + sep + body

def sanitize_markdown_tables(text: str) -> str:
    """
    Find all markdown pipe tables in text and normalize them to be renderer-safe.
    Works for any column count.
    """
    lines = text.splitlines()
    out = []
    i = 0
    n = len(lines)

    while i < n:
        # detect potential table header + separator
        if "|" in lines[i] and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1] or ""):
            header_line = lines[i]
            #sep_line = lines[i + 1]

            header_cells_raw = _split_row_preserve_escaped_pipes(header_line)
            # infer column count from header
            col_count = max(1, len(header_cells_raw))
            header_cells = _normalize_row_cells(header_cells_raw, col_count)

            # collect data rows until non-table line encountered
            j = i + 2
            data_rows: List[List[str]] = []
            while j < n:
                line = lines[j]
                if not line.strip():
                    break  # blank line ends table
                # ★ 重要：若這行沒有 '|'，當成上一列最後一格的續行（多段落/多行）
                if "|" not in line:
                    if data_rows:
                        #data_rows[-1][-1] = _escape_cell(data_rows[-1][-1] + "\n" + line)
                        last_cell_content = data_rows[-1][-1]
                        data_rows[-1][-1] = f"{last_cell_content}<br>{_escape_cell(line)}"
                        j += 1
                        continue
                    else:
                        break
            
                # 正常表格列
                row_cells_raw = _split_row_preserve_escaped_pipes(line)

                # ★ 新增：修復少一欄（日期表最常見漏掉 〃）造成的整列左移錯位
                '''
                if len(row_cells_raw) == col_count - 1:
                    h0 = (header_cells_raw[0] if header_cells_raw else "").strip()
                    if "日期" in h0:
                        row_cells_raw = [ROWSPAN_MARKER] + row_cells_raw
                '''      
                # Heuristic: if row is wildly short (e.g., 1 cell) but looks like continuation,
                # append to last row's last cell instead of making a broken new row.
                #if data_rows and len(row_cells_raw) < max(2, col_count - 1) and not line.strip().startswith("|"):
                #    data_rows[-1][-1] = _escape_cell(data_rows[-1][-1] + "\n" + line)
                #else:
                #    row_cells = _normalize_row_cells(row_cells_raw, col_count)
                # 如果欄位數不足（例如 LLM 漏掉最後一個 |），強制補齊
                row_cells = _normalize_row_cells(row_cells_raw, col_count)
                        
                data_rows.append(row_cells)
                j += 1

            out.append(_rebuild_table(header_cells, data_rows).rstrip("\n"))
            i = j
            continue

        out.append(lines[i])
        i += 1

    return "\n".join(out)