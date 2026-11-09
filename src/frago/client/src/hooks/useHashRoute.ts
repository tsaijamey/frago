/**
 * 让地址栏和界面互相跟得住。
 *
 * 两个方向：界面往地址栏写由 `pageStore.switchPage` 管；地址栏往界面写归这里——
 * 人按后退键、手改地址、或者从别处粘一条链接进来，都得落到对应那一页。
 *
 * 挂载时还会把地址补齐一次（`replace`，不留历史记录）：首次打开地址栏是空的，
 * 不补的话第一次点导航会在历史里留下"空地址 → 某页"，后退键把人退到一个没有
 * 内容的地址上。
 */

import { useEffect } from 'react';
import { activeRouteId, usePageStore } from '@/stores/pageStore';
import { pathForPage, readLocationRoute, writeLocationRoute } from '@/routes';

export function useHashRoute(): void {
  useEffect(() => {
    const sync = () => {
      const route = readLocationRoute();
      const state = usePageStore.getState();
      const currentId = activeRouteId(state);
      // 旧名字的地址（`/teaming`）或直达真实路径（`/sessions/<id>`）读得出页面，
      // 但地址栏要改写成规范的 `/#/<路径>`，否则人从这里复制出去的还是旧地址。
      const canonical = pathForPage(route.page, route.id);
      const currentHashPath = window.location.hash.replace(/^#/, '').split('?')[0];
      if (currentHashPath !== canonical || window.location.pathname !== '/') {
        writeLocationRoute(canonical, true);
      }
      // 地址栏说的就是现在这一页时不动手：`switchPage` 刚写完地址也会触发
      // hashchange，再落一次状态等于把同一次跳转做两遍。
      if (state.currentPage === route.page && currentId === route.id) return;
      state.applyRoute(route.page, route.id);
    };

    const hasExplicitRoute =
      Boolean(window.location.hash && window.location.hash !== '#' && window.location.hash !== '#/') ||
      Boolean(
        (window.location.protocol === 'http:' || window.location.protocol === 'https:') &&
          window.location.pathname &&
          window.location.pathname !== '/' &&
          window.location.pathname !== '/index.html'
      );

    if (hasExplicitRoute) {
      sync();
    } else {
      const state = usePageStore.getState();
      writeLocationRoute(pathForPage(state.currentPage, activeRouteId(state)), true);
    }

    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
    };
  }, []);
}
