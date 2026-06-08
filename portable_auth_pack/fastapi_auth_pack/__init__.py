"""Portable FastAPI account-management pack."""

from .auth_store import AUTH_STORE, AuthStore, AuthUser, create_token, parse_token
from .dependencies import current_user, require_superuser
from .router import router

__all__ = [
    "AUTH_STORE",
    "AuthStore",
    "AuthUser",
    "create_token",
    "parse_token",
    "current_user",
    "require_superuser",
    "router",
]
