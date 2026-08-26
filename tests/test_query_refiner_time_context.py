from datetime import datetime

from agent.config.query_refiner_settings import load_report_refiner_config
from agent.refiners import query_refiner


def test_report_refiner_timeout_defaults_to_sixty_seconds(monkeypatch) -> None:
    monkeypatch.delenv("QUERY_REFINER_REPORT_TIMEOUT", raising=False)
    monkeypatch.delenv("QUERY_REFINER_TIMEOUT", raising=False)

    assert load_report_refiner_config().timeout_sec == 60.0


def test_time_reference_calculates_completed_week_boundaries(monkeypatch) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 25, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(query_refiner, "datetime", FixedDatetime)

    reference = query_refiner._time_reference()

    assert reference["reference_date"] == "2026-08-25"
    assert reference["previous_week_from"] == "2026-08-17"
    assert reference["previous_week_to"] == "2026-08-23"
    assert reference["previous_two_weeks_from"] == "2026-08-10"
    assert reference["previous_two_weeks_to"] == "2026-08-23"


def test_report_refiner_resolves_last_year_from_auditable_reference(monkeypatch) -> None:
    captured = {}
    trace = {}

    monkeypatch.setattr(query_refiner, "REFINER_REPORT_ENABLED", True)
    monkeypatch.setattr(
        query_refiner,
        "_time_reference",
        lambda: {
            "timezone": "Asia/Taipei",
            "reference_time": "2026-08-25T12:00:00+08:00",
            "reference_date": "2026-08-25",
            "current_year": "2026",
            "previous_year": "2025",
            "week_start": "monday",
            "previous_week_from": "2026-08-17",
            "previous_week_to": "2026-08-23",
            "previous_two_weeks_from": "2026-08-10",
            "previous_two_weeks_to": "2026-08-23",
        },
    )

    def fake_call_llm(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return '{"refined_question":"請整理 2025-01-01 至 2025-12-31 的加薩新聞"}'

    monkeypatch.setattr(query_refiner, "call_llm", fake_call_llm)

    refined = query_refiner.refine_question_for_data_agent(
        "請整理去年加薩新聞",
        trace=trace,
    )

    assert refined == "請整理 2025-01-01 至 2025-12-31 的加薩新聞"
    assert "今年=2026，去年=2025" in captured["system_prompt"]
    assert "整體檢索範圍必須是 2025-01-01 至 2025-12-31" in captured["system_prompt"]
    assert "背景敘述中的月份只能標成重點時段" in captured["system_prompt"]
    assert "上一週=2026-08-17 至 2026-08-23" in captured["system_prompt"]
    assert "前兩週（指目前週之前的兩個完整週）=2026-08-10 至 2026-08-23" in captured["system_prompt"]
    assert "『前 N 週』表示目前週之前連續 N 個完整週" in captured["system_prompt"]
    assert "『N 週前』表示往前偏移 N 週的單一完整週" in captured["system_prompt"]
    assert "『過去 N 週』則表示截至 reference_date" in captured["system_prompt"]
    assert captured["include_current_time"] is True
    assert trace["query_refiner"]["report"]["time_context"] == {
        "enabled": True,
        "reason": "query_refiner_relative_date_resolution",
        "timezone": "Asia/Taipei",
        "reference_time": "2026-08-25T12:00:00+08:00",
        "reference_date": "2026-08-25",
        "current_year": "2026",
        "previous_year": "2025",
        "week_start": "monday",
        "previous_week_from": "2026-08-17",
        "previous_week_to": "2026-08-23",
        "previous_two_weeks_from": "2026-08-10",
        "previous_two_weeks_to": "2026-08-23",
    }


def test_report_refiner_keeps_last_year_as_full_scope_despite_background_month(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(query_refiner, "REFINER_REPORT_ENABLED", True)
    monkeypatch.setattr(
        query_refiner,
        "_time_reference",
        lambda: {
            "timezone": "Asia/Taipei",
            "reference_time": "2026-08-25T12:00:00+08:00",
            "reference_date": "2026-08-25",
            "current_year": "2026",
            "previous_year": "2025",
            "week_start": "monday",
            "previous_week_from": "2026-08-17",
            "previous_week_to": "2026-08-23",
            "previous_two_weeks_from": "2026-08-10",
            "previous_two_weeks_to": "2026-08-23",
        },
    )

    def fake_call_llm(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return (
            '{"refined_question":"蒐集 2025-01-01 至 2025-12-31 加薩停火、'
            '人質談判及人道援助資訊；2025年10月為重點時段"}'
        )

    monkeypatch.setattr(query_refiner, "call_llm", fake_call_llm)

    refined = query_refiner.refine_question_for_data_agent(
        "去年加薩衝突持續造成危機。10月間哈馬斯表示準備釋放人質。"
        "請持續蒐集去年加薩停火、人質談判及人道援助資訊。",
    )

    assert refined.startswith("蒐集 2025-01-01 至 2025-12-31")
    assert "2025年10月為重點時段" in refined
    assert "任務指令" in captured["system_prompt"]
    assert "背景說明中的月份、日期或事件時間" in captured["system_prompt"]
    assert "只有任務指令本身明確要求" in captured["system_prompt"]
    assert "10月" not in captured["system_prompt"]
