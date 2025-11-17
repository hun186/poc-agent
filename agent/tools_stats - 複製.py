# agent/tools_stats.py
from smolagents import Tool
from datetime import datetime
from collections import Counter
from typing import List, Dict, Any


class AggregateMonthQuarter(Tool):
    # 這個 name 很重要，要跟你在 prompt 叫的函式名完全一樣
    name = "aggregate_month_quarter"
    description = (
        "根據 evidence_snippets 的 article_date_iso 欄位，"
        "統計每月與每季的出現次數。"
    )
    # ★ 這裡把 type 改成 'array'，並指定 items 型別
    inputs = {
        "evidence_snippets": {
            "type": "array",
            "items": {
                "type": "object"   # 每個元素是一個 dict/snippet
            },
            "description": "包含 article_date_iso 的 snippet 陣列",
        }
    }
    # ★ output_type 不能用 'dict'，改成 'object'（也可用 'any'）
    output_type = "object"

    def forward(self, evidence_snippets: List[Dict[str, Any]]) -> Dict[str, Any]:
        month_counter = Counter()
        quarter_counter = Counter()

        for s in evidence_snippets:
            date_str = s.get("article_date_iso")
            if not date_str:
                continue
            try:
                dt = datetime.fromisoformat(date_str)
            except Exception:
                continue

            month_key = f"{dt.year:04d}-{dt.month:02d}"
            month_counter[month_key] += 1

            q = (dt.month - 1) // 3 + 1
            quarter_key = f"{dt.year:04d}-Q{q}"
            quarter_counter[quarter_key] += 1

        return {
            "month_counts": dict(sorted(month_counter.items())),
            "quarter_counts": dict(sorted(quarter_counter.items())),
        }