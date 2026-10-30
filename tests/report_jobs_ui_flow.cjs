'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'sra_api', 'static', 'report_jobs_ui.js'), 'utf8');
const ids = ['authToken','prompt','filename','jobId','watchBtn','stopBtn','submitBtn','downloadBtn',
  'progressCard','message','phaseTitle','jobStatus','phaseElapsed','observation','lastChecked','failureMessage'];
const elements = Object.fromEntries(ids.map(id => [id, {
  value: '', hidden: false, disabled: false, textContent: '', className: '', handlers: {},
  addEventListener(kind, fn) { this.handlers[kind] = fn; }
}]));
const events = {};
const calls = [];
const planned = [];
const timers = new Map();
let nextTimer = 0;
let downloadClicks = 0;
function response(status, body) {
  return {status, ok: status >= 200 && status < 300,
    json: async () => body, blob: async () => ({size: 10})};
}
const document = {
  hidden: false,
  getElementById: (id) => elements[id],
  addEventListener: (kind, fn) => { events[kind] = fn; },
  body: {appendChild() {}},
  createElement() { return {style: {}, click() { downloadClicks++; }, remove() {}}; }
};
const window = {addEventListener: (kind, fn) => { events[kind] = fn; }};
const sandbox = {
  document, window, AbortController, console,
  fetch: async (url, opts) => {
    calls.push({url, opts});
    assert.equal(opts.credentials, 'omit');
    assert.equal(opts.cache, 'no-store');
    assert.equal(opts.redirect, 'error');
    const next = planned.shift();
    assert.ok(next, 'unexpected network request');
    return next;
  },
  setTimeout: (fn, delay) => { timers.set(++nextTimer, {fn, delay}); return nextTimer; },
  clearTimeout: (key) => { timers.delete(key); },
  URL: {createObjectURL() { return 'blob:test'; }, revokeObjectURL() {}}
};
vm.runInNewContext(source, sandbox, {filename: 'report_jobs_ui.js'});
const tick = async () => new Promise(resolve => setImmediate(resolve));
function fire(id, kind='click') { return elements[id].handlers[kind](); }
function progress(jobId, status, phase, long=false) {
  return {job_id: jobId, status, progress: {
    phase, elapsed_seconds: long ? 45 : 1, long_running: long,
    observation: status === 'completed' || status === 'failed' ? 'terminal' : long ? 'long_running' : 'active',
    failure_category: status === 'failed' ? 'timeout' : null
  }};
}
(async () => {
  elements.authToken.value = 'secret';
  elements.jobId.value = 'job-A';
  planned.push(response(200, progress('job-A','running','agent_execution',true)));
  fire('watchBtn');
  await tick();
  assert.match(elements.phaseTitle.textContent, /Agent/);
  assert.match(elements.message.textContent, /不能據此判定/);
  assert.equal(elements.downloadBtn.hidden, true);
  assert.equal(timers.size, 1);
  const [key, scheduled] = [...timers][0];
  assert.equal(scheduled.delay, 3000);
  timers.delete(key);
  planned.push(response(200, progress('job-A','completed','completed')));
  scheduled.fn();
  await tick();
  assert.equal(elements.downloadBtn.hidden, false);
  assert.equal(timers.size, 0);
  planned.push(response(200, null));
  await fire('downloadBtn');
  assert.equal(downloadClicks, 1);
  assert.equal(calls.at(-1).url, '/v1/report/jobs/job-A/word');
  assert.equal(calls.at(-1).opts.headers.Authorization, 'Bearer secret');
  // The only timer after a download is a local blob URL revocation.
  timers.clear();
  elements.jobId.value = 'job-B';
  planned.push(response(404, {detail: 'SECRET-SERVER-ERROR'}));
  fire('watchBtn');
  await tick();
  assert.match(elements.message.textContent, /找不到任務/);
  assert.doesNotMatch(elements.message.textContent, /SECRET/);
  assert.equal(elements.stopBtn.disabled, true);
  assert.equal(elements.downloadBtn.hidden, true);
  assert.equal(timers.size, 0);

  elements.prompt.value = 'PRIVATE PROMPT';
  elements.filename.value = 'test.docx';
  planned.push(response(202, {job_id: 'job-C', status:'queued'}));
  planned.push(response(200, progress('job-C','queued','queued')));
  await fire('submitBtn');
  await tick();
  assert.equal(calls.at(-2).url, '/v1/report/jobs');
  assert.equal(JSON.parse(calls.at(-2).opts.body).prompt, 'PRIVATE PROMPT');
  assert.equal(elements.prompt.value, '');
  assert.equal(elements.jobId.value, 'job-C');
  assert.match(elements.phaseTitle.textContent, /等待/);
  fire('stopBtn');
  assert.match(elements.message.textContent, /不會被取消/);
  assert.equal(timers.size, 0);

  elements.jobId.value = 'job-D';
  planned.push(response(200, progress('job-D','failed','failed')));
  fire('watchBtn');
  await tick();
  assert.match(elements.failureMessage.textContent, /逾時/);
  assert.equal(elements.downloadBtn.hidden, true);
  assert.equal(timers.size, 0);

  elements.jobId.value = 'job-E';
  planned.push(response(200, progress('job-E','running','docx_export')));
  fire('watchBtn');
  await tick();
  assert.equal(timers.size, 1);
  elements.authToken.value = 'new-secret';
  fire('authToken','input');
  assert.equal(timers.size, 0);
  assert.equal(elements.stopBtn.disabled, true);
  assert.equal(elements.downloadBtn.hidden, true);
  console.log('Report Job UI behavior PASS: owner-scope headers, live phases, terminal stops, errors, download and token change');
})().catch(err => { console.error(err); process.exitCode = 1; });
