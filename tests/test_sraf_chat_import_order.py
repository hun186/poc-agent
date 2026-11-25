"""Fresh process import orders must not depend on previous test collection."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", [
    "api.services.report_job_worker",
    "api.routers.chat",
    "api.services.sraf_chat_deep_dispatch",
    "api.services.sraf_chat_deep_turn",
])
def test_import_order(first, tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = """
import importlib
import sys
importlib.import_module(sys.argv[1])
from api.services.report_job_worker import ReportJobWorker
from api.services.sessions import ChatMessage
from api.routers.chat import router
from api.services import report_job_worker
from api.services.sraf_chat_deep_turn import resolve_deep_admission, DeepRuntimeUnavailable
from types import SimpleNamespace
assert report_job_worker.ChatMessage is ChatMessage
assert any(r.path == '/v1/chat/completions' for r in router.routes)
try:
    resolve_deep_admission(SimpleNamespace())
except DeepRuntimeUnavailable:
    pass
else:
    raise AssertionError('missing exact runtime must still be denied')
"""
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1",
               SRA_AUTH_USERS_FILE=str(tmp_path / "users.json"))
    subprocess.run([sys.executable, "-c", script, first], cwd=tmp_path,
                   env=env, check=True, timeout=60, capture_output=True)
