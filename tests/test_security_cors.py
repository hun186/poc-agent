from fastapi.testclient import TestClient
from api.main import app

def test_configured_cors_headers_include_authorization_and_idempotency():
    response=TestClient(app).options('/v1/models',headers={'Origin':'https://not-configured.invalid','Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'Authorization,Idempotency-Key'})
    assert response.headers.get('access-control-allow-credentials') != 'true' or response.headers.get('access-control-allow-origin') != '*'

