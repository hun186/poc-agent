document.getElementById('accountStatsUsernameSearch').oninput = renderAccountStatsUserPicker;
document.getElementById('accountStatsSelectVisibleUsersBtn').onclick = () => setVisibleAccountStatsUsers(true);
document.getElementById('accountStatsClearVisibleUsersBtn').onclick = () => setVisibleAccountStatsUsers(false);
document.getElementById('accountStatsClearAllUsersBtn').onclick = () => { pageState.accountStatsSelectedUsers = []; renderAccountStatsUserPicker(); };
bindPagerActions('users', () => pageState.usersPage, (page) => { pageState.usersPage = page; }, renderUsersPage);
bindPagerActions('loginAudit', () => pageState.loginAuditPage, (page) => { pageState.loginAuditPage = page; }, renderLoginAuditPage);
document.getElementById('copyResetTokenBtn').onclick = async () => {
  try {
    await copyTextToClipboard(document.getElementById('resetTokenModalValue').value);
    document.getElementById('resetTokenCopyStatus').textContent = '已複製 token。';
  } catch (err) {
    document.getElementById('resetTokenCopyStatus').textContent = String(err.message || err);
  }
};
document.getElementById('closeResetTokenModalBtn').onclick = closeResetTokenDialog;
document.getElementById('resetTokenModal').onclick = (ev) => { if (ev.target === document.getElementById('resetTokenModal')) closeResetTokenDialog(); };
