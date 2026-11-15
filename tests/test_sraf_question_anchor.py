"""#406: pure, explicitly original-question subject contract (offline only)."""
from __future__ import annotations

import pytest

from agent.es.evidence_core.question_anchor import (
    derive_explicit_question_anchor, text_explicitly_mentions_anchor,
)


AXES = [
    {"加薩", "加沙"}, {"停火談判"}, {"聯合國"},
    {"平民保護"}, {"醫療"},
]


def test_explicit_first_line_subject_is_unique_and_from_original_axis():
    question = "主題：加薩\n請整理2025年的停火與醫療情況"
    result = derive_explicit_question_anchor(question, AXES)
    assert result is not None
    assert result.literal == "加薩"
    assert result.axis_index == 0
    assert text_explicitly_mentions_anchor("加薩醫院附近醫療人道援助", result)
    assert not text_explicitly_mentions_anchor("蘇丹的聯合國人道援助", result)
    assert not text_explicitly_mentions_anchor("完全無關的另一地區", result)


def test_single_trusted_subject_does_not_infer_other_auxiliary_axes():
    anchor = derive_explicit_question_anchor("必要主體:Gaza", [{"Gaza"}, {"UN"}, {"aid"}])
    assert anchor is not None
    assert anchor.axis_index == 0
    assert text_explicitly_mentions_anchor("Ceasefire in GAZA!", anchor)
    assert not text_explicitly_mentions_anchor("Gazans received aid", anchor)
    assert not text_explicitly_mentions_anchor("Megazacity statement", anchor)
    assert not text_explicitly_mentions_anchor("UN aid update", anchor)


@pytest.mark.parametrize("question", [
    "請整理2025年加薩停火與人道援助",
    "2025年蘇丹人道援助與加薩比較",
    "前言\n主題：加薩\n這是引用新聞內文而非明確第一行要求",
    "主題：加薩、蘇丹",
    "主題：加薩 / 蘇丹",
    "主題：2025",
    "主題：加薩\n排除加薩",
    "主題：加薩\n不包含加薩",
    "主題：加薩\n不要討論加薩",
    "主題：未出現在核心群組的實體",
    "",
    "X" * 8193,
])
def test_no_implicit_subject_from_mentions_or_ambiguous_claims(question):
    assert derive_explicit_question_anchor(question, AXES) is None


def test_ambiguous_group_membership_and_large_group_fails_closed():
    assert derive_explicit_question_anchor(
        "必要主題：加薩", [{"加薩"}, {"加薩", "人道援助"}]
    ) is None
    assert derive_explicit_question_anchor(
        "主題：加薩", [{"加薩"}] * 33
    ) is None
    assert derive_explicit_question_anchor(
        "主題：加薩", [set(str(x) for x in range(33))] + [{"加薩"}]
    ) is None


def test_name_must_be_present_exactly_as_single_group_member():
    assert derive_explicit_question_anchor(
        "主題：加薩", [{"加薩衝突"}, {"停火談判"}]
    ) is None
    assert derive_explicit_question_anchor(
        "主題：聯合國", AXES
    ).axis_index == 2
    assert derive_explicit_question_anchor(
        "主題：加薩", [{"加沙"}, {"停火談判"}]
    ) is None  # no invented transliteration/LLM alias authorization


def test_passage_boundary_and_length_fails_closed():
    anchor = derive_explicit_question_anchor("主題：加薩", AXES)
    assert anchor is not None
    assert not text_explicitly_mentions_anchor("加薩" + "資料" * 5000, anchor)
    assert text_explicitly_mentions_anchor("加薩新聞", anchor)
    assert not text_explicitly_mentions_anchor(None, anchor)
