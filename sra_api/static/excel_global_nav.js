/* Single-source SRAF cross-page navigation for 9002 and standalone pages.
 * Only hardcoded same-origin paths; no remote menu data, HTML injection or secrets.
 */
(function () {
  'use strict';
  const MENU = [
    {title: 'ES 資料庫', links: [
      ['搜尋與編輯文件', '/editor'],
      ['新增文件', '/editor'],
      ['統計與檢核曲線儀表板', '/editor']
    ]},
    {title: '匯入管理', links: [
      ['Excel→SQL 匯入查詢儀表板', '/excel-to-sql-dashboard'],
      ['Excel 匯入作業中心', '/excel-to-sql-import-center'],
      ['任務 JSON 管理', '/excel-to-sql-task-configs'],
      ['SQL 來源資料編輯器', '/excel-to-sql-source-editor'],
      ['SQL 來源資料統計儀表板', '/excel-to-sql-source-dashboard']
    ]},
    {title: '系統管理', links: [['帳號審核', '/editor']]},
    {title: '帳號安全', links: [
      ['變更密碼', '/editor'], ['帳號操作記錄', '/editor']
    ]}
  ];
  const PAGE_LINKS = [
    {id: 'agentDataFlowBtn', label: '代理人資料流程圖', path: '/agent-data-flow'},
    {id: 'reportJobsBtn', label: '報告任務進度', path: '/report-jobs'},
    {id: 'requirementProductBtn', label: '需求任務與執行紀錄', path: '/requirement-product'}
  ];
  const currentPath = window.location && window.location.pathname || '';
  const makeLink = (label, path, cssClass) => {
    const a = document.createElement('a');
    a.textContent = label;
    a.href = path;
    a.className = cssClass;
    if (currentPath === path) a.setAttribute('aria-current', 'page');
    return a;
  };
  function renderShared(nav) {
    // Some pages contain a separate whoami display; preserve that owned node.
    const identity = Array.from(nav.children).filter(node => node.id === 'whoami');
    nav.replaceChildren(...identity);
    for (const group of MENU) {
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = group.title;
      const panel = document.createElement('div');
      panel.className = 'global-nav-actions';
      for (const [label, path] of group.links) {
        panel.appendChild(makeLink(label, path, 'global-nav-link'));
      }
      details.append(summary, panel);
      nav.appendChild(details);
    }
    for (const item of PAGE_LINKS) {
      nav.appendChild(makeLink(item.label, item.path, 'global-nav-direct'));
    }
    nav.appendChild(makeLink('前往登入 / 編輯器', '/editor', 'global-nav-direct'));
  }
  const editorSlot = document.getElementById('srafEditorExternalNav');
  if (editorSlot) {
    for (const item of PAGE_LINKS) {
      const button = document.createElement('button');
      button.id = item.id;
      button.type = 'button';
      button.textContent = item.label;
      button.className = 'nav-root-btn secondary';
      editorSlot.appendChild(button);
    }
  }

  const navs = Array.from(document.querySelectorAll('.global-tree-nav'));
  const supportsHover = typeof window.matchMedia === 'function' &&
    window.matchMedia('(hover: hover)').matches;
  for (const nav of navs) {
    renderShared(nav);
    const menus = Array.from(nav.querySelectorAll(':scope > details'));
    const closeTimers = new WeakMap();
    const closeDelayMs = 600;
    const cancelClose = (menu) => {
      const timer = closeTimers.get(menu);
      if (timer) window.clearTimeout(timer);
      closeTimers.delete(menu);
    };
    const closeMenus = (except) => menus.forEach((menu) => {
      if (menu !== except) { cancelClose(menu); menu.open = false; }
    });
    for (const menu of menus) {
      menu.addEventListener('mouseenter', () => {
        if (!supportsHover) return;
        cancelClose(menu); closeMenus(menu); menu.open = true;
      });
      menu.addEventListener('toggle', () => {
        if (menu.open) closeMenus(menu);
      });
      menu.addEventListener('mouseleave', () => {
        if (!supportsHover) return;
        cancelClose(menu);
        closeTimers.set(menu, window.setTimeout(() => {
          menu.open = false; closeTimers.delete(menu);
        }, closeDelayMs));
      });
    }
    document.addEventListener('pointerdown', (event) => {
      if (!nav.contains(event.target)) closeMenus();
    });
    nav.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeMenus();
        nav.querySelector('summary:focus')?.blur();
      }
    });
  }
})();
