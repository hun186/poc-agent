(function () {
  const navs = document.querySelectorAll('.global-tree-nav');
  const supportsHover = window.matchMedia('(hover: hover)').matches;

  navs.forEach((nav) => {
    const menus = Array.from(nav.querySelectorAll(':scope > details'));
    const closeTimers = new WeakMap();
    const closeDelayMs = 600;

    const cancelClose = (menu) => {
      const timer = closeTimers.get(menu);
      if (timer) window.clearTimeout(timer);
      closeTimers.delete(menu);
    };

    const closeMenus = (except) => {
      menus.forEach((menu) => {
        if (menu !== except) {
          cancelClose(menu);
          menu.open = false;
        }
      });
    };

    menus.forEach((menu) => {
      menu.addEventListener('mouseenter', () => {
        if (!supportsHover) return;
        cancelClose(menu);
        closeMenus(menu);
        menu.open = true;
      });

      menu.addEventListener('toggle', () => {
        if (menu.open) closeMenus(menu);
      });

      menu.addEventListener('mouseleave', () => {
        if (!supportsHover) return;
        cancelClose(menu);
        closeTimers.set(menu, window.setTimeout(() => {
          menu.open = false;
          closeTimers.delete(menu);
        }, closeDelayMs));
      });
    });

    document.addEventListener('pointerdown', (event) => {
      if (!nav.contains(event.target)) closeMenus();
    });

    nav.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeMenus();
        nav.querySelector('summary:focus')?.blur();
      }
    });
  });
})();
