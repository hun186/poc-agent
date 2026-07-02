const tokenKey = 'sra_editor_token';
let currentUserRole = '';
let taskConfigReviewTasks = [];
let dashboardTasks = [];
let connectionSourceTasks = [];
const importRecordsPager = { page: 1, pageSize: 25, rows: [] };
const myTaskConfigsPager = { page: 1, pageSize: 25, rows: [] };
const ROLE_SUPERUSER = 'superuser';
const ROLE_DB_OPERATOR = 'db_operator';
function $(id) { return document.getElementById(id); }
function escapeHtml(v) { return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function authToken() { return localStorage.getItem(tokenKey) || ''; }
function statusBadge(s) { return `<span class="status ${escapeHtml(s)}">${escapeHtml(s || '(empty)')}</span>`; }
function showError(text) { const el=$('msg'); if (!el) return; if (!text) { el.classList.add('hidden'); el.textContent=''; } else { el.classList.remove('hidden'); el.textContent=text; } }
function notifyImportant(message) { if (message) window.alert(message); }
function showTaskConfigMessage(text, options = {}) {
  showError(text);
  if (options.alert !== false && text) notifyImportant(text);
}
function formatApiErrorDetail(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(item => {
      if (typeof item === 'string') return item;
      const loc = Array.isArray(item?.loc) ? item.loc.filter(part => part !== 'body').join('.') : '';
      const msg = item?.msg || item?.message || JSON.stringify(item);
      return loc ? `${loc}：${msg}` : msg;
    }).join('\n');
  }
  if (detail && typeof detail === 'object') return detail.message || detail.msg || JSON.stringify(detail);
  return String(detail || '');
}
async function responseErrorText(res) {
  const text = await res.text();
  try {
    const data = JSON.parse(text);
    return formatApiErrorDetail(data.detail ?? data);
  } catch (_) {
    return text;
  }
}
function fillTable(id, rows, render) { document.querySelector(`#${id} tbody`).innerHTML = rows.map(render).join('') || '<tr><td colspan="99" class="muted">無資料</td></tr>'; }
function renderPagedTable(tableId, pager, render, prefix) {
  const page = SraAuditTools.paginateRows(pager.rows, pager.page, pager.pageSize);
  pager.page = page.page;
  fillTable(tableId, page.rows, render);
  SraAuditTools.updatePager({pageData: page, infoId: `${prefix}PageInfo`, firstId: `${prefix}FirstBtn`, prevId: `${prefix}PrevBtn`, inputId: `${prefix}PageInput`, gotoId: `${prefix}GotoBtn`, nextId: `${prefix}NextBtn`, lastId: `${prefix}LastBtn`, inputLabel: `${prefix} 頁數`});
}
function bindPagedTable(prefix, pager, renderPage) {
  if (!document.getElementById(`${prefix}PageInfo`)) return;
  SraAuditTools.bindPager({firstId: `${prefix}FirstBtn`, prevId: `${prefix}PrevBtn`, inputId: `${prefix}PageInput`, gotoId: `${prefix}GotoBtn`, nextId: `${prefix}NextBtn`, lastId: `${prefix}LastBtn`, getPage: () => pager.page, setPage: page => { pager.page = page; }, renderPage});
}
function pad2(v) { return String(v).padStart(2, '0'); }
function normalizeAuditUtc(text) { const raw = String(text || ''); if (!raw) return null; const trimmed = raw.replace(/(\.\d{3})\d+/, '$1'); return /[zZ]|[+-]\d\d:?\d\d$/.test(trimmed) ? trimmed : trimmed + 'Z'; }
function formatAuditTime(value) { const raw = String(value || ''); const normalized = normalizeAuditUtc(raw); if (!normalized) return ''; const local = new Date(normalized); if (Number.isNaN(local.getTime())) return escapeHtml(raw); return `<div>${escapeHtml(local.toLocaleString())}</div><div class="muted">UTC：${escapeHtml(raw)}</div>`; }
function localInputToUtcIso(id) { const el = $(id); const v = el?.value || ''; return v ? new Date(v).toISOString() : ''; }
function setPreview(html) { const box = $('previewBox') || $('msg'); if (!box) return; if (!html) { box.classList.add('hidden'); if (box.id === 'previewBox') box.innerHTML=''; return; } box.classList.remove('hidden'); if (box.id === 'previewBox') box.innerHTML=html; else box.innerHTML=html; }
function summarizeFailures(summary) {
  const entries = Object.entries(summary || {}).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 3);
  if (!entries.length) return '<span class="muted">無錯誤摘要</span>';
  return `<ul>${entries.map(([message, count]) => `<li>${escapeHtml(message)}：${escapeHtml(count)} 筆</li>`).join('')}</ul>`;
}
function sampleDiagnostics(samples) {
  const rows = (samples || []).filter(item => item.status === 'failed').slice(0, 3);
  if (!rows.length) return '';
  return `<div class="muted">樣本：${rows.map(item => `第 ${escapeHtml(item.row_no)} 列 ${escapeHtml(item.message)}`).join('；')}</div>`;
}
function importRecordDiagnostics(r) {
  const result = r.import_result || r.preview || {};
  const failed = Number(result.failed_rows ?? result.failed ?? 0);
  if (!failed) return '<span class="muted">—</span>';
  return `<div class="diagnostics"><strong>失敗 ${escapeHtml(failed)} 筆</strong><details><summary>展開 / 收合錯誤診斷</summary>${summarizeFailures(result.failure_summary)}${sampleDiagnostics(result.samples)}</details></div>`;
}
async function loadCurrentUser() {
  const token = authToken();
  if (!token || !$('whoami')) return;
  try {
    const res = await fetch('/v1/auth/me', { headers: { Authorization: 'Bearer ' + token } });
    if (!res.ok) throw new Error('unauthorized');
    const data = await res.json(); const user = data.user || {};
    currentUserRole = user.role || '';
    $('whoami').textContent = user.username ? `${user.username} (${user.role || '-'})` : '未登入';
    updateSuperuserTaskReviewVisibility();
    updateTaskConfigPermissionVisibility();
  } catch (_) { $('whoami').textContent = '登入已失效'; }
}
function taskOptionLabel(t) {
  const status = t.status || (t.enabled ? 'active' : 'pending');
  const suffix = status ? ` / ${status}` : '';
  return `${t.name || t.config_path} (${t.config_path}${suffix})`;
}
function mergeTasksByConfigPath(...groups) {
  const map = new Map();
  groups.flat().forEach(task => {
    if (!task?.config_path || map.has(task.config_path)) return;
    map.set(task.config_path, task);
  });
  return Array.from(map.values());
}
function canReviewTaskMappings() { return currentUserRole === ROLE_DB_OPERATOR || currentUserRole === ROLE_SUPERUSER; }
function updateTaskConfigPermissionVisibility() {
  const card = $('taskConfigCard');
  if (!card) return;
  const allowed = canReviewTaskMappings();
  card.classList.toggle('hidden', !allowed);
  if (!allowed) showError('建立 Excel→SQL 任務設定檔需要資料庫管理權限（db_operator / superuser）。你可以從編輯器導航關閉或避免進入此頁。');
}

function isActiveConnectionSourceTask(task) {
  return Boolean(task?.enabled) || String(task?.status || '').toLowerCase() === 'active';
}
async function loadTaskConfigSourceCandidates(token) {
  if (!$('taskConnectionSource')) return dashboardTasks;
  const scope = currentUserRole === ROLE_SUPERUSER ? 'all' : 'mine';
  const res = await fetch(`/v1/excel-to-sql/task-configs?scope=${scope}`, { headers: { Authorization: 'Bearer ' + token } });
  if (!res.ok) return dashboardTasks;
  const taskConfigs = (await res.json()).tasks || [];
  return mergeTasksByConfigPath(dashboardTasks, taskConfigs).filter(isActiveConnectionSourceTask);
}
async function loadTasks() {
  const needsUploadTasks = Boolean($('task'));
  const needsConnectionSources = Boolean($('taskConnectionSource'));
  if (!needsUploadTasks && !needsConnectionSources) return;
  const token = authToken();
  if (!token) { showError('請先到 /editor 登入；本頁會沿用 sra_editor_token。'); return; }
  const res = await fetch('/v1/excel-to-sql/dashboard-tasks', { headers: { Authorization: 'Bearer ' + token } });
  if (!res.ok) return;
  dashboardTasks = (await res.json()).tasks || [];
  const taskOptions = dashboardTasks.map(t => `<option value="${escapeHtml(t.config_path)}">${escapeHtml(t.name)} (${escapeHtml(t.config_path)})</option>`).join('');
  if ($('task')) $('task').innerHTML = dashboardTasks.length ? taskOptions : '<option value="">未找到 dashboard.enabled=true 的任務</option>';
  if ($('taskConnectionSource')) {
    connectionSourceTasks = await loadTaskConfigSourceCandidates(token);
    const sourceTasks = connectionSourceTasks;
    const sourceOptions = sourceTasks.map(t => `<option value="${escapeHtml(t.config_path)}">${escapeHtml(taskOptionLabel(t))}</option>`).join('');
    $('taskConnectionSource').innerHTML = '<option value="">直接填寫下方 DB 連線資訊</option>' + sourceOptions;
    applyConnectionSourceDefaults(sourceTasks);
  }
  if (dashboardTasks.length && $('uploadConfig')) $('uploadConfig').value = dashboardTasks[0].config_path;
  renderUploadTaskDetails();
  if (currentUserRole === ROLE_SUPERUSER) await loadTaskConfigReviewOptions();
}
function onTaskChange() { if ($('task').value) $('uploadConfig').value = $('task').value; renderUploadTaskDetails(); }
function setSensitiveConnectionFieldsVisible(visible) {
  const fields = $('connectionSensitiveFields');
  const notice = $('connectionSourceNotice');
  if (fields) fields.classList.toggle('hidden', !visible);
  if (notice) notice.classList.toggle('hidden', visible);
  ['taskDbServer', 'taskDbDatabase', 'taskDbUser', 'taskDbPassword'].forEach(id => {
    const input = $(id);
    if (!input) return;
    input.disabled = !visible;
    if (!visible) input.value = '';
  });
}
function applyConnectionSourceDefaults(sourceTasks = dashboardTasks) {
  const select = $('taskConnectionSource');
  const usingSource = Boolean(select?.value);
  setSensitiveConnectionFieldsVisible(!usingSource);
  if (!usingSource) return;
  const task = sourceTasks.find(item => item.config_path === select.value);
  const db = task?.review_summary?.db || {};
  if ($('taskDbDriver') && db.driver) $('taskDbDriver').value = db.driver;
  if ($('taskTrustedConnection')) $('taskTrustedConnection').checked = Boolean(db.trusted_connection);
}
async function uploadExcelRecord() {
  showError(''); setPreview('');
  const input = $('uploadExcel');
  if (!input.files.length) { showError('請先選擇 Excel 檔案。'); return; }
  const body = new FormData(); body.append('file', input.files[0]);
  const params = new URLSearchParams({ config: $('uploadConfig').value });
  const res = await fetch('/v1/excel-to-sql/import-records?' + params.toString(), { method:'POST', headers:{ Authorization:'Bearer ' + authToken() }, body });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  const data = await res.json();
  setPreview(`<strong>已建立記錄：</strong>${escapeHtml(data.record.id)}，請先執行預掃描。`);
  await loadImportRecords();
}
async function previewImportRecord(id) {
  showError('');
  const res = await fetch(`/v1/excel-to-sql/import-records/${encodeURIComponent(id)}/preview`, { method:'POST', headers:{ Authorization:'Bearer ' + authToken() } });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  const data = await res.json(); const p = data.preview || {};
  setPreview(`<strong>預掃描結果：</strong>總列數 ${p.total_rows||0}，預估新增 ${p.will_insert||0}，重複 ${p.duplicate||0}，錯誤 ${p.failed||0}<br><span class="muted">工作表：${escapeHtml((p.sheets||[]).join(', '))}</span><div>${summarizeFailures(p.failure_summary)}</div>${sampleDiagnostics(p.samples)}`);
  await loadImportRecords();
}
async function confirmImportRecord(id) {
  if (!confirm('確定要依預掃描結果執行實際匯入 SQL？')) return;
  const res = await fetch(`/v1/excel-to-sql/import-records/${encodeURIComponent(id)}/confirm`, { method:'POST', headers:{ Authorization:'Bearer ' + authToken() } });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  const data = await res.json(); const r = data.import_result || {};
  setPreview(`<strong>匯入完成：</strong>新增 ${r.inserted_rows||0}，重複 ${r.duplicate_rows||0}，錯誤 ${r.failed_rows||0}<div>${summarizeFailures(r.failure_summary)}</div>`);
  await loadImportRecords();
}
function importRecordCounts(r) { return r.import_result || r.preview || {}; }
function openAuditForImportRecord(id) {
  const row = window.__importRecordById?.[id];
  if (!row) return;
  const params = new URLSearchParams();
  if (row.config_path) params.set('config', row.config_path);
  const storedName = row.stored_filename || '';
  if (storedName) params.set('source_file_filter', storedName);
  params.set('page', '1');
  location.href = '/excel-to-sql-dashboard?' + params.toString() + '#recentAuditSection';
}
function importRecordActions(r) {
  if (r.status === 'deleted') return '<span class="muted">—</span>';
  const auditDisabled = r.stored_filename ? '' : ' disabled title="此記錄缺少導入檔名，無法快速篩選 audit"';
  return `<div class="record-actions"><button class="ghost" onclick="previewImportRecord('${escapeHtml(r.id)}')">預掃描</button><button onclick="confirmImportRecord('${escapeHtml(r.id)}')">確認匯入SQL</button><button class="secondary" onclick="openAuditForImportRecord('${escapeHtml(r.id)}')"${auditDisabled}>查詢已匯入列</button></div>`;
}
async function loadImportRecords() {
  const params = new URLSearchParams();
  const map = { filename:'recordFilenameFilter', status:'recordStatusFilter', actor:'recordActorFilter' };
  Object.entries(map).forEach(([k,id]) => { const v=$(id).value.trim(); if (v) params.set(k,v); });
  const startIso = localInputToUtcIso('recordStartFilter'); const endIso = localInputToUtcIso('recordEndFilter');
  if (startIso) params.set('start_ts', startIso); if (endIso) params.set('end_ts', endIso);
  const res = await fetch('/v1/excel-to-sql/import-records?' + params.toString(), { headers:{ Authorization:'Bearer ' + authToken() } });
  if (!res.ok) return;
  const data = await res.json();
  const rows = data.records || [];
  window.__importRecordById = Object.fromEntries(rows.map(row => [String(row.id), row]));
  importRecordsPager.rows = rows;
  importRecordsPager.page = 1;
  renderImportRecordsPage();
}
function renderImportRecordsPage() {
  renderPagedTable('importRecords', importRecordsPager, r => { const c=importRecordCounts(r); return `<tr><td data-label="日期">${formatAuditTime(r.created_at)}</td><td data-label="使用者">${escapeHtml(r.username)}</td><td data-label="原始檔名">${escapeHtml(r.original_filename)}</td><td data-label="導入檔名"><code>${escapeHtml(r.stored_filename || '')}</code></td><td data-label="設定檔">${escapeHtml(r.config_path)}</td><td data-label="狀態">${statusBadge(r.status)}</td><td data-label="新增">${escapeHtml(c.inserted_rows ?? c.will_insert ?? '')}</td><td data-label="重複">${escapeHtml(c.duplicate_rows ?? c.duplicate ?? '')}</td><td data-label="錯誤">${escapeHtml(c.failed_rows ?? c.failed ?? '')}</td><td data-label="大小">${escapeHtml(r.file_size || 0)}</td><td data-label="錯誤診斷">${importRecordDiagnostics(r)}</td><td data-label="操作">${importRecordActions(r)}</td></tr>`; }, 'importRecords');
}
function mappingRowTemplate(index) {
  return `<div class="mapping-row" data-mapping-row="1"><div><label>來源欄位</label><input class="mapping-source" placeholder="Excel 欄名" /></div><div><label>目的欄位</label><input class="mapping-dest" placeholder="sql_field" /></div><div><label>SQL 型別</label><input class="mapping-type" list="sqlTypeOptions" placeholder="長文字建議 NVARCHAR(MAX)，短代碼才用 NVARCHAR(255)" /></div><div><label>比對 <button class="ghost" onclick="showMatchHelp()" type="button">?</button></label><select class="mapping-match"><option value="">預設</option><option value="exact">exact</option><option value="prefix">prefix</option><option value="contains">contains</option></select></div><div><label>必填</label><select class="mapping-required"><option value="false">否</option><option value="true">是</option></select></div><button class="secondary" onclick="removeTaskMappingRow(this)" type="button">移除</button></div>`;
}
function compositeRowTemplate(index) {
  return `<div class="composite-row" data-composite-row="1"><div><label>來源欄位（逗號分隔）</label><input class="composite-sources" placeholder="日期, 地點, 敘述" /></div><div><label>SQL 新欄位</label><input class="composite-dest" placeholder="complete_description" /></div><div><label>模板（可選）</label><input class="composite-template" placeholder="日期是{日期}，發生地點是{地點}，當天的敘述是{敘述}" /></div><div><label>分隔字串</label><input class="composite-separator" value=" " /></div><div><label>SQL 型別</label><input class="composite-type" list="sqlTypeOptions" placeholder="選擇或手動輸入，例如 NVARCHAR(MAX)" /></div><div><label>必填</label><select class="composite-required"><option value="false">否</option><option value="true">是</option></select></div><button class="secondary" onclick="removeCompositeMappingRow(this)" type="button">移除</button></div>`;
}
function addTaskMappingRow() { const box = $('taskMappings'); if (box) box.insertAdjacentHTML('beforeend', mappingRowTemplate(box.children.length)); }
function removeTaskMappingRow(button) { button.closest('[data-mapping-row]')?.remove(); }
function addCompositeMappingRow() { const box = $('taskCompositeMappings'); if (box) box.insertAdjacentHTML('beforeend', compositeRowTemplate(box.children.length)); }
function removeCompositeMappingRow(button) { button.closest('[data-composite-row]')?.remove(); }
function taskValue(id) { return ($(id)?.value || '').trim(); }
function taskNumber(id, fallback) { const raw = taskValue(id); return raw ? Number(raw) : fallback; }
function normalizeTaskFilename() {
  const input = $('taskFilename');
  const raw = (input?.value || '').trim();
  if (!raw || raw.toLowerCase().endsWith('.json')) return { filename: raw, changed: false };
  const filename = `${raw}.json`;
  if (input) input.value = filename;
  return { filename, changed: true };
}
function collectTaskMappings() {
  return Array.from(document.querySelectorAll('[data-mapping-row]')).map(row => ({
    source_column: row.querySelector('.mapping-source')?.value.trim() || '',
    dest_field: row.querySelector('.mapping-dest')?.value.trim() || '',
    dest_field_type: row.querySelector('.mapping-type')?.value.trim() || 'NVARCHAR(MAX)',
    match: row.querySelector('.mapping-match')?.value || '',
    required: row.querySelector('.mapping-required')?.value === 'true',
  })).filter(item => item.source_column || item.dest_field);
}
function collectCompositeMappings() {
  return Array.from(document.querySelectorAll('[data-composite-row]')).map(row => ({
    source_columns: (row.querySelector('.composite-sources')?.value || '').split(',').map(v => v.trim()).filter(Boolean),
    dest_field: row.querySelector('.composite-dest')?.value.trim() || '',
    template: row.querySelector('.composite-template')?.value.trim() || '',
    separator: row.querySelector('.composite-separator')?.value ?? ' ',
    dest_field_type: row.querySelector('.composite-type')?.value.trim() || 'NVARCHAR(MAX)',
    required: row.querySelector('.composite-required')?.value === 'true',
  })).filter(item => item.source_columns.length || item.dest_field);
}

function findTemplatePlaceholders(template) {
  return Array.from(String(template || '').matchAll(/\{([^{}]+)\}/g)).map(match => match[1].trim()).filter(Boolean);
}
function validateTaskConfigPayload(payload) {
  const errors = [];
  const dests = new Set();
  payload.mappings.forEach((item, idx) => {
    if (!item.source_column || !item.dest_field) errors.push(`第 ${idx + 1} 筆欄位對應需同時填來源欄位與目的欄位。`);
    const key = String(item.dest_field || '').toLowerCase();
    if (key && dests.has(key)) errors.push(`目的欄位重複：${item.dest_field}`);
    if (key) dests.add(key);
  });
  payload.composite_mappings.forEach((item, idx) => {
    if (item.source_columns.length < 2 || !item.dest_field) errors.push(`第 ${idx + 1} 筆拼裝欄位錯誤：每個拼裝欄位都需要至少兩個來源欄位與一個 SQL 新欄位。`);
    const uniqueSources = new Set(item.source_columns.map(v => v.toLowerCase()));
    if (uniqueSources.size !== item.source_columns.length) errors.push(`第 ${idx + 1} 筆拼裝欄位的來源欄位重複。`);
    const key = String(item.dest_field || '').toLowerCase();
    if (key && dests.has(key)) errors.push(`目的欄位重複：${item.dest_field}`);
    if (key) dests.add(key);
    const placeholders = findTemplatePlaceholders(item.template);
    const sourceSet = new Set(item.source_columns);
    placeholders.filter(name => !sourceSet.has(name)).forEach(name => errors.push(`第 ${idx + 1} 筆拼裝模板使用了未列入來源欄位的 {${name}}。`));
  });
  return errors;
}

async function createTaskConfig() {
  showError(''); setPreview('');
  const normalizedFilename = normalizeTaskFilename();
  if (normalizedFilename.changed) {
    showError(`已自動補上 .json 副檔名：${normalizedFilename.filename}`);
  }
  const payload = {
    filename: normalizedFilename.filename, task_name: taskValue('taskName'), connection_source_config: taskValue('taskConnectionSource'), db_driver: taskValue('taskDbDriver') || 'auto',
    db_server: taskValue('taskDbServer'), db_database: taskValue('taskDbDatabase'), db_user: taskValue('taskDbUser'), db_password: taskValue('taskDbPassword'),
    db_trusted_connection: $('taskTrustedConnection')?.checked || false, db_encrypt: true, db_trust_server_certificate: true, source_directory: taskValue('taskSourceDirectory') || './data/excel_inbox', file_pattern: taskValue('taskFilePattern') || '*.xlsx',
    source_sheet: taskValue('taskSourceSheet'), header_row: taskNumber('taskHeaderRow', 1), start_row: taskNumber('taskStartRow', 2),
    destination_table: taskValue('taskDestinationTable'), audit_table: taskValue('taskAuditTable') || 'dbo.ExcelImportAudit', default_field_type: taskValue('taskDefaultFieldType') || 'NVARCHAR(MAX)',
    hash_field: taskValue('taskHashField') || 'hash_value', overwrite: $('taskOverwrite')?.checked || false, mappings: collectTaskMappings(), composite_mappings: collectCompositeMappings(),
  };
  if (!payload.task_name) { showTaskConfigMessage('請輸入任務名稱。'); return; }
  if (!payload.mappings.length) { showTaskConfigMessage('請至少新增一筆 Excel 欄位對應。'); return; }
  const validationErrors = validateTaskConfigPayload(payload);
  if (validationErrors.length) { showTaskConfigMessage('智慧檢查發現設定問題：\n' + validationErrors.join('\n')); return; }
  const res = await fetch('/v1/excel-to-sql/task-configs', { method:'POST', headers:{ 'Content-Type':'application/json', Authorization:'Bearer ' + authToken() }, body: JSON.stringify(payload) });
  if (!res.ok) { showTaskConfigMessage(await responseErrorText(res)); return; }
  const data = await res.json();
  const task = data.task || {};
  const successMessage = `已建立待審任務設定檔：${task.config_path || ''}\n狀態：${task.status || 'pending'}。\n請通知 superuser 審核啟用後再上傳匯入。`;
  setPreview(`<strong>已建立待審任務設定檔：</strong>${escapeHtml(task.config_path || '')}<br><span class="muted">狀態：${escapeHtml(task.status || 'pending')}。請通知 superuser 審核啟用後再上傳匯入。</span>`);
  notifyImportant(successMessage);
  if ($('approveTaskConfigPath') && task.config_path) $('approveTaskConfigPath').value = task.config_path;
  await loadTasks();
  await loadMyTaskConfigs();
}

function updateSuperuserTaskReviewVisibility() {
  const box = $('superuserTaskReview');
  if (!box) return;
  box.classList.toggle('hidden', currentUserRole !== ROLE_SUPERUSER);
}
function reviewListItems(items) {
  return Object.entries(items || {}).map(([key, value]) => `<li><strong>${escapeHtml(key)}：</strong>${escapeHtml(value ?? '')}</li>`).join('');
}
function formatMappingSource(item) {
  const compose = item.compose || {};
  const template = compose.template ? `；模板：${compose.template}` : '';
  const sources = Array.isArray(compose.source_columns) ? compose.source_columns.join(', ') : (item.source_column || '');
  const sourceMatches = compose.source_matches ? `；來源比對：${Object.entries(compose.source_matches).map(([key, value]) => `${key}=${value}`).join(', ')}` : '';
  return `${sources}${sourceMatches}${template}`;
}
function renderMappingsForReview(mappings) {
  const rows = (mappings || []).map(item => `${escapeHtml(formatMappingSource(item))} → ${escapeHtml(item.dest_field || '')} <span class="muted">(${escapeHtml(item.dest_field_type || '')}${item.required ? '，必填' : ''}，${escapeHtml(item.match || 'exact')})</span>`);
  return rows.length ? `<ul>${rows.map(row => `<li>${row}</li>`).join('')}</ul>` : '<span class="muted">未設定欄位對應</span>';
}
function renderUploadTaskDetails() {
  const box = $('uploadTaskDetails');
  if (!box) return;
  const config = taskValue('task') || taskValue('uploadConfig');
  const task = dashboardTasks.find(item => item.config_path === config);
  if (!task?.review_summary) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  const summary = task.review_summary || {};
  box.classList.remove('hidden');
  if (!canReviewTaskMappings()) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  box.innerHTML = `<strong>目前匯入任務的 Excel→SQL 欄位轉換</strong><div class="muted">資料庫管理者可在上傳前先確認此任務會把哪些 Excel 欄位寫入哪些 SQL 欄位。</div><div class="review-card"><h4>Excel 欄位 → SQL 欄位</h4>${renderMappingsForReview(summary.mappings)}</div>`;
}
function renderTaskReviewDetails() {
  const box = $('taskReviewDetails');
  const config = taskValue('approveTaskConfigPath');
  if (!box || !config) { if (box) box.classList.add('hidden'); return; }
  const task = taskConfigReviewTasks.find(item => item.config_path === config);
  if (!task) { box.classList.add('hidden'); return; }
  const summary = task.review_summary || {};
  box.classList.remove('hidden');
  box.innerHTML = `<strong>JSON 任務轉換細節</strong><div class="muted">審核前請確認資料來源、目的資料表、欄位對應與自動建表 / 建欄設定；Server、資料庫名稱、DB 使用者與密碼等敏感欄位已遮蔽。</div><div class="review-grid"><div class="review-card"><h4>資料庫連線</h4><ul>${reviewListItems(summary.db)}</ul></div><div class="review-card"><h4>Excel 來源</h4><ul>${reviewListItems(summary.source)}</ul></div><div class="review-card"><h4>SQL 目的地</h4><ul>${reviewListItems(summary.destination)}</ul></div><div class="review-card"><h4>Audit / 匯入設定</h4><ul>${reviewListItems({ audit_table: summary.audit?.table, audit_enabled: summary.audit?.enabled, batch_size: summary.import?.batch_size, skip_empty_rows: summary.import?.skip_empty_rows, retry_max_attempts: summary.retry?.max_attempts })}</ul></div></div><div class="review-card"><h4>Excel 欄位 → SQL 欄位</h4>${renderMappingsForReview(summary.mappings)}</div><details><summary>查看遮蔽敏感資訊後的 JSON</summary><pre class="review-json">${escapeHtml(JSON.stringify(task.config_preview || {}, null, 2))}</pre></details>`;
}
async function loadTaskConfigReviewOptions() {
  const select = $('approveTaskConfigPath');
  if (!select || currentUserRole !== ROLE_SUPERUSER) return;
  const res = await fetch('/v1/excel-to-sql/task-configs?scope=all', { headers:{ Authorization:'Bearer ' + authToken() } });
  if (!res.ok) return;
  taskConfigReviewTasks = (await res.json()).tasks || [];
  select.innerHTML = taskConfigReviewTasks.length ? taskConfigReviewTasks.map(t => `<option value="${escapeHtml(t.config_path)}">${escapeHtml(t.status || '')}｜${escapeHtml(t.name || '')}｜${escapeHtml(t.config_path || '')}</option>`).join('') : '<option value="">沒有可審核任務設定檔</option>';
  renderTaskReviewDetails();
}
async function setTaskConfigStatus() {
  showError(''); setPreview('');
  const config = taskValue('approveTaskConfigPath');
  const enabled = $('taskReviewEnabled')?.value !== 'false';
  if (!config) { showError('請先選擇任務設定檔。'); return; }
  const res = await fetch('/v1/excel-to-sql/task-configs/status', { method:'POST', headers:{ 'Content-Type':'application/json', Authorization:'Bearer ' + authToken() }, body: JSON.stringify({ config, enabled }) });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  const data = await res.json(); const task = data.task || {};
  setPreview(`<strong>已${enabled ? '啟用' : '停用'}任務：</strong>${escapeHtml(task.config_path || config)}<br><span class="muted">狀態：${escapeHtml(task.status || '')}</span>`);
  await loadTasks();
  if (enabled && $('uploadConfig') && task.config_path) $('uploadConfig').value = task.config_path;
}
async function deleteReviewedTaskConfig() {
  showError(''); setPreview('');
  const config = taskValue('approveTaskConfigPath');
  if (!config) { showError('請先選擇任務設定檔。'); return; }
  if (!confirm(`確定刪除任務設定檔 ${config}？此動作會移除 JSON 檔。`)) return;
  const res = await fetch('/v1/excel-to-sql/task-configs', { method:'DELETE', headers:{ 'Content-Type':'application/json', Authorization:'Bearer ' + authToken() }, body: JSON.stringify({ config }) });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  setPreview(`<strong>已刪除任務：</strong>${escapeHtml(config)}`);
  await loadTasks();
  await loadMyTaskConfigs();
}

function taskConfigStatusBadge(status, enabled) {
  const text = status || (enabled ? 'active' : 'pending');
  return `<span class="status ${escapeHtml(text)}">${escapeHtml(text)}</span>`;
}
function myTaskConfigActions(task) {
  const config = escapeHtml(task.config_path || '');
  return `<div class="record-actions"><button class="secondary" onclick="disableMyTaskConfig('${config}')">停用</button><button class="ghost" onclick="deleteMyTaskConfig('${config}')">刪除</button></div>`;
}
async function loadMyTaskConfigs() {
  const table = $('myTaskConfigs');
  if (!table) return;
  const res = await fetch('/v1/excel-to-sql/task-configs?scope=mine', { headers:{ Authorization:'Bearer ' + authToken() } });
  if (!res.ok) return;
  const rows = (await res.json()).tasks || [];
  myTaskConfigsPager.rows = rows;
  myTaskConfigsPager.page = 1;
  renderMyTaskConfigsPage();
}
function renderMyTaskConfigsPage() {
  renderPagedTable('myTaskConfigs', myTaskConfigsPager, task => `<tr><td>${escapeHtml(task.name || '')}</td><td><code>${escapeHtml(task.config_path || '')}</code></td><td>${taskConfigStatusBadge(task.status, task.enabled)}</td><td>${escapeHtml(task.approved_by || '')}</td><td>${myTaskConfigActions(task)}</td></tr>`, 'myTaskConfigs');
}
async function disableMyTaskConfig(config) {
  if (!config) return;
  const res = await fetch('/v1/excel-to-sql/task-configs/status', { method:'POST', headers:{ 'Content-Type':'application/json', Authorization:'Bearer ' + authToken() }, body: JSON.stringify({ config, enabled:false }) });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  setPreview(`<strong>已停用任務：</strong>${escapeHtml(config)}`);
  await loadMyTaskConfigs(); await loadTasks();
}
async function deleteMyTaskConfig(config) {
  if (!config || !confirm('確定刪除自己建立的任務設定檔？此動作會移除 JSON 檔。')) return;
  const res = await fetch('/v1/excel-to-sql/task-configs', { method:'DELETE', headers:{ 'Content-Type':'application/json', Authorization:'Bearer ' + authToken() }, body: JSON.stringify({ config }) });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  setPreview(`<strong>已刪除任務：</strong>${escapeHtml(config)}`);
  await loadMyTaskConfigs(); await loadTasks();
}
function showMatchHelp() { const dialog = $('matchHelpDialog'); if (dialog?.showModal) dialog.showModal(); }
function closeMatchHelp() { $('matchHelpDialog')?.close(); }

if (document.getElementById('importRecords') || document.getElementById('taskConfigCard')) {
  if (document.getElementById('taskConfigCard')) {
    addTaskMappingRow();
    if ($('taskConnectionSource')) $('taskConnectionSource').onchange = () => applyConnectionSourceDefaults(connectionSourceTasks);
  }
  (async () => { bindPagedTable('importRecords', importRecordsPager, renderImportRecordsPage); bindPagedTable('myTaskConfigs', myTaskConfigsPager, renderMyTaskConfigsPage); await loadCurrentUser(); await loadTasks(); await loadMyTaskConfigs(); if (document.getElementById('importRecords')) await loadImportRecords(); })().catch(err => showError(err.message || String(err)));
}
