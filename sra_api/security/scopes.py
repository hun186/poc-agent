from __future__ import annotations

from api.services.auth_support import ROLE_SUPERUSER

MODEL_READ = "model:read"
MODEL_INVOKE = "model:invoke"
REPORT_SYNC = "report:sync"
REPORT_JOB_CREATE = "report:job:create"
REPORT_JOB_READ = "report:job:read"
REPORT_JOB_DOWNLOAD = "report:job:download"
REPORT_JOB_ADMIN = "report:job:admin"
DOCUMENT_READ = "document:read"
REPORT_LEGACY_DOWNLOAD = "report:legacy-download"

REGISTERED_SCOPES = frozenset({MODEL_READ, MODEL_INVOKE, REPORT_SYNC,
    REPORT_JOB_CREATE, REPORT_JOB_READ, REPORT_JOB_DOWNLOAD, REPORT_JOB_ADMIN,
    DOCUMENT_READ, REPORT_LEGACY_DOWNLOAD})
SELF_SERVICE_SCOPES = REGISTERED_SCOPES - {REPORT_JOB_ADMIN}


def validate_scopes(scopes) -> frozenset[str]:
    result = frozenset(scopes)
    unknown = result - REGISTERED_SCOPES
    if unknown:
        raise ValueError(f"Unknown scope: {sorted(unknown)[0]}")
    return result


def scopes_for_user_role(role: str) -> frozenset[str]:
    return REGISTERED_SCOPES if role == ROLE_SUPERUSER else SELF_SERVICE_SCOPES

