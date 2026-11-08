'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'sra_api', 'static', 'requirement_product_explorer.js'), 'utf8');
function element(tag = '') {
  return {
    tag, children: [], handlers: {}, textContent: '', hidden: false, disabled: false,
    value: '', type: '', colSpan: 1,
    addEventListener(kind, fn) { this.handlers[kind] = fn; },
    appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; }
  };
}
const ids = [
  'authToken', 'loadTasks', 'message', 'taskRows', 'taskPrev', 'taskNext', 'taskPage',
  'runsPanel', 'currentTask', 'runsRows', 'runPrev', 'runNext', 'runPage',
  'itemsPanel', 'currentRun', 'itemRows', 'itemPrev', 'itemNext', 'itemPage'
];
const nodes = Object.fromEntries(ids.map(id => [id, element()]));
const document = { getElementById: id => {
  assert.ok(nodes[id], 'unknown DOM id: ' + id); return nodes[id];
}, createElement: tag => element(tag)};
const pageEvents = {};
const window = {addEventListener(kind, fn) {pageEvents[kind] = fn;}};
const calls = [];
const responses = [];
const sandbox = {
  document, window, encodeURIComponent, console,
  fetch: async (url, options) => {
    calls.push({url, options});
    assert.equal(options.method, 'GET');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.redirect, 'error');
    assert.ok(!options.body);
    assert.ok(responses.length, 'unexpected request');
    return {ok: true, status: 200, json: async () => responses.shift()};
  }
};
vm.runInNewContext(source, sandbox, {filename: 'requirement_product_explorer.js'});
function fire(id, kind='click') {return nodes[id].handlers[kind]();}
async function selectFirst(tableId, index) {
  const button = nodes[tableId].children[0].children[index].children[0];
  assert.equal(button.tag, 'button');
  assert.equal(button.disabled, false);
  await button.handlers.click();
}
(async function () {
  assert.equal(calls.length, 0, 'page load must never fetch without user request');
  await fire('loadTasks');
  assert.equal(calls.length, 0);
  assert.match(nodes.message.textContent, /Token/);
  nodes.authToken.value = 'SECRET-TOKEN-1';
  fire('authToken', 'input');

  responses.push({items: [{task_id: 'task_A', name: '<script>not markup</script>',
    execution_kind: 'one_time', product_state: 'active',
    schedule: {enabled: true, next_run_at: '2026-11-09T03:00:00Z'}}]});
  await fire('loadTasks');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/v1/requirement-tasks?limit=20&offset=0');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer SECRET-TOKEN-1');
  assert.equal(nodes.taskRows.children[0].children[0].textContent, '<script>not markup</script>');
  assert.equal(nodes.taskNext.disabled, true);

  responses.push({items: [{run_id: 'run_B', status: 'running',
    trigger: {type: 'scheduled'}, counts: {succeeded: 2, failed: 0}}]});
  await selectFirst('taskRows', 4);
  assert.equal(calls[1].url, '/v1/requirement-tasks/task_A/runs?limit=20&offset=0');
  assert.equal(nodes.runsPanel.hidden, false);
  assert.equal(nodes.runsRows.children[0].children[0].textContent, 'run_B');

  responses.push({items: [{run_item_id: 'item_C', requirement_id: 'requirement_D',
    selection_status: 'selected', status: 'completed', artifact: {available: true}}]});
  await selectFirst('runsRows', 4);
  assert.equal(calls[2].url, '/v1/requirement-runs/run_B/items?limit=20&offset=0');
  assert.equal(nodes.itemsRows, undefined);
  assert.equal(nodes.itemsPanel.hidden, false);
  assert.equal(nodes.itemRows.children[0].children[4].textContent, '有成果');

  nodes.authToken.value = 'SECRET-TOKEN-2';
  fire('authToken', 'input');
  assert.equal(nodes.taskRows.children.length, 0);
  assert.equal(nodes.runsPanel.hidden, true);
  assert.equal(nodes.itemsPanel.hidden, true);
  assert.equal(nodes.taskNext.disabled, true);
  assert.ok(!JSON.stringify(calls).includes('SECRET-TOKEN-2'));
  assert.equal(typeof pageEvents.pagehide, 'function');
  pageEvents.pagehide();
  assert.equal(nodes.authToken.value, '');
  console.log('Product read-only explorer flow PASS: no automatic requests, task/run/item reads, safe DOM, auth reset');
})().catch(error => { console.error(error); process.exitCode = 1; });
