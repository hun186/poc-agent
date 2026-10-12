"""P2.1 Product API read/preview: RBAC, lifecycle hiding, safe projections."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.editor_dependencies import current_user
from api.services.auth_store import AuthUser
from sra_api.routers.requirement_tasks import product_service, router
from sra_api.services.requirement_product_service import RequirementProductService


class ProductStore:
    def __init__(self):
        self.task = {
            "task_id": "task-1", "schedule_id": "schedule-1",
            "source_id": "source-1", "execution_kind": "recurring",
            "product_state": "active", "revision": 1,
            "created_by": "operator", "created_at": None,
            "updated_by": "operator", "updated_at": None,
        }
        self.calls = []

    def list_product_tasks(self, *, limit, offset):
        self.calls.append(("tasks", limit, offset))
        return [self.task] if offset == 0 else []

    def get_product_task(self, task_id):
        if task_id != self.task["task_id"] or self.task["product_state"] == "provisioning":
            raise KeyError("requirement_task_not_found")
        return self.task

    def get_schedule(self, schedule_id):
        assert schedule_id == self.task["schedule_id"]
        return {
            "schedule_id": schedule_id, "name": "Monthly brief",
            "enabled": True, "active_version_id": "version-1", "next_run_at": None,
        }

    def list_product_run_bindings(self, *, limit, offset):
        self.calls.append(("runs", limit, offset))
        return [{"batch_run_id": "run-1", "task_id": "task-1"}] if offset == 0 and self.task["product_state"] != "provisioning" else []

    def get_product_task_for_run(self, run_id):
        if run_id != "run-1" or self.task["product_state"] == "provisioning":
            raise KeyError("requirement_run_unavailable")
        return self.task

    def get_batch_run(self, *, schedule_id, batch_run_id):
        assert (schedule_id, batch_run_id) == ("schedule-1", "run-1")
        return {
            "batch_run_id": batch_run_id, "schedule_id": schedule_id,
            "schedule_version_id": "version-1", "snapshot_id": "snapshot-1",
            "state": "handoff_pending", "trigger_type": "scheduled",
            "scheduled_for": None, "selected_count": 0, "skipped_count": 0,
            "success_count": 0, "failure_count": 0, "items": [],
        }


class PreviewService:
    def __init__(self):
        self.calls = []

    def preview_input(self, **kwargs):
        self.calls.append(kwargs)
        return {"accepted_count": 1, "has_errors": False}


def make_client(role="data_reader", *, store=None, preview=None):
    app = FastAPI()
    app.include_router(router)
    store = store or ProductStore()
    service = RequirementProductService(schedule_store=store)
    if preview is not None:
        service.preview_input = preview.preview_input
    app.dependency_overrides[product_service] = lambda: service
    if role is not None:
        app.dependency_overrides[current_user] = lambda: AuthUser(
            username="reviewer", role=role, status="active"
        )
    return TestClient(app), store


def test_reader_list_and_get_task_only_safe_presenter_fields():
    client, store = make_client()
    listing = client.get("/v1/requirement-tasks?limit=12&offset=0")
    assert listing.status_code == 200
    assert store.calls == [("tasks", 12, 0)]
    task = listing.json()["items"][0]
    assert task["task_id"] == "task-1"
    assert task["schedule"]["active_version_id"] == "version-1"
    assert "source_config" not in json.dumps(task)
    assert client.get("/v1/requirement-tasks/task-1").json() == task


def test_reader_product_run_list_detail_and_items_use_safe_presenter():
    client, store = make_client()
    listing = client.get("/v1/requirement-runs?limit=5&offset=0")
    assert listing.status_code == 200
    run = listing.json()["items"][0]
    assert run["run_id"] == "run-1"
    assert run["status"] == "queued"
    assert run["binding"]["snapshot_id"] == "snapshot-1"
    assert "trigger_request_id" not in json.dumps(run)
    assert client.get("/v1/requirement-runs/run-1").json() == run
    assert client.get("/v1/requirement-runs/run-1/items").json() == {
        "run_id": "run-1", "items": []
    }


def test_unfinalized_product_task_and_run_are_not_visible():
    store = ProductStore()
    store.task["product_state"] = "provisioning"
    client, _ = make_client(store=store)
    assert client.get("/v1/requirement-tasks/task-1").status_code == 404
    assert client.get("/v1/requirement-runs/run-1").status_code == 404
    assert client.get("/v1/requirement-runs").json()["items"] == []


def test_missing_auth_denied_and_preview_operator_only():
    client, _ = make_client(role=None)
    assert client.get("/v1/requirement-tasks").status_code == 401
    assert client.get("/v1/requirement-runs").status_code == 401
    reader, _ = make_client(role="data_reader", preview=PreviewService())
    response = reader.post("/v1/requirement-task-previews", data={"task": '{"profile_version_id":"p1"}', "requirements_json": "[]"})
    assert response.status_code == 403


def test_preview_upload_and_direct_requirements_are_mutually_exclusive():
    preview = PreviewService()
    client, _ = make_client(role="db_operator", preview=preview)
    data = {"task": '{"profile_version_id":"profile-version-1"}'}
    uploaded = client.post(
        "/v1/requirement-task-previews", data=data,
        files={"file": ("requirements.csv", b"A,B\n1,2", "text/csv")},
    )
    assert uploaded.status_code == 200
    assert preview.calls[0]["upload_bytes"] == b"A,B\n1,2"
    assert preview.calls[0]["upload_filename"] == "requirements.csv"
    direct = client.post(
        "/v1/requirement-task-previews",
        data={**data, "requirements_json": '[{"ITEMNO":"A"}]'},
    )
    assert direct.status_code == 200
    assert preview.calls[1]["requirements"] == [{"ITEMNO": "A"}]
    assert len(preview.calls) == 2

    both = client.post(
        "/v1/requirement-task-previews",
        data={**data, "requirements_json": "[]"},
        files={"file": ("x.csv", b"x", "text/csv")},
    )
    assert both.status_code == 422
    assert both.json()["detail"] == {"code": "requirement_preview_input_invalid"}
    missing = client.post("/v1/requirement-task-previews", data=data)
    assert missing.status_code == 422
    assert len(preview.calls) == 2


def test_preview_validation_fails_before_calling_normalization():
    preview = PreviewService()
    client, _ = make_client(role="superuser", preview=preview)
    cases = [
        ({"task": "not-json", "requirements_json": "[]"}, None),
        ({"task": '{"profile_version_id":"pv"}', "requirements_json": "not-json"}, None),
        ({"task": '{"profile_version_id":"pv"}'}, ("unknown.exe", b"body", "application/octet-stream")),
        ({"task": '{"profile_version_id":"pv"}'}, ("empty.csv", b"", "text/csv")),
    ]
    for data, upload in cases:
        kwargs = {"data": data}
        if upload:
            kwargs["files"] = {"file": upload}
        response = client.post("/v1/requirement-task-previews", **kwargs)
        assert response.status_code == 422
    assert not preview.calls


def test_disabled_product_dependency_is_503_and_backend_secrets_are_never_returned():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: AuthUser(
        username="operator", role="data_reader", status="active"
    )
    client = TestClient(app)
    assert client.get("/v1/requirement-tasks").json() == {
        "detail": {"code": "requirement_dependency_unavailable"}
    }

    class BrokenProductStore(ProductStore):
        def list_product_tasks(self, *, limit, offset):
            raise RuntimeError("ODBC password=secret")

    client, _ = make_client(store=BrokenProductStore())
    response = client.get("/v1/requirement-tasks")
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "persistence_error"}}
    assert "secret" not in response.text


def test_main_registration_and_safe_product_dependency_wiring():
    from pathlib import Path
    source = Path("sra_api/main.py").read_text(encoding="utf-8")
    assert "app.include_router(requirement_tasks.router)" in source
    assert "if app.state.requirement_import_service is not None:" in source
    assert "app.state.requirement_product_service = RequirementProductService(" in source
