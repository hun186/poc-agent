function loginInputHints(username, password) {
  const hints = [];
  if (/[^\x00-\x7F]/.test(username)) hints.push('帳號含有非半形英文/數字字元，請確認是否切到中文或全形輸入。');
  if (/[\uFF01-\uFF5E]/.test(password)) hints.push('密碼含全形字元，請確認英數與符號是否為半形。');
  if (/[\u4E00-\u9FFF]/.test(password)) hints.push('密碼含中文，請確認目前輸入法是否正確。');
  if (password !== password.trim()) hints.push('密碼前後有空白；如果不是刻意設定，請刪除空白後再試。');
  return hints;
}
function loginFailureHintMessage(baseMessage, username, password) {
  const hints = loginInputHints(username, password);
  if (!hints.length) return baseMessage;
  return `${baseMessage}\n提醒：${hints.join(' ')}`;
}
async function login() {
  const username = $('authUsername').value;
  const password = $('authPassword').value;
  const hints = loginInputHints(username, password);
  setStatus('authStatus', hints.length ? `登入中...提醒：${hints.join(' ')}` : '登入中...');
  try {
    const data = await api('/v1/auth/login', {method: 'POST', body: JSON.stringify({username, password})});
    state.token = data.access_token; state.user = data.user; localStorage.setItem('sra_editor_token', state.token);
    await bootAuthed(); setStatus('authStatus', '登入成功', 'ok');
  } catch (err) { setStatus('authStatus', loginFailureHintMessage(err.message, username, password), 'error'); }
}

async function vercelPreviewLogin() {
  setStatus('authStatus', 'Vercel mock preview 登入中...');
  try {
    const options = {method: 'POST'};
    if (state.vercelPreviewSecretRequired) {
      const secret = window.prompt('請輸入 Vercel mock preview login secret');
      if (!secret) return setStatus('authStatus', '已取消 Vercel mock preview 登入', 'error');
      options.headers = {'X-SRA-Preview-Login-Secret': secret};
    }
    const data = await api('/v1/auth/vercel-preview-login', options);
    state.token = data.access_token; state.user = data.user; localStorage.setItem('sra_editor_token', state.token);
    await bootAuthed(); setStatus('authStatus', 'Vercel mock preview 已登入', 'ok');
  } catch (err) { setStatus('authStatus', err.message, 'error'); }
}
async function setupVercelPreviewLogin() {
  const btn = $('vercelPreviewLoginBtn');
  const hint = $('vercelPreviewLoginHint');
  if (!btn || !hint) return;
  try {
    const data = await api('/v1/auth/vercel-preview-login-enabled');
    state.vercelPreviewSecretRequired = Boolean(data.secret_required);
    if (data.enabled) {
      btn.classList.remove('hidden');
      hint.classList.remove('hidden');
      if (data.secret_required) hint.textContent = 'Vercel mock preview 需要輸入 preview login secret，且只供 mock 資料預覽。';
    }
  } catch (err) {
    btn.classList.add('hidden');
    hint.classList.add('hidden');
  }
}
async function register() {
  setStatus('authStatus', '建立帳號中...');
  try {
    const data = await api('/v1/auth/register', {method: 'POST', body: JSON.stringify({username: $('authUsername').value, password: $('authPassword').value, full_name: $('authFullName').value.trim(), department: $('authDepartment').value.trim(), note: $('authNote').value.trim()})});
    setStatus('authStatus', data.message, 'ok');
  } catch (err) { setStatus('authStatus', err.message, 'error'); }
}
async function forgotPassword() {
  const username = $('authUsername').value.trim();
  if (!username) return setStatus('authStatus', '請先輸入帳號。', 'error');
  setStatus('authStatus', '建立重設 token 中...');
  try {
    const data = await api('/v1/auth/forgot-password', {method: 'POST', body: JSON.stringify({username})});
    setStatus('authStatus', data.message, 'ok');
  } catch (err) { setStatus('authStatus', err.message, 'error'); }
}
async function recoverPassword() {
  const username = $('authUsername').value.trim();
  const reset_token = $('forgotResetToken').value.trim();
  const new_password = $('forgotNewPassword').value;
  if (!username || !reset_token || !new_password) return setStatus('authStatus', '請輸入帳號、reset token 與新密碼。', 'error');
  setStatus('authStatus', '重設密碼中...');
  try {
    const data = await api('/v1/auth/reset-password', {method: 'POST', body: JSON.stringify({username, reset_token, new_password})});
    $('authPassword').value = '';
    $('forgotNewPassword').value = '';
    setStatus('authStatus', data.message, 'ok');
  } catch (err) { setStatus('authStatus', err.message, 'error'); }
}
async function changePassword() {
  const current_password = $('currentPassword').value;
  const new_password = $('newPassword').value;
  if (!current_password || !new_password) return setStatus('accountStatus', '請輸入目前密碼與新密碼。', 'error');
  setStatus('accountStatus', '變更密碼中...');
  try {
    const data = await api('/v1/auth/change-password', {method: 'POST', body: JSON.stringify({current_password, new_password})});
    $('currentPassword').value = '';
    $('newPassword').value = '';
    setStatus('accountStatus', data.message, 'ok');
    setTimeout(() => logout({skipRemote: true}), 900);
  } catch (err) { setStatus('accountStatus', err.message, 'error'); }
}
function setActiveNavRoot(root) {
  const previousRoot = state.activeNavRoot;
  state.activeNavRoot = root || '';
  const panel = $('navSubPanel');
  if (panel && previousRoot !== state.activeNavRoot) {
    // An old open submenu must never reserve blank second-column space
    // when switching to another top-level button.
    panel.querySelectorAll('.nav-level').forEach(level => { level.open = false; });
  }
  document.querySelectorAll('[data-nav-root]').forEach(btn => {
    const active = btn.dataset.navRoot === state.activeNavRoot;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-expanded', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-nav-menu]').forEach(menu => menu.classList.toggle('active', menu.dataset.navMenu === state.activeNavRoot));
  if (panel) {
    panel.classList.toggle('hidden', !state.activeNavRoot);
    if (!state.activeNavRoot) return;
    const activeBtn = document.querySelector(`[data-nav-root="${CSS.escape(state.activeNavRoot)}"]`);
    if (activeBtn) {
      // Fix the left edge for BOTH compact and expanded states. Increasing
      // flyout width must not shift the first-level menu or header buttons.
      const navRect = $('mainNav').getBoundingClientRect();
      const btnRect = activeBtn.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const fullWidth = Math.min(740, Math.max(0, viewportWidth - 36));
      const panelLeft = Math.max(18, Math.min(btnRect.left, viewportWidth - 18 - fullWidth));
      const arrowLeft = Math.max(24, Math.min(btnRect.left + btnRect.width / 2 - panelLeft, Math.min(fullWidth, 266) - 24));
      panel.style.setProperty('--nav-panel-left', `${panelLeft - navRect.left}px`);
      panel.style.setProperty('--nav-panel-arrow-left', `${arrowLeft}px`);
    }
  }
}
function collapseMainNav() { setActiveNavRoot(''); }
window.addEventListener('resize', () => {
  // Re-clamp an open flyout after desktop resizing or tablet rotation;
  // reusing the same root preserves the expanded child menu and its focus.
  if (state.activeNavRoot) setActiveNavRoot(state.activeNavRoot);
});
function bindHeaderNav() {
  SraAuditTools.bindProgressiveNav({
    nav: $('mainNav'),
    getActiveRoot: () => state.activeNavRoot,
    setActiveRoot: setActiveNavRoot,
    collapse: collapseMainNav,
  });
  // Only one flyout may be open in the visible menu. Supports hover, touch
  // click and keyboard-driven native <details> without overlapping panels.
  $('navSubPanel').querySelectorAll('.nav-level').forEach(level => {
    level.addEventListener('toggle', () => {
      if (!level.open) return;
      const group = level.closest('.nav-menu');
      if (!group || !group.classList.contains('active')) return;
      group.querySelectorAll('.nav-level').forEach(other => {
        if (other !== level) other.open = false;
      });
    });
  });
}
// Feature fragments contain ONLY an allowlisted tab name, never a token or data.
// Cross-page navigation should land on the requested function, not just /editor.
function applyEditorEntryRoute() {
  if (!state.user) return;
  const entry = window.location.hash;
  const tabs = {
    '#search': 'search',
    '#stats': 'stats',
    '#account': 'account',
    '#account-audit': 'account-audit',
    '#review': 'review',
    '#new-document': 'new-document'
  };
  if (!Object.prototype.hasOwnProperty.call(tabs, entry)) return;
  const tab = tabs[entry];
  if (tab === 'review' && state.user.role !== 'superuser') {
    switchMainTab('account');
    setStatus('accountStatus', '帳號審核僅供具備系統管理權限的帳號使用。', 'error');
    collapseMainNav();
    return;
  }
  if (tab === 'new-document') {
    switchMainTab('search');
    newDoc();
  } else if (tab === 'stats') {
    switchMainTab('stats', {source: 'document', category: 'document', view: 'mine'});
  } else {
    switchMainTab(tab);
  }
  collapseMainNav();
}
window.addEventListener('hashchange', () => {
  if (state.user) applyEditorEntryRoute();
});

async function bootAuthed() {
  const me = await api('/v1/auth/me'); state.user = me.user;
  const isSuperuser = state.user && state.user.role === 'superuser';
  const canManageDbTasks = state.user && ['db_operator', 'superuser'].includes(state.user.role);
  $('auth').classList.add('hidden'); $('app').classList.remove('hidden'); $('headerLogoutBtn').classList.remove('hidden');
  $('whoami').textContent = `${state.user.username} (${state.user.role})`;
  const excelTaskConfigBtn = $('excelTaskConfigBtn');
  if (excelTaskConfigBtn) {
    excelTaskConfigBtn.classList.toggle('hidden', !canManageDbTasks);
    excelTaskConfigBtn.disabled = !canManageDbTasks;
    excelTaskConfigBtn.title = canManageDbTasks ? '' : '建立 Excel→SQL 任務設定檔需要 db_operator / superuser 權限';
  }
  const indexes = await api('/v1/editor/indexes');
  $('indexSelect').innerHTML = indexes.indexes.map(i => `<option value="${esc(i)}">${esc(i)}</option>`).join('');
  if (indexes.default_index) $('indexSelect').value = indexes.default_index;
  $('usageStatsIndex').innerHTML = '<option value="">全部</option>' + indexes.indexes.map(i => `<option value="${esc(i)}">${esc(i)}</option>`).join('');
  syncDocIndexOptions($('indexSelect').value);
  setEditorMode('new');
  await loadFormConfig($('indexSelect').value);
  $('mainNav').classList.remove('hidden');
  bindHeaderNav();
  document.querySelectorAll('[data-main-tab]').forEach(btn => btn.onclick = () => { switchMainTab(btn.dataset.mainTab, {category: btn.dataset.statsCategory || '', view: btn.dataset.statsView || '', source: btn.dataset.statsSource || ''}); collapseMainNav(); });
  if (isSuperuser) {
    $('adminCard').classList.remove('hidden');
    $('auditCard').classList.remove('hidden');
    $('accountAuditCard').classList.remove('hidden');
    document.querySelectorAll('[data-superuser-only]').forEach(el => el.classList.remove('hidden'));
    $('statsAllTabBtn').classList.remove('hidden');
    $('adminNavGroup').classList.remove('hidden');
    await refreshUsers();
    await searchAuditLogs();
    await searchAccountAuditLogs();
  } else {
    $('adminCard').classList.add('hidden');
    $('auditCard').classList.add('hidden');
    $('accountAuditCard').classList.add('hidden');
    $('adminNavGroup').classList.add('hidden');
    document.querySelectorAll('[data-superuser-only]').forEach(el => el.classList.add('hidden'));
  }
  await refreshUsageStats();
  switchMainTab('search');
  bindMultiFilterOutsideDismiss('usageStatsUsernamePicker');
  bindMultiFilterOutsideDismiss('usageStatsClientHostPicker');
  $('usageStatsUsernameSearch').oninput = renderUsageStatsUserPicker;
  $('usageStatsSelectVisibleUsersBtn').onclick = () => setVisibleUsageStatsUsers(true);
  $('usageStatsClearVisibleUsersBtn').onclick = () => setVisibleUsageStatsUsers(false);
  $('usageStatsClearAllUsersBtn').onclick = () => { state.usageStatsSelectedUsers = []; renderUsageStatsUserPicker(); };
  $('usageStatsClientHostSearch').oninput = renderUsageStatsClientHostPicker;
  $('usageStatsSelectVisibleClientHostsBtn').onclick = () => setVisibleUsageStatsClientHosts(true);
  $('usageStatsClearVisibleClientHostsBtn').onclick = () => setVisibleUsageStatsClientHosts(false);
  $('usageStatsClearAllClientHostsBtn').onclick = () => { state.usageStatsSelectedClientHosts = []; renderUsageStatsClientHostPicker(); };
  $('statsMineTabBtn').onclick = () => switchStatsView('mine');
  $('statsAllTabBtn').onclick = () => switchStatsView('all');
  switchStatsView('mine');
  applyEditorEntryRoute();
}

function setupLoginInputGuards() {
  const password = $('authPassword');
  if (!password) return;
  password.addEventListener('keyup', event => {
    if (event.getModifierState && event.getModifierState('CapsLock')) {
      setStatus('authStatus', '提醒：Caps Lock 目前開啟，密碼大小寫可能輸錯。', 'error');
    }
  });
}
setupLoginInputGuards();
