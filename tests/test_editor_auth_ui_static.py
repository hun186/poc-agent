from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


EDITOR_SCRIPT_FILES = [
    "sra_api/static/editor_core.js",
    "sra_api/static/editor_form.js",
    "sra_api/static/editor_auth_nav.js",
    "sra_api/static/editor_stats.js",
    "sra_api/static/editor_audit.js",
    "sra_api/static/editor_documents.js",
    "sra_api/static/editor_bootstrap.js",
]

PORTABLE_AUTH_PACK_SCRIPT_FILES = [
    "portable_auth_pack/static/login_admin_core.js",
    "portable_auth_pack/static/login_admin_auth.js",
    "portable_auth_pack/static/login_admin_audit.js",
    "portable_auth_pack/static/login_admin_stats.js",
    "portable_auth_pack/static/login_admin_admin.js",
    "portable_auth_pack/static/login_admin_bootstrap.js",
]


def _editor_html() -> str:
    """Return the editor shell plus split static assets for static assertions."""
    return "\n".join([
        Path("sra_api/static/editor.html").read_text(encoding="utf-8"),
        Path("sra_api/static/editor.css").read_text(encoding="utf-8"),
        *(Path(path).read_text(encoding="utf-8") for path in EDITOR_SCRIPT_FILES),
    ])



def _portable_auth_pack_html() -> str:
    """Return the portable auth pack shell plus split static assets for static assertions."""
    return "\n".join([
        Path("portable_auth_pack/static/login_admin_minimal.html").read_text(encoding="utf-8"),
        Path("portable_auth_pack/static/login_admin_minimal.css").read_text(encoding="utf-8"),
        *(Path(path).read_text(encoding="utf-8") for path in PORTABLE_AUTH_PACK_SCRIPT_FILES),
    ])


def test_editor_static_shell_loads_split_assets() -> None:
    html = Path("sra_api/static/editor.html").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/static/editor.css?v=20260614-split" />' in html
    expected_versions = {
        "editor_form.js": "20260625-array-preserve-single",
        "editor_auth_nav.js": "20260629-login-hints",
        "editor_documents.js": "20260629-login-unlock",
        "editor_bootstrap.js": "20260702-source-editor-auth-helper",
    }
    for path in EDITOR_SCRIPT_FILES:
        asset_name = Path(path).name
        version = expected_versions.get(asset_name, "20260614-split")
        assert f'<script src="/static/{asset_name}?v={version}"></script>' in html
        assert Path(path).exists()
        assert sum(1 for _ in Path(path).open(encoding="utf-8")) < 350
    assert 'editor.js?v=20260614-split' not in html
    assert '<style>' not in html
    assert '<script>\n' not in html
    assert Path("sra_api/static/editor.css").exists()
    assert not Path("sra_api/static/editor.js").exists()



def test_editor_static_assets_are_served_by_router() -> None:
    from api.routers import editor

    app = FastAPI()
    app.include_router(editor.router)
    client = TestClient(app)

    assets = ["editor.css"] + [Path(path).name for path in EDITOR_SCRIPT_FILES]
    for asset in assets:
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200
        assert response.text.strip()

    legacy_dashboard_response = client.get("/static/excel_to_sql_dashboard.js")
    current_dashboard_response = client.get("/static/excel_to_sql_dashboard_app.js")
    assert legacy_dashboard_response.status_code == 200
    assert legacy_dashboard_response.text == current_dashboard_response.text

    missing = client.get("/static/not_allowed.js")
    assert missing.status_code == 404

def test_portable_auth_pack_shell_loads_split_assets() -> None:
    html = Path("portable_auth_pack/static/login_admin_minimal.html").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="login_admin_minimal.css?v=20260614-split" />' in html
    expected_versions = {
        "login_admin_auth.js": "20260629-login-hints",
        "login_admin_admin.js": "20260629-login-unlock",
    }
    for path in PORTABLE_AUTH_PACK_SCRIPT_FILES:
        asset_name = Path(path).name
        version = expected_versions.get(asset_name, "20260614-split")
        assert f'<script src="{asset_name}?v={version}"></script>' in html
        assert Path(path).exists()
        assert sum(1 for _ in Path(path).open(encoding="utf-8")) < 200
    assert 'login_admin_minimal.js?v=20260614-split' not in html
    assert '<style>' not in html
    assert '<script>\n' not in html
    assert Path("portable_auth_pack/static/login_admin_minimal.css").exists()
    assert not Path("portable_auth_pack/static/login_admin_minimal.js").exists()

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


def test_editor_auth_ui_exposes_login_typo_hints() -> None:
    html = _editor_html()

    assert 'loginInputHints' in html
    assert 'Caps Lock 目前開啟' in html
    assert '密碼含全形字元' in html
    assert '密碼前後有空白' in html


def test_editor_auth_ui_exposes_logout_reset_controls_without_duplicate_login_audit_panel() -> None:
    html = _editor_html()

    assert "'/v1/auth/logout'" in html
    assert 'data-issue-reset-token=' in html
    assert 'data-reset-user=' in html
    assert 'data-unlock-login=' in html
    assert '解除登入冷卻' in html
    assert '/password-reset-token`' in html
    assert '/unlock-login`' in html
    assert '/reset-password`' in html
    assert '<option value="auth.login">登入</option>' in html
    assert 'id="refreshLoginAuditBtn"' not in html
    assert 'id="loginAuditHits"' not in html
    assert '/v1/auth/login-audit?limit=' not in html
    assert '登入稽核' not in html



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
    assert 'data-nav-root="pipeline" aria-expanded="false">匯入管理</button>' in html
    assert '<summary>Excel 匯入流程管理</summary>' in html
    assert 'id="excelDashboardBtn">Excel→SQL 匯入查詢儀表板</button>' in html
    assert 'id="excelImportCenterBtn">Excel 匯入作業中心</button>' in html
    assert 'id="navSubPanel" class="nav-subpanel hidden" aria-label="第二層功能選單"' in html
    assert 'class="nav-menu" data-nav-menu="content"' in html
    assert 'class="nav-level" open' in html
    assert '.nav-root-btn { min-width: 128px; padding: 12px 18px; border: 1px solid rgba(255,255,255,.18); background: rgba(71,85,105,.92);' in html
    assert '.nav-root-btn.active { outline: 3px solid rgba(147,197,253,.55); background: #1d4ed8; }' in html
    assert 'grid-template-columns: minmax(180px, 230px) minmax(240px, 1fr)' in html
    assert '.nav-actions { position: absolute; top: 0; left: calc(100% + 10px)' in html
    assert 'grid-template-columns: minmax(0, 1fr)' in html
    assert not re.search(r'\.nav-actions \{[^}]*repeat\(auto-fit, minmax\(150px, 1fr\)\)', html)
    assert '.nav-level:not([open]) .nav-actions { display: none; }' in html
    assert '.nav-level[open] summary::after { content: "右側"; }' in html
    assert '@media (max-width: 720px)' in html
    assert 'function setActiveNavRoot(root)' in html
    assert 'function collapseMainNav()' in html
    assert "setAttribute('aria-expanded', active ? 'true' : 'false')" in html
    assert "panel.style.setProperty('--nav-panel-left'" in html
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
    assert '<summary>紀錄查詢</summary>' not in html
    assert '<summary>文件異動紀錄</summary>' in html
    assert 'data-stats-category="document"' in html
    assert 'data-main-tab="account-audit">帳號操作記錄' in html
    assert 'data-stats-category="account" data-stats-view="all"' not in html
    assert 'id="accountAuditStartTs" type="datetime-local"' in html
    assert 'id="accountAuditEndTs" type="datetime-local"' in html
    assert 'id="accountAuditStatsBtn"' in html
    assert "qs.set('action_prefix', 'editor.')" in html
    assert "qs.set('action_prefix', 'auth.')" in html
    assert 'clientHost = h.client_host ? `｜IP：${esc(h.client_host)}`' in html


def test_editor_usage_stats_filters_use_shared_chart_module() -> None:
    html = _editor_html()
    tools = Path("sra_api/static/audit_tools.js").read_text(encoding="utf-8")

    assert '<script src="/static/audit_tools.js?v=20260614-multifilter"></script>' in html
    assert 'id="usageStatsCategory"' in html
    assert 'ES 文件異動紀錄使用統計' in html
    assert '帳號操作記錄使用統計' in html
    assert '全部操作使用統計' not in html
    assert 'id="usageStatsIndexField"' in html
    assert "$('usageStatsIndexField').classList.toggle('hidden', state.usageStatsSource === 'account');" in html
    assert '統計與檢核曲線儀表板' in html
    assert 'id="usageStatsChart"' in html
    assert 'id="usageStatsEventsLimit"' in html
    assert 'id="usageStatsAuditEvents"' in html
    assert 'aria-label="使用統計 audit 事件條目"' in html
    assert "events_limit: String(Math.max(1, Math.min(500, Number($('usageStatsEventsLimit').value || 100))))" in html
    assert 'timezone_offset_minutes: String(localTimezoneOffsetMinutes())' in html
    assert 'function formatLocalTimestamp(value)' in html
    assert 'function renderUsageStatsAuditEvents(filtered)' in html
    assert 'renderUsageStatsAuditEvents(filtered);' in html
    assert "'/v1/editor/usage-stats?'" in html
    assert 'SraAuditTools.renderTimeSeriesChart' in html
    assert "{label: 'IP 數', value: Object.keys(stats.by_client_host || {}).length, hint: 'client_host'}" in html
    assert "block('依 client_host IP', stats.by_client_host)" in html
    assert "$('statsMineTabBtn').textContent = isAccount ? '我的帳號操作紀錄' : '我的 ES 文件異動紀錄';" in html
    assert "$('statsAllTabBtn').textContent = isAccount ? '全體帳號操作紀錄' : '全體 ES 文件異動紀錄';" in html
    assert 'id="usageStatsCurrentScopeNote"' in html
    assert '目前顯示個人記錄' in html
    assert 'id="usageStatsScopeHelpBtn"' in html
    assert 'aria-describedby="usageStatsScopeHelpText"' in html
    assert 'id="usageStatsScopeHelpText" class="scope-help-tooltip" role="tooltip"' in html
    assert '.scope-help:hover .scope-help-tooltip, .scope-help:focus-within .scope-help-tooltip { display:block; }' in html
    assert 'title="查詢自己的紀錄' not in html
    assert '此功能需要 superuser 權限層級' in html
    assert 'id="usageStatsUsernamePicker" class="multi-filter hidden"' in html
    assert 'id="usageStatsClientHostField"' in html
    assert 'id="usageStatsClientHostPicker" class="multi-filter"' in html
    assert 'data-usage-stats-client-host' in html
    assert "client_host: state.usageStatsSelectedClientHosts.join(',')" in html
    assert "$('usageStatsClientHostField').classList.toggle('hidden', state.usageStatsSource !== 'account');" in html
    assert 'id="usageStatsUsernameSearch"' in html
    assert '勾選目前篩選' in html
    assert '清除目前篩選' in html
    assert 'data-usage-stats-user' in html
    assert "bindMultiFilterOutsideDismiss('usageStatsUsernamePicker');" in html
    assert "function bindMultiFilterOutsideDismiss(id)" in html
    assert "if (!picker.open || picker.contains(ev.target)) return;" in html
    assert "picker.removeAttribute('open');" in html
    assert "$('usageStatsUsernamePicker').classList.toggle('hidden', mine);" in html
    assert "$('usageStatsCurrentScopeNote').classList.toggle('hidden', !mine);" in html
    assert 'setUsageStatsUserOptions((data.users || []).map(u => u.username));' in html
    assert "username: state.usageStatsView === 'mine' && state.user ? state.user.username : state.usageStatsSelectedUsers.join(',')" in html
    assert 'function bindProgressiveNav(options)' in tools
    assert "matchMedia('(hover: hover) and (pointer: fine)')" in tools
    assert "event.pointerType !== 'mouse'" in tools


def test_auth_account_management_actions_are_written_to_account_audit() -> None:
    source = Path("sra_api/routers/editor_auth.py").read_text(encoding="utf-8")

    assert '"action": "auth.user_registered"' in source
    assert '"action": "auth.user_approved"' in source
    assert '"action": "auth.user_rejected"' in source
    assert '"action": "auth.user_deleted"' in source


def test_account_management_uses_role_dropdowns() -> None:
    editor_html = _editor_html()
    portable_html = _portable_auth_pack_html()

    for html in (editor_html, portable_html):
        assert 'function roleOptionsHtml(selectedRole, roleOptions)' in html
        assert 'data-role-select=' in html
        assert 'approveSelectedUser' in html
        assert 'db_operator' in html
        assert 'data_editor' in html
        assert 'data_reader' in html
        assert '核准 user' not in html
        assert '核准 superuser' not in html
        assert '拒絕申請／停權' in html
        assert '拒絕</button>' not in html


def test_usage_stats_user_picker_is_seeded_from_current_user_and_user_list() -> None:
    editor_html = _editor_html()
    portable_html = _portable_auth_pack_html()

    assert "if (state.user && !state.usageStatsUserOptions.includes(state.user.username)) state.usageStatsUserOptions.unshift(state.user.username);" in editor_html
    assert "setUsageStatsUserOptions((data.users || []).map(u => u.username));" in editor_html
    assert "if (pageState.currentUser && !pageState.accountStatsUserOptions.includes(pageState.currentUser.username)) pageState.accountStatsUserOptions.unshift(pageState.currentUser.username);" in portable_html
    assert "setAccountStatsUserOptions(pageState.accountStatsUserOptions);" in portable_html


def test_portable_auth_pack_reset_token_dialog_is_copyable() -> None:
    html = _portable_auth_pack_html()

    assert 'id="resetTokenModal"' in html
    assert 'id="resetTokenModalValue" readonly' in html
    assert 'id="copyResetTokenBtn"' in html
    assert 'navigator.clipboard.writeText' in html
    assert 'showResetTokenDialog(username, data.reset_token)' in html
    assert 'alert(`請用安全管道交付給 ${username}' not in html


def test_portable_auth_pack_exposes_account_stats_with_shared_module() -> None:
    html = _portable_auth_pack_html()

    assert '<script src="audit_tools.js?v=20260614-multifilter"></script>' in html
    assert '<script src="login_admin_auth.js?v=20260629-login-hints"></script>' in html
    assert '<script src="login_admin_admin.js?v=20260629-login-unlock"></script>' in html
    assert 'loginInputHints' in html
    assert 'Caps Lock 目前開啟' in html
    assert '解除登入冷卻' in html
    assert '/unlock-login`' in html
    assert 'id="accountStatsSection"' in html
    assert 'SraAuditTools.renderTimeSeriesChart' in html
    assert "{label: 'IP 數', value: Object.keys(stats.by_client_host || {}).length, hint: 'client_host'}" in html
    assert "category: 'account'" in html
    assert 'id="accountStatsClientHostPicker" class="multi-filter"' in html
    assert 'data-account-stats-client-host' in html
    assert "params.set('client_host', clientHost)" in html
    assert 'id="accountStatsMineBtn"' in html
    assert 'id="accountStatsAllBtn" class="secondary hidden"' in html
    assert "function setAccountStatsView(view)" in html
    assert 'timezone_offset_minutes: String(localTimezoneOffsetMinutes())' in html
    assert 'function formatLocalTimestamp(value)' in html
    assert '我的登入稽核' in html
    assert Path("portable_auth_pack/static/audit_tools.js").exists()


def test_portable_auth_pack_navigation_is_header_multilevel_and_collapsible() -> None:
    html = _portable_auth_pack_html()

    assert 'id="authPackNav" class="header-nav"' in html
    assert 'data-nav-root="identity"' in html
    assert 'data-nav-root="password"' in html
    assert 'data-nav-root="admin"' in html
    assert 'id="navSubPanel" class="nav-subpanel hidden" aria-label="第二層功能選單"' in html
    assert 'class="nav-menu" data-nav-menu="identity"' in html
    assert 'class="nav-level" open' in html
    assert 'grid-template-columns: minmax(170px, 220px) minmax(230px, 1fr)' in html
    assert '.nav-subpanel { position: absolute; top: calc(100% + .75rem); left: var(--nav-panel-left, 0px); transform: translateX(-50%);' in html
    assert '.nav-actions { position: absolute; top: 0; left: calc(100% + .6rem)' in html
    assert 'flex-direction: column' in html
    assert 'flex-wrap: nowrap' in html
    assert '.nav-level:not([open]) .nav-actions { display: none; }' in html
    assert '.nav-level[open] summary::after { content: "右側"; }' in html
    assert '@media (max-width: 720px)' in html
    assert 'function setActiveAuthPackNavRoot(root)' in html
    assert 'function collapseAuthPackNav()' in html
    assert 'SraAuditTools.bindProgressiveNav' in html
    assert "setAttribute('aria-expanded', active ? 'true' : 'false')" in html
    assert "panel.style.setProperty('--nav-panel-left'" in html


def test_navigation_hover_has_bridge_and_delayed_level_close() -> None:
    editor_html = _editor_html()
    portable_html = _portable_auth_pack_html()
    tools = Path("sra_api/static/audit_tools.js").read_text(encoding="utf-8")

    assert '.nav-level[open]::after { content: ""; position: absolute; top: 0; left: 100%; width: 10px; height: 100%; }' in editor_html
    assert '.nav-level[open]::after { content: ""; position: absolute; top: 0; left: 100%; width: .6rem; height: 100%; }' in portable_html
    assert 'const levelCloseDelayMs = Number(options.levelCloseDelayMs || 360);' in tools
    assert 'levelCloseTimers.set(details, window.setTimeout(() => { details.open = false; }, levelCloseDelayMs));' in tools


def test_editor_audit_views_are_client_paginated_after_sorting() -> None:
    html = _editor_html()
    tools = Path("sra_api/static/audit_tools.js").read_text(encoding="utf-8")

    for element_id in (
        'auditPageInfo', 'auditFirstBtn', 'auditPrevBtn', 'auditPageInput', 'auditGotoBtn', 'auditNextBtn', 'auditLastBtn',
        'accountAuditPageInfo', 'accountAuditFirstBtn', 'accountAuditPrevBtn', 'accountAuditPageInput', 'accountAuditGotoBtn', 'accountAuditNextBtn', 'accountAuditLastBtn',
        'usageStatsAuditPageInfo', 'usageStatsAuditFirstBtn', 'usageStatsAuditPrevBtn', 'usageStatsAuditPageInput', 'usageStatsAuditGotoBtn', 'usageStatsAuditNextBtn', 'usageStatsAuditLastBtn',
    ):
        assert f'id="{element_id}"' in html
    assert 'function sortAuditRows(rows)' in html
    assert 'function updateClientPager(config)' in html
    assert 'function bindClientPagerActions(prefix, getPage, setPage, renderPage)' in html
    assert "jumpTo(Number.MAX_SAFE_INTEGER)" in html
    assert "if (ev.key === 'Enter') jumpTo(Number(ev.currentTarget.value || 1));" in html
    assert '先篩選、依時間排序，再分頁顯示' in html
    assert 'function paginateAuditRows(rows, page, pageSize)' in html
    assert "typeof sharedPaginator === \'function\' ? sharedPaginator(rows, page, pageSize) : localPaginateRows(rows, page, pageSize)" in html
    assert '<script src="/static/audit_tools.js?v=20260614-multifilter"></script>' in html
    assert 'function paginateRows(rows, page, pageSize)' in tools


def test_portable_auth_pack_lists_are_client_paginated() -> None:
    html = _portable_auth_pack_html()

    for element_id in (
        'usersPageInfo', 'usersFirstBtn', 'usersPrevBtn', 'usersPageInput', 'usersGotoBtn', 'usersNextBtn', 'usersLastBtn',
        'loginAuditPageInfo', 'loginAuditFirstBtn', 'loginAuditPrevBtn', 'loginAuditPageInput', 'loginAuditGotoBtn', 'loginAuditNextBtn', 'loginAuditLastBtn',
        'loginAuditHits',
    ):
        assert f'id="{element_id}"' in html
    assert "const pageState = { usersRows: [], usersPage: 1, usersRoleOptions: [], loginAuditRows: [], loginAuditPage: 1, accountStatsView: 'mine', currentUser: null, accountStatsUserOptions: [], accountStatsSelectedUsers: [], accountStatsClientHostOptions: [], accountStatsSelectedClientHosts: [] };" in html
    assert 'function updatePager(rows, page, infoId, prevId, nextId)' in html
    assert 'function bindPagerActions(prefix, getPage, setPage, renderPage)' in html
    assert "jumpTo(Number.MAX_SAFE_INTEGER)" in html
    assert "if (ev.key === 'Enter') jumpTo(Number(ev.currentTarget.value || 1));" in html
    assert 'function paginateAuditRows(rows, page, pageSize)' in html
    assert "typeof sharedPaginator === \'function\' ? sharedPaginator(rows, page, pageSize) : localPaginateRows(rows, page, pageSize)" in html
    assert '<script src="audit_tools.js?v=20260614-multifilter"></script>' in html
    assert '<script src="login_admin_auth.js?v=20260629-login-hints"></script>' in html
    assert '<script src="login_admin_admin.js?v=20260629-login-unlock"></script>' in html
    assert 'loginInputHints' in html
    assert 'Caps Lock 目前開啟' in html
    assert '解除登入冷卻' in html
    assert '/unlock-login`' in html
    assert 'id="accountStatsCurrentScopeNote"' in html
    assert '目前顯示個人帳號操作紀錄' in html
    assert 'id="accountStatsScopeHelpBtn"' in html
    assert 'aria-describedby="accountStatsScopeHelpText"' in html
    assert 'id="accountStatsScopeHelpText" class="scope-help-tooltip" role="tooltip"' in html
    assert '.scope-help:hover .scope-help-tooltip,.scope-help:focus-within .scope-help-tooltip{display:block;}' in html
    assert 'title="查詢自己的帳號操作紀錄' not in html
    assert '此功能需要 superuser 權限層級' in html
    assert 'id="accountStatsUsernamePicker" class="multi-filter hidden"' in html
    assert 'id="accountStatsUsernameSearch"' in html
    assert 'data-account-stats-user' in html
    assert "bindMultiFilterOutsideDismiss('accountStatsUsernamePicker');" in html
    assert "function bindMultiFilterOutsideDismiss(id)" in html
    assert "if (!picker.open || picker.contains(ev.target)) return;" in html
    assert "picker.removeAttribute('open');" in html
    assert "document.getElementById('accountStatsUsernamePicker').classList.toggle('hidden', mine);" in html
    assert "document.getElementById('accountStatsCurrentScopeNote').classList.toggle('hidden', !mine);" in html
    assert "pageState.accountStatsSelectedUsers.join(',')" in html
    assert 'pageState.usersRows = (data.users || []).slice().sort' in html
    assert 'pageState.loginAuditRows = (data.events || []).slice().sort' in html
    assert 'id="accountStatsClientHostPicker" class="multi-filter"' in html
    assert 'data-account-stats-client-host' in html
    assert "params.set('client_host', clientHost)" in html
    assert 'id="accountStatsMineBtn"' in html
    assert 'id="accountStatsAllBtn" class="secondary hidden"' in html
    assert '我的帳號操作紀錄' in html
    assert '全體帳號操作紀錄' in html
    assert "function setAccountStatsView(view)" in html
    assert "pageState.accountStatsView === 'mine'" in html


def test_editor_exposes_vercel_mock_preview_login_button():
    html = Path("sra_api/static/editor.html").read_text(encoding="utf-8")
    script = Path("sra_api/static/editor_auth_nav.js").read_text(encoding="utf-8")
    bootstrap = Path("sra_api/static/editor_bootstrap.js").read_text(encoding="utf-8")

    assert 'id="vercelPreviewLoginBtn"' in html
    assert 'Vercel mock 閱讀者登入' in html
    assert '/v1/auth/vercel-preview-login-enabled' in script
    assert '/v1/auth/vercel-preview-login' in script
    assert 'vercelPreviewLoginBtn' in bootstrap


def test_portable_auth_pack_exposes_vercel_mock_preview_login_button():
    html = Path("portable_auth_pack/static/login_admin_minimal.html").read_text(encoding="utf-8")
    script = Path("portable_auth_pack/static/login_admin_auth.js").read_text(encoding="utf-8")
    bootstrap = Path("portable_auth_pack/static/login_admin_bootstrap.js").read_text(encoding="utf-8")

    assert 'id="vercelPreviewLoginBtn"' in html
    assert 'Vercel mock 閱讀者登入' in html
    assert '/v1/auth/vercel-preview-login-enabled' in script
    assert '/v1/auth/vercel-preview-login' in script
    assert 'setupVercelPreviewLogin' in bootstrap


def test_editor_array_buttons_are_real_buttons_and_report_add_status() -> None:
    html = _editor_html()

    assert 'data-add-array="${esc(section.path)}"' in html
    assert '<button class="secondary" type="button" data-add-array="${esc(section.path)}">' in html
    assert '<button class="danger" type="button" data-remove-array="${esc(section.path)}" data-remove-index="${idx}">' in html
    assert "btn.getAttribute('data-add-array')" in html
    assert "btn.getAttribute('data-remove-array')" in html
    assert 'function ensureArrayAtPath(path)' in html
    assert "setStatus('saveStatus', `已新增 ${section.item_label || section.title || '項目'}，可在新格子輸入內容。`, 'ok');" in html
    assert "if (rendered < arr.length) throw new Error" in html
    assert "setStatus('saveStatus', '新增欄位失敗：' + err.message, 'error');" in html
