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
# Preserve the original grammar and date provenance for already queued jobs.
# New forms are full matches, with no implicit clock or inferred year.
_TOPIC = r"[\u3400-\u9fffA-Za-z]+(?: [\u3400-\u9fffA-Za-z]+)*"
_Y = r"[0-9]{4}年"
_M = _Y + r"[0-9]{1,2}月"
_D = _M + r"[0-9]{1,2}日"
_ISO = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
# Longest shapes first. Year/month ranges need both explicit endpoints.
_ABSOLUTE = (
    r"(?:" + _ISO + r"至" + _ISO + "|" + _D + "至" + _D
    + "|" + _M + "至" + _M + "|" + _Y + "至" + _Y
    + "|" + _D + "|" + _M + "|" + _Y + ")"
)
_TIME = r"(?:不限事件時間|" + _ABSOLUTE + r"(?:期間)?)"
_TAIL = r"(?P<aspects>[^。?!？！\n\r]+)[。?？]?\Z"
_SENTENCES = (
    # Original comma form + ASCII comma / common no-comma absolute date.
    re.compile(r"(?:請)?分析(?P<time>" + _TIME + r")[，,] ?(?P<topic>"
               + _TOPIC + r")的" + _TAIL),
    re.compile(r"(?:請)?分析(?P<time>" + _ABSOLUTE + r"(?:期間)?)(?P<topic>"
               + _TOPIC + r")的" + _TAIL),
    # Explicit topic first: 聯合國在2023年8月的外交回應.
    re.compile(r"(?:請)?分析(?P<topic>" + _TOPIC + r")(?:在|於)(?P<time>"
               + _ABSOLUTE + r"(?:期間)?)的" + _TAIL),
    # Topic first with a natural interrogative, not a second instruction.
    re.compile(r"(?P<topic>" + _TOPIC + r")(?:在|於)(?P<time>"
               + _ABSOLUTE + r"(?:期間)?)的(?P<aspects>[^。?!？！\n\r]+?)為何[？?]\Z"),
)
# Exact, bounded exceptions for known literal names containing ambiguous
# operator characters. Do not strip these characters from arbitrary topics:
# e.g. 聯合國及北約 and 非聯合國 must remain unsupported.
_LITERAL_OPERATOR_NAMES = frozenset(("埃及", "非洲", "非洲聯盟", "非洲聯合組織"))
_TOPIC_UNSUPPORTED = re.compile(
    r"和|與|及|或|比較|對比|相較|僅|只|不|非|排除|除了|包含|必須|限定|"
    r"來源|資料庫|索引|欄位|網站|官方|媒體|新聞|分析|發布|發表|報導|"
    r"之前|之後|以來|截至|本月|上月|去年|今年|近期|最近|最新|當前|過去|"
    r"今日|昨日|明日|昨天|今天|明天|上週|本週|下週|上季|本季|下季|"
    r"期間|年度|年代|前|後|至|到|的|請|針對|關於|"
    r"年初|年中|年底|年末|月初|月中|月底|月末|日內|季度|半年|"
    r"每年|每月|每日|每週|近年|近月|近日|春季|夏季|秋季|冬季|"
    r"(?:週|周|星期)(?:末|日|天|[一二三四五六])|工作日|平日|假日|節假日|"
    r"[零一二三四五六七八九十百千兩數幾廿]+(?:年|月|日|季|週)|"
    r"\b(?:and|or|not|only|except|before|after|since|latest|from|to)\b",
    re.I,
)


def _window(value: str) -> DateWindow:
    if value == "不限事件時間":
        return DateWindow()
    raw = value.removesuffix("期間")

    def bounds(label: str):
        if re.fullmatch(_ISO, label):
            d = date.fromisoformat(label)
            return d, d, "day"
        match = re.fullmatch(
            r"([0-9]{4})年(?:([0-9]{1,2})月(?:([0-9]{1,2})日)?)?", label)
        if match is None:
            raise ValueError
        y = int(match[1])
        if match[2] is None:
            return date(y, 1, 1), date(y, 12, 31), "year"
        m = int(match[2])
        if match[3] is None:
            return date(y, m, 1), date(y, m, monthrange(y, m)[1]), "month"
        d = date(y, m, int(match[3]))
        return d, d, "day"

    labels = raw.split("至")
    first, _, precision = bounds(labels[0])
    last_first, last, end_precision = bounds(labels[-1])
    if precision != end_precision or first > last_first:
        raise ValueError
    return DateWindow(first.isoformat(), last.isoformat(), precision,
                      "explicit_user", value)


def parse_natural_deep_scope(prompt: str) -> NaturalDeepScope:
    """Accept complete explicit-date or explicitly unbounded single-topic sentences.

    E.g. 請分析2023年8月期間，聯合國的外交回應、合作進展。
    Preserve the exact original topic label, order of aspects and date phrase.
    Do not authorize ambiguous comparative, relative-date, field-constrained,
    exclusionary, multiple-branch or arbitrary free-text questions.
    """
    try:
        _original_question(prompt)
        matches = [(i, m) for i, grammar in enumerate(_SENTENCES)
                   if (m := grammar.fullmatch(prompt.strip())) is not None]
        if len(matches) != 1:
            raise ValueError
        grammar_id, match = matches[0]
        topic = match["topic"]
        # Without a delimiter, do not swallow a narrower date qualifier
        # into the topic (e.g. 八月初 / 八月下旬 / 八月中).
        # Ambiguous names may use the original comma-delimited form.
        if (grammar_id == 1 and not match["time"].endswith("期間")
                and re.match(r"初|末|底|起|迄|中(?!國|華)|上旬|下旬|"
                             r"上半|下半|第[一二三四五六七八九十]|內|間|整月|整年",
                             topic)):
            raise ValueError
        # A second location/time connector inside a topic-first label is
        # not a verified single literal topic.
        if grammar_id in (2, 3) and re.search(r"在|於", topic):
            raise ValueError
        aspects = tuple(match["aspects"].split("、"))
        if (not 1 <= len(topic) <= 100 or (topic not in _LITERAL_OPERATOR_NAMES
                and _TOPIC_UNSUPPORTED.search(topic))
                or not 1 <= len(aspects) <= 8
                or len(set(aspects)) != len(aspects)
                or not all(a in _ASPECTS for a in aspects)):
            raise ValueError
        return NaturalDeepScope(_window(match["time"]), topic, aspects)
    except Exception:
        raise ValueError("deep_natural_scope_unsupported") from None
