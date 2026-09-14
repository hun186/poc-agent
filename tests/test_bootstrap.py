import os

from config.bootstrap import bootstrap_env


def _write_env_files(project_root):
    (project_root / ".env").write_text("CONFIG_VALUE=base\nBASE_ONLY=base\n", encoding="utf-8")
    (project_root / ".env.dev").write_text("CONFIG_VALUE=dev\nPROFILE_ONLY=dev\n", encoding="utf-8")
    (project_root / ".env.prod").write_text("CONFIG_VALUE=prod\nPROFILE_ONLY=prod\n", encoding="utf-8")
    (project_root / ".env.local").write_text("CONFIG_VALUE=local\nLOCAL_ONLY=local\n", encoding="utf-8")


def test_bootstrap_logs_default_profile_and_preserves_precedence(tmp_path, monkeypatch, capsys):
    _write_env_files(tmp_path)
    for key in ("APP_ENV", "CONFIG_VALUE", "BASE_ONLY", "PROFILE_ONLY", "LOCAL_ONLY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CONFIG_VALUE", "os")

    env, loaded = bootstrap_env(project_root=tmp_path, force=True)

    output = capsys.readouterr().out
    assert "config profile: dev (selector only; not runtime mode)" in output
    assert "config precedence: OS environment > .env.local > .env.dev > .env" in output
    assert "env:dev" not in output
    assert env == "dev"
    assert loaded == [str(tmp_path / ".env"), str(tmp_path / ".env.dev"), str(tmp_path / ".env.local")]
    assert os.getenv("CONFIG_VALUE") == "os"
    assert os.getenv("BASE_ONLY") == "base"
    assert os.getenv("PROFILE_ONLY") == "dev"
    assert os.getenv("LOCAL_ONLY") == "local"


def test_bootstrap_logs_dynamic_profile_in_precedence(tmp_path, monkeypatch, capsys):
    _write_env_files(tmp_path)
    for key in ("CONFIG_VALUE", "BASE_ONLY", "PROFILE_ONLY", "LOCAL_ONLY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "prod")

    env, loaded = bootstrap_env(project_root=tmp_path, force=True)

    output = capsys.readouterr().out
    assert "config profile: prod (selector only; not runtime mode)" in output
    assert "config precedence: OS environment > .env.local > .env.prod > .env" in output
    assert "env:prod" not in output
    assert env == "prod"
    assert loaded == [str(tmp_path / ".env"), str(tmp_path / ".env.prod"), str(tmp_path / ".env.local")]
    assert os.getenv("CONFIG_VALUE") == "local"
    assert os.getenv("PROFILE_ONLY") == "prod"
