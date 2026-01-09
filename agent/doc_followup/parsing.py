# agent/doc_followup/parsing.py
from __future__ import annotations
from typing import Optional, Tuple
import re

UUID_HEX_40 = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
UUID_HYPHEN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

_CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def extract_uuid_candidates(text: str, max_n: int = 3) -> list[str]:
    """
    從使用者指令裡抓「看起來像 uuid/hash」的字串（最多 max_n 個）。
    """
    if not text:
        return []

    out: list[str] = []

    for m in UUID_HEX_40.finditer(text):
        u = m.group(0)
        if u not in out:
            out.append(u)
            if len(out) >= max_n:
                return out

    for m in UUID_HYPHEN.finditer(text):
        u = m.group(0)
        if u not in out:
            out.append(u)
            if len(out) >= max_n:
                return out

    return out

def parse_target_index(instruction: str) -> Optional[int]:
    """
    支援：第1篇、第 2 篇、第一篇、第二篇……
    找不到就回 None。
    """
    text = (instruction or "").strip()

    m = re.search(r"第\s*(\d+)\s*篇", text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    m = re.search(r"第\s*([一二三四五六七八九十]+)\s*篇", text)
    if m:
        s = m.group(1)
        return _CN_NUM.get(s)

    return None


def parse_char_range_1based(instruction: str, *, max_total_chars: int) -> Tuple[Optional[int], Optional[int]]:
    """
    回傳 (start, end) 皆為 1-based 且 end 為「含」。
    支援：
    - 前26k個字 / 前 26000 字  → (1, 26000)
    - 27k~56k個字 / 27001~56000字 / 27k 至 56k 字 → (27001, 56000)
    """
    text = (instruction or "").replace(" ", "")

    m = re.search(r"前(\d+)(k|K)?(個?字)?", text)
    if m:
        n = int(m.group(1)) * (1000 if m.group(2) else 1)
        if n <= 0:
            return None, None
        return 1, min(n, max_total_chars)  # 仍可先限制在 max_total_chars 範圍內

    m = re.search(r"(\d+)(k|K)?[~～\-至](\d+)(k|K)?(個?字)?", text)
    if m:
        s = int(m.group(1)) * (1000 if m.group(2) else 1)
        e = int(m.group(3)) * (1000 if m.group(4) else 1)
        if s <= 0 or e <= 0:
            return None, None
        if e < s:
            # 異常：改成取 s 起的一段
            return s, s + max_total_chars - 1
        return s, e

    return None, None
