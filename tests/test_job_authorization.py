from api.security.models import AuthPrincipal
from api.routers.report_jobs import _authorized
from types import SimpleNamespace

def test_job_owner_and_admin_isolation():
    job=SimpleNamespace(owner_kind='service',owner_id='batch-a')
    assert _authorized(job,AuthPrincipal('service','batch-a',None,frozenset()))
    assert not _authorized(job,AuthPrincipal('service','batch-b',None,frozenset()))
    assert _authorized(job,AuthPrincipal('service','admin',None,frozenset({'report:job:admin'})))

