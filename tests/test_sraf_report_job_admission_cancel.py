"""Offline regression for the first durable Report Job admission/cancel slice.

This does not claim support for adaptive multi-round retrieval or in-flight
LLM interruption.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security.service_key_store import ServiceKeyStore
from api.services.report_job_store import (
    IdempotencyConflict, ReportJobAdmissionFull, ReportJobStore,
)


def _create(store, index: int, *, max_active_jobs=1):
    return store.create(
        job_id=f"rpt_{index}", prompt=f"private-{index}", filename=None,
        session_id=f"s-{index}", model="m", options={}, metadata={},
        idempotency_key=f"key-{index}", request_hash=f"hash-{index}",
        owner_kind="service", owner_id="owner", max_active_jobs=max_active_jobs,
    )


def test_atomic_admission_idempotency_and_cancellation(tmp_path):
    store = ReportJobStore(tmp_path / "jobs.db")
    store.initialize()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_create, store, i) for i in range(2)]
        results = []
        errors = []
        for future in futures:
            try:
                results.append(future.result())
            except ReportJobAdmissionFull as exc:
                errors.append(exc)
    assert len(results) == len(errors) == 1
    admitted = results[0][0]
    duplicate, created = _create(store, int(admitted.job_id.split("_")[-1]))
    assert created is False and duplicate.job_id == admitted.job_id
    with pytest.raises(IdempotencyConflict):
        store.create(
            job_id="different", prompt="changed", filename=None,
            session_id=admitted.session_id, model="m", options={}, metadata={},
            idempotency_key=admitted.idempotency_key, request_hash="different",
            owner_kind="service", owner_id="owner", max_active_jobs=1,
        )
    assert not store.cancel_queued(admitted.job_id, owner_kind="service", owner_id="other")
    assert store.cancel_queued(admitted.job_id, owner_kind="service", owner_id="owner")
    assert not store.cancel_queued(admitted.job_id, owner_kind="service", owner_id="owner")
    assert store.get(admitted.job_id).status == "cancelled"
    assert store.claim_next() is None
    store.initialize()
    assert store.recover_running() == 0
    assert store.get(admitted.job_id).status == "cancelled"
    admitted_again, created = _create(store, 3)
    assert created and admitted_again.status == "queued"
    claimed = store.claim_next()
    assert claimed.job_id == admitted_again.job_id
    assert not store.cancel_queued(claimed.job_id, owner_kind="service", owner_id="owner")


@pytest.mark.parametrize("limit", [0, -1, 10001, True, "2", 1.5])
def test_invalid_limits_fail_closed(tmp_path, limit):
    store = ReportJobStore(tmp_path / "jobs.db")
    store.initialize()
    with pytest.raises(ValueError, match="invalid_report_job_admission_limit"):
        _create(store, 1, max_active_jobs=limit)


def test_api_admission_and_owner_scoped_queue_cancel(tmp_path, monkeypatch):
    import api.security.service_key_store as key_store_module

    monkeypatch.setenv("REPORT_JOBS_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("REPORT_JOBS_REPORTS_ROOT", str(tmp_path / "reports"))
    monkeypatch.setenv("REPORT_JOBS_MAX_ACTIVE", "1")
    keys = ServiceKeyStore(tmp_path / "keys.json")
    monkeypatch.setattr(key_store_module, "SERVICE_KEY_STORE", keys)
    _, key_a = keys.create(
        "one", ["report:job:create", "report:job:read", "report:job:download"], "pytest"
    )
    _, key_b = keys.create("two", ["report:job:create", "report:job:read"], "pytest")
    a = {"Authorization": f"Bearer {key_a}"}
    b = {"Authorization": f"Bearer {key_b}"}
    with TestClient(app) as client:
        # Disable background consumption; assertions remain deterministic and
        # never send a request to an ES/LLM provider.
        app.state.report_job_worker.stop()
        first = client.post(
            "/v1/report/jobs", json={"prompt": "PRIVATE"},
            headers={**a, "Idempotency-Key": "one"},
        )
        assert first.status_code == 202
        job_id = first.json()["job_id"]
        replay = client.post(
            "/v1/report/jobs", json={"prompt": "PRIVATE"},
            headers={**a, "Idempotency-Key": "one"},
        )
        assert replay.status_code == 202
        assert replay.json()["job_id"] == job_id
        full = client.post(
            "/v1/report/jobs", json={"prompt": "PRIVATE2"},
            headers={**a, "Idempotency-Key": "two"},
        )
        assert full.status_code == 429
        assert full.headers.get("retry-after") == "30"
        assert "PRIVATE" not in full.text
        assert client.post(f"/v1/report/jobs/{job_id}/cancel", headers=b).status_code == 404
        assert client.post(f"/v1/report/jobs/{job_id}/cancel").status_code == 401
        cancelled = client.post(f"/v1/report/jobs/{job_id}/cancel", headers=a)
        assert cancelled.status_code == 200
        assert cancelled.json() == {"job_id": job_id, "status": "cancelled"}
        assert client.post(f"/v1/report/jobs/{job_id}/cancel", headers=a).status_code == 409
        status = client.get(f"/v1/report/jobs/{job_id}", headers=a)
        assert status.status_code == 200
        assert status.json()["status"] == "cancelled"
        assert "PRIVATE" not in status.text
        assert client.get(f"/v1/report/jobs/{job_id}/word", headers=a).status_code == 409
        listing = client.get("/v1/report/jobs?status=cancelled", headers=a)
        assert listing.status_code == 200
        assert [row["job_id"] for row in listing.json()["items"]] == [job_id]
        second = client.post(
            "/v1/report/jobs", json={"prompt": "PRIVATE2"},
            headers={**a, "Idempotency-Key": "two"},
        )
        assert second.status_code == 202
