import json
from datetime import datetime, timedelta, timezone
import pytest
from api.security.service_key_store import ServiceKeyStore

def test_service_key_is_one_time_and_revocable(tmp_path):
    path = tmp_path / "keys.json"; store = ServiceKeyStore(path)
    item, raw = store.create("owui", ["model:read"], "admin")
    assert raw.startswith("sra_sk_") and len(raw) > 50
    persisted = path.read_text()
    assert raw not in persisted and "token_digest" in persisted
    assert store.resolve(raw)["name"] == "owui"
    assert "token_digest" not in store.list_keys()[0]
    store.revoke(item["key_id"], "admin")
    assert store.resolve(raw) is None


def test_expiration_is_validated_normalized_and_corruption_fails_closed(tmp_path):
    path = tmp_path / "keys.json"; store = ServiceKeyStore(path)
    with pytest.raises(ValueError): store.create(" ", ["model:read"], "admin")
    with pytest.raises(ValueError): store.create("x", ["model:read"], "admin", "not-a-date")
    with pytest.raises(ValueError): store.create("x", ["model:read"], "admin", "2026-01-01T00:00:00")
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    item, raw = store.create("x", ["model:read"], "admin", expiry)
    assert item["expires_at"].endswith("+00:00") and store.resolve(raw)
    original = "{broken"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(Exception): store.list_keys()
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("key_id", ["", "ABCDEF0123456789", "0123456789abcdeg", "0123456789abcde"])
def test_caller_selected_key_id_must_be_exact_lowercase_hex(tmp_path, key_id):
    store = ServiceKeyStore(tmp_path / "keys.json")
    with pytest.raises(ValueError, match="16 lowercase hexadecimal"):
        store.create("x", ["model:read"], "admin", key_id=key_id)


def test_caller_selected_key_id_rejects_collisions(tmp_path):
    store = ServiceKeyStore(tmp_path / "keys.json")
    store.create("x", ["model:read"], "admin", key_id="0123456789abcdef")
    with pytest.raises(ValueError, match="already exists"):
        store.create("y", ["model:read"], "admin", key_id="0123456789abcdef")


def test_default_creation_still_generates_a_valid_key_id(tmp_path):
    item, _ = ServiceKeyStore(tmp_path / "keys.json").create("x", ["model:read"], "admin")
    assert len(item["key_id"]) == 16
    assert set(item["key_id"]) <= set("0123456789abcdef")
