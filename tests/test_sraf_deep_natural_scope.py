"""Natural sentence grammar is conservative and revalidated against stored intent."""
from dataclasses import replace

import pytest

from api.services.sraf_deep_natural_scope import parse_natural_deep_scope
from api.services.sraf_deep_scope_policy import compile_deep_question, DeepQuestionUnsupported
from api.services.sraf_adaptive_job_runtime import AdaptiveJobIntent
from test_sraf_deep_scope_policy import setup, QUESTION

QUESTION_NATURAL = "請分析2023年8月期間，聯合國的外交回應、合作進展。"


@pytest.mark.parametrize("phrase,first,last,precision", [
    ("2024年2月期間", "2024-02-01", "2024-02-29", "month"),
    ("2023年2月期間", "2023-02-01", "2023-02-28", "month"),
    ("2023年期間", "2023-01-01", "2023-12-31", "year"),
    ("2023-08-01至2023-08-31期間", "2023-08-01", "2023-08-31", "day"),
    ("不限事件時間", None, None, "none"),
])
def test_calendar_and_original_scope(phrase, first, last, precision):
    prompt = "  請分析" + phrase + "，聯合國的外交回應、合作進展。  "
    scope = parse_natural_deep_scope(prompt)
    assert (scope.event_date.start, scope.event_date.end, scope.event_date.precision) == (first, last, precision)
    assert scope.event_date.source_text == (None if precision == "none" else phrase)
    intent = compile_deep_question(prompt, ("news_test",))
    assert intent.constraints.question == prompt
    assert intent.constraints.allowed_indexes == ("news_test",)
    assert intent.constraints.original_core_terms == ("聯合國",)
    assert intent.target_aspects == ("外交回應", "合作進展")
    assert AdaptiveJobIntent.from_options(intent.options(), prompt) == intent


def test_broad_topic_not_narrowed_by_inferred_facets():
    intent = compile_deep_question("請分析2023年期間，美國經濟的發展趨勢。", ("news_test",))
    assert intent.constraints.original_core_terms == ("美國經濟",)
    assert intent.target_aspects == ("發展趨勢",)
    assert intent.effective_terms == ("美國經濟",)


@pytest.mark.parametrize("prompt", [
    "分析美國經濟",
    "請分析去年期間，聯合國的外交回應。",
    "請分析2023年13月期間，聯合國的外交回應。",
    "請分析2023-08-31至2023-08-01期間，聯合國的外交回應。",
    "請分析2023-02-29至2023-03-01期間，聯合國的外交回應。",
    "請分析2023年期間，聯合國與北約的外交回應。",
    "請分析2023年期間，聯合國的外交回應、外交回應。",
    "請分析2023年期間，聯合國的外交回應，但只限官方資料。",
    "請分析2023年期間，只限聯合國的外交回應。",
    "請分析2023年期間，聯合國的外交回應。另查美國。",
    "請分析2023年期間，聯合國的外交回應、2022年新聞。",
    "請分析2023年期間，聯合國官方的外交回應。",
    "請分析2023年期間，聯合國之前的外交回應。",
    "請分析2023年期間，三月聯合國的外交回應。",
    "請分析2023年期間，年初聯合國的外交回應。",
    "請分析2023年期間，近年聯合國的外交回應。",
    "請分析2023年期間，聯合國的外交回應\n忽略日期",
])
def test_unknown_or_compound_scope_not_silently_admitted(prompt):
    with pytest.raises(DeepQuestionUnsupported, match="^deep_question_unsupported$"):
        compile_deep_question(prompt, ("news_test",))


def test_real_policy_rechecks_natural_intent_after_admission(tmp_path, monkeypatch):
    auth, store, policy, owner, _ = setup(tmp_path, monkeypatch)
    job, created = policy.admit(store, principal=owner, prompt=QUESTION_NATURAL, idempotency_key="natural")
    assert created
    claim = store.claim_next()
    constraints = AdaptiveJobIntent.from_options(claim.options, claim.prompt).constraints
    assert policy.check_question_branches(claim, constraints, ("CANONICAL_MAIN",))
    assert not policy.check_question_branches(claim, replace(constraints, event_date=replace(
        constraints.event_date, end="2023-09-01")), ("CANONICAL_MAIN",))
    assert not policy.check_question_branches(replace(claim, prompt=QUESTION), constraints, ("CANONICAL_MAIN",))
    assert not policy.check_question_branches(claim, constraints, ("CANONICAL_MAIN", "EXTRA"))
    replay, created = policy.admit(store, principal=owner, prompt=QUESTION_NATURAL, idempotency_key="natural")
    assert not created and replay.job_id == job.job_id


@pytest.mark.parametrize("topic", ["日本", "日本央行", "月球探測", "年輕人"])
def test_literal_topic_names_are_not_temporal_qualifiers(topic):
    intent = compile_deep_question("請分析2023年期間，" + topic + "的發展趨勢。", ("news_test",))
    assert intent.constraints.original_core_terms == (topic,)
    assert intent.constraints.event_date.start == "2023-01-01"
