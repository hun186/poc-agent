const tokenKey = 'auth_token';
const navState = { activeRoot: '' };
const pageState = { usersRows: [], usersPage: 1, usersRoleOptions: [], loginAuditRows: [], loginAuditPage: 1, accountStatsView: 'mine', currentUser: null, accountStatsUserOptions: [], accountStatsSelectedUsers: [], accountStatsClientHostOptions: [], accountStatsSelectedClientHosts: [] };
const out = (data) => document.getElementById('output').textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
const esc = (v) => String(v ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
function setActiveAuthPackNavRoot(root) {
  navState.activeRoot = root || '';
  document.querySelectorAll('[data-nav-root]').forEach(btn => {
    const active = btn.dataset.navRoot === navState.activeRoot;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-expanded', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-nav-menu]').forEach(menu => menu.classList.toggle('active', menu.dataset.navMenu === navState.activeRoot));
  const panel = document.getElementById('navSubPanel');
  panel.classList.toggle('hidden', !navState.activeRoot);
  const activeBtn = document.querySelector(`[data-nav-root="${CSS.escape(navState.activeRoot)}"]`);
  if (activeBtn && navState.activeRoot) {
    const navRect = document.getElementById('authPackNav').getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();
    panel.style.setProperty('--nav-panel-left', `${btnRect.left + btnRect.width / 2 - navRect.left}px`);
  }
}
function collapseAuthPackNav() { setActiveAuthPackNavRoot(''); }
function jumpToSection(id) {
  document.getElementById(id).scrollIntoView({behavior: 'smooth', block: 'start'});
  collapseAuthPackNav();
}
SraAuditTools.bindProgressiveNav({
  nav: document.getElementById('authPackNav'),
  getActiveRoot: () => navState.activeRoot,
  setActiveRoot: setActiveAuthPackNavRoot,
  collapse: collapseAuthPackNav,
});
document.addEventListener('click', (ev) => { if (!document.getElementById('authPackNav').contains(ev.target)) collapseAuthPackNav(); });
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') collapseAuthPackNav(); });
function formatApiError(data, fallback='') {
  const detail = data && (data.detail || data.message || data.error);
  if (Array.isArray(detail)) return detail.map(item => item.msg || JSON.stringify(item)).join('\n');
  if (detail && typeof detail === 'object') return JSON.stringify(detail, null, 2);
  return String(detail || fallback || '請求失敗');
}
async function api(path, opts = {}) {
  const headers = Object.assign({'Content-Type': 'application/json'}, opts.headers || {});
  const token = localStorage.getItem(tokenKey);
  if (token) headers.Authorization = 'Bearer ' + token;
  const res = await fetch(path, Object.assign({}, opts, {headers}));
  const text = await res.text();
  let data = {}; try { data = text ? JSON.parse(text) : {}; } catch { data = {detail: text}; }
  if (!res.ok) throw new Error(formatApiError(data, res.statusText));
  return data;
}
function payload() {
  return {
    username: document.getElementById('username').value,
    password: document.getElementById('password').value,
    full_name: document.getElementById('fullName').value,
    department: document.getElementById('department').value,
    note: document.getElementById('note').value,
  };
}
function updateCurrentUser(user) {
  pageState.currentUser = user || null;
  setAccountStatsUserOptions(pageState.accountStatsUserOptions);
  document.getElementById('accountStatsAllBtn').classList.toggle('hidden', !pageState.currentUser || pageState.currentUser.role !== 'superuser');
}
