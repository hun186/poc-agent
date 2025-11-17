import datetime
from collections import Counter
from typing import List, Dict, Any, Tuple

def aggregate_month_quarter(evidence: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    輸入：tools_es 回傳的 evidence_snippets list
          每筆至少有 article_date_iso
    輸出：
      - month_counts: {"2025-06": 10, ...}
      - quarter_counts: {"2025-Q2": 10, ...}
    """
    month_counts: Counter[str] = Counter()
    for ev in evidence:
        date_str = (ev.get("article_date_iso") or "").strip()
        if not date_str:
            continue
        try:
            dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
        except Exception:
            continue
        month_key = dt.strftime("%Y-%m")  # e.g. 2025-06
        month_counts[month_key] += 1

    quarter_counts: Counter[str] = Counter()
    for month_key, cnt in month_counts.items():
        year_str, m_str = month_key.split("-")
        m_int = int(m_str)
        q = (m_int - 1) // 3 + 1
        q_key = f"{year_str}-Q{q}"      # e.g. 2025-Q2
        quarter_counts[q_key] += cnt

    return dict(month_counts), dict(quarter_counts)