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


def test_editor_navigation_is_header_multilevel_and_collapsible() -> None:
    html = _editor_html()

    assert 'id="mainNav" class="header-nav hidden"' in html
    assert 'class="nav-root-btn" type="button" data-nav-root="content"' in html
    assert 'id="adminNavGroup" data-nav-root="system"' in html
    assert 'id="navSubPanel" class="nav-subpanel hidden" aria-label="第二層功能選單"' in html
    assert 'class="nav-menu" data-nav-menu="content"' in html
    assert 'class="nav-level" open' in html
    assert 'function setActiveNavRoot(root)' in html
    assert 'function collapseMainNav()' in html
    assert "setAttribute('aria-expanded', active ? 'true' : 'false')" in html
    assert 'SraAuditTools.bindProgressiveNav' in html
    assert 'getActiveRoot: () => state.activeNavRoot' in html
    assert 'setActiveRoot: setActiveNavRoot' in html
    assert 'setActiveRoot,\n    collapse: collapseMainNav' not in html
    assert 'id="mainNavDetails"' not in html


def test_editor_workspace_separates_document_and_account_work_areas() -> None:
    html = _editor_html()

    assert 'id="workspaceGrid" class="grid"' in html
    assert 'id="editorCard" class="card"' in html
    assert "$('editorCard').classList.toggle('hidden', !showEditor);" in html
    assert "$('workspaceGrid').classList.toggle('single-pane', !showEditor);" in html
    assert 'id="accountAuditCard" class="card hidden"' in html
    assert '文件異動紀錄查詢' in html
    assert '帳號操作紀錄查詢' in html
    assert 'data-main-tab="account-audit"' in html
    assert "qs.set('action_prefix', 'editor.')" in html
    assert "qs.set('action_prefix', 'auth.')" in html


def test_editor_usage_stats_filters_use_shared_chart_module() -> None:
    html = _editor_html()
    tools = Path("api/static/audit_tools.js").read_text(encoding="utf-8")

    assert '<script src="/static/audit_tools.js"></script>' in html
    assert 'id="usageStatsCategory"' in html
    assert '文件使用統計' in html
    assert '帳號操作統計' in html
    assert 'id="usageStatsChart"' in html
    assert "'/v1/editor/usage-stats?'" in html
    assert 'SraAuditTools.renderTimeSeriesChart' in html
    assert 'function bindProgressiveNav(options)' in tools
    assert "matchMedia('(hover: hover) and (pointer: fine)')" in tools
    assert "event.pointerType !== 'mouse'" in tools


def test_auth_account_management_actions_are_written_to_account_audit() -> None:
    source = Path("api/routers/editor.py").read_text(encoding="utf-8")

    assert '"action": "auth.user_registered"' in source
    assert '"action": "auth.user_approved"' in source
    assert '"action": "auth.user_rejected"' in source
    assert '"action": "auth.user_deleted"' in source


def test_account_management_uses_role_dropdowns() -> None:
    editor_html = _editor_html()
    portable_html = Path("portable_auth_pack/static/login_admin_minimal.html").read_text(encoding="utf-8")

    for html in (editor_html, portable_html):
        assert 'function roleOptionsHtml(selectedRole, roleOptions)' in html
        assert 'data-role-select=' in html
        assert 'approveSelectedUser' in html
        assert 'db_operator' in html
        assert 'data_editor' in html
        assert 'data_reader' in html
        assert '核准 user' not in html
        assert '核准 superuser' not in html


def test_portable_auth_pack_reset_token_dialog_is_copyable() -> None:
    html = Path("portable_auth_pack/static/login_admin_minimal.html").read_text(encoding="utf-8")

    assert 'id="resetTokenModal"' in html
    assert 'id="resetTokenModalValue" readonly' in html
    assert 'id="copyResetTokenBtn"' in html
    assert 'navigator.clipboard.writeText' in html
    assert 'showResetTokenDialog(username, data.reset_token)' in html
    assert 'alert(`請用安全管道交付給 ${username}' not in html


def test_portable_auth_pack_exposes_account_stats_with_shared_module() -> None:
    html = Path("portable_auth_pack/static/login_admin_minimal.html").read_text(encoding="utf-8")

    assert '<script src="audit_tools.js"></script>' in html
    assert 'id="accountStatsSection"' in html
    assert 'SraAuditTools.renderTimeSeriesChart' in html
    assert "category: 'account'" in html
    assert Path("portable_auth_pack/static/audit_tools.js").exists()


def test_portable_auth_pack_navigation_is_header_multilevel_and_collapsible() -> None:
    html = Path("portable_auth_pack/static/login_admin_minimal.html").read_text(encoding="utf-8")

    assert 'id="authPackNav" class="header-nav"' in html
    assert 'data-nav-root="identity"' in html
    assert 'data-nav-root="password"' in html
    assert 'data-nav-root="admin"' in html
    assert 'id="navSubPanel" class="nav-subpanel hidden" aria-label="第二層功能選單"' in html
    assert 'class="nav-menu" data-nav-menu="identity"' in html
    assert 'class="nav-level" open' in html
    assert 'function setActiveAuthPackNavRoot(root)' in html
    assert 'function collapseAuthPackNav()' in html
    assert 'SraAuditTools.bindProgressiveNav' in html
    assert "setAttribute('aria-expanded', active ? 'true' : 'false')" in html
