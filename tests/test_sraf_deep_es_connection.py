"""Real SDK construction with no network; no live Elasticsearch claim."""
from pathlib import Path

import certifi
from elasticsearch import Elasticsearch
import pytest

from api.services.sraf_deep_es_connection import (
    DeepESConfigError, DeepESConnection, build_deep_es_connection,
)


def settings():
    return {"ES_URL": "https://127.0.0.1:9200",
            "ES_USERNAME": "synthetic-reader",
            "ES_PASSWORD": "synthetic-password",
            "SRAF_DEEP_ES_CA_CERT": certifi.where()}


def test_build_real_dedicated_client_no_io_or_global_fallback(tmp_path, monkeypatch):
    from elastic_transport import Transport

    def forbidden(*a, **k):
        raise AssertionError("no provider call during construction")

    monkeypatch.setattr(Transport, "perform_request", forbidden)
    monkeypatch.setenv("SRA_VERCEL_MOCK_MODE", "force")
    first = build_deep_es_connection(settings(), project_root=tmp_path)
    second = build_deep_es_connection(settings(), project_root=tmp_path)
    try:
        client = first.get_client()
        assert type(client) is Elasticsearch
        assert first.get_client() is client
        assert second.get_client() is not client
        node = client.transport.node_pool.all()[0].config
        assert node.scheme == "https"
        assert node.verify_certs is True
        assert node.ssl_assert_hostname is not False
        assert node.ca_certs == certifi.where()
        assert client._max_retries == 0
        assert client._retry_on_timeout is False
        assert client._retry_on_status == ()
        assert "synthetic-password" not in repr(first)
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("value", [
    "http://127.0.0.1:9200", "https://user:password@127.0.0.1:9200",
    "https://127.0.0.1:9200/path", "https://127.0.0.1:9200?x=1",
    "https://127.0.0.1:9200#", "https://127.0.0.1",
    "https://127.0.0.1:9200 ", "https://%31.0.0.1:9200",
])
def test_bad_urls_fail_closed(tmp_path, value):
    env = settings()
    env["ES_URL"] = value
    with pytest.raises(DeepESConfigError, match="^deep_es_config_unverified$"):
        build_deep_es_connection(env, project_root=tmp_path)


@pytest.mark.parametrize("key", ["ES_URL", "ES_USERNAME", "ES_PASSWORD",
                                "SRAF_DEEP_ES_CA_CERT"])
def test_missing_config_has_no_default_credentials_or_implicit_trust(tmp_path, key):
    env = settings()
    del env[key]
    with pytest.raises(DeepESConfigError, match="^deep_es_config_unverified$"):
        build_deep_es_connection(env, project_root=tmp_path)


def test_real_client_required():
    class Mock:
        def options(self, **kw):
            return self
        def search(self, **kw):
            return {}
    with pytest.raises(DeepESConfigError, match="^deep_es_real_client_required$"):
        DeepESConnection(Mock())


def test_relative_default_ca_path_reuses_existing_project_location(tmp_path):
    import shutil
    ca = tmp_path / "agent" / "certs" / "http_ca.crt"
    ca.parent.mkdir(parents=True)
    shutil.copyfile(certifi.where(), ca)
    env = settings()
    del env["SRAF_DEEP_ES_CA_CERT"]
    connection = build_deep_es_connection(env, project_root=tmp_path)
    try:
        assert connection.get_client().transport.node_pool.all()[0].config.ca_certs == str(ca)
    finally:
        connection.close()
