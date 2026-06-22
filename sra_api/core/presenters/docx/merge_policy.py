# api/core/presenters/docx/merge_policy.py
import re, math, statistics
from docx.table import Table

_NO_MERGE_VALUES = {"", "—", "N/A", "未知"}

_NUMERIC_RE = re.compile(r"""^\s*[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:%|‰)?\s*$""", re.VERBOSE)
_CURRENCY_RE = re.compile(r"^\s*(?:NT\$|\$|USD|TWD|EUR|JPY|RMB|¥|€)\s*[\d,]+(?:\.\d+)?\s*$", re.IGNORECASE)

def norm_merge_key(s: str) -> str:
    t = (s or "").strip()
    t = t.replace("\u2011", "-").replace("—", "-").replace("–", "-")
    t = re.sub(r"\s+", " ", t)
    return t

def looks_like_numeric_cell(text: str) -> bool:
    if text is None:
        return False
    t = str(text).strip()
    if not t:
        return False
    # 常見統計值：3、1,234、12.5、80%、$1,000
    return bool(_NUMERIC_RE.match(t) or _CURRENCY_RE.match(t))

def is_forbidden_column_by_header(table: Table, col_idx: int) -> bool:
    # 以表頭判斷更穩：Count / 數值 / 件數 / 次數 / 比例 等欄位通常不應合併
    h = (table.cell(0, col_idx).text or "").strip().lower()
    if not h:
        return False
    forbidden_keys = [
        "count","value","num","number","total","sum","avg","mean","rate","ratio","percent","%",
        "數值","件數","次數","總計","合計","平均","比率","比例","百分比",
    ]
    return any(k in h for k in forbidden_keys)

def merge_vertical_when_same_text(table: Table, col_idx: int, start_row: int = 1, min_run: int = 2) -> None:
    if is_forbidden_column_by_header(table, col_idx):
        return

    anchor_row = None
    anchor_key = None
    run_len = 0

    def clear_cell(cell) -> None:
        # 這個最簡單也最穩：會清掉該 cell 所有段落/runs，避免 merge 後內容被拼上去
        cell.text = ""

    def flush_run(end_row_exclusive: int):
        nonlocal anchor_row, run_len
        if anchor_row is None or run_len < min_run:
            return
        anchor_cell = table.cell(anchor_row, col_idx)
        for r in range(anchor_row + 1, end_row_exclusive):
            lower_cell = table.cell(r, col_idx)
            # ★ 先清空「被合併」的儲存格，避免 merge 後重複
            clear_cell(lower_cell)
            anchor_cell.merge(lower_cell)

    for r in range(start_row, len(table.rows)):
        cell = table.cell(r, col_idx)
        raw_text = cell.text or ""
        key = norm_merge_key(raw_text)
        # ✅ 2) 數據型（統計值）一律不合併：遇到就先結束前一段 run，並重置
        if looks_like_numeric_cell(raw_text) or key in _NO_MERGE_VALUES:
            flush_run(r)
            anchor_row, anchor_key, run_len = None, None, 0
            continue

        if anchor_row is None:
            anchor_row, anchor_key, run_len = r, key, 1
            continue

        if key == anchor_key:
            run_len += 1
        else:
            flush_run(r)
            anchor_row, anchor_key, run_len = r, key, 1

    flush_run(len(table.rows))

def estimate_wrap_width(col_count: int) -> int:
    if col_count <= 4: return 42
    if col_count <= 6: return 28
    if col_count <= 8: return 18
    return 12

def estimate_cell_lines(txt: str, wrap_width: int) -> int:
    txt = (txt or "").strip()
    if not txt:
        return 1
    # 以「換行 + 粗估自動換行」估算行數
    parts = txt.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = 0
    for p in parts:
        p = p.strip()
        lines += max(1, math.ceil(len(p) / max(1, wrap_width))) if p else 1
    return max(1, lines)

def estimate_lines_per_page(doc) -> int:
    # 盡量用 section 尺寸估算一頁可容納的「行數」
    # 12pt 字體約 0.17 inch/行，加上表格內距與框線，保守抓 0.22 inch/行
    try:
        sec = doc.sections[-1]
        page_h = sec.page_height.inches
        usable = page_h - sec.top_margin.inches - sec.bottom_margin.inches
        return max(20, int(usable / 0.22))
    except Exception:
        return 40

def table_sparsity_ratio(text_rows: list[list[str]]) -> float:
    # 計算空白/0/—/N/A 比例，越高表示「空白大片」越嚴重
    if not text_rows:
        return 1.0
    total = empty = 0
    for row in text_rows:
        for v in row:
            total += 1
            t = (v or "").strip()
            if (t == "") or (t == "0") or (t in _NO_MERGE_VALUES):
                empty += 1
    return empty / max(1, total)

def should_merge_table(doc, headers: list[str], body_rows: list[list[str]], *, cfg) -> bool:
    col_count = len(headers)
    # 0) 太寬或太長：先直接判高風險（你也可改成「只合併前1欄」）
    if col_count >= cfg.merge_col_block_if_ge:
        return False

    wrap_w = estimate_wrap_width(col_count)

    # 1) 估算每列高度（用該列中「最長的格」的行數代表列高）
    row_line_heights = []
    for r in body_rows:
        est = 1
        for cell in r:
            est = max(est, estimate_cell_lines(cell, wrap_w))
        row_line_heights.append(est)

    # 2) 跨頁風險：估算總行數 vs 一頁可容納行數
    lines_per_page = estimate_lines_per_page(doc)
    total_lines = sum(row_line_heights) + 2
    likely_spans_pages = total_lines > lines_per_page

    # 3) 列高不一致：用變異係數（std/mean）判斷
    mean_h = statistics.mean(row_line_heights) if row_line_heights else 1
    stdev_h = statistics.pstdev(row_line_heights) if len(row_line_heights) >= 2 else 0
    cv = (stdev_h / mean_h) if mean_h else 0
    row_height_very_uneven = cv >= cfg.row_height_cv_threshold

    # 4) 空白大片：稀疏度過高 → 合併後更像巨大空白塊
    sparsity = table_sparsity_ratio(body_rows)
    very_sparse = sparsity >= cfg.sparsity_threshold

    return not (likely_spans_pages or row_height_very_uneven or very_sparse)
