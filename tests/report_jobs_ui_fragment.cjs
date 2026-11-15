'use strict';
// Synthetic, no-network proof of safe Report Job fragment prefill.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'sra_api', 'static', 'report_jobs_ui.js'), 'utf8'
);
const ids = [
  'authToken', 'prompt', 'filename', 'jobId', 'watchBtn', 'stopBtn',
  'submitBtn', 'downloadBtn', 'retrySubmitBtn', 'discardSubmitBtn',
  'message', 'jobStatusFilter', 'listJobsBtn', 'jobPrev', 'jobNext'
];
function openPage(fragment) {
  const controls = Object.fromEntries(ids.map(id => [id, {
    value: '', disabled: false, hidden: false, textContent: '', className: '',
    addEventListener() {}
  }]));
  let fetchCount = 0;
  const sandbox = {
    window: {
      location: {hash: fragment},
      addEventListener() {}
    },
    document: {
      hidden: false,
      getElementById(id) { return controls[id]; },
      addEventListener() {}
    },
    AbortController,
    fetch() { fetchCount++; throw Error('unexpected network call'); },
    setTimeout() { throw Error('unexpected timer'); },
    clearTimeout() {}
  };
  vm.runInNewContext(source, sandbox, {filename: 'report_jobs_ui.js'});
  return {controls, fetchCount};
}

const valid = openPage('#job=job_DEEP-42');
assert.equal(valid.controls.jobId.value, 'job_DEEP-42');
assert.match(valid.controls.message.textContent, /Token.*追蹤/);
assert.equal(valid.controls.authToken.value, '');
assert.equal(valid.fetchCount, 0, 'prefill is not authentication or an auto-query');

for (const value of [
  '', '#job=', '#job=../path', '#job=abc?token=data',
  '#job=hello%20world', '#job=abc&token=data', '#job=中文',
  '#job=' + 'a'.repeat(129), '#job=valid' + '#extra'
]) {
  const bad = openPage(value);
  assert.equal(bad.controls.jobId.value, '', value);
  assert.equal(bad.fetchCount, 0, value);
  assert.equal(bad.controls.authToken.value, '');
}
console.log('Report Job fragment prefill contract: PASS');
