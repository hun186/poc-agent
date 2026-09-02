from api.security.service_key_store import ServiceKeyStore
import api.security.service_key_store as store_module

def bearer(monkeypatch, tmp_path, scopes):
    store = ServiceKeyStore(tmp_path / "service-keys.json")
    monkeypatch.setattr(store_module, "SERVICE_KEY_STORE", store)
    _, raw = store.create("test-client", scopes, "pytest")
    return {"Authorization": f"Bearer {raw}"}
