from datetime import datetime, timedelta, timezone

from requirement_scheduler.policy import Checkpoint, evaluate_selection


def test_selection_expiry_boundary_wins_over_policy():
    now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    for policy in ("all_active", "new_or_changed", "changed_only"):
        assert evaluate_selection(policy, "rv", 1, Checkpoint(), None, now).selected
        assert evaluate_selection(policy, "rv", 1, Checkpoint(), now + timedelta(seconds=1), now).selected
        for expiry in (now, now - timedelta(seconds=1)):
            decision = evaluate_selection(policy, "rv", 1, Checkpoint(), expiry, now)
            assert decision.expired_at_selection and decision.reason == "expired_at_selection"
