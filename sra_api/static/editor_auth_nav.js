async function login() {
  setStatus('authStatus', '登入中...');
  try {
    const data = await api('/v1/auth/login', {method: 'POST', body: JSON.stringify({username: $('authUsername').value, password: $('authPassword').value})});
    state.token = data.access_token; state.user = data.user; localStorage.setItem('sra_editor_token', state.token);
    await bootAuthed(); setStatus('authStatus', '登入成功', 'ok');
  } catch (err) { setStatus('authStatus', err.message, 'error'); }
}

async function vercelPreviewLogin() {
  setStatus('authStatus', 'Vercel mock preview 登入中...');
  try {
    const data = await api('/v1/auth/vercel-preview-login', {method: 'POST'});
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
    if (data.enabled) {
      btn.classList.remove('hidden');
      hint.classList.remove('hidden');
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
  state.activeNavRoot = root || '';
  const panel = $('navSubPanel');
  document.querySelectorAll('[data-nav-root]').forEach(btn => {
    const active = btn.dataset.navRoot === state.activeNavRoot;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-expanded', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-nav-menu]').forEach(menu => menu.classList.toggle('active', menu.dataset.navMenu === state.activeNavRoot));
  if (panel) {
    panel.classList.toggle('hidden', !state.activeNavRoot);
    const activeBtn = document.querySelector(`[data-nav-root="${CSS.escape(state.activeNavRoot)}"]`);
    if (activeBtn && state.activeNavRoot) {
      const navRect = $('mainNav').getBoundingClientRect();
      const btnRect = activeBtn.getBoundingClientRect();
      const center = btnRect.left + btnRect.width / 2 - navRect.left;
      panel.style.setProperty('--nav-panel-left', `${center}px`);
      panel.style.setProperty('--nav-panel-arrow-left', '50%');
    }
  }
}
function collapseMainNav() { setActiveNavRoot(''); }
function bindHeaderNav() {
  SraAuditTools.bindProgressiveNav({
    nav: $('mainNav'),
    getActiveRoot: () => state.activeNavRoot,
    setActiveRoot: setActiveNavRoot,
    collapse: collapseMainNav,
  });
}
async function bootAuthed() {
  const me = await api('/v1/auth/me'); state.user = me.user;
  const isSuperuser = state.user && state.user.role === 'superuser';
  $('auth').classList.add('hidden'); $('app').classList.remove('hidden'); $('headerLogoutBtn').classList.remove('hidden');
  $('whoami').textContent = `${state.user.username} (${state.user.role})`;
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
}
