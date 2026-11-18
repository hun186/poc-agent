'use strict';
// Offline browser contract: shared SRAF login (same /v1/auth/login and editor storage).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(
  __dirname, '..', 'sra_api', 'static', 'report_jobs_auth.js'
), 'utf8');

function harness(initialToken = '') {
  const handlers = {};
  const calls = [];
  const expected = [];
  const store = new Map(initialToken ? [['sra_editor_token', initialToken]] : []);
  let ownerChanges = 0;
  let historyLoads = 0;
  const ids = ['authToken', 'reportAuthUsername', 'reportAuthPassword',
    'reportAuthUser', 'reportAuthStatus', 'reportLoginBtn', 'reportLogoutBtn', 'listJobsBtn'];
  const controls = Object.fromEntries(ids.map(id => [id, {
    value: '', textContent: '', hidden: false, disabled: false, events: {},
    addEventListener(name, fn) { this.events[name] = fn; },
    dispatchEvent(e) { if (id === 'authToken') ownerChanges++; this.events[e.type]?.(e); },
    click() { if (id === 'listJobsBtn') historyLoads++; else return this.events.click?.(); }
  }]));
  const window = {
    localStorage: {
      getItem(k) { return store.get(k) ?? null; },
      setItem(k, v) { store.set(k, v); },
      removeItem(k) { store.delete(k); }
    },
    addEventListener(k, fn) { handlers[k] = fn; }
  };
  vm.runInNewContext(source, {
    window, document: {getElementById(id) { return controls[id]; }},
    Event: class { constructor(type) { this.type = type; } },
    fetch: async (url, opts) => {
      calls.push({url, opts});
      assert.equal(opts.credentials, 'omit');
      assert.equal(opts.cache, 'no-store');
      assert.equal(opts.redirect, 'error');
      const next = expected.shift();
      assert.ok(next, 'unexpected request ' + url);
      assert.equal(url, next.url);
      return next.response;
    }
  }, {filename: 'report_jobs_auth.js'});
  return {
    controls, calls, handlers, store, expected,
    get ownerChanges() { return ownerChanges; },
    get historyLoads() { return historyLoads; },
    response(url, status, body) {
      expected.push({url, response: {
        status, ok: status >= 200 && status < 300, json: async () => body
      }});
    }
  };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  // Direct /report-jobs access: use existing SRAF username + password, not a pasted token.
  const a = harness();
  assert.equal(a.calls.length, 0);
  assert.match(a.controls.reportAuthStatus.textContent, /SRAF.*帳號/);
  a.controls.reportAuthUsername.value = 'aiuser';
  a.controls.reportAuthPassword.value = 'PRIVATE_SECRET';
  a.response('/v1/auth/login', 200, {
    access_token: 'PRIVATE_LOGIN_TOKEN', user: {username: 'aiuser'}
  });
  await a.controls.reportLoginBtn.events.click();
  assert.equal(a.calls[0].opts.method, 'POST');
  assert.equal(JSON.parse(a.calls[0].opts.body).username, 'aiuser');
  assert.equal(JSON.parse(a.calls[0].opts.body).password, 'PRIVATE_SECRET');
  assert.equal(a.controls.reportAuthPassword.value, '');
  assert.equal(a.store.get('sra_editor_token'), 'PRIVATE_LOGIN_TOKEN');
  assert.equal(a.controls.authToken.value, 'PRIVATE_LOGIN_TOKEN');
  assert.equal(a.historyLoads, 1, 'login reads existing owner-scoped history');
  assert.ok(a.ownerChanges >= 1, 'owner change propagated to report state fence');
  assert.doesNotMatch(a.controls.reportAuthStatus.textContent, /PRIVATE_LOGIN_TOKEN|PRIVATE_SECRET/);

  // An Editor tab logout revokes the UI's current token immediately.
  a.handlers.storage({key: 'sra_editor_token', newValue: null});
  assert.equal(a.controls.authToken.value, '');
  assert.equal(a.controls.reportLogoutBtn.hidden, true);
  assert.ok(a.ownerChanges >= 2, 'old owner state invalidated on shared logout');

  // Another SRAF tab logging in is validated by the canonical /v1/auth/me first.
  a.store.set('sra_editor_token', 'PRIVATE_SECOND_OWNER');
  a.response('/v1/auth/me', 200, {user: {username: 'second'}});
  a.handlers.storage({key: 'sra_editor_token', newValue: 'PRIVATE_SECOND_OWNER'});
  await tick();
  assert.equal(a.controls.authToken.value, 'PRIVATE_SECOND_OWNER');
  assert.equal(a.controls.reportAuthUser.textContent, '已登入：second');
  assert.equal(a.historyLoads, 2);
  a.response('/v1/auth/logout', 200, {message: 'ok'});
  await a.controls.reportLogoutBtn.events.click();
  assert.equal(a.controls.authToken.value, '');
  assert.equal(a.store.has('sra_editor_token'), false);
  assert.equal(a.calls.at(-1).opts.headers.Authorization, 'Bearer PRIVATE_SECOND_OWNER');

  // An already signed-in Editor user enters via port 9002/report-jobs without login.
  const b = (() => {
    const c = harness('PRIVATE_EDITOR_TOKEN');
    // Initial auth/me may be requested before the expectation is registered:
    // isolate it in a deferred request by checking microtask execution.
    return c;
  })();
  b.response('/v1/auth/me', 200, {user: {username: 'editor'}});
  await tick();
  assert.equal(b.calls[0].url, '/v1/auth/me');
  assert.equal(b.controls.authToken.value, 'PRIVATE_EDITOR_TOKEN');
  assert.equal(b.historyLoads, 1);

  // Expired Editor session cannot be used to read the old owner's report.
  b.response('/v1/auth/me', 401, {});
  b.handlers.storage({key: 'sra_editor_token', newValue: 'PRIVATE_EXPIRED'});
  b.store.set('sra_editor_token', 'PRIVATE_EXPIRED');
  await tick();
  assert.equal(b.controls.authToken.value, '');
  assert.equal(b.historyLoads, 1, 'no owner history read after 401');
  assert.equal(b.store.has('sra_editor_token'), false);

  // Failed login never issues a report request or saves a token.
  const c = harness();
  c.controls.reportAuthUsername.value = 'aiuser';
  c.controls.reportAuthPassword.value = 'bad';
  c.response('/v1/auth/login', 401, {detail: 'PRIVATE_SERVER_MESSAGE'});
  await c.controls.reportLoginBtn.events.click();
  assert.equal(c.controls.authToken.value, '');
  assert.equal(c.historyLoads, 0);
  assert.doesNotMatch(c.controls.reportAuthStatus.textContent, /PRIVATE_SERVER_MESSAGE/);
  assert.equal(c.controls.reportAuthPassword.value, '');
  console.log('Report Job SRAF shared account login: PASS');
})().catch(err => { console.error(err); process.exitCode = 1; });
