/* Authenticated, owner-scoped Report Job browser UI. No credentials are persisted. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const validId = /^[A-Za-z0-9_-]{1,128}$/;
  const terminal = new Set(['completed', 'failed', 'interrupted']);
  const statuses = {queued: '等待執行', running: '執行中', completed: '已完成', failed: '執行失敗', interrupted: '服務中斷'};
  const phases = {
    queued: '等待 Worker 領取',
    unobserved: '舊任務：執行階段未觀測',
    agent_execution: 'Agent 分析／檢索中（可能包含模型等待）',
    docx_export: '正在產製 Word 文件',
    finalizing: '正在寫入與驗證文件',
    completed: '報告已完成',
    failed: '報告執行失敗',
    interrupted: '執行因服務中斷而停止'
  };
  const reasons = {
    active: '執行中',
    long_running: '耗時較長；尚未確認逾時',
    duration_unavailable: '階段時間無法判定',
    terminal: '已結束'
  };
  const failures = {
    timeout: '實際呼叫逾時',
    rate_limited: '服務請求受到流量限制',
    provider_unavailable: '模型／服務暫時不可用',
    execution_error: '報告執行發生錯誤'
  };
  let generation = 0;
  let timer = null;
  let controller = null;
  let watching = false;
  let busySubmit = false;
  let currentId = '';
  let completedId = '';
  let pendingSubmission = null;
  let authVersion = 0;
  let downloadController = null;
  let historyGeneration = 0;
  let historyController = null;
  let historyBusy = false;
  let historyOffset = 0;

  function clearHistory() {
    ++historyGeneration;
    if (historyController !== null) historyController.abort();
    historyController = null;
    historyBusy = false;
    historyOffset = 0;
    $('jobRows').replaceChildren();
    $('jobPrev').disabled = true;
    $('jobNext').disabled = true;
    $('jobPage').textContent = '第 1 頁';
    $('listJobsBtn').disabled = false;
  }
  function renderHistory(items, offset) {
    const tbody = $('jobRows');
    tbody.replaceChildren();
    for (const item of items) {
      if (!item || typeof item !== 'object' ||
          !safeId(item.job_id) ||
          !Object.prototype.hasOwnProperty.call(statuses, item.status) ||
          !Object.prototype.hasOwnProperty.call(phases, item.phase)) {
        throw new Error('invalid_contract');
      }
      const tr = document.createElement('tr');
      for (const value of [
        item.job_id, statuses[item.status], phases[item.phase], item.created_at
      ]) {
        const td = document.createElement('td');
        td.textContent = value === null || value === undefined ? '—' : String(value);
        tr.appendChild(td);
      }
      const td = document.createElement('td');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary';
      button.textContent = '追蹤';
      const id = item.job_id;
      button.addEventListener('click', function () { watch(id); });
      td.appendChild(button);
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    if (!items.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 5;
      td.textContent = '此頁沒有符合目前身分的報告任務。';
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    historyOffset = offset;
    $('jobPage').textContent = '第 ' + (Math.floor(offset / 20) + 1) + ' 頁';
    $('jobPrev').disabled = offset === 0;
    $('jobNext').disabled = items.length < 20;
  }
  async function loadHistory(offset) {
    if (historyBusy) return;
    const filter = $('jobStatusFilter').value;
    if (filter && !Object.prototype.hasOwnProperty.call(statuses, filter)) {
      $('jobListMessage').textContent = '不支援的狀態篩選，請重新選擇。';
      return;
    }
    const access = token();
    if (!access) {
      $('jobListMessage').textContent = '請先輸入具備 report:job:read 權限的 Token。';
      return;
    }
    const run = ++historyGeneration;
    const ctrl = new AbortController();
    historyController = ctrl;
    historyBusy = true;
    $('listJobsBtn').disabled = true;
    $('jobPrev').disabled = true;
    $('jobNext').disabled = true;
    $('jobRows').replaceChildren();
    $('jobListMessage').textContent = '正在讀取目前身分的報告清單…';
    try {
      const response = await fetch('/v1/report/jobs?limit=20&offset=' + offset +
        (filter ? '&status=' + encodeURIComponent(filter) : ''), {
        method: 'GET', headers: {Authorization: 'Bearer ' + access},
        signal: ctrl.signal, credentials: 'omit', cache: 'no-store', redirect: 'error'
      });
      if (run !== historyGeneration || ctrl.signal.aborted) return;
      if (!response.ok) throw new Error('http_' + response.status);
      const data = await response.json();
      if (run !== historyGeneration || ctrl.signal.aborted) return;
      if (!data || !Array.isArray(data.items) || data.items.length > 20 ||
          data.limit !== 20 || data.offset !== offset ||
          data.status !== (filter || null) ||
          (filter && data.items.some(item => item.status !== filter))) {
        throw new Error('invalid_contract');
      }
      renderHistory(data.items, offset);
      $('jobListMessage').textContent = '已讀取此頁本人報告摘要；點選「追蹤」查看真正執行狀態。';
    } catch (_) {
      if (run !== historyGeneration || ctrl.signal.aborted) return;
      $('jobListMessage').textContent = '無法取得報告清單（權限或服務異常）；未顯示任何其他帳號資料。';
      $('jobRows').replaceChildren();
    } finally {
      if (historyController === ctrl) {
        historyController = null;
        historyBusy = false;
        $('listJobsBtn').disabled = false;
      }
    }
  }
  function message(value, tone) {
    $('message').textContent = value;
    $('message').className = 'message' + (tone ? ' ' + tone : '');
  }
  function token() { return $('authToken').value.trim(); }
  function safeId(value) { return validId.test(value) ? value : null; }
  function controls() {
    $('watchBtn').disabled = watching || busySubmit;
    $('stopBtn').disabled = !watching;
    $('submitBtn').disabled = busySubmit || Boolean(pendingSubmission);
    $('retrySubmitBtn').hidden = !pendingSubmission;
    $('retrySubmitBtn').disabled = busySubmit || !pendingSubmission;
    $('discardSubmitBtn').hidden = !pendingSubmission;
    $('discardSubmitBtn').disabled = busySubmit || !pendingSubmission;
    $('prompt').disabled = busySubmit || Boolean(pendingSubmission);
    $('filename').disabled = busySubmit || Boolean(pendingSubmission);
  }
  function abortDownload() {
    if (downloadController !== null) downloadController.abort();
    downloadController = null;
  }
  function stop(text) {
    generation += 1;
    watching = false;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (controller !== null) controller.abort();
    controller = null;
    controls();
    if (text) message(text);
  }
  function update(job) {
    const progress = job.progress;
    if (job.job_id !== currentId || !Object.prototype.hasOwnProperty.call(statuses, job.status) ||
        !progress || !Object.prototype.hasOwnProperty.call(phases, progress.phase)) {
      throw new Error('invalid_contract');
    }
    $('progressCard').hidden = false;
    $('phaseTitle').textContent = phases[progress.phase];
    $('jobStatus').textContent = statuses[job.status];
    $('phaseElapsed').textContent = typeof progress.elapsed_seconds === 'number' &&
      Number.isFinite(progress.elapsed_seconds) && progress.elapsed_seconds >= 0
      ? Math.floor(progress.elapsed_seconds) + ' 秒' : '無法計算';
    $('observation').textContent = reasons[progress.observation] || '狀態未確認';
    $('lastChecked').textContent = new Date().toLocaleTimeString('zh-TW');
    const hasFailure = job.status === 'failed';
    $('failureMessage').hidden = !hasFailure;
    $('failureMessage').textContent = hasFailure ? (failures[progress.failure_category] || '報告執行失敗（原因未分類）') : '';
    completedId = job.status === 'completed' ? currentId : '';
    $('downloadBtn').hidden = !completedId;
  }
  function pollLater(run, delay) {
    if (!watching || run !== generation) return;
    if (document.hidden) {
      message('分頁在背景時暫停查詢；回到此頁後會重新取得最新狀態。', 'warning');
      return;
    }
    timer = setTimeout(function () { timer = null; poll(run); }, delay);
  }
  async function poll(run) {
    if (!watching || run !== generation || document.hidden) return;
    const ctrl = new AbortController();
    controller = ctrl;
    try {
      const response = await fetch('/v1/report/jobs/' + encodeURIComponent(currentId), {
        method: 'GET', headers: {Authorization: 'Bearer ' + token()},
        signal: ctrl.signal, cache: 'no-store', credentials: 'omit', redirect: 'error'
      });
      if (run !== generation) return;
      if (!response.ok) {
        if ([401, 403, 404].includes(response.status)) {
          stop();
          completedId = '';
          $('downloadBtn').hidden = true;
          message(response.status === 404 ? '找不到任務，或目前帳號沒有讀取權限。' : 'Token 無效或沒有 Report Job 讀取權限。', 'error');
          return;
        }
        message('查詢失敗（HTTP ' + response.status + '），尚未確認任務狀態；稍後自動重試。', 'warning');
        pollLater(run, response.status === 429 ? 15000 : 10000);
        return;
      }
      const job = await response.json();
      if (run !== generation) return;
      update(job);
      if (terminal.has(job.status)) {
        stop();
        message(job.status === 'completed' ? '報告已完成，可下載 Word 文件。' :
          job.status === 'interrupted' ? '服務已中斷此任務；系統不會自動重跑。' :
            '任務已失敗，請查看分類原因。', job.status === 'completed' ? 'success' : 'error');
      } else {
        message(progressMessage(job.progress), job.progress.long_running ? 'warning' : '');
        pollLater(run, 3000);
      }
    } catch (err) {
      if (run !== generation || ctrl.signal.aborted) return;
      message('無法確認伺服器最新狀態（網路或回應格式異常）；10 秒後再試。', 'warning');
      pollLater(run, 10000);
    } finally {
      if (controller === ctrl) controller = null;
    }
  }
  function progressMessage(progress) {
    return progress.long_running
      ? '本階段耗時較長，仍在執行或等待；不能據此判定模型排隊、卡死或 Timeout。'
      : '已取得伺服器即時狀態。每 3 秒更新一次。';
  }
  function watch(id) {
    const parsed = safeId(id);
    if (!parsed) { message('Job ID 格式不正確。', 'error'); return; }
    if (!token()) { message('請先提供具備 report:job:read 權限的 Token。', 'error'); return; }
    stop();
    abortDownload();
    currentId = parsed;
    completedId = '';
    $('jobId').value = parsed;
    $('progressCard').hidden = true;
    $('downloadBtn').hidden = true;
    watching = true;
    controls();
    message('查詢中…');
    poll(generation);
  }
  async function sendCreate(attempt) {
    if (busySubmit || !attempt || !token() || attempt.authVersion !== authVersion) return;
    const access = token();
    stop();
    busySubmit = true;
    controls();
    message('正在確認報告建立結果；不會自動重送請求。');
    try {
      const response = await fetch('/v1/report/jobs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + access,
          'Idempotency-Key': attempt.key
        },
        body: attempt.body,
        cache: 'no-store', credentials: 'omit', redirect: 'error'
      });
      // A token change might invalidate ownership while the request is in flight.
      if (authVersion !== attempt.authVersion) return;
      if (!response.ok) {
        if (response.status === 408 || response.status === 429 || response.status >= 500) {
          pendingSubmission = attempt;
          message('伺服器回應異常（HTTP ' + response.status +
            '），結果尚未確認。只能使用下方相同識別碼明確重試，勿重新建立相同報告。', 'warning');
          return;
        }
        pendingSubmission = null;
        message(response.status === 401 || response.status === 403
          ? 'Token 無效或沒有 Report Job 建立權限。'
          : response.status === 409
            ? '建立識別碼衝突；請先由已授權管道查驗，未自動重送。'
            : '建立失敗（HTTP ' + response.status + '）；請檢查輸入及權限。',
          'error');
        return;
      }
      if (response.status !== 202) throw new Error('unexpected_status');
      const data = await response.json();
      if (authVersion !== attempt.authVersion) return;
      if (!data || !safeId(data.job_id)) throw new Error('invalid_contract');
      pendingSubmission = null;
      $('prompt').value = '';
      $('jobId').value = data.job_id;
      message('已取得任務 ID；開始讀取實際進度。');
      watch(data.job_id);
    } catch (_) {
      if (authVersion !== attempt.authVersion) return;
      pendingSubmission = attempt;
      message('無法確認伺服器是否已接收此報告。請使用下方相同識別碼明確重試，或先從已授權管道核對；不會自動重送。', 'warning');
    } finally {
      busySubmit = false;
      controls();
    }
  }
  async function submit() {
    if (busySubmit || pendingSubmission) return;
    const access = token();
    const prompt = $('prompt').value.trim();
    const filename = $('filename').value.trim();
    if (!access) { message('請先提供有 report:job:create 權限的 Token。', 'error'); return; }
    if (!prompt) { message('請先輸入報告需求。', 'error'); return; }
    // Fail closed without a cryptographically random request identity.
    const nonce = window.crypto && typeof window.crypto.randomUUID === 'function'
      ? window.crypto.randomUUID() : null;
    if (!nonce || !/^[a-f0-9-]{36}$/i.test(nonce)) {
      message('瀏覽器沒有安全的隨機識別碼功能；請使用可信任 HTTPS 或本機連線建立報告。', 'error');
      return;
    }
    const payload = {prompt: prompt};
    if (filename) payload.filename = filename;
    await sendCreate({key: 'sraf-report-' + nonce, body: JSON.stringify(payload), authVersion});
  }
  async function retrySubmit() {
    if (!pendingSubmission) return;
    // The original body and key are reused unchanged; no fresh POST identity.
    await sendCreate(pendingSubmission);
  }
  function discardSubmit() {
    if (busySubmit || !pendingSubmission) return;
    pendingSubmission = null;
    controls();
    message('已放棄本頁的待確認重試資料。原請求仍可能已建立報告；重新送出前請先核對，否則可能產生重複任務。', 'warning');
  }
  function authorizedDocxFilename(disposition, fallback) {
    if (typeof disposition !== 'string') return fallback;
    let filename = '';
    const extended = /(?:^|;)\s*filename\*\s*=\s*utf-8'[^']*'([^;]+)/i.exec(disposition);
    if (extended) {
      try { filename = decodeURIComponent(extended[1].trim()); }
      catch (_) { return fallback; }
    } else {
      const quoted = /(?:^|;)\s*filename\s*=\s*"((?:\\.|[^"\\])*)"/i.exec(disposition);
      if (quoted) {
        filename = quoted[1].replace(/\\(.)/g, '$1');
      } else {
        const unquoted = /(?:^|;)\s*filename\s*=\s*([^;\s]+)/i.exec(disposition);
        if (unquoted) filename = unquoted[1];
      }
    }
    filename = filename.trim();
    // Do not trust Content-Disposition as a local path or arbitrary extension.
    if (!filename || filename.length > 240 ||
        /[\/\\\x00-\x1f\x7f]/.test(filename) ||
        filename === '.' || filename === '..' || !/\.docx$/i.test(filename)) {
      return fallback;
    }
    return filename;
  }
  async function download() {
    if (!completedId || !safeId(completedId) || !token()) {
      message('只有已完成的任務可以下載，且必須提供有效 Token。', 'error');
      return;
    }
    // Reject overlapping downloads and bind the response to this identity + Job.
    if (downloadController !== null) return;
    const id = completedId;
    const version = authVersion;
    const access = token();
    const ctrl = new AbortController();
    downloadController = ctrl;
    const stillAuthorized = () =>
      !ctrl.signal.aborted && downloadController === ctrl &&
      authVersion === version && completedId === id;
    $('downloadBtn').disabled = true;
    try {
      const response = await fetch('/v1/report/jobs/' + encodeURIComponent(id) + '/word', {
        method: 'GET', headers: {Authorization: 'Bearer ' + access},
        signal: ctrl.signal, cache: 'no-store', credentials: 'omit', redirect: 'error'
      });
      if (!stillAuthorized()) return;
      if (!response.ok) {
        message(response.status === 401 || response.status === 403 || response.status === 404
          ? '無法下載：沒有權限或找不到成果。'
          : '下載失敗（HTTP ' + response.status + '），請確認文件是否仍可用。', 'error');
        return;
      }
      const blob = await response.blob();
      // A token or selected Job may change while the browser reads the bytes.
      if (!stillAuthorized()) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = authorizedDocxFilename(response.headers.get('content-disposition'), 'report-' + id + '.docx');
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
      message('已向瀏覽器提供 Word 下載。', 'success');
    } catch (_) {
      if (stillAuthorized()) message('下載連線失敗；請檢查網路與權限後再試。', 'error');
    } finally {
      if (downloadController === ctrl) downloadController = null;
      $('downloadBtn').disabled = false;
    }
  }
  $('jobStatusFilter').addEventListener('change', function () {
    clearHistory();
    $('jobListMessage').textContent = '篩選已變更；請按「讀取我的報告紀錄」取得新的授權清單。';
  });
  $('listJobsBtn').addEventListener('click', function () { loadHistory(0); });
  $('jobPrev').addEventListener('click', function () {
    if (!historyBusy && historyOffset > 0) loadHistory(Math.max(0, historyOffset - 20));
  });
  $('jobNext').addEventListener('click', function () {
    if (!historyBusy) loadHistory(historyOffset + 20);
  });
  $('watchBtn').addEventListener('click', function () { watch($('jobId').value.trim()); });
  $('stopBtn').addEventListener('click', function () { stop('已停止自動查詢。原任務仍由伺服器執行，不會被取消。'); });
  $('submitBtn').addEventListener('click', submit);
  $('retrySubmitBtn').addEventListener('click', retrySubmit);
  $('discardSubmitBtn').addEventListener('click', discardSubmit);
  $('downloadBtn').addEventListener('click', download);
  $('authToken').addEventListener('input', function () {
    ++authVersion;
    pendingSubmission = null;
    clearHistory();
    $('jobListMessage').textContent = '身分已變更；請重新讀取自己的清單。';
    $('progressCard').hidden = true;
    abortDownload();
    if (watching) stop('認證已變更；請重新查詢以確認權限。');
    completedId = '';
    $('downloadBtn').hidden = true;
    controls();
  });
  document.addEventListener('visibilitychange', function () {
    if (!watching) return;
    if (document.hidden) {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    } else if (controller === null && timer === null) {
      poll(generation);
    }
  });
  window.addEventListener('pagehide', function () {
    ++authVersion;
    pendingSubmission = null;
    $('authToken').value = '';
    clearHistory();
    $('progressCard').hidden = true;
    abortDownload();
    stop();
    controls();
  });
  controls();
})();
