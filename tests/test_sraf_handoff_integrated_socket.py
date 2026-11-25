"""Generated Pipe -> actual private Uvicorn -> real auth/replay/Job SQLite.

Only the OpenWebUI DB rows and ordinary Agent/render/persistence boundary
are synthetic (shared fixtures). No live OpenWebUI, ES, LLM or generated
report artifact is claimed. Real socket, TLS, admission and owner API checks.
"""
import asyncio
import base64
import json
import shutil
import subprocess

import pytest

from api.core import url_utils
from api.routers import report_jobs
from api.security.principal import current_principal
from api.security.sraf_handoff_config import load_handoff_receiver_config
from api.security.sraf_handoff_lifecycle import PrivateListenerRuntime
from api.services.auth_support import AuthUser
from api.services.auth_tokens import create_token
from test_sraf_chat_deep_dispatch import http, jobs, PROMPT
from test_sraf_handoff_assertion import KEY
from test_sraf_handoff_lifecycle import free_port
from test_sraf_openwebui_backend_pipe import backend, bundle


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def _bearer(auth, name):
    row = auth.get_user(name)
    return {"Authorization": "Bearer " + create_token(
        AuthUser(name, row["role"], "active"), auth.get_user)}


@pytest.mark.parametrize("mode", ["local_http", "verified_https"])
def test_bundle_to_private_socket_owner_and_relocated_retry(
        tmp_path, monkeypatch, http, backend, bundle, mode):
    public, app, identity, events, auth = http
    app.include_router(report_jobs.router)
    # Exercise real browser bearer authentication rather than the HTTP
    # fixture's dependency override for its synthetic ordinary Agent.
    app.dependency_overrides.pop(current_principal)
    monkeypatch.setattr(url_utils, "PUBLIC_API_BASE", "https://sraf.example.test")
    rows, args = backend
    rows["first"].content = PROMPT
    args["body"]["messages"][0]["content"] = PROMPT
    args["body"]["stream"] = False
    pipe = bundle.Pipe()
    pipe.valves.ENABLED = True

    root = tmp_path / "original"
    root.mkdir()
    secret = root / "issuer.key"
    secret.write_bytes(base64.urlsafe_b64encode(KEY.secret).rstrip(b"="))
    secret.chmod(0o600)
    listener = {"mode": mode, "bind_host": "127.0.0.1", "port": free_port()}
    if mode == "verified_https":
        openssl = shutil.which("openssl")
        if openssl is None:
            pytest.skip("openssl required for real temporary TLS fixture")
        cert, key = root / "receiver.pem", root / "receiver-key.pem"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-days", "1", "-subj", "/CN=fixture.invalid",
                        "-addext", "subjectAltName=IP:127.0.0.1",
                        "-keyout", str(key), "-out", str(cert)],
                       check=True, capture_output=True, timeout=30)
        listener.update(cert_file=cert.name, key_file=key.name)
    receiver = {
        "schema": "sraf_handoff_receiver_v1", "issuer": "webui-installation",
        "audience": "sraf-installation", "keys": [{"id": "current", "secret_file": secret.name}],
        "bindings": [{"external_subject": "external-123", "owner_id": "owner",
                      "account_created_at": auth.get_user("owner")["created_at"]}],
        "replay_db": "replay.sqlite", "replay_max_active": 50, "listener": listener,
    }
    transport = {"mode": mode,
                 "origin": ("https" if mode == "verified_https" else "http")
                           + f"://127.0.0.1:{listener['port']}",
                 "timeout_seconds": 10}
    if mode == "verified_https":
        transport["ca_file"] = "receiver.pem"
    sender = {"schema": "sraf_openwebui_sender_v1", "issuer": receiver["issuer"],
              "audience": receiver["audience"], "key_id": "current",
              "secret_file": secret.name, "transport": transport}

    def config_at(directory, *, initialize=False):
        _write(directory / "receiver.json", receiver)
        _write(directory / "sender.json", sender)
        env = {"SRAF_HANDOFF_ENABLED": "1",
               "SRAF_HANDOFF_CONFIG_FILE": str(directory / "receiver.json"),
               "PUBLIC_API_BASE": "https://sraf.example.test"}
        monkeypatch.setenv("SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE", str(directory / "sender.json"))
        if initialize:
            cfg = load_handoff_receiver_config(env, project_root=tmp_path, require_replay=False)
            cfg.replay.initialize_new()
        return load_handoff_receiver_config(env, project_root=tmp_path)

    async def invoke(cfg, *, reject_bad_tls=False):
        runtime = PrivateListenerRuntime(app, cfg)
        try:
            await runtime.start()
            if reject_bad_tls:
                good = transport["origin"]
                transport["origin"] = good.replace("127.0.0.1", "localhost")
                _write(root / "sender.json", sender)
                with pytest.raises(bundle.PipeError):
                    await pipe.pipe(**args)
                assert not events and not jobs(app)
                transport["origin"] = good
                _write(root / "sender.json", sender)
            return await pipe.pipe(**args)
        finally:
            await runtime.stop()
            assert runtime.task.done() and not runtime.accepting

    first = asyncio.run(invoke(config_at(root, initialize=True),
                               reject_bad_tls=mode == "verified_https"))
    msg = first["choices"][0]["message"]
    deep = msg["context"]["deep_report"]
    job_id = deep["job_id"]
    assert deep["status"] == "queued"
    assert deep["browser_status_url"] == "https://sraf.example.test/report-jobs#job=" + job_id
    assert "一般版正文" in msg["content"] and deep["browser_status_url"] in msg["content"]
    assert msg["context"]["word_export"]["url"].startswith("https://sraf.example.test/")
    assert events[:4] == ["ordinary", "session", "state", "trace"]
    assert len(jobs(app)) == 1
    endpoint = "/v1/report/jobs/" + job_id
    assert public.get(endpoint).status_code == 401
    owner = _bearer(auth, "owner")
    other = _bearer(auth, "other")
    own = public.get(endpoint, headers=owner)
    assert own.status_code == 200 and own.json()["status"] == "queued"
    assert own.json()["nround_progress_available"] is True
    assert public.get(endpoint + "/word", headers=owner).status_code == 409
    assert public.get(endpoint, headers=other).status_code == 404
    assert public.get(endpoint + "/word", headers=other).status_code == 404

    # Quiescent directory/port migration with same identity, replay DB,
    # and report store. No key reset, scope widening, or new Job.
    moved = tmp_path / "relocated"
    shutil.move(str(root), str(moved))
    previous_port = listener["port"]
    listener["port"] = free_port()
    transport["origin"] = transport["origin"].rsplit(":", 1)[0] + ":" + str(listener["port"])
    identity["receipt"] = None
    retry = asyncio.run(invoke(config_at(moved)))
    assert retry["choices"][0]["message"]["context"]["deep_report"]["job_id"] == job_id
    assert retry["choices"][0]["message"]["context"]["word_export"]["session_id"] == msg["context"]["word_export"]["session_id"]
    assert len(jobs(app)) == 1
    # Actual server-side account revocation denies subsequent signed calls
    # and the previously issued browser credential; no new Job.
    auth.reject_user("owner", rejected_by="operator")
    with pytest.raises(bundle.PipeError):
        asyncio.run(invoke(config_at(moved)))
    assert public.get(endpoint, headers=owner).status_code == 401
    assert len(events) == 8
