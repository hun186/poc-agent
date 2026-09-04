from datetime import datetime, timedelta, timezone

import pytest

from requirement_scheduler.policy import Checkpoint, evaluate_selection


NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_policy_matrix_and_expiry():
    empty = Checkpoint()
    assert evaluate_selection("all_active", "rv1", 1, empty, None, NOW).selected
    assert evaluate_selection("new_or_changed", "rv1", 1, empty, None, NOW).selected
    assert evaluate_selection("changed_only", "rv1", 1, empty, None, NOW).selected
    success = Checkpoint(last_seen_requirement_version_id="rv1", last_seen_requirement_version_number=1, last_successful_requirement_version_id="rv1", last_successful_requirement_version_number=1)
    assert evaluate_selection("all_active", "rv1", 1, success, None, NOW).selected
    assert evaluate_selection("new_or_changed", "rv1", 1, success, None, NOW).reason == "unchanged_since_success"
    failed_seen = Checkpoint(last_seen_requirement_version_id="rv1", last_seen_requirement_version_number=1)
    assert evaluate_selection("new_or_changed", "rv1", 1, failed_seen, None, NOW).selected
    assert evaluate_selection("changed_only", "rv1", 1, failed_seen, None, NOW).reason == "unchanged_since_seen"
    assert evaluate_selection("changed_only", "rv2", 2, failed_seen, None, NOW).selected
    for policy in ("all_active", "new_or_changed", "changed_only"):
        result = evaluate_selection(policy, "rv1", 1, empty, NOW, NOW)
        assert not result.selected and result.reason == "expired_at_selection" and result.expired_at_selection


def test_naive_expiry_rejected():
    with pytest.raises(ValueError, match="timezone_naive"):
        evaluate_selection("all_active", "rv1", 1, Checkpoint(), datetime.now(), NOW)
