function collectAuditQuery() {
  const qs = new URLSearchParams();
  const mapping = {
    username: $('auditUsername').value.trim(),
    action: $('auditAction').value.trim(),
    index: $('auditIndex').value.trim(),
    id: $('auditDocId').value.trim(),
    changed_path: $('auditPath').value.trim(),
    start_ts: toIsoOrEmpty($('auditStartTs').value.trim()),
    end_ts: toIsoOrEmpty($('auditEndTs').value.trim()),
    limit: String(Math.max(1, Math.min(500, Number($('auditLimit').value || 100))))
  };
  Object.entries(mapping).forEach(([k, v]) => { if (v) qs.set(k, v); });
  return qs;
}
const auditActionLabels = {
  'editor.create_document': '新增文件',
  'editor.save_document': '儲存文件',
  'editor.delete_document': '刪除文件',
  'auth.user_registered': '建立 pending 帳號',
  'auth.login': '登入',
  'auth.logout': '登出',
  'auth.password_changed': '變更密碼',
  'auth.password_reset_requested': '忘記密碼申請',
  'auth.password_recovered': 'Token 重設密碼',
  'auth.password_reset_token_issued': '管理員發 token',
  'auth.password_reset_by_superuser': '管理員重設密碼',
  'auth.user_approved': '核准帳號',
  'auth.user_rejected': '拒絕申請／停權',
  'auth.user_deleted': '刪除帳號'
};
function auditActionLabel(action) { return auditActionLabels[action] || action || '(unknown action)'; }
function renderAuditCard(h) {
  const paths = Array.isArray(h.changed_paths) ? h.changed_paths.filter(Boolean) : [];
  return `<div class="audit">
    <div><strong>${esc(auditActionLabel(h.action))}</strong><span class="muted"> ｜${esc(h.action || '')}</span></div>
    <div class="muted">${esc(formatLocalTimestamp(h.ts))}｜${esc(h.username || '-') } (${esc(h.role || '-')})</div>
    <div class="muted">index=${esc(h.index || '-')} / id=${esc(h.id || '-')} / result=${esc(h.result || '-')}</div>
    <div class="muted">異動欄位：${paths.length ? esc(paths.join(', ')) : '(無)'}</div>
  </div>`;
}
function renderAccountAuditCard(h) {
  const actor = h.actor ? `｜執行者：${esc(h.actor)}` : '';
  const detail = h.reason || h.status || h.role || h.result || '';
  const clientHost = h.client_host ? `｜IP：${esc(h.client_host)}` : '';
  const userAgent = h.user_agent ? `<div class="muted">User-Agent：${esc(h.user_agent)}</div>` : '';
  return `<div class="audit">
    <div><strong>${esc(auditActionLabel(h.action))}</strong><span class="muted"> ｜${esc(h.action || '')}</span></div>
    <div class="muted">${esc(formatLocalTimestamp(h.ts))}｜帳號：${esc(h.username || '-')}${actor}${clientHost}</div>
    ${detail ? `<div class="muted">補充：${esc(detail)}</div>` : ''}
    ${userAgent}
  </div>`;
}
function renderAuditHits(hits) {
  state.auditRows = sortAuditRows(hits || []);
  state.auditPage = 1;
  renderAuditHitsPage();
}
function renderAuditHitsPage() {
  const page = updateClientPager({rows: state.auditRows, page: state.auditPage, pageSize: 25, infoId: 'auditPageInfo', prevId: 'auditPrevBtn', nextId: 'auditNextBtn'});
  state.auditPage = page.page;
  $('auditHits').innerHTML = page.rows.map(renderAuditCard).join('') || '<p class="muted">目前篩選條件下無文件異動紀錄。</p>';
}
function renderAccountAuditHits(hits) {
  state.accountAuditRows = sortAuditRows(hits || []);
  state.accountAuditPage = 1;
  renderAccountAuditHitsPage();
}
function renderAccountAuditHitsPage() {
  const page = updateClientPager({rows: state.accountAuditRows, page: state.accountAuditPage, pageSize: 25, infoId: 'accountAuditPageInfo', prevId: 'accountAuditPrevBtn', nextId: 'accountAuditNextBtn'});
  state.accountAuditPage = page.page;
  $('accountAuditHits').innerHTML = page.rows.map(renderAccountAuditCard).join('') || '<p class="muted">目前篩選條件下無帳號操作紀錄。</p>';
}
async function searchAuditLogs() {
  setStatus('auditStatus', '查詢文件異動紀錄中...');
  try {
    const qs = collectAuditQuery();
    qs.set('action_prefix', 'editor.');
    const data = await api('/v1/editor/audit-logs?' + qs.toString(), {headers: {'Content-Type': 'application/json'}});
    const hits = data.hits || [];
    renderAuditHits(hits);
    refreshAuditFilterOptions(hits);
    setStatus('auditStatus', `文件異動共符合 ${hits.length} 筆；已先篩選、依時間排序，再分頁顯示。`, 'ok');
  } catch (err) {
    setStatus('auditStatus', err.message, 'error');
    $('auditHits').innerHTML = '';
  }
}
const ACCOUNT_AUDIT_FETCH_LIMIT = 50000;
const ACCOUNT_AUDIT_DEFAULT_LIMIT = 5000;
function accountAuditLimit() { return Math.max(1, Math.min(ACCOUNT_AUDIT_FETCH_LIMIT, Number($('accountAuditLimit').value || ACCOUNT_AUDIT_DEFAULT_LIMIT))); }
function collectAccountAuditQuery() {
  const qs = new URLSearchParams({limit: String(accountAuditLimit())});
  const username = $('accountAuditUsername').value.trim();
  const action = $('accountAuditAction').value.trim();
  const startTs = toIsoOrEmpty($('accountAuditStartTs').value.trim());
  const endTs = toIsoOrEmpty($('accountAuditEndTs').value.trim());
  if (username) qs.set('username', username);
  if (action) qs.set('action', action);
  if (startTs) qs.set('start_ts', startTs);
  if (endTs) qs.set('end_ts', endTs);
  qs.set('action_prefix', 'auth.');
  return qs;
}
function refreshAccountAuditFilterOptions(hits) {
  const usernames = [...new Set((hits||[]).map(h => String(h.username||'').trim()).filter(Boolean))].sort();
  updateAuditSelectOptions('accountAuditUsername', usernames);
}
async function searchAccountAuditLogs() {
  setStatus('accountAuditStatus', '查詢帳號操作紀錄中...');
  try {
    const qs = collectAccountAuditQuery();
    const data = await api('/v1/editor/audit-logs?' + qs.toString(), {headers: {'Content-Type': 'application/json'}});
    const hits = data.hits || [];
    renderAccountAuditHits(hits);
    refreshAccountAuditFilterOptions(hits);
    const scopeText = state.user && state.user.role === 'superuser' ? '帳號操作' : '我的帳號操作';
    const limit = Number(data.limit || accountAuditLimit());
    const truncated = Boolean(data.truncated);
    if (truncated) alert(`帳號操作紀錄已達載入上限 ${limit} 筆，尚有資料未載入。請設定帳號、動作或時間條件縮小查詢範圍。`);
    const warningText = truncated ? `；已達載入上限 ${limit} 筆，尚有未載入資料，請縮小篩選條件` : '';
    setStatus('accountAuditStatus', `${scopeText}共符合 ${data.total ?? hits.length} 筆，已載入 ${hits.length} 筆${warningText}；已先篩選、依時間排序，再分頁顯示。`, truncated ? 'error' : 'ok');
  } catch (err) {
    setStatus('accountAuditStatus', err.message, 'error');
    $('accountAuditHits').innerHTML = '';
  }
}
function clearAccountAuditFilters() {
  $('accountAuditUsername').value = '';
  $('accountAuditAction').value = '';
  $('accountAuditStartTs').value = '';
  $('accountAuditEndTs').value = '';
  $('accountAuditLimit').value = String(ACCOUNT_AUDIT_DEFAULT_LIMIT);
}

