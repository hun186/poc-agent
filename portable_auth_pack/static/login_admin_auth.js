function loginInputHints(username, password) {
  const hints = [];
  if (/[^\x00-\x7F]/.test(username)) hints.push('帳號含有非半形英文/數字字元，請確認是否切到中文或全形輸入。');
  if (/[\uFF01-\uFF5E]/.test(password)) hints.push('密碼含全形字元，請確認英數與符號是否為半形。');
  if (/[\u4E00-\u9FFF]/.test(password)) hints.push('密碼含中文，請確認目前輸入法是否正確。');
  if (password !== password.trim()) hints.push('密碼前後有空白；如果不是刻意設定，請刪除空白後再試。');
  return hints;
}
function loginFailureHintMessage(baseMessage, username, password) {
  const hints = loginInputHints(username, password);
  if (!hints.length) return baseMessage;
  return `${baseMessage}\n提醒：${hints.join(' ')}`;
}
async function login() {
  const body = payload();
  const hints = loginInputHints(body.username, body.password);
  if (hints.length) out(`登入中...提醒：${hints.join(' ')}`);
  try {
    const data = await api('/v1/auth/login', {method: 'POST', body: JSON.stringify(body)});
    localStorage.setItem(tokenKey, data.access_token);
    updateCurrentUser(data.user || null);
    out(data);
  } catch (err) { out(loginFailureHintMessage(String(err.message || err), body.username, body.password)); }
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

function setupLoginInputGuards() {
  const password = document.getElementById('password');
  if (!password) return;
  password.addEventListener('keyup', event => {
    if (event.getModifierState && event.getModifierState('CapsLock')) {
      out('提醒：Caps Lock 目前開啟，密碼大小寫可能輸錯。');
    }
  });
}
setupLoginInputGuards();
