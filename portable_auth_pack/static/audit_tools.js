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
  };
}());
