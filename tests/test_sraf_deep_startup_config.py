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
