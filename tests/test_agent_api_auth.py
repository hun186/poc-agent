from fastapi.testclient import TestClient
from api.main import app
from tests.security_test_utils import bearer

def test_models_fail_closed_and_scope_enforced(monkeypatch, tmp_path):
    client=TestClient(app)
    assert client.get('/v1/models').status_code == 401
    wrong=bearer(monkeypatch,tmp_path,['model:invoke'])
    assert client.get('/v1/models',headers=wrong).status_code == 403
    right=bearer(monkeypatch,tmp_path,['model:read'])
    assert client.get('/v1/models',headers=right).status_code == 200

