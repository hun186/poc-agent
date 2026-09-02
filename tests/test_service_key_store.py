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
