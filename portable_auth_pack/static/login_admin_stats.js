function setAccountStatsUserOptions(values) { pageState.accountStatsUserOptions = [...new Set((values || []).map(v => String(v || '').trim()).filter(Boolean))].sort(); if (pageState.currentUser && !pageState.accountStatsUserOptions.includes(pageState.currentUser.username)) pageState.accountStatsUserOptions.unshift(pageState.currentUser.username); pageState.accountStatsSelectedUsers = pageState.accountStatsSelectedUsers.filter(v => pageState.accountStatsUserOptions.includes(v)); renderAccountStatsUserPicker(); }
function visibleAccountStatsUserOptions() { const q = document.getElementById('accountStatsUsernameSearch') ? document.getElementById('accountStatsUsernameSearch').value.trim().toLowerCase() : ''; return pageState.accountStatsUserOptions.filter(v => !q || v.toLowerCase().includes(q)); }
function renderAccountStatsUserPicker() { const box = document.getElementById('accountStatsUsernameOptions'); if (!box) return; const selected = new Set(pageState.accountStatsSelectedUsers); const visible = visibleAccountStatsUserOptions(); box.innerHTML = visible.map(v => `<label class="multi-filter-option"><input type="checkbox" data-account-stats-user="${esc(v)}" ${selected.has(v) ? 'checked' : ''} /> <span>${esc(v)}</span></label>`).join('') || '<p class="muted">沒有符合關鍵字的帳號。</p>'; box.querySelectorAll('[data-account-stats-user]').forEach(input => input.onchange = () => { const value = input.dataset.accountStatsUser; pageState.accountStatsSelectedUsers = input.checked ? [...new Set(pageState.accountStatsSelectedUsers.concat([value]))] : pageState.accountStatsSelectedUsers.filter(v => v !== value); updateAccountStatsUserSummary(); }); updateAccountStatsUserSummary(); }
function updateAccountStatsUserSummary() { const selected = pageState.accountStatsSelectedUsers; document.getElementById('accountStatsUsername').value = selected.join(','); const summary = document.getElementById('accountStatsUsernameSummary'); if (!summary) return; const note = document.getElementById('accountStatsCurrentScopeText'); if (pageState.accountStatsView === 'mine') { const text = pageState.currentUser ? `目前顯示個人帳號操作紀錄：${pageState.currentUser.username}` : '目前顯示個人帳號操作紀錄'; summary.textContent = text; if (note) note.textContent = text; } else if (!selected.length) summary.textContent = '全體帳號'; else summary.textContent = selected.length <= 2 ? selected.join(', ') : `已選 ${selected.length} 個帳號`; }
function setVisibleAccountStatsUsers(checked) { const visible = visibleAccountStatsUserOptions(); pageState.accountStatsSelectedUsers = checked ? [...new Set(pageState.accountStatsSelectedUsers.concat(visible))] : pageState.accountStatsSelectedUsers.filter(v => !visible.includes(v)); renderAccountStatsUserPicker(); }
function setAccountStatsView(view) {
  const canViewAll = pageState.currentUser && pageState.currentUser.role === 'superuser';
  pageState.accountStatsView = view === 'all' && canViewAll ? 'all' : 'mine';
  const input = document.getElementById('accountStatsUsername');
  const mine = pageState.accountStatsView === 'mine';
  document.getElementById('accountStatsUsernamePicker').classList.toggle('hidden', mine);
  document.getElementById('accountStatsCurrentScopeNote').classList.toggle('hidden', !mine);
  if (mine) document.getElementById('accountStatsUsernamePicker').removeAttribute('open');
  updateAccountStatsUserSummary();
  loadAccountStats();
}
async function loadAccountStats() {
  try {
    const params = new URLSearchParams({category: 'account', chart_bucket: document.getElementById('accountStatsBucket').value, timezone_offset_minutes: String(localTimezoneOffsetMinutes())});
    const username = pageState.accountStatsView === 'mine' && pageState.currentUser ? pageState.currentUser.username : pageState.accountStatsSelectedUsers.join(',');
    const action = document.getElementById('accountStatsAction').value.trim();
    if (username) params.set('username', username);
    if (action) params.set('action', action);
    const data = await api('/v1/editor/usage-stats?' + params.toString());
    const stats = data.filtered?.stats || {};
    SraAuditTools.renderSummaryCards(document.getElementById('accountStatsCards'), [
      {label: '帳號操作數', value: stats.total_events || 0, hint: data.filtered?.is_restricted_to_self ? '限定自己' : '目前篩選'},
      {label: '動作種類', value: Object.keys(stats.by_action || {}).length, hint: 'auth.*'},
      {label: '使用者數', value: Object.keys(stats.by_user || {}).length, hint: '依目前篩選'},
      {label: 'IP 數', value: Object.keys(stats.by_client_host || {}).length, hint: 'client_host'},
    ]);
    SraAuditTools.renderTimeSeriesChart({
      rows: data.filtered?.series || [],
      bucket: data.filtered?.chart_bucket || document.getElementById('accountStatsBucket').value,
      bucketLabel: data.filtered?.chart_bucket_label || '每日',
      titleEl: document.getElementById('accountStatsTitle'),
      summaryEl: document.getElementById('accountStatsSummary'),
      chartEl: document.getElementById('accountStatsChart'),
      seriesName: '帳號操作筆數',
    });
    out(data.filtered || data);
  } catch (err) { out(String(err.message || err)); }
}
