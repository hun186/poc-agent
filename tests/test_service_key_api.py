from api.security.service_key_store import ServiceKeyStore

def test_admin_representation_excludes_digest(tmp_path):
    store=ServiceKeyStore(tmp_path/'keys.json'); item,raw=store.create('api',['model:read'],'admin')
    assert 'token_digest' not in item and raw not in str(item)

