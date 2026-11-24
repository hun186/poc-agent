"""Conservative, deterministic first natural-sentence scope compiler.

This is a bounded grammar, not general natural-language understanding.
No model, history, current clock, external data, or caller-proposed indexes.
Unknown syntax fails closed rather than silently discarding constraints.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
import re

from agent.adaptive_retrieval.contracts import DateWindow, _original_question


@dataclass(frozen=True, repr=False)
class NaturalDeepScope:
    event_date: DateWindow
    topic: str
    aspects: tuple[str, ...]


# Only literal analysis facets are recognized here. Do not transform a broad
# question into a model-selected narrow aspect, or infer omitted qualifiers.
_ASPECTS = frozenset((
    "發展趨勢", "發展情況", "主要發展", "主要事件", "外交回應", "合作進展",
    "政策變化", "政策措施", "政策進展", "經濟影響", "經濟情勢", "經濟表現",
    "市場變化", "產業發展", "影響", "原因", "後續發展", "國際反應",
))
_SENTENCE = re.compile(
    r"(?:請)?分析(?P<time>不限事件時間|[0-9]{4}年(?:[0-9]{1,2}月)?期間|"
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}至[0-9]{4}-[0-9]{2}-[0-9]{2}期間)，"
    r"(?P<topic>[\u3400-\u9fffA-Za-z]+(?: [\u3400-\u9fffA-Za-z]+)*)"
    r"的(?P<aspects>[^。\n\r]+)。?\Z"
)
_TOPIC_UNSUPPORTED = re.compile(
    r"和|與|及|或|比較|對比|相較|僅|只|不|非|排除|除了|包含|必須|限定|"
    r"來源|資料庫|索引|欄位|網站|官方|媒體|新聞|分析|發布|發表|報導|"
    r"之前|之後|以來|截至|本月|上月|去年|今年|近期|最近|最新|當前|過去|"
    r"今日|昨日|明日|昨天|今天|明天|上週|本週|下週|上季|本季|下季|"
    r"期間|年度|年代|前|後|至|到|年|月|日|季|週|的|請|針對|關於|"
    r"\b(?:and|or|not|only|except|before|after|since|latest|from|to)\b",
    re.I,
)


def _window(value: str) -> DateWindow:
    if value == "不限事件時間":
        return DateWindow()
    raw = value.removesuffix("期間")
    match = re.fullmatch(r"([0-9]{4})年(?:([0-9]{1,2})月)?", raw)
    if match:
        y = int(match[1])
        if match[2] is None:
            first, last, precision = date(y, 1, 1), date(y, 12, 31), "year"
        else:
            m = int(match[2])
            first, last = date(y, m, 1), date(y, m, monthrange(y, m)[1])
            precision = "month"
        return DateWindow(first.isoformat(), last.isoformat(), precision,
                          "explicit_user", value)
    first, last = raw.split("至")
    return DateWindow(first, last, "day", "explicit_user", value)


def parse_natural_deep_scope(prompt: str) -> NaturalDeepScope:
    """Accept complete explicit-date or explicitly unbounded single-topic sentences.

    E.g. 請分析2023年8月期間，聯合國的外交回應、合作進展。
    Preserve the exact original topic label, order of aspects and date phrase.
    Do not authorize ambiguous comparative, relative-date, field-constrained,
    exclusionary, multiple-branch or arbitrary free-text questions.
    """
    try:
        _original_question(prompt)
        match = _SENTENCE.fullmatch(prompt.strip())
        if match is None:
            raise ValueError
        topic = match["topic"]
        aspects = tuple(match["aspects"].split("、"))
        if (not 1 <= len(topic) <= 100 or _TOPIC_UNSUPPORTED.search(topic)
                or not 1 <= len(aspects) <= 8
                or len(set(aspects)) != len(aspects)
                or not all(a in _ASPECTS for a in aspects)):
            raise ValueError
        return NaturalDeepScope(_window(match["time"]), topic, aspects)
    except Exception:
        raise ValueError("deep_natural_scope_unsupported") from None
