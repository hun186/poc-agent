from __future__ import annotations

from pathlib import Path


def _editor_html() -> str:
    return Path("api/static/editor.html").read_text(encoding="utf-8")


def test_editor_auth_ui_exposes_password_recovery_and_change_controls() -> None:
    html = _editor_html()

    assert 'id="forgotPasswordBtn"' in html
    assert 'id="recoverPasswordBtn"' in html
    assert 'id="forgotResetToken"' in html
    assert 'id="forgotNewPassword"' in html
    assert 'id="accountCard"' in html
    assert 'id="changePasswordBtn"' in html
    assert 'id="currentPassword"' in html
    assert 'id="newPassword"' in html
    assert "'/v1/auth/change-password'" in html
    assert "'/v1/auth/forgot-password'" in html
    assert "'/v1/auth/reset-password'" in html


def test_editor_auth_ui_exposes_logout_reset_and_login_audit_controls() -> None:
    html = _editor_html()

    assert "'/v1/auth/logout'" in html
    assert 'data-issue-reset-token=' in html
    assert 'data-reset-user=' in html
    assert '/password-reset-token`' in html
    assert '/reset-password`' in html
    assert 'id="refreshLoginAuditBtn"' in html
    assert 'id="loginAuditHits"' in html
    assert '/v1/auth/login-audit?limit=' in html
