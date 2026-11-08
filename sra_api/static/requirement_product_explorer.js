/* Read-only Product API explorer; no credentials or data are persisted. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const LIMIT = 20;
  const safeId = (id) => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id);
  const state = {revision: 0, taskId: '', runId: '', taskOffset: 0, runOffset: 0, itemOffset: 0, taskDetailRev: 0, runDetailRev: 0};

  function note(text) { $('message').textContent = text; }
  function text(value) {
    return value === null || value === undefined || value === '' ? '—' : String(value);
  }
  function clearRows(id) { $(id).replaceChildren(); }
  function page(prefix, offset, length) {
    $(prefix + 'Page').textContent = '第 ' + (Math.floor(offset / LIMIT) + 1) + ' 頁';
    $(prefix + 'Prev').disabled = offset === 0;
    // The API provides limit/offset/items but does not promise a total count.
    $(prefix + 'Next').disabled = length < LIMIT;
  }
  function table(rowsId, values, columns, selectText, onSelect) {
    const body = $(rowsId);
    body.replaceChildren();
    if (!values.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = columns.length + (onSelect ? 1 : 0);
      td.textContent = '此頁沒有資料';
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    for (const item of values) {
      const tr = document.createElement('tr');
      for (const fn of columns) {
        const td = document.createElement('td');
        td.textContent = text(fn(item));
        tr.appendChild(td);
      }
      if (onSelect) {
        const td = document.createElement('td');
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = selectText;
        button.disabled = !safeId(onSelect.id(item));
        button.addEventListener('click', () => onSelect.open(item));
        td.appendChild(button);
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  }
  async function requestJson(path) {
    const token = $('authToken').value.trim();
    if (!token) throw new Error('missing_token');
    const response = await fetch(path, {
      method: 'GET', headers: {Authorization: 'Bearer ' + token},
      credentials: 'omit', cache: 'no-store', redirect: 'error'
    });
    if (!response.ok) throw new Error('http_' + response.status);
    return response.json();
  }
  async function api(path) {
    const payload = await requestJson(path);
    if (!payload || !Array.isArray(payload.items)) throw new Error('invalid_contract');
    return payload.items;
  }
  function showError(error) {
    const code = error && error.message;
    if (code === 'missing_token' || code === 'http_401' || code === 'http_403') {
      note('請輸入有權限的 Token，並確認帳號可讀取 Product API。');
    } else if (code === 'http_503') {
      note('目前無法使用 Product API，可能尚未設定服務。');
    } else if (code === 'http_404') {
      note('找不到指定項目，或目前帳號沒有權限。');
    } else {
      note('無法確認查詢結果，請檢查連線或稍後重試；未執行任何寫入。');
    }
  }

  function clearDetails(kind) {
    ++state[kind + 'DetailRev'];
    $(kind + 'Details').hidden = true;
    $(kind + 'Details').replaceChildren();
  }
  function presentDetails(kind, fields) {
    const target = $(kind + 'Details');
    target.replaceChildren();
    for (const [label, value] of fields) {
      const dt = document.createElement('dt');
      dt.textContent = label;
      const dd = document.createElement('dd');
      dd.textContent = text(value);
      target.appendChild(dt);
      target.appendChild(dd);
    }
    target.hidden = false;
  }
  async function loadTaskDetail() {
    const id = state.taskId;
    if (!safeId(id)) return;
    const rev = state.revision;
    const detailRev = ++state.taskDetailRev;
    $('taskDetails').hidden = true;
    $('taskDetails').replaceChildren();
    note('正在讀取任務詳細資料…');
    try {
      const item = await requestJson('/v1/requirement-tasks/' + encodeURIComponent(id));
      if (rev !== state.revision || detailRev !== state.taskDetailRev || state.taskId !== id) return;
      if (!item || Array.isArray(item) || item.task_id !== id) throw new Error('invalid_contract');
      const schedule = item.schedule || {};
      presentDetails('task', [
        ['任務 ID', item.task_id], ['任務名稱', item.name],
        ['執行型態', item.execution_kind], ['產品狀態', item.product_state],
        ['修訂版', item.revision], ['來源 ID', item.source_id],
        ['排程 ID', item.schedule_id],
        ['排程啟用', typeof schedule.enabled === 'boolean' ? (schedule.enabled ? '是' : '否') : null],
        ['啟用排程版本', schedule.active_version_id],
        ['下次排程時間', schedule.next_run_at],
        ['建立時間', item.created_at], ['更新時間', item.updated_at]
      ]);
      note('已讀取目前任務的授權詳細資料。');
    } catch (error) {
      if (rev === state.revision && detailRev === state.taskDetailRev) showError(error);
    }
  }
  async function loadRunDetail() {
    const id = state.runId;
    if (!safeId(id)) return;
    const rev = state.revision;
    const detailRev = ++state.runDetailRev;
    $('runDetails').hidden = true;
    $('runDetails').replaceChildren();
    note('正在讀取批次詳細資料…');
    try {
      const item = await requestJson('/v1/requirement-runs/' + encodeURIComponent(id));
      if (rev !== state.revision || detailRev !== state.runDetailRev || state.runId !== id) return;
      if (!item || Array.isArray(item) || item.run_id !== id || item.task_id !== state.taskId) {
        throw new Error('invalid_contract');
      }
      const binding = item.binding || {}, trigger = item.trigger || {}, counts = item.counts || {};
      presentDetails('run', [
        ['批次 ID', item.run_id], ['任務 ID', item.task_id],
        ['執行狀態', item.status], ['排程 ID', binding.schedule_id],
        ['排程版本', binding.schedule_version_id], ['需求快照 ID', binding.snapshot_id],
        ['觸發方式', trigger.type], ['排程時間', trigger.scheduled_for],
        ['選取數', counts.selected], ['略過數', counts.skipped],
        ['完成數', counts.succeeded], ['失敗數', counts.failed],
        ['錯誤分類', item.error_category],
        ['執行中超過期限', item.deadline_elapsed_during_execution === true ? '是' : '否'],
        ['建立時間', item.created_at], ['結束時間', item.completed_at]
      ]);
      note('已讀取目前批次的授權詳細資料；僅代表 API 回報狀態。');
    } catch (error) {
      if (rev === state.revision && detailRev === state.runDetailRev) showError(error);
    }
  }
  function resetItems() {
    clearDetails('run');
    state.runId = '';
    state.itemOffset = 0;
    $('itemsPanel').hidden = true;
    $('currentRun').textContent = '';
    clearRows('itemRows');
  }
  function resetRuns() {
    clearDetails('task');
    state.taskId = '';
    state.runOffset = 0;
    $('runsPanel').hidden = true;
    $('currentTask').textContent = '';
    clearRows('runsRows');
    resetItems();
  }
  async function loadTasks(offset) {
    const rev = ++state.revision;
    state.taskOffset = offset;
    resetRuns();
    clearRows('taskRows');
    note('讀取任務中…');
    try {
      const items = await api('/v1/requirement-tasks?limit=' + LIMIT + '&offset=' + offset);
      if (rev !== state.revision) return;
      table('taskRows', items, [
        task => task.name || task.task_id,
        task => text(task.execution_kind) + ' / ' + text(task.product_state),
        task => task.schedule && task.schedule.enabled ? '啟用' : '未啟用',
        task => task.schedule && task.schedule.next_run_at
      ], '查看批次', {
        id: task => task.task_id,
        open: task => loadRuns(task.task_id, 0)
      });
      page('task', offset, items.length);
      note('已讀取此頁任務；選取一項查看執行批次。');
    } catch (error) {
      if (rev === state.revision) { page('task', offset, 0); showError(error); }
    }
  }
  async function loadRuns(taskId, offset) {
    if (!safeId(taskId)) { note('任務識別碼格式不正確。'); return; }
    const rev = ++state.revision;
    state.taskId = taskId;
    state.runOffset = offset;
    clearDetails('task');
    resetItems();
    $('runsPanel').hidden = false;
    $('currentTask').textContent = taskId;
    clearRows('runsRows');
    note('讀取執行批次中…');
    try {
      const items = await api('/v1/requirement-tasks/' + encodeURIComponent(taskId) +
        '/runs?limit=' + LIMIT + '&offset=' + offset);
      if (rev !== state.revision) return;
      table('runsRows', items, [
        run => run.run_id,
        run => run.status,
        run => run.trigger && run.trigger.type,
        run => text(run.counts && run.counts.succeeded) + ' / ' +
          text(run.counts && run.counts.failed)
      ], '查看項目', {
        id: run => run.run_id,
        open: run => loadItems(run.run_id, 0)
      });
      page('run', offset, items.length);
      note('已讀取此任務的執行批次。');
    } catch (error) {
      if (rev === state.revision) { page('run', offset, 0); showError(error); }
    }
  }
  async function loadItems(runId, offset) {
    if (!safeId(runId)) { note('執行批次識別碼格式不正確。'); return; }
    const rev = ++state.revision;
    state.runId = runId;
    state.itemOffset = offset;
    clearDetails('run');
    $('itemsPanel').hidden = false;
    $('currentRun').textContent = runId;
    clearRows('itemRows');
    note('讀取執行項目中…');
    try {
      const items = await api('/v1/requirement-runs/' + encodeURIComponent(runId) +
        '/items?limit=' + LIMIT + '&offset=' + offset);
      if (rev !== state.revision) return;
      table('itemRows', items, [
        item => item.run_item_id,
        item => item.requirement_id,
        item => item.selection_status,
        item => item.status,
        item => item.artifact && item.artifact.available ? '有成果' : '未確認成果'
      ], '', null);
      page('item', offset, items.length);
      note('已讀取此批次的執行項目。成果僅表示 API metadata；不能代替實機 DOCX 驗證。');
    } catch (error) {
      if (rev === state.revision) { page('item', offset, 0); showError(error); }
    }
  }
  $('taskDetailBtn').addEventListener('click', loadTaskDetail);
  $('runDetailBtn').addEventListener('click', loadRunDetail);
  $('loadTasks').addEventListener('click', () => loadTasks(0));
  $('taskPrev').addEventListener('click', () => loadTasks(Math.max(0, state.taskOffset - LIMIT)));
  $('taskNext').addEventListener('click', () => loadTasks(state.taskOffset + LIMIT));
  $('runPrev').addEventListener('click', () => { if (state.taskId) loadRuns(state.taskId, Math.max(0, state.runOffset - LIMIT)); });
  $('runNext').addEventListener('click', () => { if (state.taskId) loadRuns(state.taskId, state.runOffset + LIMIT); });
  $('itemPrev').addEventListener('click', () => { if (state.runId) loadItems(state.runId, Math.max(0, state.itemOffset - LIMIT)); });
  $('itemNext').addEventListener('click', () => { if (state.runId) loadItems(state.runId, state.itemOffset + LIMIT); });
  $('authToken').addEventListener('input', () => {
    ++state.revision;
    resetRuns();
    state.taskOffset = 0;
    clearRows('taskRows');
    page('task', 0, 0);
    note('認證已變更，已清除上一個帳號的畫面資料；請重新載入。');
  });
  window.addEventListener('pagehide', () => {
    ++state.revision;
    $('authToken').value = '';
    resetRuns();
    clearRows('taskRows');
  });
  page('task', 0, 0);
  page('run', 0, 0);
  page('item', 0, 0);
})();