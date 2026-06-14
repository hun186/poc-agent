from __future__ import annotations

from fastapi import APIRouter

from .auth_routes import router as auth_router
from .usage_routes import (
    _account_usage_stats,
    _bucket_key,
    _parse_audit_ts,
    account_usage_stats,
    router as usage_router,
)

router = APIRouter(tags=["auth"])
router.include_router(auth_router)
router.include_router(usage_router)

__all__ = [
    "_account_usage_stats",
    "_bucket_key",
    "_parse_audit_ts",
    "account_usage_stats",
    "router",
]
