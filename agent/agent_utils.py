import datetime
from collections import Counter
#from typing import List, Dict, Any, Tuple
from typing import Any, Dict, Optional, List

'''
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
'''

def _pack_chat_history_items(items: List[dict], max_chars: int = 8000) -> str:
    """
    items: [{"role": "...", "content": "..."}]
    """
    lines: List[str] = []
    for m in items or []:
        role = (m.get("role") or "").strip()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        # 你原本 pack_chat_history 的格式即可；這裡用簡單版
        lines.append(f"{role}: {content}")
    text = "\n".join(lines)
    if max_chars and len(text) > max_chars:
        text = text[-max_chars:]
    return text

def build_query_for_agent_in_agent(
    user_msg: str,
    history_msgs: Optional[List[dict]] = None,
    memory_text: Optional[str] = None,
) -> str:
    history_text = _pack_chat_history_items(history_msgs or [], max_chars=8000)

    return (
        (f"【對話記憶】\n{memory_text}\n\n" if (memory_text or "").strip() else "") +
        f"【對話歷史】\n{history_text}\n\n"
        f"【目前問題】\n{(user_msg or '').strip()}\n\n"
        "【要求】如果是有對話歷史的多輪對話，那麼延續上文已確立的主題/時間範圍/定義；避免過度衍伸。"
    )