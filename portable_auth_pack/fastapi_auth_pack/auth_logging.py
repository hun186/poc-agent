from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_failed_login_attempt(
    username: str,
    *,
    reason: str,
    client_host: str | None,
    user_agent: str | None,
    role: str | None = None,
    status_value: str | None = None,
) -> None:
    """Emit an immediate, password-free warning log for failed login monitoring."""
    logger.warning(
        "auth.login.failed username=%s reason=%s client_host=%s user_agent=%s role=%s status=%s",
        username,
        reason,
        client_host or "-",
        user_agent or "-",
        role or "-",
        status_value or "-",
    )
