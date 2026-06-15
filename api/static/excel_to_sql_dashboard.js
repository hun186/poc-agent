const tokenKey = 'sra_editor_token';
const state = { recentPage: 1, recentTotal: 0, recentPageSize: 100, destinationTableDirty: false };
function $(id) { return document.getElementById(id); }
function escapeHtml(v) { return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function statusBadge(s) { return `<span class="status ${escapeHtml(s)}">${escapeHtml(s || '(empty)')}</span>`; }
function showError(text) { const el=$('msg'); if (!text) { el.classList.add('hidden'); el.textContent=''; } else { el.classList.remove('hidden'); el.textContent=text; } }
function metric(summary, status) { const row = summary.find(x => x.status === status); return Number(row?.count || 0); }



function renderCards(data) {
  const inserted = metric(data.summary, 'inserted');
  const duplicate = metric(data.summary, 'duplicate');
  const failed = metric(data.summary, 'failed');
  const smart = metric(data.summary, 'header_smart_match');
  const total = data.summary.reduce((a, x) => a + Number(x.count || 0), 0);
  $('cards').innerHTML = [
    ['總事件', total, 'audit rows'], ['新增', inserted, 'inserted'], ['重複略過', duplicate, 'duplicate'], ['失敗', failed, 'failed'], ['欄名智慧比對', smart, 'header_smart_match']
  ].map(([label, value, cls]) => `<div class="card"><div class="muted">${label}</div><div class="metric ${cls}">${value}</div></div>`).join('');
}
function fillTable(id, rows, render) { document.querySelector(`#${id} tbody`).innerHTML = rows.map(render).join('') || '<tr><td colspan="99" class="muted">無資料</td></tr>'; }
function authToken() { return localStorage.getItem(tokenKey) || ''; }
async function loadCurrentUser() {
  const token = authToken();
  if (!token) { $('whoami').textContent = '未登入'; return; }
  try {
    const res = await fetch('/v1/auth/me', { headers: { Authorization: 'Bearer ' + token } });
    if (!res.ok) throw new Error('unauthorized');
    const data = await res.json();
    const user = data.user || {};
    $('whoami').textContent = user.username ? `${user.username} (${user.role || '-'})` : '未登入';
  } catch (_) {
    $('whoami').textContent = '登入已失效';
  }
}
function pad2(v) { return String(v).padStart(2, '0'); }
function toLocalInputValue(d) { return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`; }
function resetDefaultWindow() {
  $('startTs').value = '';
  $('endTs').value = '';
  $('days').value = 14;
  $('chartBucket').value = 'day';
}
function fillRecentWindow() {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  $('startTs').value = toLocalInputValue(start);
  $('endTs').value = toLocalInputValue(end);
  $('days').value = 14;
}
function localInputToUtcIso(id) { const v = $(id).value; return v ? new Date(v).toISOString() : ''; }
function refreshDashboardNow() { loadDashboard(); }
function normalizeAuditUtc(text) {
  const raw = String(text || '');
  if (!raw) return null;
  const trimmed = raw.replace(/(\.\d{3})\d+/, '$1');
  return /[zZ]|[+-]\d\d:?\d\d$/.test(trimmed) ? trimmed : trimmed + 'Z';
}
function formatAuditTime(value) {
  const raw = String(value || '');
  const normalized = normalizeAuditUtc(raw);
  if (!normalized) return '';
  const local = new Date(normalized);
  if (Number.isNaN(local.getTime())) return escapeHtml(raw);
  return `<div>${escapeHtml(local.toLocaleString())}</div><div class="muted">UTC：${escapeHtml(raw)}</div>`;
}
function resetRecentPage() { state.recentPage = 1; }
function applyAuditFilters() { resetRecentPage(); loadDashboard(); }
function selectedValues(id) {
  const el = $(id);
  if (el.selectedOptions) return Array.from(el.selectedOptions).map(option => option.value).filter(Boolean);
  return Array.from(el.querySelectorAll('input[type="checkbox"]:checked')).map(input => input.value).filter(Boolean);
}
function updateDestinationTableSummary() {
  const values = selectedValues('destinationTableFilter');
  $('destinationTableSummary').textContent = values.length ? `已選 ${values.length} 個 table：${values.join(', ')}` : '全部目的地 table';
}
function clearAuditFilters() { ['statusFilter','sourceFileFilter','rowNoFilter','messageFilter','hashFilter','payloadFilter'].forEach(id => { $(id).value = ''; }); $('destinationTableFilter').querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; }); updateDestinationTableSummary(); applyAuditFilters(); }
function renderDestinationTableOptions(options) {
  const el = $('destinationTableFilter');
  const selected = new Set(selectedValues('destinationTableFilter'));
  const values = Array.from(new Set((options || []).map(value => String(value || '').trim()).filter(Boolean)));
  selected.forEach(value => { if (value && !values.includes(value)) values.push(value); });
  if (!values.length) { el.innerHTML = '<div class="muted">無可選 table</div>'; updateDestinationTableSummary(); return; }
  el.innerHTML = values.map((value, index) => `<label class="multi-select-option"><input type="checkbox" value="${escapeHtml(value)}"${selected.has(value) ? ' checked' : ''} aria-label="目的地 table ${index + 1}"><span>${escapeHtml(value)}</span></label>`).join('');
  updateDestinationTableSummary();
}
function applyDestinationTablePendingFilters() {
  if (!state.destinationTableDirty) return;
  state.destinationTableDirty = false;
  applyAuditFilters();
}
function closeDestinationTableDropdown(applyPending = false) {
  const dropdown = $('destinationTableDropdown');
  if (dropdown.open) dropdown.open = false;
  if (applyPending) applyDestinationTablePendingFilters();
}
function changeRecentPage(delta) {
  const next = state.recentPage + delta;
  const maxPage = Math.max(1, Math.ceil(state.recentTotal / Math.max(state.recentPageSize, 1)));
  if (next < 1 || next > maxPage) return;
  state.recentPage = next;
  loadDashboard();
}
function updateRecentPager(data) {
  const paging = data.recent_paging || {};
  state.recentPage = Number(paging.page || state.recentPage || 1);
  state.recentPageSize = Number(paging.page_size || $('limit').value || 100);
  state.recentTotal = Number(paging.total || (data.recent || []).length || 0);
  const totalPages = Math.max(1, Math.ceil(state.recentTotal / Math.max(state.recentPageSize, 1)));
  const start = state.recentTotal ? ((state.recentPage - 1) * state.recentPageSize + 1) : 0;
  const end = Math.min(state.recentTotal, state.recentPage * state.recentPageSize);
  $('recentPageInfo').textContent = `第 ${state.recentPage} / ${totalPages} 頁，顯示 ${start}-${end} 筆，共 ${state.recentTotal} 筆`;
  $('recentPrevBtn').disabled = state.recentPage <= 1;
  $('recentNextBtn').disabled = state.recentPage >= totalPages;
}
function renderJson(value, level = 0) {
  const indent = '  '.repeat(level);
  const nextIndent = '  '.repeat(level + 1);
  if (value === null) return '<span class="json-null">null</span>';
  if (Array.isArray(value)) {
    if (!value.length) return '[]';
    return '[\n' + value.map(item => nextIndent + renderJson(item, level + 1)).join(',\n') + '\n' + indent + ']';
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value);
    if (!entries.length) return '{}';
    return '{\n' + entries.map(([key, val]) => `${nextIndent}<span class="json-key">"${escapeHtml(key)}"</span>: ${renderJson(val, level + 1)}`).join(',\n') + '\n' + indent + '}';
  }
  if (typeof value === 'string') return `<span class="json-string">${escapeHtml(JSON.stringify(value))}</span>`;
  if (typeof value === 'number' || typeof value === 'boolean') return `<span class="json-number">${escapeHtml(value)}</span>`;
  return escapeHtml(JSON.stringify(value));
}
function payloadCell(payload) {
  const value = (payload === undefined || payload === '') ? {} : payload;
  return `<pre class="json-view">${renderJson(value)}</pre>`;
}
function renderFilteredDailyChart(rows, bucket = 'day', bucketLabel = '每日') {
  SraAuditTools.renderTimeSeriesChart({
    rows,
    bucket,
    bucketLabel,
    titleEl: $('filteredSeriesTitle'),
    summaryEl: $('filteredDailySummary'),
    chartEl: $('filteredDailyChart'),
    seriesName: 'audit 筆數',
    emptyText: '目前篩選條件下無資料',
  });
}
function onTaskChange() { if ($('task').value) $('config').value = $('task').value; applyAuditFilters(); }
async function loadTasks() {
  const token = authToken();
  if (!token) { showError('請先到 /editor 登入；本儀表板會沿用 sra_editor_token。'); return; }
  const res = await fetch('/v1/excel-to-sql/dashboard-tasks', { headers: { Authorization: 'Bearer ' + token } });
  if (!res.ok) return;
  const data = await res.json();
  const tasks = data.tasks || [];
  $('task').innerHTML = tasks.length
    ? tasks.map(t => `<option value="${escapeHtml(t.config_path)}">${escapeHtml(t.name)} (${escapeHtml(t.config_path)})</option>`).join('')
    : '<option value="">未找到 dashboard.enabled=true 的任務</option>';
  if (tasks.length) $('config').value = tasks[0].config_path;
}

async function deleteImportedRow(hashValue) {
  if (!hashValue) return;
  const reason = prompt('請輸入刪除原因（會寫入 audit）：', '資料列內容錯誤，人工刪除');
  if (reason === null) return;
  if (!confirm(`確定要從 SQL 目的表刪除 hash_value=${hashValue} 的資料列？
注意：若資料已進 ES，仍需到 ES 編輯介面另外處理。`)) return;
  const token = authToken();
  const res = await fetch('/v1/excel-to-sql/delete-row', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify({ config: $('config').value, hash_value: hashValue, reason })
  });
  if (!res.ok) { let text = await res.text(); try { text = JSON.parse(text).detail || text; } catch (_) {} showError(text); return; }
  const data = await res.json();
  showError(`已執行：${data.status}，刪除 ${data.deleted_rows} 筆。`);
  await loadDashboard();
}
function actionCell(r) {
  if (!r.hash_value || r.status === 'sql_deleted') return '';
  return `<button class="secondary" onclick="deleteImportedRow('${escapeHtml(r.hash_value)}')">刪除SQL列</button>`;
}

async function loadDashboard() {
  showError('');
  const token = authToken();
  if (!token) { showError('請先到 /editor 登入；本儀表板會沿用 sra_editor_token。'); return; }
  const pageSize = Math.max(1, Math.min(Number($('limit').value || 100), 1000));
  const params = new URLSearchParams({ config: $('config').value, days: $('days').value, limit: pageSize, page: state.recentPage, chart_bucket: $('chartBucket').value });
  const startIso = localInputToUtcIso('startTs');
  const endIso = localInputToUtcIso('endTs');
  if (startIso) params.set('start_ts', startIso);
  if (endIso) params.set('end_ts', endIso);
  const filters = { status_filter: $('statusFilter').value, source_file_filter: $('sourceFileFilter').value, row_no_filter: $('rowNoFilter').value, message_filter: $('messageFilter').value, hash_value_filter: $('hashFilter').value, payload_filter: $('payloadFilter').value };
  Object.entries(filters).forEach(([key, value]) => { if (String(value || '').trim()) params.set(key, value); });
  selectedValues('destinationTableFilter').forEach(value => params.append('destination_table_filter', value));
  const res = await fetch('/v1/excel-to-sql/dashboard?' + params.toString(), { headers: { Authorization: 'Bearer ' + token } });
  if (!res.ok) { let text = await res.text(); try { text = JSON.parse(text).detail || text; } catch (_) {} showError(text); return; }
  const data = await res.json();
  document.title = (data.task_name || 'Excel→SQL 匯入 SQL') + ' - 監控儀表板';
  if (!data.exists) showError(`audit table 尚不存在：${data.audit_table}`);
  $('timeBasis').textContent = `audit 時間以本機時間顯示（${Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'}）；起迄時間輸入也是本機時間，系統會轉成 ${data.audit_time_basis || 'UTC'} 查詢。`;
  renderCards(data);
  fillTable('daily', data.daily, r => `<tr><td>${escapeHtml(r.day)}</td><td>${statusBadge(r.status)}</td><td>${escapeHtml(r.count)}</td></tr>`);
  fillTable('files', data.files, r => `<tr><td>${escapeHtml(r.source_file)}</td><td>${escapeHtml(r.last_processed_at)}</td><td>${escapeHtml(r.inserted_rows)}</td><td>${escapeHtml(r.duplicate_rows)}</td><td>${escapeHtml(r.failed_rows)}</td><td>${escapeHtml(r.header_smart_matches)}</td></tr>`);
  renderDestinationTableOptions(data.destination_table_options || []);
  if (data.chart_bucket && $('chartBucket').value !== data.chart_bucket) $('chartBucket').value = data.chart_bucket;
  renderFilteredDailyChart(data.filtered_series || data.filtered_daily || [], data.chart_bucket || $('chartBucket').value, data.chart_bucket_label || $('chartBucket').selectedOptions[0]?.textContent || '每日');
  updateRecentPager(data);
  fillTable('recent', data.recent, r => `<tr><td>${formatAuditTime(r.processed_at)}</td><td>${statusBadge(r.status)}</td><td>${escapeHtml(r.source_file)}</td><td>${escapeHtml(r.row_no ?? '')}</td><td>${escapeHtml(r.message || '')}</td><td>${actionCell(r)}</td><td class="payload-col">${payloadCell(r.row_payload)}</td></tr>`);
}
function bindAuditFilterEvents() {
  ['statusFilter','sourceFileFilter','rowNoFilter','messageFilter','hashFilter','payloadFilter'].forEach(id => {
    const el = $(id);
    el.addEventListener('change', applyAuditFilters);
    el.addEventListener('keydown', event => { if (event.key === 'Enter') applyAuditFilters(); });
  });
  const destinationDropdown = $('destinationTableDropdown');
  $('destinationTableFilter').addEventListener('change', () => { state.destinationTableDirty = true; updateDestinationTableSummary(); });
  $('destinationTableFilter').addEventListener('keydown', event => { if (event.key === 'Enter') closeDestinationTableDropdown(true); });
  destinationDropdown.addEventListener('toggle', () => { if (!destinationDropdown.open) applyDestinationTablePendingFilters(); });
  destinationDropdown.addEventListener('focusout', () => { setTimeout(() => { if (!destinationDropdown.contains(document.activeElement)) closeDestinationTableDropdown(true); }, 0); });
  document.addEventListener('click', event => { if (!destinationDropdown.contains(event.target)) closeDestinationTableDropdown(true); });
  $('limit').addEventListener('change', applyAuditFilters);
  $('chartBucket').addEventListener('change', applyAuditFilters);
}
bindAuditFilterEvents();
// boot order includes: await loadCurrentUser(); await loadTasks(); await loadDashboard();
(async () => { resetDefaultWindow(); await loadCurrentUser(); await loadTasks(); await loadDashboard(); })().catch(err => showError(err.message || String(err)));
