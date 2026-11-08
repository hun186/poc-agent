'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'sra_api', 'static', 'report_jobs_ui.js'), 'utf8');
const ids = ['authToken','prompt','filename','jobId','watchBtn','stopBtn','submitBtn','downloadBtn',
  'progressCard','message','phaseTitle','jobStatus','phaseElapsed','observation','lastChecked','failureMessage',
  'retrySubmitBtn','discardSubmitBtn','listJobsBtn','jobListMessage','jobRows','jobPrev','jobNext','jobPage'];
const elements = Object.fromEntries(ids.map(id => [id, {
  value: '', hidden: false, disabled: false, textContent: '', className: '', handlers: {}, children: [],
  addEventListener(kind, fn) { this.handlers[kind] = fn; },
  appendChild(child) { this.children.push(child); },
  replaceChildren(...xs) { this.children = xs; }
}]));
const events = {};
const calls = [];
const planned = [];
const timers = new Map();
let nextTimer = 0;
let downloadClicks = 0;
const downloadedNames = [];
function response(status, body, disposition = null) {
  return {status, ok: status >= 200 && status < 300,
    headers: {get: (key) => key.toLowerCase() === 'content-disposition' ? disposition : null},
    json: async () => body, blob: async () => ({size: 10})};
}
const document = {
  hidden: false,
  getElementById: (id) => elements[id],
  addEventListener: (kind, fn) => { events[kind] = fn; },
  body: {appendChild() {}},
  createElement(tag) { return {
    tag, style: {}, children: [], textContent: '', handlers: {}, disabled: false,
    addEventListener(kind, fn) { this.handlers[kind] = fn; },
    appendChild(child) { this.children.push(child); },
    replaceChildren(...xs) { this.children = xs; },
    click() { downloadClicks++; downloadedNames.push(this.download); },
    remove() {}
  }; }
};
let uuidCounter = 0;
const window = {
  addEventListener: (kind, fn) => { events[kind] = fn; },
  crypto: {randomUUID() {uuidCounter++; return '00000000-0000-4000-8000-' + String(uuidCounter).padStart(12,'0');}}
};
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
  planned.push(response(200, null, 'attachment; filename="requested-report.docx"'));
  await fire('downloadBtn');
  assert.equal(downloadClicks, 1);
  assert.equal(downloadedNames.at(-1), 'requested-report.docx');
  assert.equal(calls.at(-1).url, '/v1/report/jobs/job-A/word');
  assert.equal(calls.at(-1).opts.headers.Authorization, 'Bearer secret');
  planned.push(response(200, null, "attachment; filename*=utf-8''" + encodeURIComponent('資料分析.docx')));
  await fire('downloadBtn');
  assert.equal(downloadedNames.at(-1), '資料分析.docx');
  // Unsafe, malformed or missing filename must not be a path on the user's machine.
  planned.push(response(200, null, 'attachment; filename="../../evil.docx"'));
  await fire('downloadBtn');
  assert.equal(downloadedNames.at(-1), 'report-job-A.docx');
  planned.push(response(200, null, "attachment; filename*=utf-8''%invalid"));
  await fire('downloadBtn');
  assert.equal(downloadedNames.at(-1), 'report-job-A.docx');
  planned.push(response(200, null));
  await fire('downloadBtn');
  assert.equal(downloadedNames.at(-1), 'report-job-A.docx');
  // A DOCX fetch accepted under the old bearer must not download after a
  // principal switch, even if response.blob() completes after AbortController.abort().
  let releaseBlob;
  const delayedDownload = response(200, null, 'attachment; filename="prior-owner.docx"');
  delayedDownload.blob = () => new Promise(resolve => { releaseBlob = resolve; });
  const clicksBeforeChange = downloadClicks;
  planned.push(delayedDownload);
  const pendingDownload = fire('downloadBtn');
  await tick();
  assert.equal(typeof releaseBlob, 'function');
  const signalForOldOwner = calls.at(-1).opts.signal;
  assert.equal(signalForOldOwner.aborted, false);
  elements.authToken.value = 'another-owner-token';
  fire('authToken', 'input');
  assert.equal(signalForOldOwner.aborted, true);
  releaseBlob({size: 10});
  await pendingDownload;
  assert.equal(downloadClicks, clicksBeforeChange);
  assert.equal(elements.downloadBtn.hidden, true);
  elements.authToken.value = 'secret';
  fire('authToken', 'input');

  // The only timers after downloads are local blob URL revocations.
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
  assert.equal(calls.at(-2).opts.headers['Idempotency-Key'], 'sraf-report-00000000-0000-4000-8000-000000000001');
  assert.equal(elements.retrySubmitBtn.hidden, true);
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
  // A transport failure leaves an ambiguous POST result: no blind retry.
  elements.prompt.value = 'SECOND PRIVATE PROMPT';
  elements.filename.value = 'second.docx';
  planned.push(Promise.reject(new Error('connection dropped')));
  const beforeUnknown = calls.length;
  await fire('submitBtn');
  assert.equal(calls.length, beforeUnknown + 1);
  assert.equal(elements.retrySubmitBtn.hidden, false);
  assert.equal(elements.discardSubmitBtn.hidden, false);
  assert.equal(elements.submitBtn.disabled, true);
  assert.equal(elements.prompt.disabled, true);
  const firstAttempt = calls.at(-1);
  const firstKey = firstAttempt.opts.headers['Idempotency-Key'];
  assert.ok(firstKey.startsWith('sraf-report-'));
  assert.match(elements.message.textContent, /相同識別碼/);
  await fire('submitBtn');
  assert.equal(calls.length, beforeUnknown + 1, 'new unkeyed POST must be blocked while unresolved');
  // Reuse the ORIGINAL body and key even if page data was programmatically modified.
  elements.prompt.value = 'DO NOT SUBMIT NEW VALUE';
  planned.push(response(202, {job_id:'job-retry',status:'queued'}));
  planned.push(response(200, progress('job-retry','queued','queued')));
  await fire('retrySubmitBtn');
  await tick();
  const posts = calls.filter(c => c.url === '/v1/report/jobs');
  const last = posts.at(-1);
  assert.equal(last.opts.headers['Idempotency-Key'], firstKey);
  assert.equal(last.opts.body, firstAttempt.opts.body);
  assert.equal(elements.retrySubmitBtn.hidden, true);
  assert.equal(elements.submitBtn.disabled, false);
  assert.equal(elements.prompt.disabled, false);
  assert.equal(elements.jobId.value, 'job-retry');
  assert.match(elements.phaseTitle.textContent, /等待/);

  // Determinate HTTP 409 is not an ambiguous transport result: no retry.
  elements.prompt.value = 'THIRD PRIVATE PROMPT';
  planned.push(response(409,{detail:'never leak server error'}));
  await fire('submitBtn');
  assert.equal(elements.retrySubmitBtn.hidden, true);
  assert.doesNotMatch(elements.message.textContent, /never leak/);
  assert.match(elements.message.textContent, /識別碼衝突/);

  // Manual discard warns that the original request can still exist.
  elements.prompt.value = 'FOURTH PRIVATE PROMPT';
  planned.push(Promise.reject(new Error('network uncertain')));
  await fire('submitBtn');
  assert.equal(elements.retrySubmitBtn.hidden, false);
  fire('discardSubmitBtn');
  assert.equal(elements.retrySubmitBtn.hidden, true);
  assert.match(elements.message.textContent, /可能產生重複/);

  // Changing credentials invalidates any pending attempt and clear on pagehide.
  planned.push(Promise.reject(new Error('network uncertain')));
  await fire('submitBtn');
  assert.equal(elements.retrySubmitBtn.hidden, false);
  elements.authToken.value = 'switch-account';
  fire('authToken','input');
  assert.equal(elements.retrySubmitBtn.hidden, true);
  assert.equal(elements.submitBtn.disabled, false);
  events.pagehide();
  assert.equal(elements.authToken.value, '');

  // Explicit owner history GET displays only safe metadata, never extra fields.
  elements.authToken.value = 'secret';
  fire('authToken','input');
  planned.push(response(200, {items:[
    {job_id:'job-history-A',status:'completed',phase:'completed',
      created_at:'2026-11-08T10:00:00Z',filename:'secret.docx',prompt:'DO NOT SHOW'}
  ],limit:20,offset:0}));
  await fire('listJobsBtn');
  assert.equal(calls.at(-1).url,'/v1/report/jobs?limit=20&offset=0');
  assert.equal(calls.at(-1).opts.method,'GET');
  assert.equal(calls.at(-1).opts.headers.Authorization,'Bearer secret');
  assert.equal(elements.jobRows.children.length,1,
    'history status=' + elements.jobListMessage.textContent +
    ' pending=' + planned.length + ' last_url=' + calls.at(-1).url);
  assert.equal(elements.jobRows.children[0].children[0].textContent,'job-history-A');
  assert.equal(elements.jobRows.children[0].children[2].textContent,'報告已完成');
  assert.equal(elements.jobPrev.disabled,true);
  assert.equal(elements.jobNext.disabled,true);
  assert.doesNotMatch(JSON.stringify(elements.jobRows.children),/DO NOT SHOW/);
  // A Job in this list uses the existing owner-authorized status route.
  planned.push(response(200, progress('job-history-A','completed','completed')));
  elements.jobRows.children[0].children[4].children[0].handlers.click();
  await tick();
  assert.equal(calls.at(-1).url,'/v1/report/jobs/job-history-A');
  assert.equal(elements.jobId.value,'job-history-A');

  // Switching identity during GET aborts and clears old owner history.
  let releaseHistory;
  planned.push(new Promise(resolve => {releaseHistory=resolve;}));
  const pendingHistory=fire('listJobsBtn');
  await tick();
  const signal=calls.at(-1).opts.signal;
  assert.equal(signal.aborted,false);
  elements.authToken.value='new-owner';
  fire('authToken','input');
  assert.equal(signal.aborted,true);
  assert.equal(elements.jobRows.children.length,0);
  assert.equal(elements.progressCard.hidden,true);
  releaseHistory(response(200,{items:[{job_id:'job-history-A',status:'completed',phase:'completed'}],limit:20,offset:0}));
  await pendingHistory;
  assert.equal(elements.jobRows.children.length,0);

  console.log('Report Job UI behavior PASS: owner-scope headers, live phases, terminal stops, errors, download and token change');
})().catch(err => { console.error(err); process.exitCode = 1; });
