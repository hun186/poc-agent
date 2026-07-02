const $ = id => document.getElementById(id);
const tokenKey = 'sra_editor_token';
const state = { page: 1, data: null, editing: null, usernameOptions: [], selectedUsers: [], usernameDirty: false };
function authToken() { return sessionStorage.getItem(tokenKey) || localStorage.getItem(tokenKey) || ''; }
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
    $('whoami').textContent = user.username ? `${user.username} (${user.role || '-'})` : '未登入';
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
    allLabel: '全體使用者',
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
function renderTable() {
  const data = state.data;
  if (!data) return;
  $('summary').textContent = `任務：${data.config_path}；SQL table：${data.destination_table}；總筆數：${data.total}；第 ${data.page} 頁；hash 欄位：${data.hash_field}`;
  const cols = data.columns || [];
  const rows = data.rows || [];
  const editable = new Set(data.editable_columns || []);
  const head = '<tr><th>操作</th>' + cols.map(c => `<th title="${esc(c.data_type || '')}${c.nullable ? '; nullable' : ''}">${esc(c.name)}</th>`).join('') + '</tr>';
  const body = rows.map((r, idx) => {
    const tds = cols.map(c => `<td class="${editable.has(c.name) ? '' : 'muted'}"><pre>${esc(cellValue(r[c.name]))}</pre></td>`).join('');
    return `<tr><td><button class="secondary" data-edit-index="${idx}">編輯</button></td>${tds}</tr>`;
  }).join('') || `<tr><td colspan="${cols.length + 1}" class="muted">沒有資料列</td></tr>`;
  $('tableWrap').innerHTML = `<table class="source-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  document.querySelectorAll('[data-edit-index]').forEach(btn => btn.onclick = () => startEdit(Number(btn.dataset.editIndex)));
  $('prevBtn').disabled = data.page <= 1;
  $('nextBtn').disabled = !data.has_more;
}
async function loadRows(page=1) {
  if (!token()) { show('status', '請先到 /editor 登入；本頁會沿用 sra_editor_token。', 'error'); return; }
  state.page = page;
  const params = new URLSearchParams({config: $('config').value.trim(), q: $('query').value.trim(), source_file_filter: $('sourceFileFilter').value.trim(), hash_value_filter: $('hashFilter').value.trim(), payload_filter: $('payloadFilter').value.trim(), page: String(state.page), limit: String($('limit').value || 50)});
  if ($('rowNoFilter').value) params.set('row_no_filter', $('rowNoFilter').value);
  state.selectedUsers.forEach(value => params.append('username_filter', value));
  show('status', '載入中...');
  try { state.data = await api('/v1/excel-to-sql/source-rows?' + params.toString()); state.usernameOptions = SraAuditTools.uniqueSortedValues([...(state.data.username_options || []), ...state.selectedUsers]); renderUsernameFilter(); show('status', '載入完成', 'ok'); renderTable(); }
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
$('clearFiltersBtn').onclick = () => { ['query','sourceFileFilter','rowNoFilter','hashFilter','payloadFilter'].forEach(id => { $(id).value = ''; }); state.selectedUsers = []; state.usernameDirty = false; renderUsernameFilter(); loadRows(1); };
$('prevBtn').onclick = () => loadRows(Math.max(1, state.page - 1));
$('nextBtn').onclick = () => loadRows(state.page + 1);
$('saveBtn').onclick = saveEdit;
$('cancelEditBtn').onclick = () => { $('editCard').classList.add('hidden'); state.editing = null; };

$('usernameSearch').addEventListener('input', renderUsernameFilter);
$('selectVisibleUsersBtn').addEventListener('click', () => { state.selectedUsers = SraAuditTools.setVisibleMultiFilterSelection({values: state.usernameOptions, selectedValues: state.selectedUsers, searchEl: $('usernameSearch'), checked: true}); state.usernameDirty = true; renderUsernameFilter(); });
$('clearVisibleUsersBtn').addEventListener('click', () => { state.selectedUsers = SraAuditTools.setVisibleMultiFilterSelection({values: state.usernameOptions, selectedValues: state.selectedUsers, searchEl: $('usernameSearch'), checked: false}); state.usernameDirty = true; renderUsernameFilter(); });
$('clearAllUsersBtn').addEventListener('click', () => { state.selectedUsers = []; state.usernameDirty = true; renderUsernameFilter(); });
$('usernameFilter').addEventListener('keydown', event => { if (event.key === 'Enter') closeUsernameDropdown(true); });
$('usernameDropdown').addEventListener('toggle', () => { if (!$('usernameDropdown').open) applyUsernamePendingFilters(); });
$('usernameDropdown').addEventListener('focusout', () => { setTimeout(() => { if (!$('usernameDropdown').contains(document.activeElement)) closeUsernameDropdown(true); }, 0); });
document.addEventListener('click', event => { if (!$('usernameDropdown').contains(event.target)) closeUsernameDropdown(true); });

loadMe().then(ok => ok ? loadTasks() : Promise.reject(new Error('請先登入'))).then(() => loadRows(1)).catch(err => { if (err.message !== '請先登入') show('status', err.message, 'error'); });
