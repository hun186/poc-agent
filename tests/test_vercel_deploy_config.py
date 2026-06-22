from __future__ import annotations

import json
from pathlib import Path


def test_vercel_entrypoint_reuses_api_main_app():
    entrypoint = Path("api/app.py").read_text(encoding="utf-8")

    assert "from api.main import app" in entrypoint
    assert '__all__ = ["app"]' in entrypoint


def test_vercel_json_routes_to_python_entrypoint():
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/app.py"}]
    assert config["functions"]["api/app.py"]["maxDuration"] == 60
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
