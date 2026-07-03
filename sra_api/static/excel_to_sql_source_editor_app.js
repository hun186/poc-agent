const $ = id => document.getElementById(id);
const tokenKey = 'sra_editor_token';
const state = { page: 1, data: null, editing: null, usernameOptions: [], selectedUsers: [], usernameDirty: false, pageSize: 50, total: 0, role: '', canEdit: false, canDelete: false, canBatchDelete: false, sourceSort: null, sortFields: [], loadedConfig: '' };
function authToken() { return localStorage.getItem(tokenKey) || ''; }
function token() { return authToken(); }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function show(id, msg, cls='') { const el=$(id); el.textContent=msg; el.className='status ' + cls; el.classList.toggle('hidden', !msg); }
async function api(path, options={}) {
  const headers = Object.assign({'Content-Type':'application/json'}, options.headers || {});
  if (token()) headers.Authorization = 'Bearer ' + token();
  const res = await fetch(path, Object.assign({}, options, {headers}));
  if (!res.ok) { let text = await res.text(); try { text = JSON.parse(text).detail || text; } catch (_) {} throw new Error(text); }
  return res.json();
}
async function loadCurrentUser() {
  const currentToken = authToken();
  if (!currentToken) { $('whoami').textContent = '未登入'; show('status', '請先到 /editor 登入；本頁會沿用 sra_editor_token。', 'error'); return false; }
  try {
    const res = await fetch('/v1/auth/me', { headers: { Authorization: 'Bearer ' + currentToken } });
    if (!res.ok) throw new Error('unauthorized');
    const data = await res.json();
    const user = data.user || {};
    state.role = user.role || '';
    $('whoami').textContent = user.username ? `${user.username} (${state.role || '-'})` : '未登入';
    return true;
  } catch (_) {
    $('whoami').textContent = '登入已失效';
    show('status', '登入已失效，請回 /editor 重新登入。', 'error');
    return false;
  }
}
const loadMe = loadCurrentUser;
async function loadTasks() {
  const data = await api('/v1/excel-to-sql/dashboard-tasks');
  const tasks = (data.tasks || []).filter(t => t.config_path && t.destination_table);
  $('task').innerHTML = tasks.length ? tasks.map(t => `<option value="${esc(t.config_path)}">${esc(t.name)} (${esc(t.destination_table || '未設定 table')})</option>`).join('') : '<option value="">未找到已啟用任務</option>';
  if (tasks.length) $('config').value = tasks[0].config_path;
}

function renderUsernameFilter() {
  SraAuditTools.renderMultiFilterOptions({
    values: state.usernameOptions,
    selectedValues: state.selectedUsers,
    getSelectedValues: () => state.selectedUsers,
    searchEl: $('usernameSearch'),
    optionsEl: $('usernameFilter'),
    dataAttr: 'data-source-username',
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
    allLabel: '全體匯入使用者',
    unitLabel: '位使用者',
  });
}
function applyUsernamePendingFilters() {
  if (!state.usernameDirty) return;
  state.usernameDirty = false;
  loadRows(1);
}
function closeUsernameDropdown(applyPending = false) {
  const dropdown = $('usernameDropdown');
  if (dropdown.open) dropdown.open = false;
  if (applyPending) applyUsernamePendingFilters();
}

function cellValue(value) {
  if (value && typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value ?? '');
}
function localInputToUtcIso(id) { const el = $(id); const v = el?.value || ''; return v ? new Date(v).toISOString() : ''; }
function normalizeAuditUtc(text) { const raw = String(text || ''); if (!raw) return null; const trimmed = raw.replace(/(\.\d{3})\d+/, '$1'); return /[zZ]|[+-]\d\d:?\d\d$/.test(trimmed) ? trimmed : trimmed + 'Z'; }
function formatSourceTime(value) { const raw = String(value || ''); const normalized = normalizeAuditUtc(raw); if (!normalized) return ''; const local = new Date(normalized); if (Number.isNaN(local.getTime())) return raw; return `${local.toLocaleString()}\nUTC：${raw}`; }
function displayColumnName(name) { return ({_import_username:'匯入使用者', _imported_at:'匯入執行時間', _source_excel:'來源 Excel'}[name] || name); }
function sourceSortFields() { return (state.sortFields || []).map(name => ({value: name, label: displayColumnName(name)})); }
function syncSourceSortFields(cols) { state.sortFields = (cols || []).map(c => c.name).filter(name => name && (['_import_username','_imported_at','_source_excel'].includes(String(name)) || !String(name).startsWith('_'))); if (!state.sourceSort) state.sourceSort = SraAuditTools.bindSqlSortControls({containerId: 'sourceSortControls', getFields: sourceSortFields, defaultSort: [{field: state.sortFields[0] || 'hash_value', direction: 'asc'}], onChange: () => loadRows(1)}); else state.sourceSort.setFields(); }
function sourceColumnClass(name) { return name === '_import_username' ? 'col-import-user' : (name === '_source_excel' ? 'col-source-excel' : ''); }
function sourceCellClass(name, isEditable) { return `${isEditable ? '' : 'muted'} ${sourceColumnClass(name)}`.trim(); }
function formatSourceCell(name, value) { return name === '_imported_at' ? formatSourceTime(value) : cellValue(value); }
function rowActions(index, hashValue) {
  const checkbox = state.canBatchDelete && hashValue ? `<label class="row-check"><input type="checkbox" data-source-delete-check value="${esc(hashValue)}" aria-label="勾選刪除 hash ${esc(hashValue)}" /></label>` : '';
  const editBtn = state.canEdit ? `<button class="secondary" data-edit-index="${index}">編輯</button>` : '';
  const deleteBtn = state.canDelete && hashValue ? `<button class="ghost danger" data-delete-hash="${esc(hashValue)}">刪除</button>` : '';
  return `<div class="source-actions">${checkbox}${editBtn}${deleteBtn || '<span class="muted">唯讀</span>'}</div>`;
}
function renderTable() {
  const data = state.data;
  if (!data) return;
  $('summary').textContent = `任務：${data.config_path}；SQL table：${data.destination_table}；總筆數：${data.total}；第 ${data.page} 頁；hash 欄位：${data.hash_field}`;
  const cols = data.columns || [];
  syncSourceSortFields(cols);
  const rows = data.rows || [];
  const editable = new Set(data.editable_columns || []);
  const canEdit = Boolean(data.can_edit);
  const canDelete = Boolean(data.can_delete);
  const canBatchDelete = Boolean(data.can_batch_delete);
  state.canEdit = canEdit; state.canDelete = canDelete; state.canBatchDelete = canBatchDelete;
  const selectAll = canBatchDelete ? '<input type="checkbox" id="sourceSelectAll" aria-label="勾選本頁可批次刪除 SQL 列" />' : '';
  const head = `<tr><th>${selectAll}<span class="sr-only">操作</span></th>` + cols.map(c => `<th class="${sourceColumnClass(c.name)}" title="${esc(c.data_type || '')}${c.nullable ? '; nullable' : ''}">${esc(displayColumnName(c.name))}</th>`).join('') + '</tr>';
  const body = rows.map((r, idx) => {
    const hashValue = r[data.hash_field] || '';
    const tds = cols.map(c => `<td class="${sourceCellClass(c.name, editable.has(c.name))}"><pre>${esc(formatSourceCell(c.name, r[c.name]))}</pre></td>`).join('');
    return `<tr><td>${rowActions(idx, hashValue)}</td>${tds}</tr>`;
  }).join('') || `<tr><td colspan="${cols.length + 1}" class="muted">沒有資料列</td></tr>`;
  $('tableWrap').innerHTML = `<table class="source-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  document.querySelectorAll('[data-edit-index]').forEach(btn => btn.onclick = () => startEdit(Number(btn.dataset.editIndex)));
  document.querySelectorAll('[data-delete-hash]').forEach(btn => btn.onclick = () => deleteSourceRow(btn.dataset.deleteHash));
  const selectAllBox = $('sourceSelectAll');
  if (selectAllBox) selectAllBox.onchange = () => toggleSourceSelection(selectAllBox.checked);
  document.querySelectorAll('[data-source-delete-check]').forEach(input => input.onchange = updateBatchDeleteSummary);
  updateBatchDeleteControls();
  state.page = Number(data.page || state.page || 1);
  state.pageSize = Number(data.limit || state.pageSize || 50);
  state.total = Number(data.total || rows.length || 0);
  SraAuditTools.updatePager({page: state.page, pageSize: state.pageSize, total: state.total, infoId: 'sourcePageInfo', firstId: 'sourceFirstBtn', prevId: 'sourcePrevBtn', inputId: 'sourcePageInput', gotoId: 'sourceGotoBtn', nextId: 'sourceNextBtn', lastId: 'sourceLastBtn', inputLabel: 'SQL 來源資料列頁數', maxPageSize: 50000});
}
async function loadRows(page=1) {
  if (!token()) { show('status', '請先到 /editor 登入；本頁會沿用 sra_editor_token。', 'error'); return; }
  state.page = page;
  const params = new URLSearchParams({config: $('config').value.trim(), q: $('query').value.trim(), source_file_filter: $('sourceFileFilter').value.trim(), hash_value_filter: $('hashFilter').value.trim(), payload_filter: $('payloadFilter').value.trim(), import_start_ts: localInputToUtcIso('importStartFilter'), import_end_ts: localInputToUtcIso('importEndFilter'), page: String(state.page), limit: String(Math.max(1, Math.min(50000, Number(state.pageSize || 50))))});
  if (state.sourceSort && $('config').value.trim() === state.loadedConfig) state.sourceSort.getSortParams().forEach(value => params.append('sort', value));
  if ($('rowNoFilter').value) params.set('row_no_filter', $('rowNoFilter').value);
  state.selectedUsers.forEach(value => params.append('username_filter', value));
  show('status', '載入中...');
  try { state.data = await api('/v1/excel-to-sql/source-rows?' + params.toString()); state.loadedConfig = $('config').value.trim(); state.usernameOptions = SraAuditTools.uniqueSortedValues([...(state.data.username_options || []), ...state.selectedUsers]); renderUsernameFilter(); show('status', '載入完成', 'ok'); renderTable(); }
  catch (err) { show('status', err.message, 'error'); }
}
function startEdit(index) {
  const row = state.data.rows[index];
  state.editing = row;
  $('editCard').classList.remove('hidden');
  $('editMeta').textContent = `hash=${row[state.data.hash_field]}; table=${state.data.destination_table}`;
  const editable = state.data.editable_columns || [];
  $('editFields').innerHTML = editable.map(col => `<div><label>${esc(col)}</label><textarea class="sql-edit" data-edit-col="${esc(col)}">${esc(cellValue(row[col]))}</textarea></div>`).join('');
  $('editReason').value = '';
  show('editStatus', '');
  $('editCard').scrollIntoView({behavior:'smooth', block:'start'});
}
async function saveEdit() {
  if (!state.editing || !state.data) return;
  const reason = $('editReason').value.trim();
  if (!reason) { show('editStatus', '請填寫修改原因。', 'error'); return; }
  if (!confirm('確認儲存此 SQL row 修改？此操作會寫入 audit，但不會自動同步 ES。')) return;
  const changes = {};
  document.querySelectorAll('[data-edit-col]').forEach(el => { const col = el.dataset.editCol; if (String(state.editing[col] ?? '') !== el.value) changes[col] = el.value; });
  if (!Object.keys(changes).length) { show('editStatus', '沒有欄位變更。', 'error'); return; }
  try {
    const data = await api('/v1/excel-to-sql/source-row', {method:'PATCH', body: JSON.stringify({config: $('config').value.trim(), hash_value: state.editing[state.data.hash_field], changes, reason})});
    show('editStatus', `已更新 ${data.updated_rows} 筆。${data.blocked_columns?.length ? '略過欄位：' + data.blocked_columns.join(', ') : ''}`, 'ok');
    await loadRows(state.page);
  } catch (err) { show('editStatus', err.message, 'error'); }
}
$('task').onchange = () => { if ($('task').value) $('config').value = $('task').value; loadRows(1); };
$('loadBtn').onclick = () => loadRows(1);
$('applyFiltersBtn').onclick = () => loadRows(1);
$('clearFiltersBtn').onclick = () => { ['query','sourceFileFilter','importStartFilter','importEndFilter','rowNoFilter','hashFilter','payloadFilter'].forEach(id => { $(id).value = ''; }); state.selectedUsers = []; state.usernameDirty = false; renderUsernameFilter(); loadRows(1); };
SraAuditTools.bindPager({firstId: 'sourceFirstBtn', prevId: 'sourcePrevBtn', inputId: 'sourcePageInput', gotoId: 'sourceGotoBtn', nextId: 'sourceNextBtn', lastId: 'sourceLastBtn', getPage: () => state.page, setPage: page => { state.page = page; }, getPageSize: () => state.pageSize, setPageSize: size => { state.pageSize = size; state.page = 1; }, maxPageSize: 50000, renderPage: () => loadRows(state.page)});
$('saveBtn').onclick = saveEdit;
$('cancelEditBtn').onclick = () => { $('editCard').classList.add('hidden'); state.editing = null; };
function selectedDeleteHashes() { return Array.from(document.querySelectorAll('[data-source-delete-check]:checked')).map(input => input.value).filter(Boolean); }
function toggleSourceSelection(checked) { document.querySelectorAll('[data-source-delete-check]').forEach(input => { input.checked = checked; }); updateBatchDeleteSummary(); }
function updateBatchDeleteSummary() { const count = selectedDeleteHashes().length; const total = document.querySelectorAll('[data-source-delete-check]').length; const selectAllBox = $('sourceSelectAll'); if (selectAllBox) { selectAllBox.checked = total > 0 && count === total; selectAllBox.indeterminate = count > 0 && count < total; } const el = $('batchDeleteSummary'); if (el) el.textContent = count ? `已勾選 ${count} 筆` : '尚未勾選資料列'; }
function updateBatchDeleteControls() { const box = $('batchDeleteBar'); if (box) box.classList.toggle('hidden', !state.canBatchDelete); updateBatchDeleteSummary(); }
function batchDeleteConfirmationPhrase(rowCount) { return `DELETE ${rowCount}`; }
function confirmBatchDeleteRows(hashes) { const phrase = batchDeleteConfirmationPhrase(hashes.length); const typed = prompt(`高風險操作確認：即將批次刪除 ${hashes.length} 筆 SQL 條目。\n前 ${Math.min(hashes.length, 5)} 筆 hash：\n${hashes.slice(0, 5).join('\n')}\n\n若確認要刪除，請完整輸入：${phrase}`, ''); return typed === phrase; }
async function deleteSourceRow(hashValue) {
  if (!hashValue) return;
  const reason = prompt('請輸入刪除原因（會寫入 audit）：', '資料列內容錯誤，人工刪除');
  if (reason === null) return;
  if (!reason.trim()) { show('status', '刪除需要填寫原因，避免事後無法追溯。', 'error'); return; }
  if (!confirm(`高風險操作確認：確定要從 SQL 目的表刪除 hash_value=${hashValue} 的資料列？\n此操作會寫入 audit，且不會自動刪除 ES 文件。`)) return;
  try { const data = await api('/v1/excel-to-sql/delete-row', {method:'POST', body: JSON.stringify({config: $('config').value.trim(), hash_value: hashValue, reason: reason.trim()})}); show('status', `已刪除 ${data.deleted_rows || 0} 筆；狀態：${data.status || ''}`, 'ok'); await loadRows(state.page); }
  catch (err) { show('status', err.message, 'error'); }
}
async function deleteSelectedSourceRows() {
  const hashes = selectedDeleteHashes();
  if (!hashes.length) { show('status', '請先勾選至少一筆資料列。', 'error'); return; }
  const reason = prompt('請輸入批次刪除原因（會寫入 audit 與報告）：', '復原錯誤 Excel 匯入，批次刪除');
  if (reason === null) return;
  if (!reason.trim()) { show('status', '批次刪除需要填寫原因，避免事後無法追溯。', 'error'); return; }
  if (!confirmBatchDeleteRows(hashes)) { show('status', '批次刪除已取消：確認文字不符合。', 'error'); return; }
  if (!confirm(`最後確認：確定要從 SQL 目的表刪除 ${hashes.length} 筆資料？\n此操作會逐筆寫入 audit，且不會自動刪除 ES 文件。`)) return;
  try { const data = await api('/v1/excel-to-sql/delete-rows', {method:'POST', body: JSON.stringify({config: $('config').value.trim(), hash_values: hashes, reason: reason.trim()})}); show('status', `批次刪除完成：成功刪除 ${data.deleted_rows || 0} 筆，處理 ${data.processed || 0} 個 hash。`, 'ok'); await loadRows(1); }
  catch (err) { show('status', err.message, 'error'); }
}
$('batchDeleteBtn').onclick = deleteSelectedSourceRows;

$('usernameSearch').addEventListener('input', renderUsernameFilter);
$('selectVisibleUsersBtn').addEventListener('click', () => { state.selectedUsers = SraAuditTools.setVisibleMultiFilterSelection({values: state.usernameOptions, selectedValues: state.selectedUsers, searchEl: $('usernameSearch'), checked: true}); state.usernameDirty = true; renderUsernameFilter(); });
$('clearVisibleUsersBtn').addEventListener('click', () => { state.selectedUsers = SraAuditTools.setVisibleMultiFilterSelection({values: state.usernameOptions, selectedValues: state.selectedUsers, searchEl: $('usernameSearch'), checked: false}); state.usernameDirty = true; renderUsernameFilter(); });
$('clearAllUsersBtn').addEventListener('click', () => { state.selectedUsers = []; state.usernameDirty = true; renderUsernameFilter(); });
$('usernameFilter').addEventListener('keydown', event => { if (event.key === 'Enter') closeUsernameDropdown(true); });
$('usernameDropdown').addEventListener('toggle', () => { if (!$('usernameDropdown').open) applyUsernamePendingFilters(); });
$('usernameDropdown').addEventListener('focusout', () => { setTimeout(() => { if (!$('usernameDropdown').contains(document.activeElement)) closeUsernameDropdown(true); }, 0); });
document.addEventListener('click', event => { if (!$('usernameDropdown').contains(event.target)) closeUsernameDropdown(true); });

loadMe().then(ok => ok ? loadTasks() : Promise.reject(new Error('請先登入'))).then(() => loadRows(1)).catch(err => { if (err.message !== '請先登入') show('status', err.message, 'error'); });
