from datetime import datetime, timezone

import pytest

from requirement_scheduler.recurrence import coalesce_latest, next_occurrence
from requirement_scheduler.models import RecurrenceSpec


def test_daily_weekly_monthly_interval_and_dst():
    after = datetime(2026, 1, 30, 12, tzinfo=timezone.utc)
    assert next_occurrence(RecurrenceSpec.validate({"kind": "daily", "local_time": "09:30:00"}), "Asia/Taipei", after) == datetime(2026, 1, 31, 1, 30, tzinfo=timezone.utc)
    assert next_occurrence(RecurrenceSpec.validate({"kind": "weekly", "weekdays": [1, 3], "local_time": "09:30:00"}), "UTC", after) == datetime(2026, 2, 2, 9, 30, tzinfo=timezone.utc)
    assert next_occurrence(RecurrenceSpec.validate({"kind": "monthly", "day": 31, "local_time": "09:30:00", "invalid_day": "last_day"}), "UTC", after) == datetime(2026, 1, 31, 9, 30, tzinfo=timezone.utc)
    interval = RecurrenceSpec.validate({"kind": "interval", "every": 6, "unit": "hours", "anchor_at": "2026-01-01T00:00:00+00:00"})
    assert next_occurrence(interval, "UTC", after) == datetime(2026, 1, 30, 18, tzinfo=timezone.utc)
    # Earlier fold and first valid minute after a spring gap.
    assert next_occurrence(RecurrenceSpec.validate({"kind": "daily", "local_time": "01:30:00"}), "America/New_York", datetime(2026, 11, 1, tzinfo=timezone.utc)) == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    assert next_occurrence(RecurrenceSpec.validate({"kind": "daily", "local_time": "02:30:00"}), "America/New_York", datetime(2026, 3, 8, tzinfo=timezone.utc)) == datetime(2026, 3, 8, 7, tzinfo=timezone.utc)


def test_rejects_invalid_inputs():
    for value in ({"kind": "cron", "expression": "* * * * *"}, {"kind": "daily", "local_time": "09:00:00", "sql": "select 1"}, {"kind": "interval", "every": 1, "unit": "days", "anchor_at": "2026-01-01T00:00:00"}):
        with pytest.raises(ValueError): RecurrenceSpec.validate(value)
    with pytest.raises(ValueError): next_occurrence(RecurrenceSpec.validate({"kind": "daily", "local_time": "09:00:00"}), "Not/AZone", datetime.now(timezone.utc))
    with pytest.raises(ValueError): next_occurrence(RecurrenceSpec.validate({"kind": "daily", "local_time": "09:00:00"}), "UTC", datetime.now())
    with pytest.raises(ValueError, match="second_precision"):
        RecurrenceSpec.validate({"kind":"interval","every":1,"unit":"hours","anchor_at":"2026-09-05T00:00:00.123456+00:00"})


def test_coalesce_latest_due_without_backfill():
    spec = RecurrenceSpec.validate({"kind": "daily", "local_time": "09:00:00"})
    assert coalesce_latest(spec, "UTC", datetime(2026, 1, 2, 9, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)) is None
    assert coalesce_latest(spec, "UTC", datetime(2026, 1, 1, 9, tzinfo=timezone.utc), datetime(2026, 1, 4, 10, tzinfo=timezone.utc)) == (datetime(2026, 1, 4, 9, tzinfo=timezone.utc), datetime(2026, 1, 5, 9, tzinfo=timezone.utc))
    interval = RecurrenceSpec.validate({"kind": "interval", "every": 6, "unit": "hours", "anchor_at": "2026-01-01T00:00:00+00:00"})
    assert coalesce_latest(interval, "UTC", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, 4, tzinfo=timezone.utc)) == (datetime(2026, 1, 2, tzinfo=timezone.utc), datetime(2026, 1, 2, 6, tzinfo=timezone.utc))
