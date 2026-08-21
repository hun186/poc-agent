(function () {
  const navs = document.querySelectorAll('.global-tree-nav');

  navs.forEach((nav) => {
    const menus = Array.from(nav.querySelectorAll(':scope > details'));

    const closeMenus = (except) => {
      menus.forEach((menu) => {
        if (menu !== except) menu.open = false;
      });
    };

    menus.forEach((menu) => {
      menu.addEventListener('toggle', () => {
        if (menu.open) closeMenus(menu);
      });

      menu.addEventListener('mouseleave', () => {
        menu.open = false;
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
