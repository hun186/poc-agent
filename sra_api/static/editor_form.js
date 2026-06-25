function renderField(field, value, attrs) {
  const type = field.type || 'text';
  const common = `${attrs} data-field-type="${esc(type)}" placeholder="${esc(field.placeholder || '')}"`;
  const valueText = value ?? '';
  let control = '';
  if (type === 'textarea') {
    control = `<textarea ${common}>${esc(valueText)}</textarea>`;
  } else if (type === 'select') {
    const options = Array.isArray(field.options) ? field.options : [];
    control = `<select ${attrs} data-field-type="select">${options.map(opt => {
      const val = typeof opt === 'object' ? opt.value : opt;
      const label = typeof opt === 'object' ? (opt.label || opt.value) : opt;
      return `<option value="${esc(val)}" ${String(val) === String(valueText) ? 'selected' : ''}>${esc(label)}</option>`;
    }).join('')}</select>`;
  } else if (type === 'boolean') {
    control = `<input type="checkbox" ${attrs} data-field-type="boolean" ${value ? 'checked' : ''} />`;
  } else {
    const inputType = type === 'number' ? 'number' : (type === 'date' ? 'date' : 'text');
    control = `<input type="${inputType}" ${common} value="${esc(type === 'csv' ? arrayToCsv(value) : valueText)}" />`;
  }
  return `<div class="field-card ${field.compact_hide ? "compact-hide" : ""}"><label>${esc(field.label || field.path || "")}</label>${control}${field.help ? `<div class="field-help">${esc(field.help)}</div>` : ""}</div>`;
}
function renderConfiguredForm() {
  const sections = schemaSections();
  $('schemaDescription').textContent = state.schema ? `${state.schema.label || state.schema.name}：${state.schema.description || ''}` : '表單設定尚未載入。';
  $('formSections').innerHTML = sections.map((section, sidx) => {
    const desc = section.description ? `<div class="section-desc">${esc(section.description)}</div>` : '';
    if (section.type === 'array') {
      return `<div class="form-section" data-section-index="${sidx}"><div class="section-title">${esc(section.title || section.path || '清單')}</div>${desc}<div data-array-list="${esc(section.path)}"></div><button class="secondary" type="button" data-add-array="${esc(section.path)}">${esc(section.add_label || '新增')}</button></div>`;
    }
    return `<div class="form-section" data-section-index="${sidx}"><div class="section-title">${esc(section.title || '')}</div>${desc}<div class="field-grid">${(section.fields || []).map(field => renderField(field, getPath(state.source || {}, field.path), `data-doc-path="${esc(field.path)}"`)).join("")}</div></div>`;
  }).join('');
  renderArraySections();
  document.querySelectorAll('[data-add-array]').forEach(btn => btn.onclick = () => addArrayItem(btn.getAttribute('data-add-array')));
}
function renderArraySections() {
  schemaSections().filter(section => section.type === 'array').forEach(section => {
    const list = document.querySelector(`[data-array-list="${attrSelectorValue(section.path)}"]`);
    if (!list) return;
    // Always derive array containers from the schema section path, not only from
    // values already present in the loaded ES document.  Documents can omit an
    // array field entirely, but the configured editor schema still defines the
    // item shape needed by the "新增..." buttons.
    const items = ensureArrayAtPath(section.path);
    list.innerHTML = items.map((item, idx) => `<div class="array-item" data-array-path="${esc(section.path)}" data-array-index="${idx}"><strong>${esc(section.item_label || '項目')} #${idx + 1}</strong><div class="field-grid">${(section.fields || []).map(field => renderField(field, getPath(item, field.path), `data-array-field="${esc(field.path)}"`)).join("")}</div><button class="danger" type="button" data-remove-array="${esc(section.path)}" data-remove-index="${idx}">刪除此項目</button></div>`).join('');
  });
  document.querySelectorAll('[data-remove-array]').forEach(btn => btn.onclick = () => removeArrayItem(btn.getAttribute('data-remove-array'), Number(btn.getAttribute('data-remove-index'))));
}
function normalizeLeaf(value, path = '', preserveArrayPaths = new Set()) {
  if (Array.isArray(value)) {
    if (preserveArrayPaths.has(path)) return value.map(item => normalizeLeaf(item, path, preserveArrayPaths));
    if (value.length === 0) return [];
    if (value.length === 1) return normalizeLeaf(value[0], path, preserveArrayPaths);
    return value.map(item => normalizeLeaf(item, path, preserveArrayPaths));
  }
  if (value && typeof value === 'object') {
    const out = {};
    Object.entries(value).forEach(([k, v]) => {
      const childPath = path ? `${path}.${k}` : k;
      out[k] = normalizeLeaf(v, childPath, preserveArrayPaths);
    });
    return out;
  }
  return value;
}
function normalizeSource(source) {
  const normalizers = (state.schema && state.schema.normalizers) || {};
  const arrayPaths = new Set(normalizers.array_paths || []);
  schemaSections().filter(section => section.type === 'array').forEach(section => arrayPaths.add(section.path));
  schemaSections().flatMap(section => section.fields || []).filter(field => field.type === 'csv').forEach(field => arrayPaths.add(field.path));
  const out = normalizeLeaf(JSON.parse(JSON.stringify(source || {})), '', arrayPaths);
  (normalizers.json_object_paths || []).forEach(path => {
    let value = getPath(out, path);
    if (typeof value === 'string') {
      try { value = JSON.parse(value); } catch { value = {}; }
      setPath(out, path, value);
    }
    if (Array.isArray(value) && value.length === 1 && value[0] && typeof value[0] === 'object') {
      value = value[0];
      setPath(out, path, value);
    }
    const normalized = getPath(out, path);
    if (!normalized || typeof normalized !== 'object' || Array.isArray(normalized)) setPath(out, path, {});
  });
  arrayPaths.forEach(path => { if (!Array.isArray(getPath(out, path))) setPath(out, path, []); });
  schemaSections().filter(section => section.type === 'array').forEach(section => {
    const items = getPath(out, section.path) || [];
    setPath(out, section.path, items.map(item => typeof item === 'object' && item !== null ? item : {text: String(item || '')}));
  });
  return out;
}
function populateForm(source) {
  state.source = normalizeSource(source);
  renderConfiguredForm();
  applyCompactMode();
  $('jsonEditor').value = JSON.stringify(state.source, null, 2);
}
function readFieldValue(el) {
  const type = el.dataset.fieldType || 'text';
  if (type === 'boolean') return el.checked;
  if (type === 'number') return el.value === '' ? null : Number(el.value);
  if (type === 'csv') return csvToArray(el.value);
  return el.value;
}
function collectFormToSource() {
  if (!state.source) state.source = {};
  document.querySelectorAll('[data-doc-path]').forEach(el => setPath(state.source, el.dataset.docPath, readFieldValue(el)));
  schemaSections().filter(section => section.type === 'array').forEach(section => {
    const items = Array.from(document.querySelectorAll(`[data-array-path="${attrSelectorValue(section.path)}"]`)).map(box => {
      const out = {};
      box.querySelectorAll('[data-array-field]').forEach(el => setPath(out, el.dataset.arrayField, readFieldValue(el)));
      return out;
    });
    setPath(state.source, section.path, items);
  });
  $('jsonEditor').value = JSON.stringify(state.source, null, 2);
  return state.source;
}
function ensureArrayAtPath(path) {
  const current = getPath(state.source || {}, path);
  if (Array.isArray(current)) return current;
  const next = current === undefined || current === null || current === '' ? [] : [current];
  setPath(state.source, path, next);
  return next;
}
function defaultArrayFieldValue(field) {
  if (!field) return '';
  if (field.type === 'csv') return [];
  if (field.type === 'number') return null;
  if (field.type === 'boolean') return false;
  return '';
}
function addArrayItem(path) {
  try {
    collectFormToSource();
    const section = schemaSections().find(s => s.type === 'array' && s.path === path);
    if (!section) throw new Error(`找不到表單設定中的陣列欄位：${path}`);
    const item = {};
    // Use the configured section fields as the authoritative item shape.
    // A loaded ES document may not contain the first evidence/timeline/party/person
    // row yet, so the add button must never rely on a document sample row.
    (section.fields || []).forEach(field => setPath(item, field.path, defaultArrayFieldValue(field)));
    const arr = ensureArrayAtPath(path);
    arr.push(item);
    setPath(state.source, path, arr);
    populateForm(state.source);
    const rendered = document.querySelectorAll(`[data-array-path="${attrSelectorValue(path)}"]`).length;
    if (rendered < arr.length) throw new Error(`已更新資料但未成功渲染新增格子：${path}`);
    setStatus('saveStatus', `已新增 ${section.item_label || section.title || '項目'}，可在新格子輸入內容。`, 'ok');
  } catch (err) { setStatus('saveStatus', '新增欄位失敗：' + err.message, 'error'); }
}
function removeArrayItem(path, idx) {
  try {
    collectFormToSource();
    const arr = ensureArrayAtPath(path);
    arr.splice(idx, 1); setPath(state.source, path, arr); populateForm(state.source);
  } catch (err) { setStatus('saveStatus', '刪除欄位失敗：' + err.message, 'error'); }
}

function applyCompactMode() {
  const on = $('compactModeToggle').checked;
  $('formPane').classList.toggle('compact', on);
}

async function loadFormConfig(index) {
  const qs = new URLSearchParams(); if (index) qs.set('index', index);
  state.formConfig = await api('/v1/editor/form-config' + (qs.toString() ? '?' + qs.toString() : ''));
  state.schema = state.formConfig.schema;
  populateForm(state.source || {});
}
