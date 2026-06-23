async function login() {
  try {
    const data = await api('/v1/auth/login', {method: 'POST', body: JSON.stringify(payload())});
    localStorage.setItem(tokenKey, data.access_token);
    updateCurrentUser(data.user || null);
    out(data);
  } catch (err) { out(String(err.message || err)); }
}
async function vercelPreviewLogin() {
  try {
    const options = {method: 'POST'};
    if (window.portableVercelPreviewSecretRequired) {
      const secret = window.prompt('請輸入 Vercel mock preview login secret');
      if (!secret) return out('已取消 Vercel mock preview 登入');
      options.headers = {'X-Auth-Preview-Login-Secret': secret};
    }
    const data = await api('/v1/auth/vercel-preview-login', options);
    localStorage.setItem(tokenKey, data.access_token);
    updateCurrentUser(data.user || null);
    out(data);
  } catch (err) { out(String(err.message || err)); }
}
async function setupVercelPreviewLogin() {
  const btn = document.getElementById('vercelPreviewLoginBtn');
  const hint = document.getElementById('vercelPreviewLoginHint');
  if (!btn || !hint) return;
  try {
    const data = await api('/v1/auth/vercel-preview-login-enabled');
    window.portableVercelPreviewSecretRequired = Boolean(data.secret_required);
    if (data.enabled) {
      btn.classList.remove('hidden');
      hint.classList.remove('hidden');
      if (data.secret_required) hint.textContent = 'Vercel mock preview 需要輸入 preview login secret，且只供 portable auth pack 預覽流程。';
    }
  } catch (err) {
    btn.classList.add('hidden');
    hint.classList.add('hidden');
  }
}

async function registerUser() {
  try { out(await api('/v1/auth/register', {method: 'POST', body: JSON.stringify(payload())})); }
  catch (err) { out(String(err.message || err)); }
}
async function me() {
  try { const data = await api('/v1/auth/me'); updateCurrentUser(data.user || null); out(data); }
  catch (err) { out(String(err.message || err)); }
}
async function logout() {
  try { out(await api('/v1/auth/logout', {method: 'POST'})); }
  catch (err) { out(String(err.message || err)); }
  finally { localStorage.removeItem(tokenKey); }
}
async function changePassword() {
  try {
    out(await api('/v1/auth/change-password', {method: 'POST', body: JSON.stringify({
      current_password: document.getElementById('currentPassword').value,
      new_password: document.getElementById('newPassword').value,
    })}));
  } catch (err) { out(String(err.message || err)); }
}
async function forgotPassword() {
  try { out(await api('/v1/auth/forgot-password', {method: 'POST', body: JSON.stringify({username: document.getElementById('username').value})})); }
  catch (err) { out(String(err.message || err)); }
}
async function recoverPassword() {
  try {
    out(await api('/v1/auth/reset-password', {method: 'POST', body: JSON.stringify({
      username: document.getElementById('username').value,
      reset_token: document.getElementById('resetToken').value,
      new_password: document.getElementById('newPassword').value,
    })}));
  } catch (err) { out(String(err.message || err)); }
}
