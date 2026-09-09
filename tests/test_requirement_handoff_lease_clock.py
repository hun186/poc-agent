from datetime import datetime, timedelta, timezone

import pytest

from requirement_scheduler.lease import CONTROL_DOMAIN, LeaseProof
from requirement_scheduler.store import ScheduleStore


NOW = datetime(2026, 9, 9, 8, 12, 43, tzinfo=timezone.utc)
TOKEN = "a" * 64


class LeaseDatabase:
    def __init__(self, row=None):
        self.row = list(row) if row else None
        self.executions = []

    def open_named_connection(self, _):
        return LeaseConnection(self)


class LeaseConnection:
    def __init__(self, db): self.db, self.pending = db, None
    def cursor(self): return LeaseCursor(self)
    def commit(self):
        if self.pending is not None: self.db.row = self.pending
    def rollback(self): self.pending = None
    def close(self): pass


class LeaseCursor:
    def __init__(self, connection):
        self.connection, self.results, self.rowcount = connection, [], -1

    def fetchone(self): return self.results.pop(0) if self.results else None

    def execute(self, sql, *params):
        normalized = " ".join(sql.split())
        self.connection.db.executions.append((normalized, params))
        self.results, self.rowcount = [], -1
        if normalized == "SELECT SYSUTCDATETIME()":
            self.results = [(NOW.replace(tzinfo=None),)]
        elif normalized == "SELECT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')":
            self.results = [(NOW,)]
        elif normalized.startswith("SELECT owner_id,lease_token,fencing_generation,expires_at"):
            if self.connection.db.row is not None:
                self.results = [tuple(self.connection.db.row)]
        elif normalized.startswith("INSERT INTO"):
            self.connection.pending = [params[1], params[2], params[3], params[5]]
            self.rowcount = 1
        elif "SET owner_id=?" in normalized:
            row = self.connection.db.row
            matches = row is not None and row[2] == params[7] and row[3] <= params[8]
            self.rowcount = int(matches)
            if matches: self.connection.pending = [params[0], params[1], params[2], params[4]]
        elif "SET heartbeat_at=?" in normalized:
            row = self.connection.db.row
            matches = bool(row and row[0] == params[4] and row[1] == params[5]
                           and row[2] == params[6] and row[3] > params[7]
                           and params[3] == CONTROL_DOMAIN)
            self.rowcount = int(matches)
            if matches: self.connection.pending = [row[0], row[1], row[2], params[1]]
        elif "SET expires_at=?,updated_at=?" in normalized:
            row = self.connection.db.row
            matches = bool(row and params[2] == CONTROL_DOMAIN and row[0] == params[3]
                           and row[1] == params[4] and row[2] == params[5]
                           and row[3] > params[6])
            self.rowcount = int(matches)
            if matches: self.connection.pending = [row[0], row[1], row[2], params[0]]
        return self


def proof(owner="worker", token=TOKEN, generation=1):
    return LeaseProof(CONTROL_DOMAIN, owner, token, generation, NOW + timedelta(minutes=1))


def test_acquire_uses_aware_sql_clock_for_new_and_expired_takeover(monkeypatch):
    monkeypatch.setattr("requirement_scheduler.store.new_lease_token", lambda: TOKEN)
    fresh = LeaseDatabase()
    acquired = ScheduleStore(fresh, "db").acquire_lease("worker", 60)
    assert acquired.expires_at == NOW + timedelta(seconds=60)

    expired = LeaseDatabase(["old", "b" * 64, 7, NOW - timedelta(seconds=1)])
    taken = ScheduleStore(expired, "db").acquire_lease("worker", 60)
    assert taken.fencing_generation == 8
    assert expired.row == ["worker", TOKEN, 8, NOW + timedelta(seconds=60)]


def test_acquire_rejects_unexpired_aware_lease():
    db = LeaseDatabase(["other", "b" * 64, 1, NOW + timedelta(seconds=1)])
    with pytest.raises(RuntimeError, match="lease_unavailable"):
        ScheduleStore(db, "db").acquire_lease("worker", 60)


@pytest.mark.parametrize("field,value", [
    (0, "other"), (1, "b" * 64), (2, 2), (3, NOW - timedelta(seconds=1)),
])
def test_renew_remains_fenced_and_requires_unexpired_lease(field, value):
    row = ["worker", TOKEN, 1, NOW + timedelta(minutes=1)]
    row[field] = value
    db = LeaseDatabase(row)
    with pytest.raises(RuntimeError, match="lease_lost"):
        ScheduleStore(db, "db").renew_lease(proof(), 60)


def test_renew_and_release_use_aware_sql_clock_and_all_fences():
    db = LeaseDatabase(["worker", TOKEN, 1, NOW + timedelta(minutes=1)])
    renewed = ScheduleStore(db, "db").renew_lease(proof(), 120)
    assert renewed.expires_at == NOW + timedelta(seconds=120)
    assert ScheduleStore(db, "db").release_lease(renewed) is True
    assert db.row[3] == NOW
    assert all(params[3 if "heartbeat_at" in sql else 2] == CONTROL_DOMAIN
               for sql, params in db.executions if sql.startswith("UPDATE"))


def test_release_wrong_owner_token_generation_or_expired_fails_closed():
    for row in (["other", TOKEN, 1, NOW + timedelta(1)],
                ["worker", "b" * 64, 1, NOW + timedelta(1)],
                ["worker", TOKEN, 2, NOW + timedelta(1)],
                ["worker", TOKEN, 1, NOW - timedelta(1)]):
        assert ScheduleStore(LeaseDatabase(row), "db").release_lease(proof()) is False


def test_requirement_handoff_sql_clock_has_one_explicit_utc_offset_contract():
    db = LeaseDatabase()
    ScheduleStore(db, "db").acquire_lease("worker", 60)
    clock_queries = [sql for sql, _ in db.executions if "SYSUTCDATETIME" in sql]
    assert clock_queries == ["SELECT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')"]
