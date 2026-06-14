function setAccountStatsUserOptions(values) { pageState.accountStatsUserOptions = SraAuditTools.uniqueSortedValues(values); if (pageState.currentUser && !pageState.accountStatsUserOptions.includes(pageState.currentUser.username)) pageState.accountStatsUserOptions.unshift(pageState.currentUser.username); pageState.accountStatsSelectedUsers = pageState.accountStatsSelectedUsers.filter(v => pageState.accountStatsUserOptions.includes(v)); renderAccountStatsUserPicker(); }
function setAccountStatsClientHostOptions(values) { pageState.accountStatsClientHostOptions = SraAuditTools.uniqueSortedValues(values); renderAccountStatsClientHostPicker(); }
function renderAccountStatsPicker(config) { SraAuditTools.renderMultiFilterOptions({values: config.values, selectedValues: config.selected, getSelectedValues: config.getSelected, searchEl: document.getElementById(config.searchId), optionsEl: document.getElementById(config.optionsId), dataAttr: config.dataAttr, emptyText: config.emptyText, onSelectionChange: config.onChange}); SraAuditTools.summarizeMultiFilterSelection({selectedValues: config.selected, hiddenInput: document.getElementById(config.hiddenId), summaryEl: document.getElementById(config.summaryId), allLabel: config.allLabel, unitLabel: config.unitLabel}); }
function renderAccountStatsUserPicker() { renderAccountStatsPicker({values: pageState.accountStatsUserOptions, selected: pageState.accountStatsSelectedUsers, getSelected: () => pageState.accountStatsSelectedUsers, searchId: 'accountStatsUsernameSearch', optionsId: 'accountStatsUsernameOptions', hiddenId: 'accountStatsUsername', summaryId: 'accountStatsUsernameSummary', dataAttr: 'data-account-stats-user', emptyText: '沒有符合關鍵字的帳號。', allLabel: '全體帳號', unitLabel: '個帳號', onChange: values => { pageState.accountStatsSelectedUsers = values; updateAccountStatsUserSummary(); renderAccountStatsUserPicker(); }}); updateAccountStatsUserSummary(); }
function renderAccountStatsClientHostPicker() { renderAccountStatsPicker({values: pageState.accountStatsClientHostOptions, selected: pageState.accountStatsSelectedClientHosts, getSelected: () => pageState.accountStatsSelectedClientHosts, searchId: 'accountStatsClientHostSearch', optionsId: 'accountStatsClientHostOptions', hiddenId: 'accountStatsClientHost', summaryId: 'accountStatsClientHostSummary', dataAttr: 'data-account-stats-client-host', emptyText: '沒有符合關鍵字的 IP。', allLabel: '全部 IP', unitLabel: '個 IP', onChange: values => { pageState.accountStatsSelectedClientHosts = values; renderAccountStatsClientHostPicker(); }}); }
function updateAccountStatsUserSummary() { const selected = pageState.accountStatsSelectedUsers; document.getElementById('accountStatsUsername').value = selected.join(','); const summary = document.getElementById('accountStatsUsernameSummary'); if (!summary) return; const note = document.getElementById('accountStatsCurrentScopeText'); if (pageState.accountStatsView === 'mine') { const text = pageState.currentUser ? `目前顯示個人帳號操作紀錄：${pageState.currentUser.username}` : '目前顯示個人帳號操作紀錄'; summary.textContent = text; if (note) note.textContent = text; } else SraAuditTools.summarizeMultiFilterSelection({selectedValues: selected, hiddenInput: document.getElementById('accountStatsUsername'), summaryEl: summary, allLabel: '全體帳號', unitLabel: '個帳號'}); }
function setVisibleAccountStatsUsers(checked) { pageState.accountStatsSelectedUsers = SraAuditTools.setVisibleMultiFilterSelection({values: pageState.accountStatsUserOptions, selectedValues: pageState.accountStatsSelectedUsers, searchEl: document.getElementById('accountStatsUsernameSearch'), checked}); renderAccountStatsUserPicker(); }
function setVisibleAccountStatsClientHosts(checked) { pageState.accountStatsSelectedClientHosts = SraAuditTools.setVisibleMultiFilterSelection({values: pageState.accountStatsClientHostOptions, selectedValues: pageState.accountStatsSelectedClientHosts, searchEl: document.getElementById('accountStatsClientHostSearch'), checked}); renderAccountStatsClientHostPicker(); }
function setAccountStatsView(view) {
  const canViewAll = pageState.currentUser && pageState.currentUser.role === 'superuser';
  pageState.accountStatsView = view === 'all' && canViewAll ? 'all' : 'mine';
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
    const clientHost = pageState.accountStatsSelectedClientHosts.join(',');
    if (username) params.set('username', username);
    if (action) params.set('action', action);
    if (clientHost) params.set('client_host', clientHost);
    const data = await api('/v1/editor/usage-stats?' + params.toString());
    const stats = data.filtered?.stats || {};
    setAccountStatsClientHostOptions(Object.keys(stats.by_client_host || {}));
    SraAuditTools.renderSummaryCards(document.getElementById('accountStatsCards'), [
      {label: '帳號操作數', value: stats.total_events || 0, hint: data.filtered?.is_restricted_to_self ? '限定自己' : '目前篩選'},
      {label: '動作種類', value: Object.keys(stats.by_action || {}).length, hint: 'auth.*'},
      {label: '使用者數', value: Object.keys(stats.by_user || {}).length, hint: '依目前篩選'},
      {label: 'IP 數', value: Object.keys(stats.by_client_host || {}).length, hint: 'client_host'},
    ]);
    SraAuditTools.renderTimeSeriesChart({
      rows: data.filtered?.series || [], bucket: data.filtered?.chart_bucket || document.getElementById('accountStatsBucket').value, bucketLabel: data.filtered?.chart_bucket_label || '每日', titleEl: document.getElementById('accountStatsTitle'), summaryEl: document.getElementById('accountStatsSummary'), chartEl: document.getElementById('accountStatsChart'), seriesName: '帳號操作筆數',
    });
    out(data.filtered || data);
  } catch (err) { out(String(err.message || err)); }
}
