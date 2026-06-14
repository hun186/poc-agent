function toIsoOrEmpty(localValue) {
  if (!localValue) return '';
  const d = new Date(localValue);
  return Number.isNaN(d.getTime()) ? '' : d.toISOString();
}
function localTimezoneOffsetMinutes() { return -new Date().getTimezoneOffset(); }
function formatLocalTimestamp(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit'}).format(d);
}

function bindMultiFilterOutsideDismiss(id) {
  const picker = $(id);
  if (!picker || picker.dataset.outsideDismissBound === 'true') return;
  picker.dataset.outsideDismissBound = 'true';
  document.addEventListener('click', (ev) => {
    if (!picker.open || picker.contains(ev.target)) return;
    picker.removeAttribute('open');
  });
}
function setUsageStatsUserOptions(values) {
  state.usageStatsUserOptions = [...new Set((values || []).map(v => String(v || '').trim()).filter(Boolean))].sort();
  if (state.user && !state.usageStatsUserOptions.includes(state.user.username)) state.usageStatsUserOptions.unshift(state.user.username);
  state.usageStatsSelectedUsers = state.usageStatsSelectedUsers.filter(v => state.usageStatsUserOptions.includes(v));
  renderUsageStatsUserPicker();
}
function visibleUsageStatsUserOptions() {
  const q = $('usageStatsUsernameSearch') ? $('usageStatsUsernameSearch').value.trim().toLowerCase() : '';
  return state.usageStatsUserOptions.filter(v => !q || v.toLowerCase().includes(q));
}
function renderUsageStatsUserPicker() {
  const box = $('usageStatsUsernameOptions');
  if (!box) return;
  const visible = visibleUsageStatsUserOptions();
  const selected = new Set(state.usageStatsSelectedUsers);
  box.innerHTML = visible.map(v => `<label class="multi-filter-option"><input type="checkbox" data-usage-stats-user="${esc(v)}" ${selected.has(v) ? 'checked' : ''} /> <span>${esc(v)}</span></label>`).join('') || '<p class="muted">沒有符合關鍵字的使用者。</p>';
  box.querySelectorAll('[data-usage-stats-user]').forEach(input => input.onchange = () => {
    const value = input.dataset.usageStatsUser;
    state.usageStatsSelectedUsers = input.checked ? [...new Set(state.usageStatsSelectedUsers.concat([value]))] : state.usageStatsSelectedUsers.filter(v => v !== value);
    updateUsageStatsUserSummary();
  });
  updateUsageStatsUserSummary();
}
function updateUsageStatsUserSummary() {
  const selected = state.usageStatsSelectedUsers;
  $('usageStatsUsername').value = selected.join(',');
  const summary = $('usageStatsUsernameSummary');
  if (!summary) return;
  const note = $('usageStatsCurrentScopeText');
  if (state.usageStatsView === 'mine') {
    const text = state.user ? `目前顯示個人記錄：${state.user.username}` : '目前顯示個人記錄';
    summary.textContent = text;
    if (note) note.textContent = text;
  } else if (!selected.length) summary.textContent = '全體使用者';
  else summary.textContent = selected.length <= 2 ? selected.join(', ') : `已選 ${selected.length} 位使用者`;
}
function setVisibleUsageStatsUsers(checked) {
  const visible = visibleUsageStatsUserOptions();
  state.usageStatsSelectedUsers = checked ? [...new Set(state.usageStatsSelectedUsers.concat(visible))] : state.usageStatsSelectedUsers.filter(v => !visible.includes(v));
  renderUsageStatsUserPicker();
}
function updateAuditSelectOptions(id, values) {
  const el = $(id);
  const current = el.value;
  const opts = ['<option value="">全部</option>'].concat((values || []).map(v => `<option value="${esc(v)}">${esc(v)}</option>`));
  el.innerHTML = opts.join('');
  if (current && values.includes(current)) el.value = current;
}
function refreshAuditFilterOptions(hits) {
  const usernames = [...new Set((hits||[]).map(h => String(h.username||'').trim()).filter(Boolean))].sort();
  const indexes = [...new Set((hits||[]).map(h => String(h.index||'').trim()).filter(Boolean))].sort();
  const paths = [...new Set((hits||[]).flatMap(h => Array.isArray(h.changed_paths) ? h.changed_paths : []).map(v => String(v||'').trim()).filter(Boolean))].sort();
  updateAuditSelectOptions('auditUsername', usernames);
  updateAuditSelectOptions('auditIndex', indexes);
  updateAuditSelectOptions('auditPath', paths);
}
function renderUsageStats(targetId, stats) {
  if (!stats) {
    $(targetId).innerHTML = '<div class="muted">暫無資料</div>';
    return;
  }
  const block = (title, obj) => `<div class="user"><strong>${esc(title)}</strong>${Object.entries(obj || {}).map(([k, v]) => `<div class="muted">${esc(k)}: ${esc(v)}</div>`).join('')}</div>`;
  $(targetId).innerHTML = `<div class="user"><strong>總操作次數</strong><div class="muted">${esc(stats.total_events || 0)}</div><div class="muted">異動欄位總數：${esc(stats.changed_paths_total || 0)}</div></div>${block('依動作', stats.by_action)}${block('依索引', stats.by_index)}${block('依使用者', stats.by_user)}`;
}
async function refreshUsageStats() {
  try {
    const data = await api('/v1/editor/usage-stats?' + collectUsageStatsQuery().toString());
    renderUsageStats('myStats', data.me);
    if (state.user && state.user.role === 'superuser') renderUsageStats('adminStats', data.all);
    renderFilteredUsageStats(data.filtered);
    setStatus('usageStatsStatus', data.filtered?.is_restricted_to_self ? '已載入自己的使用統計；superuser 可查詢全體帳號。' : '已載入使用統計。', 'ok');
  } catch (err) {
    $('myStats').innerHTML = `<div class="status error">${esc(err.message)}</div>`;
    $('adminStats').innerHTML = `<div class="status error">${esc(err.message)}</div>`;
    setStatus('usageStatsStatus', err.message, 'error');
  }
}
function configureUsageStatsSource(source) {
  state.usageStatsSource = source === 'account' ? 'account' : 'document';
  const category = $('usageStatsCategory');
  const options = state.usageStatsSource === 'account'
    ? [{value: 'account', label: '帳號操作記錄使用統計'}]
    : [{value: 'document', label: 'ES 文件異動紀錄使用統計'}];
  category.innerHTML = options.map(opt => `<option value="${esc(opt.value)}">${esc(opt.label)}</option>`).join('');
  category.value = options[0].value;
  $('usageStatsIndexField').classList.toggle('hidden', state.usageStatsSource === 'account');
  if (state.usageStatsSource === 'account') $('usageStatsIndex').value = '';
  updateStatsViewLabels();
}
function updateStatsViewLabels() {
  const isAccount = state.usageStatsSource === 'account';
  $('statsMineTabBtn').textContent = isAccount ? '我的帳號操作紀錄' : '我的 ES 文件異動紀錄';
  $('statsAllTabBtn').textContent = isAccount ? '全體帳號操作紀錄' : '全體 ES 文件異動紀錄';
}
function collectUsageStatsQuery() {
  const params = new URLSearchParams({
    category: $('usageStatsCategory').value,
    chart_bucket: $('usageStatsBucket').value,
    events_limit: String(Math.max(1, Math.min(500, Number($('usageStatsEventsLimit').value || 100)))),
    timezone_offset_minutes: String(localTimezoneOffsetMinutes()),
  });
  const mapping = {
    username: state.usageStatsView === 'mine' && state.user ? state.user.username : state.usageStatsSelectedUsers.join(','),
    action: $('usageStatsAction').value.trim(),
    index: state.usageStatsSource === 'account' ? '' : $('usageStatsIndex').value.trim(),
    start_ts: toIsoOrEmpty($('usageStatsStartTs').value.trim()),
    end_ts: toIsoOrEmpty($('usageStatsEndTs').value.trim()),
  };
  Object.entries(mapping).forEach(([key, value]) => { if (value) params.set(key, value); });
  return params;
}
function auditTimestampValue(row) {
  const ts = row && (row.ts || row.processed_at || row.created_at);
  const value = ts ? Date.parse(ts) : NaN;
  return Number.isNaN(value) ? 0 : value;
}
function sortAuditRows(rows) { return (rows || []).slice().sort((a, b) => auditTimestampValue(b) - auditTimestampValue(a)); }
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
function pagerId(config, suffix) {
  const base = (config.prevId || '').replace(/PrevBtn$/, '');
  return config[suffix] || (base ? `${base}${suffix[0].toUpperCase()}${suffix.slice(1)}` : '');
}
function updateClientPager(config) {
  const page = paginateAuditRows(config.rows, config.page, config.pageSize || 25);
  const info = $(config.infoId);
  const first = $(pagerId(config, 'firstBtn'));
  const prev = $(config.prevId);
  const next = $(config.nextId);
  const last = $(pagerId(config, 'lastBtn'));
  const input = $(pagerId(config, 'pageInput'));
  if (info) info.textContent = `第 ${page.page} / ${page.totalPages} 頁，顯示 ${page.start}-${page.end} 筆，共 ${page.total} 筆`;
  if (first) first.disabled = page.page <= 1;
  if (prev) prev.disabled = page.page <= 1;
  if (next) next.disabled = page.page >= page.totalPages;
  if (last) last.disabled = page.page >= page.totalPages;
  if (input) {
    input.value = String(page.page);
    input.max = String(page.totalPages);
  }
  return page;
}
function bindClientPagerActions(prefix, getPage, setPage, renderPage) {
  const jumpTo = (page) => { setPage(page); renderPage(); };
  $(`${prefix}FirstBtn`).onclick = () => jumpTo(1);
  $(`${prefix}PrevBtn`).onclick = () => jumpTo(getPage() - 1);
  $(`${prefix}NextBtn`).onclick = () => jumpTo(getPage() + 1);
  $(`${prefix}LastBtn`).onclick = () => jumpTo(Number.MAX_SAFE_INTEGER);
  $(`${prefix}GotoBtn`).onclick = () => jumpTo(Number($(`${prefix}PageInput`).value || 1));
  $(`${prefix}PageInput`).onkeydown = (ev) => { if (ev.key === 'Enter') jumpTo(Number(ev.currentTarget.value || 1)); };
}
function renderUsageStatsAuditEvents(filtered) {
  const events = sortAuditRows((filtered && filtered.events) || []);
  const total = filtered?.events_total ?? events.length;
  const limit = filtered?.events_limit ?? events.length;
  state.usageStatsAuditRows = events;
  state.usageStatsAuditPage = 1;
  state.usageStatsAuditMeta = { total, limit };
  renderUsageStatsAuditEventsPage();
}
function renderUsageStatsAuditEventsPage() {
  const page = updateClientPager({rows: state.usageStatsAuditRows, page: state.usageStatsAuditPage, pageSize: 25, infoId: 'usageStatsAuditPageInfo', prevId: 'usageStatsAuditPrevBtn', nextId: 'usageStatsAuditNextBtn'});
  state.usageStatsAuditPage = page.page;
  $('usageStatsAuditEvents').innerHTML = page.rows.map((h) => {
    const paths = Array.isArray(h.changed_paths) ? h.changed_paths.filter(Boolean) : [];
    return `<div class="audit">
      <div><strong>${esc(auditActionLabel(h.action))}</strong><span class="muted"> ｜${esc(h.action || '')}</span></div>
      <div class="muted">${esc(formatLocalTimestamp(h.ts))}｜${esc(h.username || '-') } (${esc(h.role || '-')})</div>
      <div class="muted">index=${esc(h.index || '-')} / id=${esc(h.id || '-')} / result=${esc(h.result || '-')}</div>
      <div class="muted">異動欄位：${paths.length ? esc(paths.join(', ')) : '(無)'}</div>
    </div>`;
  }).join('') || '<p class="muted">目前篩選條件下無 audit 事件。</p>';
  const meta = state.usageStatsAuditMeta || {};
  if (state.usageStatsAuditRows.length && Number(meta.total || 0) > state.usageStatsAuditRows.length) {
    $('usageStatsAuditEvents').insertAdjacentHTML('afterbegin', `<p class="muted">先套用統計篩選與時間排序，再分頁顯示；目前載入最近 ${esc(state.usageStatsAuditRows.length)} / ${esc(meta.total)} 筆（上限 ${esc(meta.limit)} 筆）。</p>`);
  }
}
function renderFilteredUsageStats(filtered) {
  if (!filtered) return;
  const stats = filtered.stats || {};
  SraAuditTools.renderSummaryCards($('usageStatsSummaryCards'), [
    {label: '總操作次數', value: stats.total_events || 0, hint: filtered.category || 'all'},
    {label: '異動欄位總數', value: stats.changed_paths_total || 0, hint: '文件類動作會累計欄位'},
    {label: '動作種類', value: Object.keys(stats.by_action || {}).length, hint: '依目前篩選'},
    {label: '使用者數', value: Object.keys(stats.by_user || {}).length, hint: '依目前篩選'},
  ]);
  SraAuditTools.renderTimeSeriesChart({
    rows: filtered.series || [],
    bucket: filtered.chart_bucket || $('usageStatsBucket').value,
    bucketLabel: filtered.chart_bucket_label || '每日',
    titleEl: $('usageStatsSeriesTitle'),
    summaryEl: $('usageStatsSeriesSummary'),
    chartEl: $('usageStatsChart'),
    seriesName: '使用統計筆數',
  });
  renderUsageStatsAuditEvents(filtered);
}
async function loadFilteredUsageStats() {
  setStatus('usageStatsStatus', '查詢使用統計中...');
  try {
    const data = await api('/v1/editor/usage-stats?' + collectUsageStatsQuery().toString());
    renderUsageStats('myStats', data.me);
    if (state.user && state.user.role === 'superuser') renderUsageStats('adminStats', data.all);
    renderFilteredUsageStats(data.filtered);
    setStatus('usageStatsStatus', data.filtered?.is_restricted_to_self ? '已套用篩選（一般使用者限定自己的紀錄）。' : '已套用統計篩選。', 'ok');
  } catch (err) {
    setStatus('usageStatsStatus', err.message, 'error');
  }
}
function clearUsageStatsFilters() {
  configureUsageStatsSource(state.usageStatsSource || 'document');
  state.usageStatsSelectedUsers = [];
  $('usageStatsUsernameSearch').value = '';
  renderUsageStatsUserPicker();
  $('usageStatsAction').value = '';
  $('usageStatsIndex').value = '';
  $('usageStatsStartTs').value = '';
  $('usageStatsEndTs').value = '';
  $('usageStatsBucket').value = 'day';
  $('usageStatsEventsLimit').value = '100';
}
function switchMainTab(tab, opts={}) {
  if (tab === 'stats') {
    configureUsageStatsSource(opts.source || opts.category || state.usageStatsSource || 'document');
    if (opts.category) $('usageStatsCategory').value = opts.category;
    if (opts.view) switchStatsView(opts.view);
    else loadFilteredUsageStats();
  }
  $('searchCard').classList.toggle('hidden', tab !== 'search');
  $('statsCard').classList.toggle('hidden', tab !== 'stats');
  $('accountCard').classList.toggle('hidden', tab !== 'account');
  $('adminCard').classList.toggle('hidden', tab !== 'review');
  $('auditCard').classList.toggle('hidden', tab !== 'audit');
  $('accountAuditCard').classList.toggle('hidden', tab !== 'account-audit');
  const showEditor = tab === 'search';
  $('editorCard').classList.toggle('hidden', !showEditor);
  $('workspaceGrid').classList.toggle('single-pane', !showEditor);
}
function switchStatsView(view) {
  const canViewAll = state.user && state.user.role === 'superuser';
  state.usageStatsView = view === 'all' && canViewAll ? 'all' : 'mine';
  const mine = state.usageStatsView === 'mine';
  $('usageStatsUsernamePicker').classList.toggle('hidden', mine);
  $('usageStatsCurrentScopeNote').classList.toggle('hidden', !mine);
  if (mine) $('usageStatsUsernamePicker').removeAttribute('open');
  updateUsageStatsUserSummary();
  $('myStats').classList.toggle('hidden', !mine);
  $('adminStats').classList.toggle('hidden', mine);
  updateStatsViewLabels();
  loadFilteredUsageStats();
}
