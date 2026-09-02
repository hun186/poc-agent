import pytest
from api.security.signed_urls import sign_resource, verify_resource_token

def test_exact_signed_resource_binding(monkeypatch):
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "x" * 32)
    token = sign_resource("doc_fulltext", doc_id="a", format="txt", download="1", text_layer="raw")
    assert verify_resource_token(token, "doc_fulltext", doc_id="a", format="txt", download="1", text_layer="raw")
    with pytest.raises(ValueError):
        verify_resource_token(token, "doc_fulltext", doc_id="b", format="txt", download="1", text_layer="raw")
    with pytest.raises(ValueError): verify_resource_token(token + "x", "doc_fulltext", doc_id="a", format="txt", download="1", text_layer="raw")

def test_expired_token(monkeypatch):
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "x" * 32)
    token = sign_resource("doc_detail", ttl_seconds=1, doc_id="a")
    monkeypatch.setattr("api.security.signed_urls.time.time", lambda: 9999999999)
    with pytest.raises(ValueError): verify_resource_token(token, "doc_detail", doc_id="a")

