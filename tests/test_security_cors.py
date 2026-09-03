from __future__ import annotations

import os
import subprocess
import sys


def _cors_options(extra_env):
    script = """
import json
from fastapi.testclient import TestClient
from api.main import app
middleware = next(item for item in app.user_middleware if item.cls.__name__ == 'CORSMiddleware')
client = TestClient(app)
headers = {'Access-Control-Request-Method':'POST', 'Access-Control-Request-Headers':'Authorization,Content-Type,Idempotency-Key,X-OpenWebUI-Chat-Id,X-Conversation-Id,X-Session-Id'}
allowed = client.options('/v1/chat/completions', headers={'Origin':'https://ui.example', **headers})
denied = client.options('/v1/chat/completions', headers={'Origin':'https://other.example', **headers})
print(json.dumps({'options':middleware.kwargs, 'allowed_status':allowed.status_code, 'allowed_origin':allowed.headers.get('access-control-allow-origin'), 'allowed_headers':allowed.headers.get('access-control-allow-headers',''), 'denied_origin':denied.headers.get('access-control-allow-origin')}, sort_keys=True))
"""
    env = os.environ.copy()
    for key in ("APP_ENV", "ENV", "PY_ENV", "CORS_ALLOWED_ORIGINS"):
        env.pop(key, None)
    env.update(extra_env)
    result = subprocess.run([sys.executable, "-c", script], env=env, text=True, capture_output=True, check=True)
    return __import__("json").loads(result.stdout.strip().splitlines()[-1])


def test_production_empty_cors_is_not_wildcard():
    options = _cors_options({"APP_ENV":"production", "CORS_ALLOWED_ORIGINS":""})
    assert options["options"]["allow_origins"] == []
    assert options["options"]["allow_credentials"] is True


def test_configured_cors_supports_openwebui_preflight_headers():
    options = _cors_options({"APP_ENV":"production", "CORS_ALLOWED_ORIGINS":"https://ui.example"})
    assert options["options"]["allow_origins"] == ["https://ui.example"]
    assert set(options["options"]["allow_headers"]) >= {
        "Authorization", "Content-Type", "Idempotency-Key", "X-OpenWebUI-Chat-Id",
        "X-Conversation-Id", "X-Session-Id",
    }
    assert options["allowed_status"] == 200
    assert options["allowed_origin"] == "https://ui.example"
    assert "X-OpenWebUI-Chat-Id".lower() in options["allowed_headers"].lower()
    assert options["denied_origin"] is None
