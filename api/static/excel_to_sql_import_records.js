function setPreview(html) { const box = $('previewBox'); if (!html) { box.classList.add('hidden'); box.innerHTML=''; } else { box.classList.remove('hidden'); box.innerHTML=html; } }
async function uploadExcelRecord() {
  showError(''); setPreview('');
  const input = $('uploadExcel');
  if (!input.files.length) { showError('請先選擇 Excel 檔案。'); return; }
  const token = authToken();
  const body = new FormData(); body.append('file', input.files[0]);
  const params = new URLSearchParams({ config: $('uploadConfig').value || $('config').value });
  const res = await fetch('/v1/excel-to-sql/import-records?' + params.toString(), { method:'POST', headers:{ Authorization:'Bearer ' + token }, body });
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
  setPreview(`<strong>預掃描結果：</strong>總列數 ${p.total_rows||0}，預估新增 ${p.will_insert||0}，重複 ${p.duplicate||0}，錯誤 ${p.failed||0}<br><span class="muted">工作表：${escapeHtml((p.sheets||[]).join(', '))}</span>`);
  await loadImportRecords();
}
async function confirmImportRecord(id) {
  if (!confirm('確定要依預掃描結果執行實際匯入 SQL？')) return;
  const res = await fetch(`/v1/excel-to-sql/import-records/${encodeURIComponent(id)}/confirm`, { method:'POST', headers:{ Authorization:'Bearer ' + authToken() } });
  if (!res.ok) { let text=await res.text(); try{text=JSON.parse(text).detail||text;}catch(_){} showError(text); return; }
  const data = await res.json(); const r = data.import_result || {};
  setPreview(`<strong>匯入完成：</strong>新增 ${r.inserted_rows||0}，重複 ${r.duplicate_rows||0}，錯誤 ${r.failed_rows||0}`);
  await loadImportRecords(); await loadDashboard();
}
function importRecordCounts(r) { return r.import_result || r.preview || {}; }
function importRecordActions(r) {
  if (r.status === 'deleted') return '';
  return `<div class="record-actions"><button class="ghost" onclick="previewImportRecord('${escapeHtml(r.id)}')">預掃描</button><button onclick="confirmImportRecord('${escapeHtml(r.id)}')">確認匯入SQL</button><button class="secondary" onclick="deleteSingleImportRecord('${escapeHtml(r.id)}')">刪除記錄</button></div>`;
}
async function loadImportRecords() {
  const params = new URLSearchParams();
  const map = { filename:'recordFilenameFilter', status:'recordStatusFilter', actor:'recordActorFilter', start_ts:'recordStartFilter', end_ts:'recordEndFilter' };
  Object.entries(map).forEach(([k,id]) => { const v=$(id).value.trim(); if (v) params.set(k,v); });
  const res = await fetch('/v1/excel-to-sql/import-records?' + params.toString(), { headers:{ Authorization:'Bearer ' + authToken() } });
  if (!res.ok) return;
  const data = await res.json();
  fillTable('importRecords', data.records || [], r => { const c=importRecordCounts(r); return `<tr><td><input type="checkbox" data-record-id="${escapeHtml(r.id)}" /></td><td>${formatAuditTime(r.created_at)}</td><td>${escapeHtml(r.username)}</td><td>${escapeHtml(r.original_filename)}</td><td>${escapeHtml(r.config_path)}</td><td>${statusBadge(r.status)}</td><td>${escapeHtml(c.inserted_rows ?? c.will_insert ?? '')}</td><td>${escapeHtml(c.duplicate_rows ?? c.duplicate ?? '')}</td><td>${escapeHtml(c.failed_rows ?? c.failed ?? '')}</td><td>${escapeHtml(r.file_size || 0)}</td><td>${importRecordActions(r)}</td></tr>`; });
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
