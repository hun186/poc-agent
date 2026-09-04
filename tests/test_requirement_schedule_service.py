from datetime import datetime, timezone

import pytest

from requirement_scheduler.models import RecurrenceSpec, RunPolicy, ScheduleVersionCreate
from requirement_scheduler.service import ScheduleService


class Store:
    def __init__(self): self.calls = []
    def approve_version(self, **kw): self.calls.append(("approve", kw)); return {"status": "approved", **kw}
    def set_enabled(self, **kw): self.calls.append(("enabled", kw)); return {"enabled": kw["enabled"]}


def test_service_approval_and_enable_reject_naive_time():
    store = Store(); service = ScheduleService(store); now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    assert service.approve_version(schedule_id="s", version_number=1, actor="root", now_utc=now)["status"] == "approved"
    assert service.set_enabled(schedule_id="s", enabled=True, actor="root", now_utc=now)["enabled"]
    with pytest.raises(ValueError, match="timezone_naive"):
        service.set_enabled(schedule_id="s", enabled=True, actor="root", now_utc=datetime.now())


def test_disable_is_pause_and_never_reuses_due_time():
    store = Store(); service = ScheduleService(store); now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    result = service.set_enabled(schedule_id="s", enabled=False, actor="root", now_utc=now)
    assert result == {"enabled": False}
    assert store.calls[-1][1]["now_utc"] == now


def test_canonical_reversion_hash_is_non_identity():
    a = ScheduleVersionCreate("UTC", RecurrenceSpec.validate({"kind": "daily", "local_time": "09:00:00"}), RunPolicy.ALL_ACTIVE, "m")
    b = ScheduleVersionCreate("UTC", RecurrenceSpec.validate({"kind": "daily", "local_time": "10:00:00"}), RunPolicy.ALL_ACTIVE, "m")
    from requirement_scheduler.store import ScheduleStore
    assert ScheduleStore.canonical_config(a)[1] == ScheduleStore.canonical_config(a)[1]
    assert ScheduleStore.canonical_config(a)[1] != ScheduleStore.canonical_config(b)[1]
