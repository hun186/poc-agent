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


def test_vercel_api_folder_contains_only_shim_and_single_entrypoint():
    api_py_files = sorted(Path("api").rglob("*.py"))

    assert api_py_files == [Path("api/__init__.py"), Path("api/index.py")]
    shim = Path("api/__init__.py").read_text(encoding="utf-8")
    entrypoint = Path("api/index.py").read_text(encoding="utf-8")
    assert '"sra_api"' in shim
    assert "_API_SHIM_DIR" in shim
    assert "__path__" in shim
    assert "from api.main import app" in entrypoint


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
