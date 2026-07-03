const $ = id => document.getElementById(id);
const tokenKey = 'sra_editor_token';
const state = { data: null };
function token() { return localStorage.getItem(tokenKey) || ''; }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function show(msg, cls='') { const el = $('status'); el.textContent = msg; el.className = 'status ' + cls; el.classList.toggle('hidden', !msg); }
async function api(path) {
  const headers = {'Content-Type':'application/json'};
  if (token()) headers.Authorization = 'Bearer ' + token();
  const res = await fetch(path, {headers});
  if (!res.ok) { let text = await res.text(); try { text = JSON.parse(text).detail || text; } catch (_) {} throw new Error(text); }
  return res.json();
}
async function loadCurrentUser() {
  if (!token()) { $('whoami').textContent = '未登入'; show('請先到 /editor 登入；本頁會沿用 sra_editor_token。', 'error'); return false; }
  try { const data = await api('/v1/auth/me'); const user = data.user || {}; $('whoami').textContent = user.username ? `${user.username} (${user.role || '-'})` : '未登入'; return true; }
  catch (_) { $('whoami').textContent = '登入已失效'; show('登入已失效，請回 /editor 重新登入。', 'error'); return false; }
}
async function loadTasks() {
  const data = await api('/v1/excel-to-sql/dashboard-tasks');
  const tasks = (data.tasks || []).filter(t => t.config_path && t.destination_table);
  $('task').innerHTML = tasks.length ? tasks.map(t => `<option value="${esc(t.config_path)}">${esc(t.name)} (${esc(t.destination_table || '未設定 table')})</option>`).join('') : '<option value="">未找到已啟用任務</option>';
  if (tasks.length) $('config').value = tasks[0].config_path;
}
function localInputToUtcIso(id) { const value = $(id)?.value || ''; return value ? new Date(value).toISOString() : ''; }
function paramsForStats() {
  const params = new URLSearchParams({
    config: $('config').value.trim(), q: $('query').value.trim(), source_file_filter: $('sourceFileFilter').value.trim(),
    hash_value_filter: $('hashFilter').value.trim(), payload_filter: $('payloadFilter').value.trim(),
    import_start_ts: localInputToUtcIso('importStartFilter'), import_end_ts: localInputToUtcIso('importEndFilter'),
    group_by: $('groupBy').value, top: $('top').value || '20',
  });
  if ($('rowNoFilter').value) params.set('row_no_filter', $('rowNoFilter').value);
  $('usernameFilter').value.split(',').map(v => v.trim()).filter(Boolean).forEach(v => params.append('username_filter', v));
  return params;
}
function renderGroupOptions(data) {
  const current = $('groupBy').value || data.group_by || '';
  $('groupBy').innerHTML = (data.groupable_columns || []).map(col => `<option value="${esc(col)}">${esc(col)}</option>`).join('');
  if ((data.groupable_columns || []).includes(current)) $('groupBy').value = current;
}
function renderMetrics(data) {
  $('metrics').innerHTML = `<div class="metric"><span class="muted">符合篩選資料列</span><strong>${Number(data.total || 0).toLocaleString()}</strong></div><div class="metric"><span class="muted">SQL table</span><strong style="font-size:18px">${esc(data.destination_table || '-')}</strong></div><div class="metric"><span class="muted">分組欄位</span><strong style="font-size:18px">${esc(data.group_by || '-')}</strong></div>`;
}
function attributeGroupCard(group, total) {
  const rows = group.items || [];
  const maxCount = Math.max(1, ...rows.map(row => Number(row.count || 0)));
  const items = rows.map(row => {
    const count = Number(row.count || 0);
    const pct = total ? count / Number(total) * 100 : 0;
    return `<li><span class="group-value" title="${esc(row.value || '(空值)')}">${esc(row.value || '(空值)')}</span><strong>${count.toLocaleString()}</strong><span class="muted">${pct.toFixed(1)}%</span><div class="bar"><span style="width:${Math.max(2, count / maxCount * 100)}%"></span></div></li>`;
  }).join('') || '<li class="muted">沒有資料</li>';
  return `<article class="attribute-card"><h3>${esc(group.label || group.key || '分群')}</h3><ul>${items}</ul></article>`;
}
function renderAttributeGroups(data) {
  $('attributeGroups').innerHTML = (data.attribute_groups || []).map(group => attributeGroupCard(group, Number(data.total || 0))).join('') || '<p class="muted">沒有可顯示的分群統計。</p>';
}

function renderGroups(data) {
  const rows = data.groups || [];
  const maxCount = Math.max(1, ...rows.map(row => Number(row.count || 0)));
  $('groupSummary').textContent = `依 ${data.group_by || '-'} 顯示前 ${rows.length} 名；分組欄位只能從目的資料表既有欄位選擇。`;
  $('groupTable').innerHTML = `<table><thead><tr><th>值</th><th>筆數</th><th>占比</th><th>視覺化</th></tr></thead><tbody>${rows.map(row => { const count = Number(row.count || 0); const pct = data.total ? count / Number(data.total) * 100 : 0; return `<tr><td>${esc(row.value || '(空值)')}</td><td>${count.toLocaleString()}</td><td>${pct.toFixed(1)}%</td><td><div class="bar"><span style="width:${Math.max(2, count / maxCount * 100)}%"></span></div></td></tr>`; }).join('') || '<tr><td colspan="4" class="muted">沒有分組資料</td></tr>'}</tbody></table>`;
}
function renderNumeric(data) {
  const rows = data.numeric_summaries || [];
  $('numericTable').innerHTML = `<table><thead><tr><th>欄位</th><th>非空筆數</th><th>最小值</th><th>最大值</th><th>平均</th><th>總和</th></tr></thead><tbody>${rows.map(row => `<tr><td>${esc(row.column)}</td><td>${esc(row.count)}</td><td>${esc(row.min)}</td><td>${esc(row.max)}</td><td>${esc(row.avg)}</td><td>${esc(row.sum)}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">此資料表沒有可摘要的數值欄位</td></tr>'}</tbody></table>`;
}
async function loadStats() {
  if (!token()) { show('請先到 /editor 登入；本頁會沿用 sra_editor_token。', 'error'); return; }
  show('統計資料載入中...');
  try { const data = await api('/v1/excel-to-sql/source-stats?' + paramsForStats().toString()); state.data = data; renderGroupOptions(data); renderMetrics(data); renderAttributeGroups(data); renderGroups(data); renderNumeric(data); show('統計完成', 'ok'); }
  catch (err) { show(err.message, 'error'); }
}
$('task').onchange = () => { if ($('task').value) $('config').value = $('task').value; loadStats(); };
$('loadBtn').onclick = loadStats;
$('groupBy').onchange = loadStats;
$('clearFiltersBtn').onclick = () => { ['query','sourceFileFilter','importStartFilter','importEndFilter','usernameFilter','rowNoFilter','hashFilter','payloadFilter'].forEach(id => { $(id).value = ''; }); loadStats(); };
loadCurrentUser().then(ok => ok ? loadTasks() : Promise.reject(new Error('請先登入'))).then(loadStats).catch(err => { if (err.message !== '請先登入') show(err.message, 'error'); });
