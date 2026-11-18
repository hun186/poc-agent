/* Reuse SRAF Editor's existing login/session; no second identity store or cookie. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const SESSION_KEY = 'sra_editor_token';
  let generation = 0;
  let loginBusy = false;

  function status(text) { $('reportAuthStatus').textContent = text; }
  function storedToken() {
    try { return window.localStorage.getItem(SESSION_KEY) || ''; }
    catch (_) { return ''; }
  }
  function storeToken(value) {
    try {
      if (value) window.localStorage.setItem(SESSION_KEY, value);
      else window.localStorage.removeItem(SESSION_KEY);
      return true;
    } catch (_) { return false; }
  }
  function clearStoredIfSame(oldToken) {
    if (storedToken() === oldToken) storeToken('');
  }
  function setCredential(value) {
    const input = $('authToken');
    if (input.value === value) return;
    input.value = value;
    // Reuse the Report Job UI's existing owner-change fence: clear history,
    // abort in-flight reads/downloads, and discard pending ambiguous POSTs.
    input.dispatchEvent(new Event('input'));
  }
  function signedOut(message) {
    setCredential('');
    $('reportAuthUser').textContent = '';
    $('reportLogoutBtn').hidden = true;
    $('reportLoginBtn').hidden = false;
    status(message || '請使用既有 SRAF 帳號登入。');
  }
  function signedIn(value, user) {
    if (!user || typeof user.username !== 'string' || !user.username ||
        typeof value !== 'string' || !value || value.length > 4096) {
      throw new Error('invalid_login_contract');
    }
    setCredential(value);
    $('reportAuthUser').textContent = '已登入：' + user.username;
    $('reportLogoutBtn').hidden = false;
    $('reportLoginBtn').hidden = true;
    $('reportAuthPassword').value = '';
    status('已使用 SRAF 統一帳號登入；只能查看您有權限的報告。');
    // Reuse the existing owner-scoped GET /v1/report/jobs, never POST.
    $('listJobsBtn').click();
  }
  function opts(token) {
    return {
      method: 'GET',
      headers: {'Authorization': 'Bearer ' + token},
      credentials: 'omit', cache: 'no-store', redirect: 'error'
    };
  }
  async function restore(token, run) {
    if (!token || token.length > 4096) return signedOut('請使用既有 SRAF 帳號登入。');
    status('正在確認既有 SRAF 登入狀態…');
    try {
      const response = await fetch('/v1/auth/me', opts(token));
      if (run !== generation) return;
      if (!response.ok) throw new Error('session_expired');
      const data = await response.json();
      if (run !== generation) return;
      if (!data || !data.user || typeof data.user.username !== 'string') {
        throw new Error('session_invalid');
      }
      signedIn(token, data.user);
    } catch (_) {
      if (run !== generation) return;
      // Network failure is not proof of invalidation. Never claim ownership
      // or send authorized report requests without successful /auth/me.
      signedOut('無法驗證目前登入狀態；請重新登入。');
      // Only discard the shared token for a definite 401/403 response.
      // Avoid overwriting a concurrent login from another SRAF tab.
    }
  }

  async function login() {
    if (loginBusy) return;
    const username = $('reportAuthUsername').value.trim();
    const password = $('reportAuthPassword').value;
    if (!username || !password) {
      status('請輸入 SRAF 帳號與密碼。');
      return;
    }
    const run = ++generation;
    loginBusy = true;
    $('reportLoginBtn').disabled = true;
    signedOut('正在使用 SRAF 原有帳號登入…');
    // Switching principals must stop all previous owner-scoped operations
    // before the new credential is obtained.
    try {
      const response = await fetch('/v1/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username, password}),
        credentials: 'omit', cache: 'no-store', redirect: 'error'
      });
      if (run !== generation) return;
      if (!response.ok) {
        status(response.status === 429
          ? '登入嘗試次數過多，請稍後再試。'
          : '登入失敗，請確認 SRAF 帳號已啟用且密碼正確。');
        return;
      }
      const data = await response.json();
      if (run !== generation) return;
      if (!data || !data.user || !data.access_token ||
          data.user.username !== username) throw new Error('invalid_login_contract');
      signedIn(data.access_token, data.user);
      if (!storeToken(data.access_token)) {
        status('已登入此頁；瀏覽器未允許共用登入狀態，返回管理頁可能需要重新登入。');
      }
    } catch (_) {
      if (run === generation) signedOut('登入無法完成；請檢查連線後重試。');
    } finally {
      $('reportAuthPassword').value = '';
      loginBusy = false;
      $('reportLoginBtn').disabled = false;
    }
  }

  async function logout() {
    const oldToken = $('authToken').value;
    const run = ++generation;
    signedOut('已退出報告頁面，正在登出 SRAF…');
    clearStoredIfSame(oldToken);
    $('reportAuthPassword').value = '';
    if (!oldToken) {
      status('已登出。');
      return;
    }
    try {
      const response = await fetch('/v1/auth/logout', {
        method: 'POST',
        headers: {'Authorization': 'Bearer ' + oldToken},
        credentials: 'omit', cache: 'no-store', redirect: 'error'
      });
      if (run === generation) {
        status(response.ok ? '已登出 SRAF。' :
          '已清除本機登入狀態，但無法確認伺服器已撤銷憑證。');
      }
    } catch (_) {
      if (run === generation) {
        status('已清除本機登入狀態，但無法確認伺服器已撤銷憑證。');
      }
    }
  }

  $('reportLoginBtn').addEventListener('click', login);
  $('reportAuthPassword').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); login(); }
  });
  $('reportLogoutBtn').addEventListener('click', logout);
  window.addEventListener('storage', (event) => {
    if (event.key !== SESSION_KEY) return;
    const run = ++generation;
    signedOut('SRAF 登入身分已變更，正在重新確認…');
    if (typeof event.newValue === 'string' && event.newValue) {
      restore(event.newValue, run);
    } else status('已從另一個 SRAF 頁面登出。');
  });
  window.addEventListener('pagehide', () => {
    ++generation;
    $('reportAuthPassword').value = '';
  });

  const existing = storedToken();
  if (existing) restore(existing, ++generation);
  else signedOut('請使用原本 SRAF 帳號與密碼登入；無須手動貼 Token。');
})();
