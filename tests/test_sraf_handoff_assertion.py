"""Actual HMAC verification; no auth route, providers, or secret file writes."""
import base64
import hashlib
import hmac
import json

import pytest

from api.security.sraf_handoff_assertion import (
    HandoffDenied, HandoffKey, HandoffTrust, sign_chat_assertion, verify_chat_assertion,
)

BODY = b'{"messages":[{"role":"user","content":"synthetic"}]}'
NOW = 1_800_000_000
KEY = HandoffKey("current", b"A" * 32)
NEXT = HandoffKey("next", b"B" * 32)


def trust(*keys, issuer="webui-installation", audience="sraf-installation"):
    return HandoffTrust(issuer, audience, keys or (KEY,))


def sign(t=None, **changes):
    params = dict(key_id="current", external_subject="external-123",
                  chat_id="chat-123", message_id="message-456", body=BODY, now=NOW)
    params.update(changes)
    return sign_chat_assertion(t or trust(), **params)


def verify(token, t=None, **changes):
    params = dict(body=BODY, method="POST", path="/v1/chat/completions", now=NOW)
    params.update(changes)
    return verify_chat_assertion(t or trust(), token, **params)


def test_roundtrip_fresh_nonce_and_no_user_privilege_claims():
    a, b = verify(sign()), verify(sign())
    assert a.issuer == "webui-installation"
    assert a.audience == "sraf-installation"
    assert a.external_subject == "external-123"
    assert a.chat_id == b.chat_id == "chat-123"
    assert a.message_id == b.message_id == "message-456"
    assert a.nonce != b.nonce
    assert a.expires_at == NOW + 30
    assert a.body_sha256 == hashlib.sha256(BODY).hexdigest()
    assert not hasattr(a, "role") and not hasattr(a, "scopes")
    assert "external-123" not in repr(a)
    assert "AAAA" not in repr(KEY)


@pytest.mark.parametrize("changes", [
    {"body": BODY + b" "}, {"method": "GET"}, {"path": "/v1/report/jobs/deep"},
    {"now": NOW + 30}, {"now": NOW - 6}, {"now": True},
])
def test_request_and_time_bound(changes):
    with pytest.raises(HandoffDenied, match="^handoff_assertion_denied$"):
        verify(sign(), **changes)


def test_tamper_and_wrong_logical_deployment_denied():
    token = sign()
    for value in (token + "A", token.replace("srafh1.", "srafh2."),
                  token.replace(".current.", ".unknown."), "Bearer " + token,
                  "a" * 9000, token + ".extra"):
        with pytest.raises(HandoffDenied):
            verify(value)
    for target in (trust(issuer="other"), trust(audience="other"), trust(NEXT),
                   trust(HandoffKey("current", b"C" * 32))):
        with pytest.raises(HandoffDenied):
            verify(token, target)


def test_key_rotation_does_not_depend_on_host_ip_or_openwebui_login_key():
    old_token = sign()
    during = trust(KEY, NEXT)
    assert verify(old_token, during).external_subject == "external-123"
    new_token = sign(during, key_id="next")
    assert verify(new_token, trust(NEXT)).external_subject == "external-123"
    with pytest.raises(HandoffDenied):
        verify(old_token, trust(NEXT))


@pytest.mark.parametrize("changes", [
    {"external_subject": "a/b"}, {"external_subject": ""}, {"chat_id": "x\n"},
    {"message_id": "x" * 129}, {"ttl": 61}, {"ttl": True}, {"body": b""},
])
def test_signer_rejects_ambiguous_input(changes):
    with pytest.raises(HandoffDenied):
        sign(**changes)


def test_even_valid_mac_cannot_add_role_or_duplicate_claim():
    def b64(b):
        return base64.urlsafe_b64encode(b).decode().rstrip("=")
    _, kid, payload, _ = sign().split(".")
    raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    for extra in (b',"role":"admin"}', b',"sub":"another-account"}'):
        altered = b64(raw[:-1] + extra)
        mac = hmac.new(KEY.secret, b"SRAF-BACKEND-CHAT-HANDOFF-V1\x00"
                       + kid.encode() + b"\x00" + altered.encode(), hashlib.sha256).digest()
        with pytest.raises(HandoffDenied):
            verify("srafh1." + kid + "." + altered + "." + b64(mac))


def test_key_id_delimiter_not_accepted_at_configuration():
    with pytest.raises(HandoffDenied):
        HandoffKey("current.v2", b"C" * 32)
    # The dot delimiter restriction is only for the key ID, not subjects.
    assert verify(sign(external_subject="external.user")).external_subject == "external.user"
