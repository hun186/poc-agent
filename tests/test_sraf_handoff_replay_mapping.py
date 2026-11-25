"""Real SQLite replay and real AuthStore, without API mounting or provider IO."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3

import pytest

from api.security.sraf_handoff_assertion import HandoffDenied
from api.security.sraf_handoff_replay import HandoffReplayStore
from api.security.sraf_handoff_mapping import (
    ExternalAccountBinding, HandoffSubjectMap, map_verified_chat_once,
)
from test_sraf_handoff_assertion import BODY, NOW, KEY, NEXT, sign, trust
from test_sraf_deep_scope_policy import setup


def consume(store, token, t=None, **kw):
    params = dict(body=BODY, method="POST", path="/v1/chat/completions", now=NOW)
    params.update(kw)
    return store.verify_once(t or trust(), token, **params)


def test_atomic_replay_across_instances_and_restart(tmp_path):
    path = tmp_path / "replay.db"
    store = HandoffReplayStore(path)
    store.initialize()
    token = sign()
    def attempt(_):
        try:
            consume(HandoffReplayStore(path), token)
            return True
        except HandoffDenied:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(8))) == 1
    with pytest.raises(HandoffDenied):
        consume(HandoffReplayStore(path), token, trust(KEY, NEXT))
    assert consume(store, sign()).assertion.message_id == "message-456"
    with sqlite3.connect(path) as con:
        dump = "\n".join(con.iterdump())
    for private in ("external-123", "chat-123", "message-456", "synthetic", token):
        assert private not in dump


def test_capacity_expiry_and_clock_rollback_cannot_replay(tmp_path):
    store = HandoffReplayStore(tmp_path / "replay.db", max_active=1)
    store.initialize()
    first = sign(ttl=5)
    consume(store, first)
    with pytest.raises(HandoffDenied, match="handoff_replay_capacity"):
        consume(store, sign())
    later = NOW + 6
    consume(store, sign(now=later), now=later)
    # Old nonce was pruned but durable expiry watermark still denies replay.
    with pytest.raises(HandoffDenied, match="handoff_replay_denied"):
        consume(store, first, now=NOW)


def test_missing_or_uninitialized_database_is_not_implicitly_created(tmp_path):
    path = tmp_path / "absent.db"
    store = HandoffReplayStore(path)
    with pytest.raises(HandoffDenied, match="handoff_replay_unavailable"):
        consume(store, sign())
    assert not path.exists()
    with sqlite3.connect(path):
        pass
    with pytest.raises(HandoffDenied, match="handoff_replay_unavailable"):
        consume(store, sign())


def test_explicit_mapping_actual_account_status_and_generation(tmp_path, monkeypatch):
    auth, _, _, _, _ = setup(tmp_path, monkeypatch)
    replay = HandoffReplayStore(tmp_path / "replay.db")
    replay.initialize()
    created = auth.get_user("other")["created_at"]
    binding = ExternalAccountBinding("webui-installation", "sraf-installation",
                                     "external-123", "other", created)
    mapping = HandoffSubjectMap((binding,))
    def mapped(token, m=mapping):
        return map_verified_chat_once(trust(), m, replay, token, body=BODY,
            method="POST", path="/v1/chat/completions", now=NOW)
    token = sign()
    identity = mapped(token)
    assert identity.owner_id == "other" and identity.account_created_at == created
    assert identity.role == "data_reader" and identity.message_id == "message-456"
    assert not hasattr(identity, "credential_id") and not hasattr(identity, "scopes")
    with pytest.raises(HandoffDenied):
        mapped(token)
    # Same-name subject is not identity proof; no automatic mapping.
    with pytest.raises(HandoffDenied, match="handoff_account_denied"):
        mapped(sign(external_subject="other"))
    with pytest.raises(HandoffDenied, match="handoff_account_denied"):
        mapped(sign(), HandoffSubjectMap((replace(binding, account_created_at="old"),)))
    auth.approve_user("other", "data_editor", approved_by="owner")
    assert mapped(sign()).role == "data_editor"
    auth.reject_user("other", rejected_by="owner")
    with pytest.raises(HandoffDenied, match="handoff_account_denied"):
        mapped(sign())
    auth.delete_user("other")
    with pytest.raises(HandoffDenied, match="handoff_account_denied"):
        mapped(sign())


def test_mapping_rejects_ambiguous_duplicate_subject_or_shared_account():
    b = ExternalAccountBinding("webui-installation", "sraf-installation",
                               "external-123", "other", "generation")
    for duplicate in (b, replace(b, owner_id="different"), replace(b, external_subject="different")):
        with pytest.raises(HandoffDenied, match="handoff_mapping_invalid"):
            HandoffSubjectMap((b, duplicate))
