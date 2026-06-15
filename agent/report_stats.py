# agent/report_stats.py

def compress_stats(stats: dict, top_k_peak_days: int = 5) -> dict:
    day_counts = stats.get("day_counts") or {}
    # 轉成 list[ (date, count) ]
    day_items = sorted(day_counts.items())  # 依日期排序

    if day_items:
        first_day = day_items[0][0]
        last_day = day_items[-1][0]
    else:
        first_day = last_day = None

    # 取高峰日（依 count 由大到小取前 K 名）
    peak_days = sorted(day_items, key=lambda x: x[1], reverse=True)[:top_k_peak_days]

    # month & quarter 轉陣列形式
    month_counts = stats.get("month_counts") or {}
    quarter_counts = stats.get("quarter_counts") or {}

    month_arr = sorted(month_counts.items())        # e.g. [("2025-01", 34), ...]
    quarter_arr = sorted(quarter_counts.items())    # e.g. [("2025-Q1", 198), ...]

    return {
        "docs": stats.get("doc_count", 0),
        "snips": stats.get("snippet_count", 0),
        "active_days": stats.get("active_days", 0),
        "month": month_arr,
        "quarter": quarter_arr,
        "peak_days": peak_days,
        "first_last": [first_day, last_day],
    }

