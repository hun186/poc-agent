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

  function message(value, tone) {
    $('message').textContent = value;
    $('message').className = 'message' + (tone ? ' ' + tone : '');
  }
  function token() { return $('authToken').value.trim(); }
  function safeId(value) { return validId.test(value) ? value : null; }
  function controls() {
    $('watchBtn').disabled = watching || busySubmit;
    $('stopBtn').disabled = !watching;
    $('submitBtn').disabled = busySubmit;
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
  async function submit() {
    const access = token();
    const prompt = $('prompt').value.trim();
    const filename = $('filename').value.trim();
    if (!access) { message('請先提供有 report:job:create 權限的 Token。', 'error'); return; }
    if (!prompt) { message('請先輸入報告需求。', 'error'); return; }
    if (busySubmit) return;
    stop();
    busySubmit = true;
    controls();
    message('正在建立任務；此請求不會自動重送。');
    try {
      const payload = {prompt: prompt};
      if (filename) payload.filename = filename;
      const response = await fetch('/v1/report/jobs', {
        method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + access},
        body: JSON.stringify(payload), cache: 'no-store', credentials: 'omit', redirect: 'error'
      });
      if (!response.ok) {
        message(response.status === 401 || response.status === 403
          ? 'Token 無效或沒有 Report Job 建立權限。'
          : '建立失敗（HTTP ' + response.status + '）；請檢查資料及權限。', 'error');
        return;
      }
      if (response.status !== 202) throw new Error('unexpected_status');
      const data = await response.json();
      if (!safeId(data.job_id)) throw new Error('invalid_contract');
      $('prompt').value = '';
      $('jobId').value = data.job_id;
      message('已收到任務 ID，開始查詢進度。');
      watch(data.job_id);
    } catch (err) {
      message('無法確認建立結果。請先從其他已授權管道核對，勿直接重送以免產生重複任務。', 'error');
    } finally {
      busySubmit = false;
      controls();
    }
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
    const id = completedId;
    $('downloadBtn').disabled = true;
    try {
      const response = await fetch('/v1/report/jobs/' + encodeURIComponent(id) + '/word', {
        method: 'GET', headers: {Authorization: 'Bearer ' + token()},
        cache: 'no-store', credentials: 'omit', redirect: 'error'
      });
      if (!response.ok) {
        message(response.status === 401 || response.status === 403 || response.status === 404
          ? '無法下載：沒有權限或找不到成果。'
          : '下載失敗（HTTP ' + response.status + '），請確認文件是否仍可用。', 'error');
        return;
      }
      const blob = await response.blob();
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
    } catch (err) {
      message('下載連線失敗；請檢查網路與權限後再試。', 'error');
    } finally {
      $('downloadBtn').disabled = false;
    }
  }
  $('watchBtn').addEventListener('click', function () { watch($('jobId').value.trim()); });
  $('stopBtn').addEventListener('click', function () { stop('已停止自動查詢。原任務仍由伺服器執行，不會被取消。'); });
  $('submitBtn').addEventListener('click', submit);
  $('downloadBtn').addEventListener('click', download);
  $('authToken').addEventListener('input', function () {
    if (watching) stop('認證已變更；請重新查詢以確認權限。');
    completedId = '';
    $('downloadBtn').hidden = true;
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
  window.addEventListener('pagehide', function () { stop(); });
  controls();
})();
