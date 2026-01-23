#agent/es/evidence_core/text_norm.py
from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)


def normalize_for_match(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = re.sub(r"[‐-–—−]", "-", s)
    s = re.sub(r"\s+", "", s)
    s = _PUNCT.sub("", s)
    return s
