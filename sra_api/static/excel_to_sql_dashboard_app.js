const tokenKey = 'sra_editor_token';
const state = { recentPage: 1, recentTotal: 0, recentPageSize: 100, destinationTableDirty: false, usernameOptions: [], selectedUsers: [], usernameDirty: false, batchDeleteReport: null, canDelete: false };
function $(id) { return document.getElementById(id); }
function escapeHtml(v) { return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function statusBadge(s) { return `<span class="status ${escapeHtml(s)}">${escapeHtml(s || '(empty)')}</span>`; }
function showError(text) { const el=$('msg'); if (!text) { el.classList.add('hidden'); el.textContent=''; } else { el.classList.remove('hidden'); el.textContent=text; alert(text); } }
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
function applyInitialQueryParams() {
  const query = new URLSearchParams(window.location.search || '');
  const map = { config: 'config', days: 'days', source_file_filter: 'sourceFileFilter', status_filter: 'statusFilter', row_no_filter: 'rowNoFilter', message_filter: 'messageFilter', hash_value_filter: 'hashFilter', payload_filter: 'payloadFilter', chart_bucket: 'chartBucket' };
  Object.entries(map).forEach(([param, id]) => { const value = query.get(param); if (value !== null && $(id)) $(id).value = value; });
  const users = query.getAll('username_filter').map(value => String(value || '').trim()).filter(Boolean);
  if (users.length) state.selectedUsers = users;
}
function fillRecentWindow() {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  $('startTs').value = toLocalInputValue(start);
  $('endTs').value = toLocalInputValue(end);
  $('days').value = 14;
}
function localInputToUtcIso(id) { const el = $(id); const v = el?.value || ''; return v ? new Date(v).toISOString() : ''; }
function auditRangeStartIso() { return localInputToUtcIso('auditStartTs') || localInputToUtcIso('startTs'); }
function auditRangeEndIso() { return localInputToUtcIso('auditEndTs') || localInputToUtcIso('endTs'); }
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
function renderUsernameFilter() {
  SraAuditTools.renderMultiFilterOptions({
    values: state.usernameOptions,
    selectedValues: state.selectedUsers,
    getSelectedValues: () => state.selectedUsers,
    searchEl: $('usernameSearch'),
    optionsEl: $('usernameFilter'),
    dataAttr: 'data-audit-username',
    emptyText: '沒有符合關鍵字的使用者。',
    onSelectionChange: values => { state.selectedUsers = values; state.usernameDirty = true; updateUsernameSummary(); },
  });
  updateUsernameSummary();
}
function updateUsernameSummary() {
  SraAuditTools.summarizeMultiFilterSelection({
    selectedValues: state.selectedUsers,
    hiddenInput: $('usernameFilterValue'),
    summaryEl: $('usernameSummary'),
    allLabel: '全體使用者',
    unitLabel: '位使用者',
  });
}
function applyUsernamePendingFilters() {
  if (!state.usernameDirty) return;
  state.usernameDirty = false;
  applyAuditFilters();
}
function closeUsernameDropdown(applyPending = false) {
  const dropdown = $('usernameDropdown');
  if (dropdown.open) dropdown.open = false;
  if (applyPending) applyUsernamePendingFilters();
}
function clearAuditFilters() { ['statusFilter','sourceFileFilter','auditStartTs','auditEndTs','rowNoFilter','messageFilter','hashFilter','payloadFilter'].forEach(id => { $(id).value = ''; }); state.selectedUsers = []; state.usernameDirty = false; renderUsernameFilter(); $('destinationTableFilter').querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; }); updateDestinationTableSummary(); applyAuditFilters(); }
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
function updateRecentPager(data) {
  const paging = data.recent_paging || {};
  state.recentPage = Number(paging.page || state.recentPage || 1);
  state.recentPageSize = Number(paging.page_size || $('limit').value || 100);
  state.recentTotal = Number(paging.total || (data.recent || []).length || 0);
  const page = SraAuditTools.updatePager({page: state.recentPage, pageSize: state.recentPageSize, total: state.recentTotal, infoId: 'recentPageInfo', firstId: 'recentFirstBtn', prevId: 'recentPrevBtn', inputId: 'recentPageInput', gotoId: 'recentGotoBtn', nextId: 'recentNextBtn', lastId: 'recentLastBtn', inputLabel: '最近 audit 事件頁數'});
  state.recentPage = page.page;
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

function rowConfigPath(row) { return String(row?.source_config_path || $('config').value || '').trim(); }
function rowDestinationTable(row) { return String(row?.destination_table || row?.row_payload?.destination_table || '').trim(); }
async function deleteImportedRow(hashValue, rowConfig = '', rowDestination = '') {
  if (!hashValue) return;
  const deleteConfig = String(rowConfig || $('config').value || '').trim();
  const currentConfig = String($('config').value || '').trim();
  if (deleteConfig && currentConfig && deleteConfig !== currentConfig) {
    if (!confirm(`這筆 audit 事件的來源任務設定檔是：${deleteConfig}\n目前上方選取的是：${currentConfig}\n\n將改用 audit 事件的來源任務刪除對應 SQL table，是否繼續？`)) return;
  }
  const reason = prompt('請輸入刪除原因（會寫入 audit）：', '資料列內容錯誤，人工刪除');
  if (reason === null) return;
  if (!confirm(`確定要從 SQL 目的表刪除 hash_value=${hashValue} 的資料列？
注意：若資料已進 ES，仍需到 ES 編輯介面另外處理。`)) return;
  const token = authToken();
  const res = await fetch('/v1/excel-to-sql/delete-row', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify({ config: deleteConfig || $('config').value, hash_value: hashValue, reason })
  });
  if (!res.ok) { let text = await res.text(); try { text = JSON.parse(text).detail || text; } catch (_) {} showError(text); return; }
  const data = await res.json();
  showError(`已執行：${data.status}，刪除 ${data.deleted_rows} 筆。來源任務：${data.config_path || deleteConfig || '(未提供)'}；目的地 table：${data.destination_table || rowDestination || '(未提供)'}`);
  await loadDashboard();
}

function syncOperatorSourceVisibility() {
  const table = $('recent');
  if (table) table.classList.toggle('operator-source-hidden', !state.canDelete);
}
function operatorSourceCell(r) {
  if (!state.canDelete) return '';
  const sourceConfig = rowConfigPath(r);
  const destination = rowDestinationTable(r);
  const selected = String($('config').value || '').trim();
  const mismatch = sourceConfig && selected && sourceConfig !== selected;
  const sourceLabel = sourceConfig ? sourceConfig.split('/').pop() : '(未解析)';
  const tableLabel = destination || '(未提供 table)';
  const warning = mismatch ? '<div class="muted">⚠ 與上方任務不同</div>' : '';
  return `<div title="來源任務：${escapeHtml(sourceConfig || '(未解析)')}&#10;SQL table：${escapeHtml(destination || '(未提供)')}"><strong>${escapeHtml(sourceLabel)}</strong><div class="muted">${escapeHtml(tableLabel)}</div>${warning}</div>`;
}
function actionCell(r) {
  if (!state.canDelete || !r.hash_value || r.status === 'sql_deleted') return '';
  return `<button class="secondary" onclick="deleteImportedRow('${escapeHtml(r.hash_value)}', '${escapeHtml(rowConfigPath(r))}', '${escapeHtml(rowDestinationTable(r))}')">刪除SQL列</button>`;
}

function selectedDeletableRows() {
  return Array.from(document.querySelectorAll('[data-recent-delete-check]:checked')).map(input => ({
    hash_value: input.value,
    audit_id: input.dataset.auditId || '',
    source_file: input.dataset.sourceFile || '',
    row_no: input.dataset.rowNo || '',
    config_path: input.dataset.configPath || '',
    destination_table: input.dataset.destinationTable || '',
  })).filter(item => item.hash_value);
}
function toggleRecentSelection(checked) {
  document.querySelectorAll('[data-recent-delete-check]').forEach(input => { input.checked = checked; });
}
function batchDeleteConfirmationPhrase(rowCount) { return `DELETE ${rowCount}`; }
function confirmBatchDeleteRows(rows) {
  const rowCount = rows.length;
  const sampleHashes = rows.slice(0, 5).map(item => item.hash_value).join('\n');
  const phrase = batchDeleteConfirmationPhrase(rowCount);
  const typed = prompt(
    `高風險操作確認：即將批次刪除 ${rowCount} 筆 SQL 條目。\n` +
    `前 ${Math.min(rowCount, 5)} 筆 hash：\n${sampleHashes}\n\n` +
    `若確認要刪除，請完整輸入：${phrase}`,
    ''
  );
  return typed === phrase;
}
async function deleteSelectedImportedRows() {
  const rows = selectedDeletableRows();
  if (!rows.length) { showError('請先勾選至少一筆可刪除的 SQL 列。'); return; }
  const reason = prompt('請輸入批次刪除原因（會寫入 audit 與報告）：', '復原錯誤 Excel 匯入，批次刪除');
  if (reason === null) return;
  if (!reason.trim()) { showError('批次刪除需要填寫原因，避免事後無法追溯。'); return; }
  if (!confirmBatchDeleteRows(rows)) { showError('批次刪除已取消：確認文字不符合。'); return; }
  if (!confirm(`最後確認：確定要從 SQL 目的表刪除 ${rows.length} 筆資料？\n此操作會逐筆寫入 audit，且不會自動刪除 ES 文件。`)) return;
  const configPaths = Array.from(new Set(rows.map(item => String(item.config_path || $('config').value || '').trim()).filter(Boolean)));
  if (configPaths.length > 1) { showError(`批次刪除只能勾選同一個來源任務設定檔的 SQL 列；目前包含：${configPaths.join(', ')}`); return; }
  const deleteConfig = configPaths[0] || $('config').value;
  const token = authToken();
  const res = await fetch('/v1/excel-to-sql/delete-rows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify({ config: deleteConfig, hash_values: rows.map(item => item.hash_value), reason: reason.trim() })
  });
  if (!res.ok) { let text = await res.text(); try { text = JSON.parse(text).detail || text; } catch (_) {} showError(text); return; }
  const data = await res.json();
  state.batchDeleteReport = data.report || null;
  if ($('downloadBatchDeleteReportBtn')) $('downloadBatchDeleteReportBtn').disabled = !state.batchDeleteReport;
  showError(`批次刪除完成：成功刪除 ${data.deleted_rows || 0} 筆，處理 ${data.processed || 0} 個 hash。可下載批次刪除報告 Excel。`);
  await loadDashboard();
}
function flattenReportRow(row) {
  return {
    deleted_at: row.deleted_at || '',
    actor: row.actor || '',
    config_path: row.config_path || '',
    hash_value: row.hash_value || '',
    status: row.status || '',
    deleted_rows: row.deleted_rows ?? '',
    destination_table: row.destination_table || '',
    hash_field: row.hash_field || '',
    reason: row.reason || '',
    source_file: row.source_file || '',
    row_no: row.row_no || '',
    error: row.error || '',
    deleted_row_payloads: JSON.stringify(row.deleted_row_payloads || [], null, 2),
  };
}
function downloadBatchDeleteReport() {
  const report = state.batchDeleteReport;
  if (!report?.rows?.length) { showError('目前沒有可下載的批次刪除報告。'); return; }
  const headers = ['deleted_at','actor','config_path','hash_value','status','deleted_rows','destination_table','hash_field','reason','source_file','row_no','error','deleted_row_payloads'];
  const bodyRows = report.rows.map(flattenReportRow);
  const htmlRows = [headers, ...bodyRows.map(row => headers.map(header => row[header] ?? ''))]
    .map(cells => '<tr>' + cells.map(cell => `<td>${escapeHtml(cell)}</td>`).join('') + '</tr>').join('');
  const html = `<html><head><meta charset="utf-8" /></head><body><table>${htmlRows}</table></body></html>`;
  const blob = new Blob([html], { type: 'application/vnd.ms-excel;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `excel_sql_batch_delete_report_${new Date().toISOString().replace(/[:.]/g, '-')}.xls`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
function selectionCell(r) {
  if (!state.canDelete || !r.hash_value || r.status === 'sql_deleted') return '';
  return `<input type="checkbox" data-recent-delete-check value="${escapeHtml(r.hash_value)}" data-audit-id="${escapeHtml(r.audit_id || '')}" data-source-file="${escapeHtml(r.source_file || '')}" data-row-no="${escapeHtml(r.row_no ?? '')}" data-config-path="${escapeHtml(rowConfigPath(r))}" data-destination-table="${escapeHtml(rowDestinationTable(r))}" aria-label="勾選刪除 hash ${escapeHtml(r.hash_value)}">`;
}

async function loadDashboard() {
  showError('');
  const token = authToken();
  if (!token) { showError('請先到 /editor 登入；本儀表板會沿用 sra_editor_token。'); return; }
  const pageSize = Math.max(1, Math.min(Number($('limit').value || state.recentPageSize || 100), 1000));
  state.recentPageSize = pageSize;
  const params = new URLSearchParams({ config: $('config').value, days: $('days').value, limit: pageSize, page: state.recentPage, chart_bucket: $('chartBucket').value });
  const startIso = auditRangeStartIso();
  const endIso = auditRangeEndIso();
  if (startIso) params.set('start_ts', startIso);
  if (endIso) params.set('end_ts', endIso);
  const filters = { status_filter: $('statusFilter').value, source_file_filter: $('sourceFileFilter').value, row_no_filter: $('rowNoFilter').value, message_filter: $('messageFilter').value, hash_value_filter: $('hashFilter').value, payload_filter: $('payloadFilter').value };
  Object.entries(filters).forEach(([key, value]) => { if (String(value || '').trim()) params.set(key, value); });
  selectedValues('destinationTableFilter').forEach(value => params.append('destination_table_filter', value));
  state.selectedUsers.forEach(value => params.append('username_filter', value));
  const res = await fetch('/v1/excel-to-sql/dashboard?' + params.toString(), { headers: { Authorization: 'Bearer ' + token } });
  if (!res.ok) { let text = await res.text(); try { text = JSON.parse(text).detail || text; } catch (_) {} showError(text); return; }
  const data = await res.json();
  state.canDelete = Boolean(data.can_delete);
  syncOperatorSourceVisibility();
  document.title = (data.task_name || 'Excel→SQL 匯入 SQL') + ' - 匯入查詢儀表板';
  if (!data.exists) showError(`audit table 尚不存在：${data.audit_table}`);
  $('timeBasis').textContent = `audit 時間以本機時間顯示（${Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'}）；起迄時間輸入也是本機時間，系統會轉成 ${data.audit_time_basis || 'UTC'} 查詢。`;
  renderCards(data);
  fillTable('daily', data.daily, r => `<tr><td>${escapeHtml(r.day)}</td><td>${statusBadge(r.status)}</td><td>${escapeHtml(r.count)}</td></tr>`);
  fillTable('files', data.files, r => `<tr><td>${escapeHtml(r.source_file)}</td><td>${escapeHtml(r.last_processed_at)}</td><td>${escapeHtml(r.inserted_rows)}</td><td>${escapeHtml(r.duplicate_rows)}</td><td>${escapeHtml(r.failed_rows)}</td><td>${escapeHtml(r.header_smart_matches)}</td></tr>`);
  renderDestinationTableOptions(data.destination_table_options || []);
  state.usernameOptions = SraAuditTools.uniqueSortedValues([...(data.username_options || []), ...state.selectedUsers]);
  renderUsernameFilter();
  if (data.chart_bucket && $('chartBucket').value !== data.chart_bucket) $('chartBucket').value = data.chart_bucket;
  renderFilteredDailyChart(data.filtered_series || data.filtered_daily || [], data.chart_bucket || $('chartBucket').value, data.chart_bucket_label || $('chartBucket').selectedOptions[0]?.textContent || '每日');
  updateRecentPager(data);
  if ($('recentSelectAll')) $('recentSelectAll').checked = false;
  fillTable('recent', data.recent, r => `<tr><td class="select-col">${selectionCell(r)}</td><td class="time-col">${formatAuditTime(r.processed_at)}</td><td class="status-col">${statusBadge(r.status)}</td><td class="file-col" title="${escapeHtml(r.source_file)}">${escapeHtml(r.source_file)}</td><td class="user-col">${escapeHtml(r.username || '')}</td><td class="row-col">${escapeHtml(r.row_no ?? '')}</td><td class="message-col">${escapeHtml(r.message || '')}</td><td class="op-col">${operatorSourceCell(r)}</td><td class="action-col">${actionCell(r)}</td><td class="payload-col">${payloadCell(r.row_payload)}</td></tr>`);
}
function bindAuditFilterEvents() {
  ['statusFilter','sourceFileFilter','auditStartTs','auditEndTs','rowNoFilter','messageFilter','hashFilter','payloadFilter'].forEach(id => {
    const el = $(id);
    el.addEventListener('change', applyAuditFilters);
    el.addEventListener('keydown', event => { if (event.key === 'Enter') applyAuditFilters(); });
  });
  const destinationDropdown = $('destinationTableDropdown');
  const usernameDropdown = $('usernameDropdown');
  $('usernameSearch').addEventListener('input', renderUsernameFilter);
  $('selectVisibleUsersBtn').addEventListener('click', () => { state.selectedUsers = SraAuditTools.setVisibleMultiFilterSelection({values: state.usernameOptions, selectedValues: state.selectedUsers, searchEl: $('usernameSearch'), checked: true}); state.usernameDirty = true; renderUsernameFilter(); });
  $('clearVisibleUsersBtn').addEventListener('click', () => { state.selectedUsers = SraAuditTools.setVisibleMultiFilterSelection({values: state.usernameOptions, selectedValues: state.selectedUsers, searchEl: $('usernameSearch'), checked: false}); state.usernameDirty = true; renderUsernameFilter(); });
  $('clearAllUsersBtn').addEventListener('click', () => { state.selectedUsers = []; state.usernameDirty = true; renderUsernameFilter(); });
  $('usernameFilter').addEventListener('keydown', event => { if (event.key === 'Enter') closeUsernameDropdown(true); });
  usernameDropdown.addEventListener('toggle', () => { if (!usernameDropdown.open) applyUsernamePendingFilters(); });
  usernameDropdown.addEventListener('focusout', () => { setTimeout(() => { if (!usernameDropdown.contains(document.activeElement)) closeUsernameDropdown(true); }, 0); });
  document.addEventListener('click', event => { if (!usernameDropdown.contains(event.target)) closeUsernameDropdown(true); });
  $('destinationTableFilter').addEventListener('change', () => { state.destinationTableDirty = true; updateDestinationTableSummary(); });
  $('destinationTableFilter').addEventListener('keydown', event => { if (event.key === 'Enter') closeDestinationTableDropdown(true); });
  destinationDropdown.addEventListener('toggle', () => { if (!destinationDropdown.open) applyDestinationTablePendingFilters(); });
  destinationDropdown.addEventListener('focusout', () => { setTimeout(() => { if (!destinationDropdown.contains(document.activeElement)) closeDestinationTableDropdown(true); }, 0); });
  document.addEventListener('click', event => { if (!destinationDropdown.contains(event.target)) closeDestinationTableDropdown(true); });
  $('limit').addEventListener('change', applyAuditFilters);
  $('chartBucket').addEventListener('change', applyAuditFilters);
}
bindAuditFilterEvents();
SraAuditTools.bindPager({firstId: 'recentFirstBtn', prevId: 'recentPrevBtn', inputId: 'recentPageInput', gotoId: 'recentGotoBtn', nextId: 'recentNextBtn', lastId: 'recentLastBtn', getPage: () => state.recentPage, setPage: page => { state.recentPage = page; }, renderPage: loadDashboard});
// boot order includes: await loadCurrentUser(); await loadTasks(); await loadDashboard();
(async () => { resetDefaultWindow(); applyInitialQueryParams(); await loadCurrentUser(); await loadTasks(); applyInitialQueryParams(); await loadDashboard(); })().catch(err => showError(err.message || String(err)));
