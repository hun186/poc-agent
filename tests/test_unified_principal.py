import pytest
from api.security.models import AuthPrincipal
from api.security.scopes import REGISTERED_SCOPES, REPORT_JOB_ADMIN, scopes_for_user_role, validate_scopes

def test_unknown_scope_is_rejected():
    with pytest.raises(ValueError): validate_scopes(["root:anything"])

def test_role_scopes_and_principal_id():
    assert REPORT_JOB_ADMIN not in scopes_for_user_role("data_reader")
    assert REPORT_JOB_ADMIN in scopes_for_user_role("superuser")
    assert AuthPrincipal("service", "openwebui", None, frozenset()).principal_id == "service:openwebui"

