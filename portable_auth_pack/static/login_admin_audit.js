function tsValue(row) {
  const value = row && row.ts ? Date.parse(row.ts) : NaN;
  return Number.isNaN(value) ? 0 : value;
}
function localTimezoneOffsetMinutes() { return -new Date().getTimezoneOffset(); }
function formatLocalTimestamp(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit"}).format(d);
}
function localPaginateRows(rows, page, pageSize) {
  const allRows = Array.isArray(rows) ? rows : [];
  const size = Math.max(1, Number(pageSize || 25));
  const total = allRows.length;
  const totalPages = Math.max(1, Math.ceil(total / size));
  const currentPage = Math.min(Math.max(1, Number(page || 1)), totalPages);
  const startIndex = (currentPage - 1) * size;
  return {
    rows: allRows.slice(startIndex, startIndex + size),
    page: currentPage,
    pageSize: size,
    total,
    totalPages,
    start: total ? startIndex + 1 : 0,
    end: Math.min(total, startIndex + size),
  };
}
function paginateAuditRows(rows, page, pageSize) {
  const sharedPaginator = window.SraAuditTools && window.SraAuditTools.paginateRows;
  return typeof sharedPaginator === 'function' ? sharedPaginator(rows, page, pageSize) : localPaginateRows(rows, page, pageSize);
}
function pagerElementId(prevId, suffix) {
  const base = String(prevId || '').replace(/PrevBtn$/, '');
  return base ? `${base}${suffix}` : '';
}
function updatePager(rows, page, infoId, prevId, nextId) {
  const pageData = paginateAuditRows(rows, page, 25);
  const first = document.getElementById(pagerElementId(prevId, 'FirstBtn'));
  const prev = document.getElementById(prevId);
  const next = document.getElementById(nextId);
  const last = document.getElementById(pagerElementId(prevId, 'LastBtn'));
  const input = document.getElementById(pagerElementId(prevId, 'PageInput'));
  document.getElementById(infoId).textContent = `第 ${pageData.page} / ${pageData.totalPages} 頁，顯示 ${pageData.start}-${pageData.end} 筆，共 ${pageData.total} 筆`;
  if (first) first.disabled = pageData.page <= 1;
  if (prev) prev.disabled = pageData.page <= 1;
  if (next) next.disabled = pageData.page >= pageData.totalPages;
  if (last) last.disabled = pageData.page >= pageData.totalPages;
  if (input) {
    input.value = String(pageData.page);
    input.max = String(pageData.totalPages);
  }
  return pageData;
}
function bindPagerActions(prefix, getPage, setPage, renderPage) {
  const jumpTo = (page) => { setPage(page); renderPage(); };
  document.getElementById(`${prefix}FirstBtn`).onclick = () => jumpTo(1);
  document.getElementById(`${prefix}PrevBtn`).onclick = () => jumpTo(getPage() - 1);
  document.getElementById(`${prefix}NextBtn`).onclick = () => jumpTo(getPage() + 1);
  document.getElementById(`${prefix}LastBtn`).onclick = () => jumpTo(Number.MAX_SAFE_INTEGER);
  document.getElementById(`${prefix}GotoBtn`).onclick = () => jumpTo(Number(document.getElementById(`${prefix}PageInput`).value || 1));
  document.getElementById(`${prefix}PageInput`).onkeydown = (ev) => { if (ev.key === 'Enter') jumpTo(Number(ev.currentTarget.value || 1)); };
}
function renderLoginAuditPage() {
  const page = updatePager(pageState.loginAuditRows, pageState.loginAuditPage, 'loginAuditPageInfo', 'loginAuditPrevBtn', 'loginAuditNextBtn');
  pageState.loginAuditPage = page.page;
  document.getElementById('loginAuditHits').innerHTML = page.rows.map(ev => `<div class="audit"><strong>${esc(ev.username || '-')}</strong><div class="muted">${esc(formatLocalTimestamp(ev.ts))} success=${esc(ev.success)} reason=${esc(ev.reason || '-')} role=${esc(ev.role || '-')} status=${esc(ev.status || '-')}</div><div class="muted">client=${esc(ev.client_host || '-')} user_agent=${esc(ev.user_agent || '-')}</div></div>`).join('') || '<p class="muted">尚無登入稽核紀錄。</p>';
}
async function loginAudit() {
  try {
    const data = await api('/v1/auth/login-audit');
    pageState.loginAuditRows = (data.events || []).slice().sort((a, b) => tsValue(b) - tsValue(a));
    pageState.loginAuditPage = 1;
    renderLoginAuditPage();
    out(data);
  }
  catch (err) { out(String(err.message || err)); }
}

function bindMultiFilterOutsideDismiss(id) { const picker = document.getElementById(id); if (!picker || picker.dataset.outsideDismissBound === 'true') return; picker.dataset.outsideDismissBound = 'true'; document.addEventListener('click', (ev) => { if (!picker.open || picker.contains(ev.target)) return; picker.removeAttribute('open'); }); }
