/* Read-only Product API explorer; no credentials or data are persisted. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const LIMIT = 20;
  const safeId = (id) => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id);
  const state = {revision: 0, taskId: '', runId: '', taskOffset: 0, runOffset: 0, itemOffset: 0};

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
  async function api(path) {
    const token = $('authToken').value.trim();
    if (!token) throw new Error('missing_token');
    const response = await fetch(path, {
      method: 'GET', headers: {Authorization: 'Bearer ' + token},
      credentials: 'omit', cache: 'no-store', redirect: 'error'
    });
    if (!response.ok) throw new Error('http_' + response.status);
    const payload = await response.json();
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
  function resetItems() {
    state.runId = '';
    state.itemOffset = 0;
    $('itemsPanel').hidden = true;
    $('currentRun').textContent = '';
    clearRows('itemRows');
  }
  function resetRuns() {
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