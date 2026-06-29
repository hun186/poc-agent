function collectSearchQuery(pageOverride) {
  const size = Math.max(1, Math.min(200, Number($('searchSize').value || 20)));
  const page = Math.max(1, Number(pageOverride || state.searchPage || 1));
  return new URLSearchParams({
    index: $('indexSelect').value,
    q: $('query').value,
    size: String(size),
    page: String(page),
    start_ts: toIsoOrEmpty($('searchStartTs').value.trim()),
    end_ts: toIsoOrEmpty($('searchEndTs').value.trim()),
  });
}
function updateSearchPagerButtons() {
  $('searchPrevBtn').disabled = state.searchPage <= 1;
  $('searchNextBtn').disabled = !state.searchHasMore;
}

function clearAuditFilters() {
  ['auditUsername','auditAction','auditIndex','auditDocId','auditPath','auditStartTs','auditEndTs'].forEach(id => { $(id).value = ''; });
  $('auditLimit').value = 100;
}
async function searchDocs(pageOverride=null) {
  if (pageOverride !== null) state.searchPage = Math.max(1, Number(pageOverride || 1));
  setStatus('searchStatus', '搜尋中...'); $('hits').innerHTML = '';
  try {
    const qs = collectSearchQuery(state.searchPage);
    const data = await api('/v1/editor/search?' + qs.toString(), {headers: {'Content-Type': 'application/json'}});
    state.latestHits = data.hits || [];
    state.searchPage = Number(data.page || state.searchPage || 1);
    state.searchHasMore = Boolean(data.has_more);
    updateSearchPagerButtons();
    setStatus('searchStatus', `共 ${data.total || 0} 筆，目前第 ${state.searchPage} 頁，顯示 ${data.hits.length} 筆`, 'ok');
    $('hits').innerHTML = data.hits.map((h, idx) => `<div class="hit"><div class="row" style="align-items:flex-start;"><div style="flex:0 0 auto;"><input type="checkbox" data-hit-check="${idx}" /></div><div style="flex:1;"><strong>${esc(titleFromSource(h.source))}</strong><div class="muted">${esc(h.index)} / ${esc(h.id)}</div><div class="row"><button data-hit="${idx}">載入</button><button class="danger" data-delete-hit="${idx}">刪除</button></div></div></div></div>`).join('');
    document.querySelectorAll('[data-hit]').forEach(btn => btn.onclick = () => loadDoc(data.hits[Number(btn.dataset.hit)].index, data.hits[Number(btn.dataset.hit)].id));
    document.querySelectorAll('[data-delete-hit]').forEach(btn => btn.onclick = () => deleteSingleHit(Number(btn.dataset.deleteHit)));
  } catch (err) { state.searchHasMore = false; updateSearchPagerButtons(); setStatus('searchStatus', err.message, 'error'); }
}
async function deleteSingleHit(hitIdx) {
  const hit = state.latestHits[hitIdx];
  if (!hit) return;
  if (!confirm(`確定刪除文件 ${hit.id}？`)) return;
  try {
    const qs = new URLSearchParams({index: hit.index, id: hit.id});
    await api('/v1/editor/doc?' + qs.toString(), {method: 'DELETE'});
    setStatus('searchStatus', `已刪除 ${hit.id}`, 'ok');
    await searchDocs();
  } catch (err) { state.searchHasMore = false; updateSearchPagerButtons(); setStatus('searchStatus', err.message, 'error'); }
}
async function deleteSelectedHits() {
  const checked = Array.from(document.querySelectorAll('[data-hit-check]:checked'));
  if (!checked.length) return setStatus('searchStatus', '請先勾選要刪除的文件', 'error');
  const ids = checked.map(el => {
    const hit = state.latestHits[Number(el.dataset.hitCheck)];
    return hit ? hit.id : '';
  }).filter(Boolean);
  if (!ids.length) return setStatus('searchStatus', '勾選資料無效，請重新搜尋', 'error');
  if (!confirm(`確定批次刪除 ${ids.length} 筆文件？`)) return;
  try {
    const index = $('indexSelect').value;
    const result = await api('/v1/editor/docs', {method: 'DELETE', body: JSON.stringify({index, ids})});
    setStatus('searchStatus', `批次刪除完成：成功 ${result.deleted_ids.length} 筆，未找到 ${result.not_found_ids.length} 筆`, 'ok');
    await searchDocs();
  } catch (err) { state.searchHasMore = false; updateSearchPagerButtons(); setStatus('searchStatus', err.message, 'error'); }
}
async function loadDoc(index, id) {
  setStatus('saveStatus', '載入文件中...');
  try {
    if (index !== $('indexSelect').value) $('indexSelect').value = index;
    await loadFormConfig(index);
    const qs = new URLSearchParams({index, id});
    const data = await api('/v1/editor/doc?' + qs.toString());
    syncDocIndexOptions(data.index); $('docId').value = data.id;
    state.loadedDocId = data.id || '';
    setEditorMode('edit');
    populateForm(data.source);
    setStatus('saveStatus', '文件已載入，可用設定檔定義的表單修改欄位。', 'ok');
  } catch (err) { setStatus('saveStatus', err.message, 'error'); }
}
function formatJson() {
  try { $('jsonEditor').value = JSON.stringify(JSON.parse($('jsonEditor').value), null, 2); setStatus('saveStatus', 'JSON 格式正確', 'ok'); }
  catch (err) { setStatus('saveStatus', 'JSON 格式錯誤：' + err.message, 'error'); }
}
function reloadFormFromJson() {
  try { populateForm(JSON.parse($('jsonEditor').value)); setStatus('saveStatus', '已由 JSON 重新載入表單', 'ok'); }
  catch (err) { setStatus('saveStatus', 'JSON 格式錯誤：' + err.message, 'error'); }
}
async function saveDoc() {
  if (!$('docIndex').value) return setStatus('saveStatus', '請先選擇 index', 'error');
  let source; try { source = collectFormToSource(); } catch (err) { return setStatus('saveStatus', '表單資料錯誤：' + err.message, 'error'); }
  setStatus('saveStatus', '儲存中...');
  try {
    const docId = $('docId').value.trim();
    const data = await api('/v1/editor/doc', {method: 'PUT', body: JSON.stringify({index: $('docIndex').value, id: docId || null, source})});
    const changed = data.changed_paths && data.changed_paths.length ? `\n異動欄位：${data.changed_paths.join(', ')}` : '';
    $('docId').value = data.id || docId;
    if (data.result === 'noop' && data.id) {
      await loadDoc(data.index || $('docIndex').value, data.id);
      const explain = data.message || '內容無異動（noop）';
      setStatus('saveStatus', `${explain}，已切換為既有文件編輯模式 / ID: ${data.id}`, 'ok');
      return;
    }
    setStatus('saveStatus', `儲存成功：${data.result || 'updated'} / ID: ${$('docId').value || '(自動產生失敗)'}${changed}`, 'ok');
  } catch (err) { setStatus('saveStatus', err.message, 'error'); }
}
async function saveAsNewDoc() {
  if (!$('docIndex').value) return setStatus('saveStatus', '請先選擇 index', 'error');
  let source;
  try { source = collectFormToSource(); } catch (err) { return setStatus('saveStatus', '表單資料錯誤：' + err.message, 'error'); }
  const cloned = JSON.parse(JSON.stringify(source || {}));
  const currentId = $('docId').value.trim();
  const loadedId = String(state.loadedDocId || '').trim();
  const unchangedLoadedId = loadedId && currentId && currentId === loadedId;
  if (unchangedLoadedId) {
    const ok = confirm('目前文件 ID 仍是原文件 ID。\n若你要指定新的文件 ID，請先修改「目前文件 ID」。\n\n按「確定」：自動產生新 ID 另存\n按「取消」：返回先改 ID');
    if (!ok) return setStatus('saveStatus', '已取消另存，請先修改文件 ID 後再另存', 'error');
  }
  if (currentId) delete cloned.uuid;
  setStatus('saveStatus', '另存新文件中...');
  try {
    const targetId = unchangedLoadedId ? null : (currentId || null);
    const data = await api('/v1/editor/doc', {method: 'PUT', body: JSON.stringify({index: $('docIndex').value, id: targetId, source: cloned})});
    if (data.id) {
      await loadDoc(data.index || $('docIndex').value, data.id);
      const uuidHint = currentId ? '（已忽略原文件 uuid，避免覆蓋）' : '';
      setStatus('saveStatus', `另存成功：新 ID ${data.id}${uuidHint}`, 'ok');
      return;
    }
    setStatus('saveStatus', '另存完成，但未取得新 ID', 'error');
  } catch (err) { setStatus('saveStatus', err.message, 'error'); }
}
function roleOptionsHtml(selectedRole, roleOptions) {
  const options = roleOptions && roleOptions.length ? roleOptions : [
    {value: 'superuser', label: '最高級全能者'},
    {value: 'db_operator', label: '資料庫操作者'},
    {value: 'data_editor', label: '資料修改者'},
    {value: 'data_reader', label: '資料閱讀者'},
  ];
  return options.map(opt => `<option value="${esc(opt.value)}" ${opt.value === selectedRole ? 'selected' : ''}>${esc(opt.label)} (${esc(opt.value)})</option>`).join('');
}
async function refreshUsers() {
  try {
    const data = await api('/v1/auth/users');
    const roleOptions = data.role_options || [];
    setUsageStatsUserOptions((data.users || []).map(u => u.username));
    $('users').innerHTML = data.users.map(u => `<div class="user"><strong>${esc(u.username)}</strong><div class="muted">status=${esc(u.status)}, role=${esc(u.role)}</div><div class="muted">姓名=${esc(u.full_name || '-')}, 單位=${esc(u.department || '-')}, 備註=${esc(u.note || '-')}</div><div class="row"><label class="inline-label">帳號層級<select data-role-select="${esc(u.username)}">${roleOptionsHtml(u.role, roleOptions)}</select></label><button data-approve-user="${esc(u.username)}">核准 / 更新層級</button><button data-issue-reset-token="${esc(u.username)}" class="secondary">產生 reset token</button><button data-unlock-login="${esc(u.username)}" class="secondary" title="清除該帳號目前記憶體中的登入冷卻紀錄。">解除登入冷卻</button><button data-reset-user="${esc(u.username)}" class="secondary">直接重設密碼</button><button data-reject-user="${esc(u.username)}" class="danger" title="pending 帳號會被拒絕申請；active 帳號會被停權並讓既有 token 失效。">拒絕申請／停權</button><button data-delete-user="${esc(u.username)}" class="danger">刪除帳號</button></div></div>`).join('');
    document.querySelectorAll('[data-approve-user]').forEach(btn => btn.onclick = () => approveSelectedUser(btn.dataset.approveUser));
    document.querySelectorAll('[data-issue-reset-token]').forEach(btn => btn.onclick = () => issuePasswordResetToken(btn.dataset.issueResetToken));
    document.querySelectorAll('[data-unlock-login]').forEach(btn => btn.onclick = () => unlockUserLogin(btn.dataset.unlockLogin));
    document.querySelectorAll('[data-reset-user]').forEach(btn => btn.onclick = () => resetUserPassword(btn.dataset.resetUser));
    document.querySelectorAll('[data-reject-user]').forEach(btn => btn.onclick = () => rejectUser(btn.dataset.rejectUser));
    document.querySelectorAll('[data-delete-user]').forEach(btn => btn.onclick = () => deleteUser(btn.dataset.deleteUser));
  } catch (err) { $('users').innerHTML = `<div class="status error">${esc(err.message)}</div>`; }
}
async function approveSelectedUser(username) {
  const select = Array.from(document.querySelectorAll('[data-role-select]')).find(el => el.dataset.roleSelect === username);
  await approveUser(username, select ? select.value : 'data_reader');
}
async function approveUser(username, role) { await api(`/v1/auth/users/${encodeURIComponent(username)}/approve`, {method:'POST', body: JSON.stringify({role})}); await refreshUsers(); }
async function rejectUser(username) { await api(`/v1/auth/users/${encodeURIComponent(username)}/reject`, {method:'POST'}); await refreshUsers(); }
async function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  const ok = document.execCommand('copy');
  ta.remove();
  if (!ok) throw new Error('瀏覽器不允許自動複製，請手動選取文字複製。');
}
function showResetTokenDialog(username, token) {
  $('resetTokenModalHelp').textContent = `請用安全管道交付給 ${username}。token 只會顯示這一次，請直接複製保存。`;
  $('resetTokenModalValue').value = token || '';
  $('resetTokenCopyStatus').classList.add('hidden');
  $('resetTokenModal').classList.remove('hidden');
  $('resetTokenModalValue').focus();
  $('resetTokenModalValue').select();
}
function closeResetTokenDialog() { $('resetTokenModal').classList.add('hidden'); }
async function issuePasswordResetToken(username) {
  const data = await api(`/v1/auth/users/${encodeURIComponent(username)}/password-reset-token`, {method:'POST'});
  showResetTokenDialog(username, data.reset_token);
}
async function unlockUserLogin(username) {
  const data = await api(`/v1/auth/users/${encodeURIComponent(username)}/unlock-login`, {method:'POST'});
  setStatus('accountStatus', data.message || `已解除 ${username} 的登入冷卻。`, 'ok');
  await refreshUsers();
}
async function resetUserPassword(username) {
  const new_password = prompt(`請輸入 ${username} 的新密碼（至少 8 字元）：`);
  if (!new_password) return;
  await api(`/v1/auth/users/${encodeURIComponent(username)}/reset-password`, {method:'POST', body: JSON.stringify({new_password})});
  await refreshUsers();
}
async function deleteUser(username) {
  if (!confirm(`確定刪除帳號 ${username}？`)) return;
  await api(`/v1/auth/users/${encodeURIComponent(username)}`, {method:'DELETE'});
  await refreshUsers();
}
async function uploadRawContentFile() {
  const file = $('contentFileInput').files && $('contentFileInput').files[0];
  if (!file) return setStatus('saveStatus', '請先選擇檔案', 'error');
  const formData = new FormData();
  formData.append('file', file);
  setStatus('saveStatus', '抽取文字中...');
  try {
    const headers = state.token ? { Authorization: 'Bearer ' + state.token } : {};
    const res = await fetch('/v1/editor/extract-text', { method: 'POST', headers, body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '文字擷取失敗');
    collectFormToSource();
    const original = String(getPath(state.source, 'rawInfo.content') || '');
    const merged = original ? `${original}\n\n${data.text || ''}` : String(data.text || '');
    setPath(state.source, 'rawInfo.content', merged);
    populateForm(state.source);
    setStatus('saveStatus', `已抽取 ${file.name}，可再按「儲存到 ES」`, 'ok');
  } catch (err) { setStatus('saveStatus', err.message, 'error'); }
}

function newDoc() {
  const index = $('indexSelect').value;
  if (!index) return setStatus('saveStatus', '請先選擇 index', 'error');
  syncDocIndexOptions(index);
  setEditorMode('new');
  $('docId').value = '';
  state.loadedDocId = '';
  state.source = {};
  populateForm(state.source);
  setStatus('saveStatus', '已切換為新增模式：可留空 ID。儲存時會優先使用 source.uuid，若沒有則自動產生 sha1 uuid。', 'ok');
}

async function logout(opts = {}) {
  if (state.token && !opts.skipRemote) {
    try { await api('/v1/auth/logout', {method:'POST'}); } catch (_) { /* local cleanup still applies */ }
  }
  state.token = ''; state.user = null; localStorage.removeItem('sra_editor_token'); $('headerLogoutBtn').classList.add('hidden'); location.reload();
}
function showPane(which) { $('formPane').classList.toggle('hidden', which !== 'form'); $('jsonPane').classList.toggle('hidden', which !== 'json'); $('formTabBtn').classList.toggle('active', which === 'form'); $('jsonTabBtn').classList.toggle('active', which === 'json'); }
$('loginBtn').onclick = login; $('forgotPasswordBtn').onclick = forgotPassword; $('recoverPasswordBtn').onclick = recoverPassword; $('changePasswordBtn').onclick = changePassword; $('searchPrevBtn').onclick = () => { if (state.searchPage > 1) searchDocs(state.searchPage - 1); }; $('searchNextBtn').onclick = () => { if (state.searchHasMore) searchDocs(state.searchPage + 1); }; $('navNewDocBtn').onclick = () => { newDoc(); collapseMainNav(); }; $('registerBtn').onclick = register; $('searchBtn').onclick = () => searchDocs(1); $('saveBtn').onclick = saveDoc; $('saveAsNewBtn').onclick = saveAsNewDoc; $('formatBtn').onclick = formatJson; $('headerLogoutBtn').onclick = logout; $('refreshUsersBtn').onclick = refreshUsers; $('refreshStatsBtn').onclick = refreshUsageStats; $('extractTextBtn').onclick = uploadRawContentFile;
