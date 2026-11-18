"""Offline citation-label policy: do not confuse existence with grounded facts."""
from agent.utils.report_citation_audit import (
    AUDIT_SCHEMA, MAX_TEXT_CHARS, audit_report_citation_labels,
    citation_integrity_notice,
)


def test_valid_references_and_numeric_list_stay_unchanged():
    message = "來源1指出甲事，並綜合來源2、3及（來源5）對照。"
    audit = audit_report_citation_labels(message, [1, 2, 3, 5])
    assert audit == {
        "schema": AUDIT_SCHEMA, "status": "labels_match",
        "labels_seen": 4, "unique_labels": 4,
        "unmapped_labels": 0, "allowed_reference_count": 4,
    }
    assert citation_integrity_notice(audit) is None


def test_out_of_scope_labels_flagged_without_leaking_source_ids_or_user_text():
    secret = "PRIVATE-SOURCE-ID-SHOULD-NOT-LEAK"
    audit = audit_report_citation_labels(
        f"來源1 有證據，來源77 {secret} 缺乏對照。",
        [1, 2],
    )
    assert audit["status"] == "unmapped"
    assert audit["unmapped_labels"] == 1
    assert secret not in str(audit)
    assert secret not in (citation_integrity_notice(audit) or "")
    assert "無法對應" in citation_integrity_notice(audit)


def test_no_labels_is_not_fabricated_reference_or_factual_verdict():
    audit = audit_report_citation_labels("有一項事件需要調查。", [1])
    assert audit["status"] == "no_labels"
    assert "未標示" in citation_integrity_notice(audit)
    assert "確認" in citation_integrity_notice(audit)
    assert audit_report_citation_labels("沒有引用。", [])["status"] == "no_labels"
    assert citation_integrity_notice(audit_report_citation_labels("無引用。", [])) is None


def test_year_not_mistaken_for_citation_after_colon():
    audit = audit_report_citation_labels("資料來源：2026年新聞列表。", [1])
    assert audit["status"] == "no_labels"


def test_fail_closed_on_malformed_inputs_and_limits():
    for references in ([True], [-1], [0], [1, 1], [None], list(range(501))):
        audit = audit_report_citation_labels("來源1", references)
        assert audit["status"] == "invalid_contract"
        assert audit["unmapped_labels"] == 0
    assert audit_report_citation_labels(None, [1])["status"] == "invalid_contract"
    assert audit_report_citation_labels("x" * (MAX_TEXT_CHARS + 1), [1])["status"] == "invalid_contract"
    assert "未完成" in citation_integrity_notice(
        audit_report_citation_labels(None, [1]))


def test_citations_are_audit_only_not_source_factual_quality():
    audit = audit_report_citation_labels("來源1：未經證實的陳述。", [1])
    assert audit["status"] == "labels_match"
    # Matching IDs does NOT establish semantic truth or provenance quality.
    assert "semantic" not in audit and "factual" not in audit
