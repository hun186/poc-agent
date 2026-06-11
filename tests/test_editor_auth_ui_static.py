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



def test_editor_auth_ui_reset_token_dialog_is_copyable() -> None:
    html = _editor_html()

    assert 'id="resetTokenModal"' in html
    assert 'id="resetTokenModalValue" readonly' in html
    assert 'id="copyResetTokenBtn"' in html
    assert 'navigator.clipboard.writeText' in html
    assert 'showResetTokenDialog(username, data.reset_token)' in html
    assert 'alert(`請用安全管道交付給 ${username}' not in html


def test_editor_navigation_is_top_collapsible() -> None:
    html = _editor_html()

    assert 'class="card top-nav hidden"' in html
    assert 'id="mainNavDetails" open' in html
    assert '.top-nav { position: sticky; top: 0;' in html
    assert 'function collapseMainNav()' in html
    assert 'switchMainTab(btn.dataset.mainTab); collapseMainNav();' in html


def test_portable_auth_pack_reset_token_dialog_is_copyable() -> None:
    html = Path("portable_auth_pack/static/login_admin_minimal.html").read_text(encoding="utf-8")

    assert 'id="resetTokenModal"' in html
    assert 'id="resetTokenModalValue" readonly' in html
    assert 'id="copyResetTokenBtn"' in html
    assert 'navigator.clipboard.writeText' in html
    assert 'showResetTokenDialog(username, data.reset_token)' in html
    assert 'alert(`請用安全管道交付給 ${username}' not in html
