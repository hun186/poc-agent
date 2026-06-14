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
    pageState.usersRows = (data.users || []).slice().sort((a, b) => String(a.username || '').localeCompare(String(b.username || '')));
    pageState.usersRoleOptions = roleOptions;
    setAccountStatsUserOptions((data.users || []).map(u => u.username));
    pageState.usersPage = 1;
    renderUsersPage();
    out(data);
  } catch (err) { out(String(err.message || err)); }
}
function renderUsersPage() {
  const roleOptions = pageState.usersRoleOptions || [];
  const page = updatePager(pageState.usersRows, pageState.usersPage, 'usersPageInfo', 'usersPrevBtn', 'usersNextBtn');
  pageState.usersPage = page.page;
  document.getElementById('users').innerHTML = page.rows.map(u => `<div class="user"><strong>${esc(u.username)}</strong> status=${esc(u.status)} role=${esc(u.role)} <select data-role-select="${esc(u.username)}">${roleOptionsHtml(u.role, roleOptions)}</select> <button onclick="approveSelectedUser('${esc(u.username)}')">核准 / 更新層級</button><button class="secondary" onclick="issuePasswordResetToken('${esc(u.username)}')">產生 reset token</button><button class="danger" title="pending 帳號會被拒絕申請；active 帳號會被停權並讓既有 token 失效。" onclick="rejectUser('${esc(u.username)}')">拒絕申請／停權</button><button class="danger" onclick="resetUserPassword('${esc(u.username)}')">直接重設密碼</button><button class="danger" onclick="deleteUser('${esc(u.username)}')">刪除</button></div>`).join('') || '<p class="muted">尚無帳號。</p>';
}
async function approveSelectedUser(username) {
  const select = Array.from(document.querySelectorAll('[data-role-select]')).find(el => el.dataset.roleSelect === username);
  await approveUser(username, select ? select.value : 'data_reader');
}
async function approveUser(username, role) { out(await api(`/v1/auth/users/${encodeURIComponent(username)}/approve`, {method: 'POST', body: JSON.stringify({role})})); await refreshUsers(); }
async function rejectUser(username) { out(await api(`/v1/auth/users/${encodeURIComponent(username)}/reject`, {method: 'POST'})); await refreshUsers(); }
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
  document.getElementById('resetTokenModalHelp').textContent = `請用安全管道交付給 ${username}。token 只會顯示這一次，請直接複製保存。`;
  document.getElementById('resetTokenModalValue').value = token || '';
  document.getElementById('resetTokenCopyStatus').textContent = '';
  document.getElementById('resetTokenModal').classList.remove('hidden');
  document.getElementById('resetTokenModalValue').focus();
  document.getElementById('resetTokenModalValue').select();
}
function closeResetTokenDialog() { document.getElementById('resetTokenModal').classList.add('hidden'); }
async function issuePasswordResetToken(username) {
  const data = await api(`/v1/auth/users/${encodeURIComponent(username)}/password-reset-token`, {method: 'POST'});
  out(data);
  showResetTokenDialog(username, data.reset_token);
}
async function resetUserPassword(username) {
  const new_password = prompt(`請輸入 ${username} 的新密碼（至少 8 字元）`);
  if (!new_password) return;
  out(await api(`/v1/auth/users/${encodeURIComponent(username)}/reset-password`, {method: 'POST', body: JSON.stringify({new_password})}));
  await refreshUsers();
}
async function deleteUser(username) { out(await api(`/v1/auth/users/${encodeURIComponent(username)}`, {method: 'DELETE'})); await refreshUsers(); }
bindMultiFilterOutsideDismiss('accountStatsUsernamePicker');
bindMultiFilterOutsideDismiss('accountStatsClientHostPicker');
