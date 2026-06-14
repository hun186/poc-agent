async function login() {
  try {
    const data = await api('/v1/auth/login', {method: 'POST', body: JSON.stringify(payload())});
    localStorage.setItem(tokenKey, data.access_token);
    updateCurrentUser(data.user || null);
    out(data);
  } catch (err) { out(String(err.message || err)); }
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
