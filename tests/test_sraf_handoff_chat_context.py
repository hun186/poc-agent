"""Real signature, replay DB, AuthStore, scoped session and deep policy checks."""
from dataclasses import replace
import time

import pytest

from api.security.scopes import REPORT_JOB_ADMIN, MODEL_INVOKE
from api.security.sraf_handoff_assertion import HandoffDenied
from api.security.sraf_handoff_replay import HandoffReplayStore
from api.security.sraf_handoff_mapping import ExternalAccountBinding, HandoffSubjectMap
from api.security.sraf_handoff_chat_context import prepare_handoff_chat, revalidate_handoff_chat
from api.services.sraf_deep_scope_policy import binding_for_principal, DeepScopeDenied
from api.services.sraf_session_namespace import scoped_session_owned
from test_sraf_handoff_assertion import BODY, sign, trust
from test_sraf_deep_scope_policy import setup, QUESTION


@pytest.fixture
def env(tmp_path, monkeypatch):
    auth, store, policy, owner, other = setup(tmp_path, monkeypatch)
    replay = HandoffReplayStore(tmp_path / "replay.db")
    replay.initialize()
    mapping = HandoffSubjectMap(tuple(
        ExternalAccountBinding("webui-installation", "sraf-installation",
            subject, name, auth.get_user(name)["created_at"])
        for subject, name in (("external-123", "owner"), ("external-456", "other"))))
    return auth, store, policy, replay, mapping, owner, other


def header(**changes):
    return (b"x-sraf-backend-assertion", sign(now=int(time.time()), **changes).encode())


def prepare(env, headers, **changes):
    params = dict(headers=headers, body=BODY, method="POST", path="/v1/chat/completions")
    params.update(changes)
    return prepare_handoff_chat(trust(), env[4], env[3], **params)


def test_stable_scope_and_turn_independent_of_nonce_and_no_admin_grant(env):
    first = prepare(env, (header(),))
    second = prepare(env, (header(),))
    assert first.principal.subject == "owner"
    assert first.principal.account_created_at == env[4].bindings[0].account_created_at
    assert MODEL_INVOKE in first.principal.scopes
    assert REPORT_JOB_ADMIN not in first.principal.scopes
    assert first.principal.credential_id != second.principal.credential_id
    assert first.session == second.session and first.turn_token == second.turn_token
    next_turn = prepare(env, (header(message_id="next-message"),))
    assert next_turn.session == first.session and next_turn.turn_token != first.turn_token
    next_chat = prepare(env, (header(chat_id="next-chat"),))
    assert next_chat.session != first.session and next_chat.turn_token != first.turn_token
    other = prepare(env, (header(external_subject="external-456"),))
    assert other.session != first.session and other.turn_token != first.turn_token
    assert not scoped_session_owned(first.session.key, other.principal)
    assert scoped_session_owned(first.session.key, env[5])
    revalidate_handoff_chat(first, env[4])
    job, created = env[2].admit(env[1], principal=first.principal,
                                prompt=QUESTION, idempotency_key=first.turn_token)
    assert created and job.owner_id == "owner"
    with pytest.raises(DeepScopeDenied):
        env[2].admit(env[1], principal=other.principal,
                     prompt=QUESTION, idempotency_key=other.turn_token)


@pytest.mark.parametrize("name", [
    b"Authorization", b"Cookie", b"Idempotency-Key", b"X-SRAF-OpenWebUI-Chat-Id",
    b"x-openwebui-chat-id", b"x-conversation-id", b"x-session-id",
])
def test_no_conflicting_headers_or_ordinary_fallback(env, name):
    token = header()
    with pytest.raises(HandoffDenied):
        prepare(env, (token, (name, b"forged")))
    # Rejected before consuming assertion, then exact admitted once.
    prepare(env, (token,))
    with pytest.raises(HandoffDenied):
        prepare(env, (token,))


def test_duplicate_headers_query_and_wrong_body_denied(env):
    token = header()
    for headers, kwargs in [
        ((), {}), ((token, token), {}), ((token,), {"query_string": b"user=owner"}),
        ((token,), {"body": BODY + b" "}), ((token,), {"method": "GET"}),
    ]:
        with pytest.raises(HandoffDenied):
            prepare(env, headers, **kwargs)
    prepare(env, (token,))


def test_revocation_generation_or_mapping_change_fences_pending_request(env):
    context = prepare(env, (header(),))
    auth, store, policy, _, mapping, _, _ = env
    with pytest.raises(HandoffDenied):
        revalidate_handoff_chat(context, HandoffSubjectMap((mapping.bindings[1],)))
    wrong = replace(context.principal, account_created_at="different-generation")
    assert binding_for_principal(wrong) is None
    with pytest.raises(DeepScopeDenied):
        policy.admit(store, principal=wrong, prompt=QUESTION, idempotency_key="wrong")
    auth.reject_user("owner", rejected_by="operator")
    with pytest.raises(HandoffDenied):
        revalidate_handoff_chat(context, mapping)
    assert binding_for_principal(context.principal) is None
