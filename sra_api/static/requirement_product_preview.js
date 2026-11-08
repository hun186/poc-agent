/* Existing Requirement Product no-persistence preview API; never creates tasks. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const MAX_FILE = 10 * 1024 * 1024;
  const MAX_JSON = 1024 * 1024;
  const FILE_EXT = /\.(csv|json|xlsx)$/i;
  let generation = 0;
  let controller = null;
  let busy = false;
  function message(value) { $('previewMessage').textContent = value; }
  function clearProfileOptions() {
    $('previewProfileSelect').replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '請先按載入清單；也可以直接輸入 ID';
    $('previewProfileSelect').appendChild(placeholder);
    $('previewProfileSelect').value = '';
  }
  function clearResult() {
    $('previewResult').hidden = true;
    $('previewSummary').replaceChildren();
    $('previewRows').replaceChildren();
    $('previewDiagnostics').replaceChildren();
  }
  function invalidate() {
    ++generation;
    if (controller !== null) controller.abort();
    controller = null;
    clearResult();
  }
  function controls() {
    $('previewBtn').disabled = busy;
    $('loadProfilesBtn').disabled = busy;
    $('previewProfileSelect').disabled = busy;
    $('previewClearBtn').disabled = busy;
    $('previewProfile').disabled = busy;
    $('previewMode').disabled = busy;
    $('previewFile').disabled = busy;
    $('previewJson').disabled = busy;
  }
  function selectMode() {
    const fileMode = $('previewMode').value === 'file';
    $('previewFileGroup').hidden = !fileMode;
    $('previewJsonGroup').hidden = fileMode;
    invalidate();
    message('請選擇檔案或輸入 JSON，再點選預覽。');
  }
  function scalar(value) {
    if (value === null || value === undefined || value === '') return '—';
    return String(value);
  }
  function addDetails(label, value) {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = scalar(value);
    $('previewSummary').appendChild(dt);
    $('previewSummary').appendChild(dd);
  }
  function renderRows(rows) {
    const tbody = $('previewRows');
    tbody.replaceChildren();
    for (const item of rows) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('invalid_contract');
      const tr = document.createElement('tr');
      for (const value of [
        item.source_row_number, item.external_item_id, item.title,
        typeof item.prompt_content === 'string' ? item.prompt_content.slice(0, 180) : null,
        item.expires_at
      ]) {
        const td = document.createElement('td');
        td.textContent = scalar(value);
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }
  function renderDiagnostic(items, name) {
    for (const diag of items) {
      if (!diag || typeof diag !== 'object' || Array.isArray(diag)) throw new Error('invalid_contract');
      const entry = document.createElement('p');
      // Only bounded textual diagnostics. Never interpret or inject HTML.
      entry.textContent = name + '：' + JSON.stringify(diag).slice(0, 350);
      $('previewDiagnostics').appendChild(entry);
    }
  }
  function nonNegativeInteger(value) {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
  }
  function render(result, requestedProfile) {
    if (!result || typeof result !== 'object' || Array.isArray(result) ||
        !result.profile || result.profile.profile_version_id !== requestedProfile ||
        !nonNegativeInteger(result.row_count) ||
        !nonNegativeInteger(result.accepted_count) ||
        !nonNegativeInteger(result.rejected_count) ||
        !Array.isArray(result.normalized_preview) || result.normalized_preview.length > 100 ||
        !Array.isArray(result.errors) || result.errors.length > 100 ||
        !Array.isArray(result.warnings) || result.warnings.length > 100) {
      throw new Error('invalid_contract');
    }
    clearResult();
    addDetails('Profile Version', requestedProfile);
    addDetails('資料列數', result.row_count);
    addDetails('接受筆數', result.accepted_count);
    addDetails('拒絕筆數', result.rejected_count);
    addDetails('錯誤狀態', result.has_errors === true ? '有錯誤' : '未報告錯誤');
    addDetails('取樣限制', result.preview_truncated === true ? '結果已截斷取樣' : 'API 回傳資料範圍內');
    addDetails('來源 SHA-256', typeof result.source_sha256 === 'string' ? result.source_sha256 : null);
    renderRows(result.normalized_preview);
    renderDiagnostic(result.errors, '錯誤');
    renderDiagnostic(result.warnings, '警告');
    if (!result.errors.length && !result.warnings.length) {
      const p = document.createElement('p');
      p.textContent = '此回應未列出錯誤或警告；不代表實機 SQL／Worker 驗收通過。';
      $('previewDiagnostics').appendChild(p);
    }
    $('previewResult').hidden = false;
  }
  function buildPayload() {
    const profile = $('previewProfile').value.trim();
    if (!profile || profile.length > 128) throw new Error('missing_profile');
    const data = new FormData();
    data.append('task', JSON.stringify({profile_version_id: profile}));
    if ($('previewMode').value === 'file') {
      const file = $('previewFile').files && $('previewFile').files[0];
      if (!file || !FILE_EXT.test(file.name) || file.size <= 0 || file.size > MAX_FILE) {
        throw new Error('invalid_file');
      }
      data.append('file', file, file.name);
    } else if ($('previewMode').value === 'json') {
      const source = $('previewJson').value.trim();
      const size = new TextEncoder().encode(source).length;
      if (!source || size > MAX_JSON) throw new Error('invalid_json');
      let parsed;
      try { parsed = JSON.parse(source); } catch (_) { throw new Error('invalid_json'); }
      if (!Array.isArray(parsed)) throw new Error('invalid_json');
      data.append('requirements_json', source);
    } else {
      throw new Error('invalid_mode');
    }
    return {profile, data};
  }
  function showError(error) {
    const code = error && error.message;
    if (code === 'missing_token' || code === 'http_401' || code === 'http_403') {
      message('目前沒有預覽權限，請使用具 db_operator 權限的 Token。');
    } else if (code === 'missing_profile') {
      message('請輸入已核准的 Profile Version ID。');
    } else if (code === 'invalid_file') {
      message('請選擇非空白 CSV／JSON／XLSX，且檔案大小不超過 10 MiB。');
    } else if (code === 'invalid_json') {
      message('請輸入合法 JSON 陣列，UTF-8 大小不超過 1 MiB。');
    } else if (code === 'http_400' || code === 'http_413' || code === 'http_422') {
      message('輸入格式、資料大小或 Profile 驗證未通過，請確認資料後再試。');
    } else if (code === 'http_503') {
      message('預覽服務目前未設定或不可用。');
    } else {
      message('預覽結果無法確認（網路、授權或回應契約異常）；本頁不會自動重新送出。');
    }
  }
  async function loadProfiles() {
    if (busy) return;
    const access = $('authToken').value.trim();
    if (!access) { message('請先輸入具備 Requirement 清單讀取權限的 Token。'); return; }
    invalidate();
    clearProfileOptions();
    const run = generation;
    const ctrl = new AbortController();
    controller = ctrl;
    busy = true;
    controls();
    message('正在讀取目前帳號可見的 Profile 清單…');
    try {
      const response = await fetch('/v1/requirement-import-profiles', {
        method: 'GET', headers: {Authorization: 'Bearer ' + access},
        signal: ctrl.signal, credentials: 'omit', cache: 'no-store', redirect: 'error'
      });
      if (run !== generation || ctrl.signal.aborted) return;
      if (!response.ok) throw new Error('http_' + response.status);
      const data = await response.json();
      if (run !== generation || ctrl.signal.aborted) return;
      if (!data || !Array.isArray(data.items)) throw new Error('invalid_contract');
      let count = 0;
      for (const profile of data.items) {
        if (count >= 100) break;
        if (!profile || typeof profile !== 'object' || Array.isArray(profile) ||
            !(profile.enabled === true || profile.enabled === 1) ||
            typeof profile.active_version_id !== 'string' ||
            profile.active_version_id.length < 1 || profile.active_version_id.length > 128 ||
            typeof profile.profile_id !== 'string') continue;
        const option = document.createElement('option');
        option.value = profile.active_version_id;
        option.textContent = String(profile.name || profile.profile_id).slice(0, 80) +
          '｜' + profile.active_version_id;
        $('previewProfileSelect').appendChild(option);
        count++;
      }
      message(count ? '已讀取 ' + count + ' 個可選 Profile；請選取版本，後端將核驗其核准狀態。'
        : '未找到可選的已啟用 Profile，仍可貼上已核准的版本 ID。');
    } catch (_) {
      if (run !== generation || ctrl.signal.aborted) return;
      clearProfileOptions();
      message('無法取得 Profile 清單（權限、服務或網路異常）。可手動輸入已核准的版本 ID。');
    } finally {
      if (controller === ctrl) controller = null;
      busy = false;
      controls();
    }
  }
  async function submitPreview() {
    if (busy) return;
    let payload;
    try {
      if (!$('authToken').value.trim()) throw new Error('missing_token');
      payload = buildPayload();
    } catch (error) { showError(error); return; }
    invalidate();
    const run = generation;
    const access = $('authToken').value.trim();
    const ctrl = new AbortController();
    controller = ctrl;
    busy = true;
    controls();
    message('資料正在預覽；不會建立任務或觸發排程。');
    try {
      const response = await fetch('/v1/requirement-task-previews', {
        method: 'POST',
        headers: {Authorization: 'Bearer ' + access},
        body: payload.data,
        signal: ctrl.signal, credentials: 'omit', cache: 'no-store', redirect: 'error'
      });
      if (run !== generation || ctrl.signal.aborted) return;
      if (!response.ok) throw new Error('http_' + response.status);
      const result = await response.json();
      if (run !== generation || ctrl.signal.aborted) return;
      render(result, payload.profile);
      message('已取得標準化預覽取樣；沒有建立任務、執行批次或持久化結果。');
    } catch (error) {
      if (run !== generation || ctrl.signal.aborted) return;
      clearResult();
      showError(error);
    } finally {
      if (controller === ctrl) controller = null;
      busy = false;
      controls();
    }
  }
  $('loadProfilesBtn').addEventListener('click', loadProfiles);
  $('previewProfileSelect').addEventListener('change', function () {
    const value = $('previewProfileSelect').value;
    if (!value) return;
    $('previewProfile').value = value;
    invalidate();
    message('已選取 Profile Version；請提供資料再預覽。');
  });
  $('previewBtn').addEventListener('click', submitPreview);
  $('previewClearBtn').addEventListener('click', function () {
    invalidate();
    $('previewFile').value = '';
    $('previewJson').value = '';
    message('已清除預覽與輸入內容；未修改伺服器資料。');
  });
  $('previewMode').addEventListener('change', selectMode);
  for (const id of ['previewProfile', 'previewFile', 'previewJson']) {
    $(id).addEventListener('change', function () {
      invalidate();
      message('輸入已變更，請重新預覽。');
    });
  }
  $('authToken').addEventListener('input', function () {
    invalidate();
    clearProfileOptions();
    $('previewProfile').value = '';
    message('Token 已變更，先前的預覽已清除。');
  });
  window.addEventListener('pagehide', function () {
    invalidate();
    clearProfileOptions();
    $('previewProfile').value = '';
    $('authToken').value = '';
    $('previewFile').value = '';
    $('previewJson').value = '';
  });
  controls();
  clearProfileOptions();
  selectMode();
})();