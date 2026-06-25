const state = { token: localStorage.getItem('sra_editor_token') || '', user: null, source: null, formConfig: null, schema: null, latestHits: [], editorMode: 'new', loadedDocId: '', searchPage: 1, searchHasMore: false, activeNavRoot: '', auditRows: [], auditPage: 1, accountAuditRows: [], accountAuditPage: 1, usageStatsAuditRows: [], usageStatsAuditPage: 1, usageStatsSource: 'document', usageStatsView: 'mine', usageStatsUserOptions: [], usageStatsSelectedUsers: [], usageStatsClientHostOptions: [], usageStatsSelectedClientHosts: [] };
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
function formatApiError(data, fallback='') {
  const detail = data && (data.detail || data.message || data.error);
  if (Array.isArray(detail)) return detail.map(item => item.msg || JSON.stringify(item)).join('\n');
  if (detail && typeof detail === 'object') return JSON.stringify(detail, null, 2);
  return String(detail || fallback || '請求失敗');
}
function setStatus(id, message, kind='') {
  const el = $(id); el.textContent = message || ''; el.className = 'status' + (message ? '' : ' hidden') + (kind ? ' ' + kind : '');
}
function setEditorMode(mode) {
  state.editorMode = mode === 'edit' ? 'edit' : 'new';
  const lock = state.editorMode === 'edit';
  $('docIndex').disabled = lock;
  $('editorModeBanner').textContent = lock
    ? '目前模式：編輯既有文件模式（index 已鎖定）'
    : '目前模式：新增文件模式（可選 index）';
  $('editorModeBanner').className = 'status ' + (lock ? 'ok' : '');
  $('docIndexHint').textContent = lock
    ? '目前為編輯既有文件模式，index 已鎖定以避免誤寫到其他索引。'
    : '目前為新增文件模式，可先選擇要寫入的 index。';
}
function syncDocIndexOptions(selected) {
  $('docIndex').innerHTML = $('indexSelect').innerHTML || '';
  if (selected) $('docIndex').value = selected;
  if (!$('docIndex').value && $('indexSelect').value) $('docIndex').value = $('indexSelect').value;
}
function attrSelectorValue(value) { return String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"'); }
function getPath(obj, path) {
  const p = String(path || '');
  if (!p) return undefined;
  if (obj && typeof obj === 'object' && Object.prototype.hasOwnProperty.call(obj, p)) return obj[p];
  return p.split('.').filter(Boolean).reduce((cur, key) => {
    if (!cur || typeof cur !== 'object') return undefined;
    if (Object.prototype.hasOwnProperty.call(cur, key)) return cur[key];
    return undefined;
  }, obj);
}
function setPath(obj, path, value) {
  const p = String(path || '');
  const keys = p.split('.').filter(Boolean); if (!keys.length) return;
  let cur = obj;
  keys.slice(0, -1).forEach(k => { if (!cur[k] || typeof cur[k] !== 'object' || Array.isArray(cur[k])) cur[k] = {}; cur = cur[k]; });
  cur[keys[keys.length - 1]] = value;
  if (obj && typeof obj === 'object' && Object.prototype.hasOwnProperty.call(obj, p) && keys.length > 1) obj[p] = value;
}
function csvToArray(value) { return String(value || '').split(',').map(v => v.trim()).filter(Boolean); }
function arrayToCsv(value) { return Array.isArray(value) ? value.join(', ') : ''; }
async function api(path, opts={}) {
  const headers = Object.assign({'Content-Type': 'application/json'}, opts.headers || {});
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  const res = await fetch(path, Object.assign({}, opts, {headers}));
  const text = await res.text();
  let data = {}; try { data = text ? JSON.parse(text) : {}; } catch { data = {detail: text}; }
  if (!res.ok) throw new Error(formatApiError(data, res.statusText));
  return data;
}
function titleFromSource(src) {
  const md = Array.isArray(src.multidim_event_json)
    ? src.multidim_event_json.find(item => item && typeof item === 'object' && !Array.isArray(item))
    : (src.multidim_event_json && typeof src.multidim_event_json === 'object' ? src.multidim_event_json : null);
  return src.title || src.subject || (src.communication && src.communication.subject) || (src.rawInfo && (src.rawInfo.title || src.rawInfo.date)) || (md && md.article_title) || src.uuid || '(無標題)';
}
function schemaSections() { return (state.schema && Array.isArray(state.schema.sections)) ? state.schema.sections : []; }
