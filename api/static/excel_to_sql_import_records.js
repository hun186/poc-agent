const tokenKey = 'sra_editor_token';
function $(id) { return document.getElementById(id); }
function escapeHtml(v) { return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function authToken() { return localStorage.getItem(tokenKey) || ''; }
function statusBadge(s) { return `<span class="status ${escapeHtml(s)}">${escapeHtml(s || '(empty)')}</span>`; }
function showError(text) { const el=$('msg'); if (!el) return; if (!text) { el.classList.add('hidden'); el.textContent=''; } else { el.classList.remove('hidden'); el.textContent=text; } }
function fillTable(id, rows, render) { document.querySelector(`#${id} tbody`).innerHTML = rows.map(render).join('') || '<tr><td colspan="99" class="muted">無資料</td></tr>'; }
function pad2(v) { return String(v).padStart(2, '0'); }
function normalizeAuditUtc(text) { const raw = String(text || ''); if (!raw) return null; const trimmed = raw.replace(/(\.\d{3})\d+/, '$1'); return /[zZ]|[+-]\d\d:?\d\d$/.test(trimmed) ? trimmed : trimmed + 'Z'; }
function formatAuditTime(value) { const raw = String(value || ''); const normalized = normalizeAuditUtc(raw); if (!normalized) return ''; const local = new Date(normalized); if (Number.isNaN(local.getTime())) return escapeHtml(raw); return `<div>${escapeHtml(local.toLocaleString())}</div><div class="muted">UTC：${escapeHtml(raw)}</div>`; }
function localInputToUtcIso(id) { const el = $(id); const v = el?.value || ''; return v ? new Date(v).toISOString() : ''; }
function setPreview(html) { const box = $('previewBox'); if (!html) { box.classList.add('hidden'); box.innerHTML=''; } else { box.classList.remove('hidden'); box.innerHTML=html; } }
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
  return `<div class="diagnostics"><strong>失敗 ${escapeHtml(failed)} 筆</strong>${summarizeFailures(result.failure_summary)}${sampleDiagnostics(result.samples)}</div>`;
}
async function loadCurrentUser() {
  const token = authToken();
  if (!token || !$('whoami')) return;
  try {
    const res = await fetch('/v1/auth/me', { headers: { Authorization: 'Bearer ' + token } });
    if (!res.ok) throw new Error('unauthorized');
    const data = await res.json(); const user = data.user || {};
    $('whoami').textContent = user.username ? `${user.username} (${user.role || '-'})` : '未登入';
  } catch (_) { $('whoami').textContent = '登入已失效'; }
}
async function loadTasks() {
  if (!$('task')) return;
  const token = authToken();
  if (!token) { showError('請先到 /editor 登入；本頁會沿用 sra_editor_token。'); return; }
  const res = await fetch('/v1/excel-to-sql/dashboard-tasks', { headers: { Authorization: 'Bearer ' + token } });
  if (!res.ok) return;
  const tasks = (await res.json()).tasks || [];
  $('task').innerHTML = tasks.length ? tasks.map(t => `<option value="${escapeHtml(t.config_path)}">${escapeHtml(t.name)} (${escapeHtml(t.config_path)})</option>`).join('') : '<option value="">未找到 dashboard.enabled=true 的任務</option>';
  if (tasks.length && $('uploadConfig')) $('uploadConfig').value = tasks[0].config_path;
}
function onTaskChange() { if ($('task').value) $('uploadConfig').value = $('task').value; }
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
function importRecordActions(r) { if (r.status === 'deleted') return '<span class="muted">—</span>'; return `<div class="record-actions"><button class="ghost" onclick="previewImportRecord('${escapeHtml(r.id)}')">預掃描</button><button onclick="confirmImportRecord('${escapeHtml(r.id)}')">確認匯入SQL</button><button class="secondary" onclick="deleteSingleImportRecord('${escapeHtml(r.id)}')">刪除記錄</button></div>`; }
async function loadImportRecords() {
  const params = new URLSearchParams();
  const map = { filename:'recordFilenameFilter', status:'recordStatusFilter', actor:'recordActorFilter' };
  Object.entries(map).forEach(([k,id]) => { const v=$(id).value.trim(); if (v) params.set(k,v); });
  const startIso = localInputToUtcIso('recordStartFilter'); const endIso = localInputToUtcIso('recordEndFilter');
  if (startIso) params.set('start_ts', startIso); if (endIso) params.set('end_ts', endIso);
  const res = await fetch('/v1/excel-to-sql/import-records?' + params.toString(), { headers:{ Authorization:'Bearer ' + authToken() } });
  if (!res.ok) return;
  const data = await res.json();
  fillTable('importRecords', data.records || [], r => { const c=importRecordCounts(r); return `<tr><td data-label="選取"><input type="checkbox" data-record-id="${escapeHtml(r.id)}" aria-label="選取匯入記錄 ${escapeHtml(r.original_filename)}" /></td><td data-label="日期">${formatAuditTime(r.created_at)}</td><td data-label="使用者">${escapeHtml(r.username)}</td><td data-label="檔名">${escapeHtml(r.original_filename)}</td><td data-label="設定檔">${escapeHtml(r.config_path)}</td><td data-label="狀態">${statusBadge(r.status)}</td><td data-label="新增">${escapeHtml(c.inserted_rows ?? c.will_insert ?? '')}</td><td data-label="重複">${escapeHtml(c.duplicate_rows ?? c.duplicate ?? '')}</td><td data-label="錯誤">${escapeHtml(c.failed_rows ?? c.failed ?? '')}</td><td data-label="大小">${escapeHtml(r.file_size || 0)}</td><td data-label="錯誤診斷">${importRecordDiagnostics(r)}</td><td data-label="操作">${importRecordActions(r)}</td></tr>`; });
}
function selectedImportRecordIds() { return Array.from(document.querySelectorAll('#importRecords tbody input[data-record-id]:checked')).map(el => el.dataset.recordId); }
function toggleAllImportRecords(checked) { document.querySelectorAll('#importRecords tbody input[data-record-id]').forEach(el => { el.checked = checked; }); }
async function deleteSingleImportRecord(id) { await deleteImportRecords([id]); }
async function deleteSelectedImportRecords() { const ids = selectedImportRecordIds(); if (!ids.length) { showError('請先勾選要刪除的匯入記錄。'); return; } await deleteImportRecords(ids); }
async function deleteImportRecords(ids) {
  const reason = prompt('請輸入刪除匯入記錄原因：', '使用者清理匯入記錄'); if (reason === null) return;
  const res = await fetch('/v1/excel-to-sql/import-records', { method:'DELETE', headers:{ 'Content-Type':'application/json', Authorization:'Bearer ' + authToken() }, body: JSON.stringify({ record_ids: ids, reason }) });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  await loadImportRecords();
}
if (document.getElementById('importRecords')) {
  (async () => { await loadCurrentUser(); await loadTasks(); await loadImportRecords(); })().catch(err => showError(err.message || String(err)));
}
