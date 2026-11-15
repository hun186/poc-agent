"""Conservative explicit-subject contract for one-round Evidence shadow (#406).

Only the ORIGINAL request's first nonempty line can designate an explicitly
required subject. LLM-rewritten search terms, generic co-occurrences, inferred
locations and model-proposed aliases NEVER create a required subject.
No Evidence is selected or rejected by this helper.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import List, Optional, Set

from .text_norm import normalize_for_match

_MAX_QUESTION_CHARS = 8192
_MAX_SUBJECT_CHARS = 64
_MAX_GROUPS = 32
_MAX_GROUP_TERMS = 32
_MAX_TEXT_CHARS = 4096
_SUBJECT_LINE = re.compile(
    r"(?:必要主題|必要主體|主要主體|主題)[ \t]*[：:][ \t]*(.+?)"
)
_SINGLE_SUBJECT = re.compile(r"[\w\u4e00-\u9fff\- ]{2,64}", re.UNICODE)
_NEGATIONS = ("排除", "不包含", "不含", "不討論", "不要討論")


@dataclass(frozen=True)
class ExplicitQuestionAnchor:
    # Private value never belongs in logs, Trace counters, URLs or response.
    literal: str
    axis_index: int


def derive_explicit_question_anchor(
    original_question: Optional[str],
    term_groups: List[Set[str]],
) -> Optional[ExplicitQuestionAnchor]:
    """Require an explicit first-line marker and exactly one semantic axis.

    Fail closed rather than promote an LLM keyword or a random substring in
    prose to a mandatory subject. This does not perform general NER or prove
    that the semantic axis is correctly generated. That remains later review.
    """
    if not isinstance(original_question, str) or not (
        0 < len(original_question) <= _MAX_QUESTION_CHARS
    ):
        return None
    if not isinstance(term_groups, list) or not (
        1 <= len(term_groups) <= _MAX_GROUPS
    ):
        return None
    first = next(
        (line.strip() for line in original_question.splitlines() if line.strip()),
        "",
    )
    found = _SUBJECT_LINE.fullmatch(first)
    if found is None:
        return None
    name = found.group(1).strip(" \t。")
    if not _SINGLE_SUBJECT.fullmatch(name):
        return None
    normalized = normalize_for_match(name)
    if len(normalized) < 2 or normalized.isnumeric():
        return None
    if any(f"{word}{name}" in original_question for word in _NEGATIONS):
        return None

    found_axes = []
    for i, group in enumerate(term_groups):
        if not isinstance(group, set) or len(group) > _MAX_GROUP_TERMS:
            return None
        if any(
            isinstance(term, str) and len(term) <= _MAX_SUBJECT_CHARS
            and normalize_for_match(term) == normalized
            for term in group
        ):
            found_axes.append(i)
    if len(found_axes) != 1:
        return None
    return ExplicitQuestionAnchor(literal=name, axis_index=found_axes[0])


def text_explicitly_mentions_anchor(
    text: str, anchor: ExplicitQuestionAnchor,
) -> bool:
    """Only the passage's own text can establish an independent anchor.

    English ASCII entity names require lexical boundaries (Gaza != Gazans).
    Chinese text uses the same NFKC/casefold matching basis as current
    Evidence topic matching. Both text and anchor are tightly bounded.
    """
    if not isinstance(text, str) or len(text) > _MAX_TEXT_CHARS:
        return False
    name = anchor.literal
    if name.isascii():
        haystack = unicodedata.normalize("NFKC", text).casefold()
        return bool(re.search(
            r"(?<![a-z0-9])" + re.escape(name.casefold()) + r"(?![a-z0-9])",
            haystack,
        ))
    needle = normalize_for_match(name)
    return bool(needle and needle in normalize_for_match(text))
