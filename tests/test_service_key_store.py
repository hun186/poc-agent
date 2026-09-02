import json
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

