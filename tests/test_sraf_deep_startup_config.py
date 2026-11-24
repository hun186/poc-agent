"""Offline configuration tests; never contact providers or the AuthStore."""
import json

import pytest

from api.services.sraf_deep_startup_config import (
    DeepStartupConfigError, load_deep_startup_config,
)


def valid():
    return {
        "SRAF_DEEP_REPORT_ENABLED": "1",
        "SRAF_DEEP_OWNER_GRANTS_JSON": json.dumps([
            {"owner_id": "synthetic-owner", "account_created_at": "2026-01-01T00:00:00Z",
             "indexes": ["synthetic_index"]},
        ]),
        "SRAF_DEEP_MAX_ACTIVE_JOBS": "3",
        "SRAF_DEEP_OLLAMA_ENDPOINT": "http://127.0.0.1:11434",
        "SRAF_DEEP_PLANNER_MODEL": "synthetic-plan",
        "SRAF_DEEP_SEMANTIC_MODEL": "synthetic-semantic",
        "SRAF_DEEP_REPORT_MODEL": "synthetic-report",
        "SRAF_DEEP_NUM_CTX": "131072",
    }


def test_default_disabled_and_no_implicit_enable():
    assert load_deep_startup_config({}) is None
    env = valid()
    del env["SRAF_DEEP_REPORT_ENABLED"]
    assert load_deep_startup_config(env) is None
    assert load_deep_startup_config({"SRAF_DEEP_REPORT_ENABLED": "0",
                                     "SRAF_DEEP_OWNER_GRANTS_JSON": "not-json"}) is None


def test_explicit_config_preserves_private_policy_and_model_roles():
    env = valid()
    result = load_deep_startup_config(env)
    assert result.policy.grants[0].indexes == ("synthetic_index",)
    assert result.policy.max_active_jobs == 3
    assert result.models.endpoint == "http://127.0.0.1:11434/api/chat"
    assert result.models.planner_model == "synthetic-plan"
    assert result.models.semantic_model == "synthetic-semantic"
    assert result.models.report_model == "synthetic-report"
    assert result.models.num_ctx == 131072
    assert "synthetic-owner" not in repr(result)


@pytest.mark.parametrize("key", [k for k in valid() if k != "SRAF_DEEP_REPORT_ENABLED"])
def test_enabled_missing_settings_fail_closed(key):
    env = valid()
    del env[key]
    with pytest.raises(DeepStartupConfigError, match="^deep_startup_config_invalid$"):
        load_deep_startup_config(env)


@pytest.mark.parametrize("flag", ["true", "yes", "", " 1", "2", "false"])
def test_ambiguous_opt_in_rejected(flag):
    with pytest.raises(DeepStartupConfigError, match="^deep_startup_flag_invalid$"):
        load_deep_startup_config({"SRAF_DEEP_REPORT_ENABLED": flag})


@pytest.mark.parametrize(("key", "bad"), [
    ("SRAF_DEEP_MAX_ACTIVE_JOBS", "0"),
    ("SRAF_DEEP_MAX_ACTIVE_JOBS", "1001"),
    ("SRAF_DEEP_NUM_CTX", "8192"),
    ("SRAF_DEEP_NUM_CTX", "1e5"),
    ("SRAF_DEEP_OLLAMA_ENDPOINT", "https://example.com:443"),
    ("SRAF_DEEP_REPORT_MODEL", "synthetic-cloud"),
    ("SRAF_DEEP_OWNER_GRANTS_JSON", "[]"),
    ("SRAF_DEEP_OWNER_GRANTS_JSON", '{"owner_id":"x"}'),
    ("SRAF_DEEP_OWNER_GRANTS_JSON", '[{"owner_id":"x","owner_id":"y","account_created_at":"z","indexes":["a"]}]'),
    ("SRAF_DEEP_OWNER_GRANTS_JSON", '[{"owner_id":"x","account_created_at":"z","indexes":"a"}]'),
    ("SRAF_DEEP_OWNER_GRANTS_JSON", '[{"owner_id":"x","account_created_at":"z","indexes":["*"]}]'),
    ("SRAF_DEEP_OWNER_GRANTS_JSON", '[{"owner_id":"x","account_created_at":"z","indexes":["a"],"extra":true}]'),
    ("SRAF_DEEP_OWNER_GRANTS_JSON", '[{"owner_id":"x","account_created_at":"z","indexes":["a"]},{"owner_id":"x","account_created_at":"z2","indexes":["b"]}]'),
])
def test_invalid_configuration_redacted(key, bad):
    env = valid()
    env[key] = bad
    with pytest.raises(DeepStartupConfigError, match="^deep_startup_config_invalid$") as exc:
        load_deep_startup_config(env)
    assert exc.value.__suppress_context__


def test_config_is_detached_from_mutable_environment():
    env = valid()
    result = load_deep_startup_config(env)
    env["SRAF_DEEP_REPORT_MODEL"] = "changed"
    env["SRAF_DEEP_OWNER_GRANTS_JSON"] = "[]"
    assert result.models.report_model == "synthetic-report"
    assert result.policy.grants[0].owner_id == "synthetic-owner"


def test_fresh_process_config_does_not_import_auth_or_agent(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    script = '''
import sys, json
from importlib.abc import MetaPathFinder
class DenyRuntime(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('api.services.auth_', 'sra_api.services.auth_', 'agent.', 'api.services.sraf_deep_scope_policy', 'api.services.sraf_adaptive_job_runtime')):
            raise AssertionError('unexpected runtime import: ' + fullname)
sys.meta_path.insert(0, DenyRuntime())
from api.services.sraf_deep_startup_config import load_deep_startup_config
assert load_deep_startup_config({}) is None
assert load_deep_startup_config(json.loads(sys.argv[1])).policy.max_active_jobs == 3
'''
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1',
               SRA_AUTH_USERS_FILE=str(tmp_path / 'auth' / 'users.json'))
    subprocess.run([sys.executable, '-c', script, json.dumps(valid())],
                   cwd=tmp_path, env=env, check=True, timeout=30)
    assert not (tmp_path / 'auth').exists()
