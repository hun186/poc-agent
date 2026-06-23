from __future__ import annotations

import json
from pathlib import Path


def test_vercel_entrypoint_reuses_api_main_app():
    entrypoint = Path("app.py").read_text(encoding="utf-8")

    assert "from api.main import app" in entrypoint
    assert '__all__ = ["app"]' in entrypoint
    assert not Path("api/app.py").exists()


def test_vercel_json_uses_zero_config_fastapi_discovery():
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

    assert "version" not in config
    assert "builds" not in config
    assert "routes" not in config
    assert "functions" not in config
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index.py"}]
    assert config["env"]["SRA_VERCEL_MOCK_MODE"] == "auto"
    assert config["env"]["API_STORE_ENABLED"] == "0"


def test_vercel_deploy_doc_lists_mock_and_secret_settings():
    doc = Path("docs/vercel_deploy.md").read_text(encoding="utf-8")

    assert "SRA_VERCEL_MOCK_MODE=auto" in doc
    assert "SRA_AUTH_SECRET" in doc
    assert "Excel→SQL dashboard" in doc
    assert "Do not commit real secrets" in doc


def test_env_example_documents_vercel_mock_defaults():
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "SRA_VERCEL_MOCK_MODE=auto" in env_example
    assert "API_STORE_ENABLED=0" in env_example


def test_vercel_hobby_plan_does_not_use_legacy_builds_or_api_entrypoint():
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

    assert Path("app.py").exists()
    assert not Path("api/app.py").exists()
    assert Path("api/index.py").exists()
    assert "builds" not in config
    assert "routes" not in config


def test_vercel_entrypoint_imports_under_vercel_environment(tmp_path):
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "VERCEL": "1",
        "VERCEL_ENV": "production",
        "APP_ENV": "production",
        "SRA_AUTH_USERS_FILE": str(tmp_path / "users.json"),
        "SRA_LOGIN_AUDIT_FILE": str(tmp_path / "login_audit.json"),
    }
    code = (
        "from fastapi.testclient import TestClient\n"
        "from app import app\n"
        "response = TestClient(app).get('/healthz')\n"
        "assert response.status_code == 200, response.text\n"
        "print(response.json())\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "'ok': True" in result.stdout or '"ok": true' in result.stdout


def test_vercel_api_folder_keeps_only_shim_and_entrypoint_in_deployment():
    api_py_files = sorted(Path("api").rglob("*.py"))
    vercelignore = Path(".vercelignore").read_text(encoding="utf-8")

    assert Path("api/__init__.py") in api_py_files
    assert Path("api/index.py") in api_py_files
    ignored = {
        line.strip()
        for line in vercelignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert Path("api/routers").exists() is False
    assert Path("api/static").exists() is False
    assert "api/routers/" not in ignored
    assert "api/static/" not in ignored
    shim = Path("api/__init__.py").read_text(encoding="utf-8")
    entrypoint = Path("api/index.py").read_text(encoding="utf-8")
    assert '"sra_api"' in shim
    assert "_API_SHIM_DIR" in shim
    assert "__path__ = [str(_SOURCE_DIR), str(_API_SHIM_DIR)]" in shim
    assert "from api.main import app" in entrypoint


def test_api_imports_prefer_relocated_sra_api_source():
    import api.routers.editor as editor_router

    assert "sra_api/routers/editor.py" in editor_router.__file__.replace("\\", "/")


def test_vercel_default_auth_state_uses_tmp_directory(monkeypatch):
    import tempfile

    from api.services.auth_support import _auth_file, _login_audit_file

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SRA_AUTH_USERS_FILE", raising=False)
    monkeypatch.delenv("SRA_LOGIN_AUDIT_FILE", raising=False)

    tmp_root = Path(tempfile.gettempdir()).resolve()
    auth_file = _auth_file()
    audit_file = _login_audit_file()

    assert auth_file.resolve().is_relative_to(tmp_root)
    assert audit_file.resolve().is_relative_to(tmp_root)
    assert auth_file.name == ".sra_users.json"
    assert audit_file.name == ".sra_users.login_audit.json"


def test_vercel_default_editor_audit_uses_tmp_directory(monkeypatch):
    import tempfile

    from api.services.editor_audit import audit_log_path

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SRA_EDITOR_AUDIT_LOG", raising=False)

    tmp_root = Path(tempfile.gettempdir()).resolve()
    path = audit_log_path()

    assert path.resolve().is_relative_to(tmp_root)
    assert path.name == "editor_audit.jsonl"


def test_root_redirects_to_editor_under_vercel_environment(tmp_path):
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "VERCEL": "1",
        "VERCEL_ENV": "production",
        "APP_ENV": "production",
        "SRA_AUTH_USERS_FILE": str(tmp_path / "users.json"),
        "SRA_LOGIN_AUDIT_FILE": str(tmp_path / "login_audit.json"),
    }
    code = (
        "from fastapi.testclient import TestClient\n"
        "from api.index import app\n"
        "response = TestClient(app, follow_redirects=False).get('/')\n"
        "assert response.status_code in {307, 308}, response.text\n"
        "assert response.headers['location'] == '/editor'\n"
        "print(response.status_code, response.headers['location'])\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_vercel_mock_preview_login_returns_usable_token(tmp_path):
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "VERCEL": "1",
        "VERCEL_ENV": "preview",
        "APP_ENV": "dev",
        "SRA_AUTH_USERS_FILE": str(tmp_path / "users.json"),
        "SRA_LOGIN_AUDIT_FILE": str(tmp_path / "login_audit.json"),
    }
    code = (
        "from pathlib import Path\n"
        "import tempfile\n"
        "from fastapi.testclient import TestClient\n"
        "from api.index import app\n"
        "from api.services.editor_audit import audit_log_path\n"
        "client = TestClient(app)\n"
        "enabled = client.get('/v1/auth/vercel-preview-login-enabled')\n"
        "assert enabled.status_code == 200, enabled.text\n"
        "assert enabled.json()['enabled'] is True, enabled.text\n"
        "login = client.post('/v1/auth/vercel-preview-login')\n"
        "assert login.status_code == 200, login.text\n"
        "payload = login.json()\n"
        "assert payload['user']['username'] == 'vercel_mock_reader'\n"
        "assert payload['user']['role'] == 'data_reader'\n"
        "me = client.get('/v1/auth/me', headers={'Authorization': 'Bearer ' + payload['access_token']})\n"
        "assert me.status_code == 200, me.text\n"
        "audit_path = audit_log_path()\n"
        "assert audit_path.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())\n"
        "assert audit_path.exists(), audit_path\n"
        "assert 'vercel_mock_preview' in audit_path.read_text(encoding='utf-8')\n"
        "print(payload['user'])\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_vercel_mock_preview_login_disabled_without_mock_runtime(tmp_path):
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "SRA_VERCEL_MOCK_MODE": "never",
        "SRA_AUTH_USERS_FILE": str(tmp_path / "users.json"),
        "SRA_LOGIN_AUDIT_FILE": str(tmp_path / "login_audit.json"),
    }
    code = (
        "from fastapi.testclient import TestClient\n"
        "from api.index import app\n"
        "client = TestClient(app)\n"
        "enabled = client.get('/v1/auth/vercel-preview-login-enabled')\n"
        "assert enabled.status_code == 200, enabled.text\n"
        "assert enabled.json()['enabled'] is False, enabled.text\n"
        "login = client.post('/v1/auth/vercel-preview-login')\n"
        "assert login.status_code == 404, login.text\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
