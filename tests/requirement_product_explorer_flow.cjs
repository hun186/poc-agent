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
  'itemsPanel', 'currentRun', 'itemRows', 'itemPrev', 'itemNext', 'itemPage',
  'taskDetailBtn', 'taskDetails', 'runDetailBtn', 'runDetails',
  'loadAllRuns', 'allRunRows', 'allRunPrev', 'allRunNext', 'allRunPage', 'openRunTaskBtn',
  'lookupRunId', 'lookupRunBtn'
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
  assert.equal(calls.at(-1).url, '/v1/requirement-tasks/task_A/runs?limit=20&offset=0');
  assert.equal(nodes.runsPanel.hidden, false);
  assert.equal(nodes.runsRows.children[0].children[0].textContent, 'run_B');

  responses.push({task_id: 'task_A', name: '<script>task detail</script>',
    revision: 3, source_id: 'source-x',
    execution_kind: 'one_time', product_state: 'active',
    schedule: {enabled: true, active_version_id: 'version-7', next_run_at: null}});
  await fire('taskDetailBtn');
  assert.equal(calls.at(-1).url, '/v1/requirement-tasks/task_A');
  assert.equal(nodes.taskDetails.hidden, false);
  assert.equal(nodes.taskDetails.children[3].textContent, '<script>task detail</script>');
  assert.equal(nodes.taskDetails.children[9].textContent, '3');


  responses.push({items: [{run_item_id: 'item_C', requirement_id: 'requirement_D',
    selection_status: 'selected', status: 'completed', artifact: {available: true}}]});
  await selectFirst('runsRows', 4);
  assert.equal(calls.at(-1).url, '/v1/requirement-runs/run_B/items?limit=20&offset=0');
  assert.equal(nodes.itemsRows, undefined);
  assert.equal(nodes.itemsPanel.hidden, false);
  assert.equal(nodes.itemRows.children[0].children[4].textContent, '有成果');

  responses.push({run_id:'run_B', task_id:'task_A', status:'running',
    binding:{schedule_id:'schedule-1', schedule_version_id:'version-7',
      snapshot_id:'snap-1'}, trigger:{type:'scheduled',scheduled_for:'2026-11-09T03:00:00Z'},
    counts:{selected:3,skipped:1,succeeded:2,failed:0},
    deadline_elapsed_during_execution:false});
  await fire('runDetailBtn');
  assert.equal(calls.at(-1).url, '/v1/requirement-runs/run_B');
  assert.equal(nodes.runDetails.hidden, false);
  assert.equal(nodes.runDetails.children[1].textContent, 'run_B');
  assert.equal(nodes.runDetails.children[3].textContent, 'task_A');



  // Global Run API is already available; this UI must use that existing GET.
  responses.push({items:[{run_id:'run_Global',task_id:'task_Global',status:'running',
    trigger:{type:'manual'},counts:{succeeded:4,failed:1}}]});
  await fire('loadAllRuns');
  assert.equal(calls.at(-1).url,'/v1/requirement-runs?limit=20&offset=0');
  assert.equal(nodes.allRunRows.children[0].children[0].textContent,'run_Global');
  assert.equal(nodes.allRunRows.children[0].children[1].textContent,'task_Global');
  assert.equal(nodes.allRunNext.disabled,true);
  responses.push({items:[{run_item_id:'item_global',requirement_id:'req_global',
    selection_status:'selected',status:'completed',artifact:{available:false}}]});
  await selectFirst('allRunRows',5);
  assert.equal(calls.at(-1).url,'/v1/requirement-runs/run_Global/items?limit=20&offset=0');
  assert.equal(nodes.itemsPanel.hidden,false);
  assert.equal(nodes.openRunTaskBtn.hidden,false);
  assert.equal(nodes.itemRows.children[0].children[0].textContent,'item_global');
  responses.push({run_id:'run_Global',task_id:'task_Global',status:'running',
    binding:{snapshot_id:'snap'},trigger:{type:'manual'},counts:{succeeded:4,failed:1}});
  await fire('runDetailBtn');
  assert.equal(calls.at(-1).url,'/v1/requirement-runs/run_Global');
  assert.equal(nodes.runDetails.hidden,false);
  // Return to the canonical task-scoped view without assuming the Run was on page 1.
  responses.push({items:[{run_id:'run_Global',task_id:'task_Global',status:'running',
    trigger:{type:'manual'},counts:{succeeded:4,failed:1}}]});
  fire('openRunTaskBtn');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.at(-1).url,'/v1/requirement-tasks/task_Global/runs?limit=20&offset=0');
  assert.equal(nodes.runsPanel.hidden,false);
  assert.equal(nodes.itemsPanel.hidden,true);

  // Direct lookup is strict, bounded, authorized and does not assume a task ID.
  const beforeInvalid = calls.length;
  nodes.lookupRunId.value = '../private';
  await fire('lookupRunBtn');
  assert.equal(calls.length, beforeInvalid);
  assert.match(nodes.message.textContent, /格式不正確/);
  nodes.lookupRunId.value = 'run_Lookup';
  responses.push({run_id:'run_NOT_requested',task_id:'task_Other'});
  await fire('lookupRunBtn');
  assert.equal(calls.length,beforeInvalid+1);
  assert.equal(calls.at(-1).url,'/v1/requirement-runs/run_Lookup');
  assert.equal(nodes.itemsPanel.hidden,true);
  assert.match(nodes.message.textContent,/無法確認/);

  responses.push({run_id:'run_Lookup',task_id:'task_Verified',status:'completed'});
  responses.push({items:[{run_item_id:'item_verified',requirement_id:'req_v',
    selection_status:'selected',status:'completed',artifact:{available:true}}]});
  await fire('lookupRunBtn');
  assert.equal(calls.at(-2).url,'/v1/requirement-runs/run_Lookup');
  assert.equal(calls.at(-1).url,'/v1/requirement-runs/run_Lookup/items?limit=20&offset=0');
  assert.equal(nodes.itemRows.children[0].children[0].textContent,'item_verified');
  assert.equal(nodes.openRunTaskBtn.hidden,false);
  responses.push({run_id:'run_Lookup',task_id:'task_Verified',status:'completed',
    binding:{},trigger:{type:'manual'},counts:{}});
  await fire('runDetailBtn');
  assert.equal(nodes.runDetails.children[3].textContent,'task_Verified');

  // In-flight lookup from an old identity cannot resolve to an items GET.
  let resolveLookup;
  responses.push(new Promise(resolve=>{resolveLookup=resolve;}));
  const pendingLookup=fire('lookupRunBtn');
  await new Promise(resolve=>setImmediate(resolve));
  const beforeSwitch = calls.length;
  nodes.authToken.value='SECRET-TOKEN-2';
  fire('authToken','input');
  resolveLookup({run_id:'run_Lookup',task_id:'task_Verified'});
  await pendingLookup;
  assert.equal(calls.length,beforeSwitch);
  assert.equal(nodes.itemsPanel.hidden,true);
  assert.equal(nodes.lookupRunId.value,'');
  nodes.authToken.value='SECRET-TOKEN-1';
  fire('authToken','input');

  // Changing the bearer while a global history GET is in flight must discard it.
  let resolveHistory;
  responses.push(new Promise(resolve=>{resolveHistory=resolve;}));
  fire('loadAllRuns');
  await new Promise(resolve=>setImmediate(resolve));
  const previousRows=nodes.allRunRows.children.length;
  nodes.authToken.value='SECRET-TOKEN-2';
  fire('authToken','input');
  resolveHistory({items:[{run_id:'oldRun',task_id:'oldTask'}]});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(previousRows,0);
  assert.equal(nodes.allRunRows.children.length,0);
  assert.equal(nodes.allRunNext.disabled,true);
  nodes.authToken.value='SECRET-TOKEN-1';
  fire('authToken','input');

  // An in-flight detail result for the old bearer must never repopulate the UI.
  let finishOld;
  responses.push(new Promise(resolve => {finishOld = resolve;}));
  const pending = fire('runDetailBtn');
  await new Promise(resolve => setImmediate(resolve));
  nodes.authToken.value = 'SECRET-TOKEN-2';
  fire('authToken', 'input');
  finishOld({run_id:'run_B',task_id:'task_A',status:'completed'});
  await pending;
  assert.equal(nodes.runDetails.hidden, true);
  assert.equal(nodes.runDetails.children.length, 0);

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
