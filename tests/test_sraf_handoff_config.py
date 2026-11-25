"""Real temporary config files and replay DB; no provider/network/auth startup."""
import base64
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from api.security.sraf_handoff_assertion import HandoffDenied
from api.security.sraf_handoff_config import load_handoff_receiver_config
from tools.sraf_handoff_preflight import main
from test_sraf_handoff_assertion import BODY, NOW, KEY, sign, trust


def fixture(root):
    root.mkdir()
    secret = root / "issuer.key"
    secret.write_bytes(base64.urlsafe_b64encode(KEY.secret).rstrip(b"=") + b"\n")
    secret.chmod(0o600)
    obj = {"schema": "sraf_handoff_receiver_v1", "issuer": "webui-installation",
           "audience": "sraf-installation",
           "keys": [{"id": "current", "secret_file": "issuer.key"}],
           "bindings": [{"external_subject": "external-123", "owner_id": "mapped-user",
                         "account_created_at": "synthetic-generation"}],
           "replay_db": "replay.sqlite", "replay_max_active": 12,
           "listener": {"mode": "local_http", "bind_host": "127.0.0.1", "port": 19002}}
    path = root / "receiver.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    env = {"SRAF_HANDOFF_ENABLED": "1", "SRAF_HANDOFF_CONFIG_FILE": str(path),
           "PUBLIC_API_BASE": "http://sraf.example.test:9002"}
    return env, obj, path


def load(env, root, **kwargs):
    return load_handoff_receiver_config(env, project_root=root, **kwargs)


def test_default_disabled_does_not_read_any_file(tmp_path):
    assert load({"SRAF_HANDOFF_CONFIG_FILE": "absent"}, tmp_path) is None
    assert load({"SRAF_HANDOFF_ENABLED": "0", "SRAF_HANDOFF_CONFIG_FILE": "absent"}, tmp_path) is None
    with pytest.raises(HandoffDenied):
        load({"SRAF_HANDOFF_ENABLED": "yes"}, tmp_path)


def test_portable_relative_config_and_explicit_replay_creation(tmp_path):
    root = tmp_path / "original"
    env, _, path = fixture(root)
    with pytest.raises(HandoffDenied, match="handoff_replay_unavailable"):
        load(env, tmp_path)
    assert not (root / "replay.sqlite").exists()
    initial = load(env, tmp_path, require_replay=False)
    initial.replay.initialize_new()
    config = load(env, tmp_path)
    assert config.listener.port == 19002
    assert config.public_base == "http://sraf.example.test:9002"
    assert config.mapping.bindings[0].owner_id == "mapped-user"
    assert "mapped-user" not in repr(config) and "AAAA" not in repr(config)
    token = sign()
    config.replay.verify_once(config.trust, token, body=BODY,
        method="POST", path="/v1/chat/completions", now=NOW)
    with pytest.raises(HandoffDenied, match="handoff_replay_create_denied"):
        initial.replay.initialize_new()
    # Quiescent synthetic relocation of config, key and replay together.
    target = tmp_path / "relocated"
    shutil.move(str(root), str(target))
    env["SRAF_HANDOFF_CONFIG_FILE"] = str(target / path.name)
    relocated = load(env, tmp_path)
    with pytest.raises(HandoffDenied, match="handoff_replay_denied"):
        relocated.replay.verify_once(relocated.trust, token, body=BODY,
            method="POST", path="/v1/chat/completions", now=NOW)


@pytest.mark.parametrize("change", [
    {"extra": "x"}, {"schema": "wrong"}, {"keys": []}, {"bindings": []},
    {"replay_db": ""}, {"listener": {"mode": "local_http", "bind_host": "0.0.0.0", "port": 19002}},
    {"keys": [{"id": "current", "secret_file": "absent"}]},
    {"keys": [{"id": "current", "secret_file": "issuer.key", "secret": "forbidden"}]},
])
def test_malformed_config_never_creates_replay(tmp_path, change):
    root = tmp_path / "cfg"
    env, obj, path = fixture(root)
    obj.update(change)
    path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(HandoffDenied):
        load(env, tmp_path, require_replay=False)
    assert not (root / "replay.sqlite").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX private key file permissions")
def test_world_readable_signing_secret_rejected(tmp_path):
    root = tmp_path / "cfg"
    env, _, _ = fixture(root)
    (root / "issuer.key").chmod(0o644)
    with pytest.raises(HandoffDenied):
        load(env, tmp_path, require_replay=False)


def test_existing_empty_replay_db_is_not_repaired(tmp_path):
    root = tmp_path / "cfg"
    env, _, _ = fixture(root)
    path = root / "replay.sqlite"
    with sqlite3.connect(path):
        pass
    with pytest.raises(HandoffDenied, match="handoff_replay_unavailable"):
        load(env, tmp_path)
    config = load(env, tmp_path, require_replay=False)
    with pytest.raises(HandoffDenied, match="handoff_replay_create_denied"):
        config.replay.initialize_new()


def test_no_check_cli_is_inert(capsys):
    assert main([]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_TESTED"
