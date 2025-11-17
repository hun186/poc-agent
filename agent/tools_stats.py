# agent/tools_stats.py
from smolagents import Tool
from datetime import datetime
from collections import Counter
from typing import List, Dict, Any, Tuple, Set


class AggregateMonthQuarter(Tool):
    '''
    1.時間粒度
     (1)先把 snippet 的日期轉成 datetime：
      i.article_date_iso → date_iso → date 依序嘗試
      ii.支援 "2025-06-21T00:00:00.000Z" 這種格式
     (2)以「日」當作最小單位，date_key = "YYYY-MM-DD"
    2.去重單位：(uuid, date)
     (1)同一篇文件（同一個 uuid），同一天出現再多段 snippet → 只算 1 次
     (2)同一篇文件跨多天有活動（例如 6/21、6/22） → 每一天都會算進去
    3.統計內容
     (1)day_counts[YYYY-MM-DD]：那一天有多少「文件 × 日期」
     (2)month_counts[YYYY-MM]：那個月總共有多少「文件 × 日期」
     (3)quarter_counts[YYYY-Qx]：那一季總共有多少「文件 × 日期」
     (4)doc_count：參與這次統計的不同文件數（uuid 數）
     (5)snippet_count：原始 snippet 數（方便你對照 size）
     (6)active_days：有活動記錄的天數（有至少 1 個 (uuid, date)）
    '''
    # 這個 name 很重要，要跟你在 prompt 叫的函式名完全一樣
    name = "aggregate_month_quarter"
    description = (
        "根據 evidence_snippets 的日期欄位，"
        "以『文件 × 日期』為單位，統計每日、每月與每季的出現次數，"
        "並回傳文件總數與片段總數。"
    )

    # es_search_news 會傳一個 snippet list 進來
    inputs = {
        "evidence_snippets": {
            "type": "array",
            "items": {
                "type": "object"   # 每個元素是一個 dict/snippet
            },
            "description": (
                "包含日期與 uuid 的 snippet 陣列；"
                "建議至少具備：uuid、article_date_iso 或 date_iso。"
            ),
        }
    }

    # smolagents 這裡要用 "object" 而不是 "dict"
    output_type = "object"
    
    def _is_valid_year(self, dt: datetime) -> bool:
        return 1900 <= dt.year <= 2100
    
    def _extract_date(self, s: Dict[str, Any]) -> datetime | None:
        """
        從 snippet 中盡量抓出一個 ISO 日期字串，轉成 datetime。
        優先順序：
        1) article_date_iso
        2) date_iso
        3) date
        ※ 若是 list 取第 1 個；若結尾有 'Z' 先去掉再丟給 fromisoformat。
        """
        date_str = (
            s.get("article_date_iso")
            or s.get("date_iso")
            or s.get("date")
        )
        if not date_str:
            return None

        # 可能是 list，例如 ["2025-06-21T00:00:00.000Z"]
        if isinstance(date_str, list):
            if not date_str:
                return None
            date_str = date_str[0]

        if not isinstance(date_str, str):
            return None

        # 去掉尾巴的 Z（ISO8601 with Z）
        if date_str.endswith("Z"):
            date_str = date_str[:-1]

        try:
            return datetime.fromisoformat(date_str)
        except Exception:
            return None

    def _extract_uuid(self, s: Dict[str, Any]) -> str | None:
        """
        優先用 snippet.uuid；若沒有再嘗試 source_id 等欄位。
        這裡寧可多區分，也不要隨便用 'unknown' 把不同文件混在一起。
        """
        uid = s.get("uuid") or s.get("source_id")
        if isinstance(uid, list):
            return uid[0] if uid else None
        if isinstance(uid, str):
            return uid
        return None

    def forward(self, evidence_snippets: List[Dict[str, Any]]) -> Dict[str, Any]:
        # 計數器
        month_counter: Counter[str] = Counter()
        quarter_counter: Counter[str] = Counter()
        day_counter: Counter[str] = Counter()

        # 去重集合
        doc_ids: Set[str] = set()              # 有出現過的文件（uuid）
        doc_day_seen: Set[Tuple[str, str]] = set()  # (uuid, date_key) 去重

        for s in evidence_snippets:
            dt = self._extract_date(s)
            if dt is None:
                continue
            if not self._is_valid_year(dt):
                continue   # 避免奇怪年份干擾統計

            uuid = self._extract_uuid(s)
            if uuid is None:
                # 沒有 uuid 就沒辦法做「文件 × 日期」的去重，只能跳過
                continue

            doc_ids.add(uuid)

            # 以「日」為最小時間單位
            date_key = dt.strftime("%Y-%m-%d")

            # 同一份文件在同一天只算一次
            key = (uuid, date_key)
            if key in doc_day_seen:
                continue
            doc_day_seen.add(key)

            # 月 / 季 key
            month_key = f"{dt.year:04d}-{dt.month:02d}"
            q = (dt.month - 1) // 3 + 1
            quarter_key = f"{dt.year:04d}-Q{q}"

            # 計數
            day_counter[date_key] += 1
            month_counter[month_key] += 1
            quarter_counter[quarter_key] += 1

        return {
            # 有幾篇不同 uuid 的文件參與計算
            "doc_count": len(doc_ids),
            # 所有 snippet 總數（不去重，方便 debug 或當作參考）
            "snippet_count": len(evidence_snippets),
            # 有活動的「天數」（至少一份文件在當天提到）
            "active_days": len(day_counter),

            # 每日 / 每月 / 每季統計（已依 key 排序）
            "day_counts": dict(sorted(day_counter.items())),
            "month_counts": dict(sorted(month_counter.items())),
            "quarter_counts": dict(sorted(quarter_counter.items())),
        }
