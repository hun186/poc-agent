(function () {
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }
  function normalizeBucketLabel(value, bucket) {
    const text = String(value || '');
    if (!text) return '';
    if (bucket === 'hour' || bucket === '6_hours' || bucket === '12_hours') return text.replace('T', ' ').slice(0, 16);
    if (bucket === 'month') return text.slice(0, 7);
    return text.slice(0, 10);
  }
  function compactBucketLabel(label, bucket) {
    const text = String(label || '');
    if (bucket === 'hour' || bucket === '6_hours' || bucket === '12_hours') return text.slice(5, 16);
    if (bucket === 'month') return text;
    return text.slice(5);
  }
  function renderTimeSeriesChart(options) {
    const rows = options.rows || [];
    const bucket = options.bucket || 'day';
    const bucketLabel = options.bucketLabel || '每日';
    const titleEl = options.titleEl;
    const summaryEl = options.summaryEl;
    const chartEl = options.chartEl;
    const emptyText = options.emptyText || '目前篩選條件下無資料';
    const seriesName = options.seriesName || 'audit 筆數';
    const data = rows.map((row) => ({
      bucket: normalizeBucketLabel(row.bucket_start ?? row.day ?? row.bucket, bucket),
      count: Number(row.count || 0),
    })).filter((row) => row.bucket);
    const total = data.reduce((sum, row) => sum + row.count, 0);
    if (titleEl) titleEl.textContent = `${bucketLabel} ${seriesName}（套用目前篩選）`;
    if (summaryEl) summaryEl.textContent = data.length ? `${data.length} 個區間，共 ${total} 筆` : `無符合篩選的 ${seriesName}`;
    if (!chartEl) return;
    if (!data.length) {
      chartEl.className = 'chart-empty';
      chartEl.textContent = emptyText;
      return;
    }
    const width = 920;
    const height = 260;
    const margin = { top: 18, right: 22, bottom: 46, left: 52 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;
    const maxCount = Math.max(...data.map((row) => row.count), 1);
    const x = (index) => margin.left + (data.length === 1 ? innerWidth / 2 : (index * innerWidth) / (data.length - 1));
    const y = (count) => margin.top + innerHeight - (count / maxCount) * innerHeight;
    const points = data.map((row, index) => `${x(index)},${y(row.count)}`).join(' ');
    const yTicks = [0, Math.ceil(maxCount / 2), maxCount].filter((value, index, arr) => arr.indexOf(value) === index);
    const maxLabels = 7;
    const labelEvery = Math.max(1, Math.ceil(data.length / maxLabels));
    const grid = yTicks.map((value) => {
      const yy = y(value);
      return `<line class="chart-grid" x1="${margin.left}" y1="${yy}" x2="${width - margin.right}" y2="${yy}"></line><text class="chart-label" x="${margin.left - 8}" y="${yy + 4}" text-anchor="end">${escapeHtml(value)}</text>`;
    }).join('');
    const labels = data.map((row, index) => {
      if (index % labelEvery !== 0 && index !== data.length - 1) return '';
      return `<text class="chart-label" x="${x(index)}" y="${height - 18}" text-anchor="middle">${escapeHtml(compactBucketLabel(row.bucket, bucket))}</text>`;
    }).join('');
    const circles = data.map((row, index) => `<circle class="chart-point" cx="${x(index)}" cy="${y(row.count)}" r="4"><title>${escapeHtml(row.bucket)}：${escapeHtml(row.count)} 筆</title></circle>`).join('');
    chartEl.className = '';
    chartEl.innerHTML = `<svg class="audit-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(bucketLabel)} ${escapeHtml(seriesName)}曲線圖" preserveAspectRatio="none">${grid}<line class="chart-axis" x1="${margin.left}" y1="${margin.top + innerHeight}" x2="${width - margin.right}" y2="${margin.top + innerHeight}"></line><line class="chart-axis" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${margin.top + innerHeight}"></line><polyline class="chart-line" points="${points}"></polyline>${circles}${labels}</svg>`;
  }
  function uniqueSortedValues(values) {
    return [...new Set((values || []).map((value) => String(value || '').trim()).filter(Boolean))].sort();
  }
  function visibleMultiFilterOptions(values, searchEl) {
    const q = searchEl ? searchEl.value.trim().toLowerCase() : '';
    return uniqueSortedValues(values).filter((value) => !q || value.toLowerCase().includes(q));
  }
  function renderMultiFilterOptions(options) {
    const box = options.optionsEl;
    if (!box) return;
    const selected = new Set(options.selectedValues || []);
    const visible = visibleMultiFilterOptions(options.values || [], options.searchEl);
    const attr = options.dataAttr || 'data-multi-filter-value';
    box.innerHTML = visible.map((value) => `<label class="multi-filter-option"><input type="checkbox" ${attr}="${escapeHtml(value)}" ${selected.has(value) ? 'checked' : ''} /> <span>${escapeHtml(value)}</span></label>`).join('') || `<p class="muted">${escapeHtml(options.emptyText || '沒有符合關鍵字的選項。')}</p>`;
    box.querySelectorAll(`[${attr}]`).forEach((input) => {
      input.onchange = () => {
        const value = input.getAttribute(attr);
        const current = new Set(options.getSelectedValues ? options.getSelectedValues() : options.selectedValues || []);
        if (input.checked) current.add(value); else current.delete(value);
        if (options.onSelectionChange) options.onSelectionChange([...current]);
      };
    });
  }
  function summarizeMultiFilterSelection(options) {
    const selected = options.selectedValues || [];
    if (options.hiddenInput) options.hiddenInput.value = selected.join(',');
    if (!options.summaryEl) return;
    if (!selected.length) options.summaryEl.textContent = options.allLabel || '全部';
    else options.summaryEl.textContent = selected.length <= 2 ? selected.join(', ') : `已選 ${selected.length} ${options.unitLabel || '個項目'}`;
  }
  function setVisibleMultiFilterSelection(options) {
    const visible = visibleMultiFilterOptions(options.values || [], options.searchEl);
    const selected = new Set(options.selectedValues || []);
    visible.forEach((value) => { if (options.checked) selected.add(value); else selected.delete(value); });
    return [...selected];
  }
  function renderSummaryCards(targetEl, cards) {
    if (!targetEl) return;
    targetEl.innerHTML = (cards || []).map((card) => `<div class="stat-card"><div class="muted">${escapeHtml(card.label)}</div><div class="stat-metric">${escapeHtml(card.value)}</div><div class="muted">${escapeHtml(card.hint || '')}</div></div>`).join('');
  }
  function supportsHoverNav() {
    return Boolean(window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches);
  }
  function bindProgressiveNav(options) {
    const nav = options.nav;
    if (!nav) return;
    const rootSelector = options.rootSelector || '[data-nav-root]';
    const levelSelector = options.levelSelector || '.nav-level';
    const getActiveRoot = options.getActiveRoot || (() => '');
    const setActiveRoot = options.setActiveRoot;
    const collapse = options.collapse || (() => setActiveRoot && setActiveRoot(''));
    const openDelayMs = Number(options.openDelayMs || 80);
    const closeDelayMs = Number(options.closeDelayMs || 360);
    const levelCloseDelayMs = Number(options.levelCloseDelayMs || 360);
    let closeTimer = 0;
    let openTimer = 0;
    const levelCloseTimers = new WeakMap();
    const clearLevelCloseTimer = (details) => {
      const timer = levelCloseTimers.get(details);
      if (timer) window.clearTimeout(timer);
      levelCloseTimers.delete(details);
    };
    const clearTimers = () => { window.clearTimeout(closeTimer); window.clearTimeout(openTimer); };
    nav.querySelectorAll(rootSelector).forEach((btn) => {
      btn.addEventListener('click', () => setActiveRoot(getActiveRoot() === btn.dataset.navRoot ? '' : btn.dataset.navRoot));
      btn.addEventListener('pointerenter', (event) => {
        if (event.pointerType !== 'mouse' || !supportsHoverNav()) return;
        clearTimers();
        openTimer = window.setTimeout(() => setActiveRoot(btn.dataset.navRoot), openDelayMs);
      });
    });
    nav.addEventListener('pointerenter', (event) => {
      if (event.pointerType === 'mouse' && supportsHoverNav()) window.clearTimeout(closeTimer);
    });
    nav.addEventListener('pointerleave', (event) => {
      if (event.pointerType !== 'mouse' || !supportsHoverNav()) return;
      window.clearTimeout(closeTimer);
      closeTimer = window.setTimeout(collapse, closeDelayMs);
    });
    nav.querySelectorAll(levelSelector).forEach((details) => {
      details.addEventListener('pointerenter', (event) => {
        if (event.pointerType !== 'mouse' || !supportsHoverNav()) return;
        clearLevelCloseTimer(details);
        details.open = true;
      });
      details.addEventListener('pointerleave', (event) => {
        if (event.pointerType !== 'mouse' || !supportsHoverNav()) return;
        clearLevelCloseTimer(details);
        levelCloseTimers.set(details, window.setTimeout(() => { details.open = false; }, levelCloseDelayMs));
      });
    });
  }

  function ensurePagerStyles() {
    if (document.getElementById('sraAuditToolsPagerStyles')) return;
    const style = document.createElement('style');
    style.id = 'sraAuditToolsPagerStyles';
    style.textContent = `
      .pager {
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
        flex-wrap: wrap !important;
        margin: 10px 0 !important;
      }
      .pager button { flex: 0 0 auto !important; padding: 7px 10px; }
      .pager .pager-jump,
      .pager .pager-size {
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: 0 !important;
        white-space: nowrap !important;
      }
      .pager .pager-size label {
        display: inline-flex !important;
        align-items: center !important;
        gap: 4px !important;
        margin: 0 !important;
        font-size: 13px !important;
        font-weight: 600 !important;
      }
      .pager .pager-size select {
        width: auto !important;
        min-width: 72px !important;
        flex: 0 0 auto !important;
        padding: 7px 9px !important;
        box-sizing: border-box !important;
      }
      .pager .pager-jump input,
      .pager .pager-size input,
      .pager input[type="number"] {
        width: 78px !important;
        min-width: 78px !important;
        max-width: 78px !important;
        flex: 0 0 78px !important;
        padding: 7px 9px !important;
        box-sizing: border-box !important;
      }
      .pager .sr-only {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        padding: 0 !important;
        margin: -1px !important;
        overflow: hidden !important;
        clip: rect(0, 0, 0, 0) !important;
        white-space: nowrap !important;
        border: 0 !important;
      }
    `;
    document.head.appendChild(style);
  }

  function clampPageSize(value, fallback) {
    const base = Number(fallback || 25);
    const parsed = Number(value);
    const raw = Number.isFinite(parsed) ? parsed : (Number.isFinite(base) ? base : 25);
    return Math.max(1, Math.min(1000, Math.floor(raw)));
  }

  function pagerRoot(options) {
    const ids = [options.infoId, options.firstId, options.prevId, options.inputId, options.gotoId, options.nextId, options.lastId];
    for (const id of ids) {
      const el = id ? document.getElementById(id) : null;
      const root = el ? el.closest('.pager') : null;
      if (root) return root;
    }
    const els = [options.infoEl, options.firstEl, options.prevEl, options.inputEl, options.gotoEl, options.nextEl, options.lastEl];
    for (const el of els) {
      const root = el ? el.closest('.pager') : null;
      if (root) return root;
    }
    return null;
  }

  function pageSizeControlId(options, suffix) {
    const base = options.inputId || options.infoId || 'pager';
    return `${base}PageSize${suffix}`;
  }

  function syncPageSizeControls(options, pageSize) {
    const root = pagerRoot(options);
    if (!root) return;
    const normalized = clampPageSize(pageSize, options.defaultPageSize || 25);
    const select = root.querySelector('[data-pager-size-select]');
    const input = root.querySelector('[data-pager-size-input]');
    if (select) select.value = Array.from(select.options).some((option) => Number(option.value) === normalized) ? String(normalized) : '';
    if (input) input.value = String(normalized);
  }

  function ensurePageSizeControls(options) {
    if (!options.getPageSize || !options.setPageSize) return;
    const root = pagerRoot(options);
    if (!root || root.querySelector('[data-pager-size-control]')) return;
    const sizes = (options.pageSizeOptions || [10, 25, 50, 100, 200]).map((value) => clampPageSize(value, 25));
    const uniqueSizes = [...new Set(sizes)].sort((a, b) => a - b);
    const currentSize = clampPageSize(options.getPageSize(), options.defaultPageSize || uniqueSizes[0] || 25);
    const control = document.createElement('span');
    control.className = 'pager-size';
    control.dataset.pagerSizeControl = 'true';
    const selectId = pageSizeControlId(options, 'Select');
    const inputId = pageSizeControlId(options, 'Input');
    control.innerHTML = `<label for="${escapeHtml(selectId)}">每頁顯示</label><select id="${escapeHtml(selectId)}" data-pager-size-select aria-label="每頁顯示筆數選單"><option value="">自訂</option>${uniqueSizes.map((size) => `<option value="${size}">${size}</option>`).join('')}</select><label class="sr-only" for="${escapeHtml(inputId)}">直接輸入每頁筆數</label><input id="${escapeHtml(inputId)}" data-pager-size-input type="number" min="1" max="1000" inputmode="numeric" aria-label="直接輸入每頁筆數" /><span class="muted">筆</span>`;
    const first = typeof options.firstId === 'string' ? document.getElementById(options.firstId) : options.firstEl;
    root.insertBefore(control, first || root.firstChild);
    const select = control.querySelector('[data-pager-size-select]');
    const input = control.querySelector('[data-pager-size-input]');
    const applySize = (value) => {
      const size = clampPageSize(value, options.getPageSize());
      options.setPageSize(size);
      if (options.setPage) options.setPage(1);
      if (input) input.value = String(size);
      if (select) select.value = uniqueSizes.includes(size) ? String(size) : '';
      if (options.renderPage) options.renderPage();
    };
    if (select) select.onchange = () => { if (select.value) applySize(select.value); };
    if (input) {
      input.onkeydown = (ev) => { if (ev.key === 'Enter') applySize(ev.currentTarget.value); };
      input.onchange = () => applySize(input.value);
    }
    syncPageSizeControls(options, currentSize);
  }

  // Caller supplies the already filtered and sorted rows; this helper only slices the visible page range.
  function paginateRows(rows, page, pageSize) {
    const allRows = Array.isArray(rows) ? rows : [];
    const size = Math.max(1, Number(pageSize || 25));
    const total = allRows.length;
    const totalPages = Math.max(1, Math.ceil(total / size));
    const currentPage = Math.min(Math.max(1, Number(page || 1)), totalPages);
    const startIndex = (currentPage - 1) * size;
    return {
      rows: allRows.slice(startIndex, startIndex + size),
      page: currentPage,
      pageSize: size,
      total,
      totalPages,
      start: total ? startIndex + 1 : 0,
      end: Math.min(total, startIndex + size),
    };
  }

  function updatePager(options) {
    ensurePagerStyles();
    const pageData = options.pageData || {};
    const currentPage = Math.max(1, Number(pageData.page || options.page || 1));
    const pageSize = Math.max(1, Number(pageData.pageSize || pageData.page_size || options.pageSize || 25));
    const total = Math.max(0, Number(pageData.total || options.total || 0));
    const totalPages = Math.max(1, Number(pageData.totalPages || Math.ceil(total / pageSize) || 1));
    const start = total ? Number(pageData.start || ((currentPage - 1) * pageSize + 1)) : 0;
    const end = total ? Number(pageData.end || Math.min(total, currentPage * pageSize)) : 0;
    const info = options.infoEl || (options.infoId ? document.getElementById(options.infoId) : null);
    const first = options.firstEl || (options.firstId ? document.getElementById(options.firstId) : null);
    const prev = options.prevEl || (options.prevId ? document.getElementById(options.prevId) : null);
    const input = options.inputEl || (options.inputId ? document.getElementById(options.inputId) : null);
    const goto = options.gotoEl || (options.gotoId ? document.getElementById(options.gotoId) : null);
    const next = options.nextEl || (options.nextId ? document.getElementById(options.nextId) : null);
    const last = options.lastEl || (options.lastId ? document.getElementById(options.lastId) : null);
    if (info) info.textContent = options.label || `第 ${currentPage} / ${totalPages} 頁，顯示 ${start}-${end} 筆，共 ${total} 筆`;
    [first, prev].forEach((el) => { if (el) el.disabled = currentPage <= 1; });
    [next, last].forEach((el) => { if (el) el.disabled = currentPage >= totalPages; });
    if (input) {
      input.value = String(currentPage);
      input.min = '1';
      input.max = String(totalPages);
      input.setAttribute('aria-label', options.inputLabel || '頁數');
    }
    if (goto) goto.disabled = totalPages <= 1 && currentPage === 1;
    syncPageSizeControls(options, pageSize);
    return { page: currentPage, pageSize, total, totalPages, start, end };
  }
  function bindPager(options) {
    ensurePagerStyles();
    ensurePageSizeControls(options);
    const getPage = options.getPage || (() => 1);
    const setPage = options.setPage || (() => {});
    const renderPage = options.renderPage || (() => {});
    const jumpTo = (page) => { setPage(page); renderPage(); };
    const bind = (idOrEl, handler) => {
      const el = typeof idOrEl === 'string' ? document.getElementById(idOrEl) : idOrEl;
      if (el) el.onclick = handler;
    };
    bind(options.firstId || options.firstEl, () => jumpTo(1));
    bind(options.prevId || options.prevEl, () => jumpTo(getPage() - 1));
    bind(options.nextId || options.nextEl, () => jumpTo(getPage() + 1));
    bind(options.lastId || options.lastEl, () => jumpTo(Number.MAX_SAFE_INTEGER));
    bind(options.gotoId || options.gotoEl, () => {
      const input = typeof options.inputId === 'string' ? document.getElementById(options.inputId) : options.inputEl;
      jumpTo(Number(input?.value || 1));
    });
    const input = typeof options.inputId === 'string' ? document.getElementById(options.inputId) : options.inputEl;
    if (input) input.onkeydown = (ev) => { if (ev.key === 'Enter') jumpTo(Number(ev.currentTarget.value || 1)); };
  }

  window.SraAuditTools = {
    escapeHtml,
    normalizeBucketLabel,
    compactBucketLabel,
    renderTimeSeriesChart,
    renderSummaryCards,
    uniqueSortedValues,
    visibleMultiFilterOptions,
    renderMultiFilterOptions,
    summarizeMultiFilterSelection,
    setVisibleMultiFilterSelection,
    bindProgressiveNav,
    paginateRows,
    updatePager,
    bindPager,
  };
}());
