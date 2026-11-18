"""Short Evidence signal tests use no ES, SQL, model or external services."""
from agent.utils.report_evidence_information import (
    SCHEMA, assess_report_evidence_information as assess,
    evidence_information_notice,
)


def test_single_short_sentence_warns_without_dropping_its_reference():
    rows = [{"ref_no": 1, "note": "習近平會見某代表。"}]
    snapshot = [dict(row) for row in rows]
    quality = assess(rows)
    assert quality["schema"] == SCHEMA
    assert quality["rows"] == 1
    assert quality["status"] == "limited_text"
    assert quality["short_notes"] == 1
    assert "文字過短" in evidence_information_notice(quality)
    assert rows == snapshot


def test_date_only_evidence_warns_not_invents_event_content():
    quality = assess([{"ref_no": 1, "note": "2023-08-24"}])
    assert quality["date_only_notes"] == 1
    assert quality["status"] == "limited_text"
    assert "因果關係" in evidence_information_notice(quality)


def test_multiple_detailed_evidence_has_no_automatic_sufficiency_claim():
    rows = [{"ref_no": n, "note": "活動描述與背景資料。" * 15}
            for n in range(1, 5)]
    quality = assess(rows)
    assert quality["status"] == "measured_only"
    assert quality["rows"] == 4
    assert quality["short_notes"] == 0
    assert quality["date_only_notes"] == 0
    assert evidence_information_notice(quality) is None
    assert "fact_checked" not in quality


def test_no_evidence_is_handled_by_separate_guard():
    assert assess([])["status"] == "no_evidence"
    assert evidence_information_notice(assess([])) is None


def test_invalid_rows_fail_closed_without_leaking_private_notes():
    for rows in (
        None, {}, [None], [{"ref_no": True, "note": "x"}],
        [{"ref_no": 1, "note": 123}], [{"ref_no": 1, "note": "x" * 50001}],
        [{"ref_no": 1, "note": "x"}, {"ref_no": 1, "note": "y"}],
        [{"ref_no": i, "note": "x"} for i in range(501)],
    ):
        quality = assess(rows)
        assert quality["status"] == "not_assessed"
        assert quality["rows"] == 0
        assert "x" not in str(quality)
        assert evidence_information_notice(quality)
