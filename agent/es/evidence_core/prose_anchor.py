"""Conservative natural-language subject proposal for SHADOW diagnostics ONLY.

Never authorize real Evidence admission: LLM-generated keyword groups can be
wrong, and the first noun of a sentence is not a verified required subject.
Only the bounded ORIGINAL user question is inspected; no ES or LLM calls.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional, Set

from .question_anchor import ExplicitQuestionAnchor
from .text_norm import normalize_for_match

_PREFIX = re.compile(
    r"^(?:請幫我|請|麻煩|幫我)?(?:分析|整理|評估|研究|探討|說明)"
    r"(?:一下)?(?:關於)?"
)
_YEAR = re.compile(r"^(?:19|20)\d{2}年")
_COMPARE = ("比較", "對照", "對比", "差異", "之間", "與", "和", "跟",
            "以及", "相較", "相對", "vs", "versus", "對")
_NEGATIVE = ("排除", "不包含", "不含", "不討論", "不涉及", "不要",
             "exclude", "excluding", "without", "omit")
_QUOTE = ("引文", "逐字稿", "引用文字", "引用範例", "quotedtext")
_LABEL = re.compile(r"(?:必要主題|必要主體|主要主體|主題)[ \t]*[：:]")
_TERM = re.compile(r"[\w\u4e00-\u9fff\- ]{2,64}", re.UNICODE)


def propose_prose_shadow_anchor(
    original_question: Optional[str],
    term_groups: list[Set[str]],
) -> Optional[ExplicitQuestionAnchor]:
    """A narrow observed *proposal*, not proof of topic or entity identity.

    Example eligible: 請分析加薩的停火情勢
    Example eligible: 請分析加薩停火與? (actually rejected if comparative)
    Comparison, negation, quoted and ambiguous axes always abstain.
    """
    if not isinstance(original_question, str) or not (
        0 < len(original_question) <= 8192
    ):
        return None
    if not isinstance(term_groups, list) or not (1 <= len(term_groups) <= 32):
        return None
    first = next(
        (line.strip() for line in original_question.splitlines() if line.strip()), ""
    )
    if not 0 < len(first) <= 240:
        return None
    line = unicodedata.normalize("NFKC", first).casefold()
    prefix = _PREFIX.match(line)
    if prefix is None:
        return None
    body = _YEAR.sub("", line[prefix.end():].strip(), count=1).strip()
    if not body or _LABEL.search(original_question):
        return None
    all_normal = normalize_for_match(original_question)
    if any(mark in all_normal for mark in (*_COMPARE, *_NEGATIVE, *_QUOTE)):
        return None

    prefixes: list[tuple[int, str]] = []
    terms: list[tuple[int, str]] = []
    for axis, group in enumerate(term_groups):
        if not isinstance(group, set) or len(group) > 32:
            return None
        for term in group:
            if not isinstance(term, str) or not (2 <= len(term) <= 64):
                continue
            if _TERM.fullmatch(term) is None:
                continue
            norm = unicodedata.normalize("NFKC", term).casefold().strip()
            if not 2 <= len(normalize_for_match(norm)) <= 12:
                continue
            terms.append((axis, norm))
            if body.startswith(norm):
                prefixes.append((axis, norm))
    axes = {axis for axis, _ in prefixes}
    if len(axes) != 1:
        return None
    axis = next(iter(axes))
    best = max((word for i, word in prefixes if i == axis), key=len)
    remainder = body[len(best):].strip()
    if not remainder:
        return None
    if not (remainder.startswith(("的", "：", ":", "，", ","))
            or any(remainder.startswith(t) for i, t in terms if i != axis)):
        return None
    return ExplicitQuestionAnchor(literal=best, axis_index=axis)
