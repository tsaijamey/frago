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
import { usePageStore } from '@/stores/pageStore';
import { parsePath, pathForPage, writeLocationRoute } from '@/routes';

export function useHashRoute(): void {
  useEffect(() => {
    const {
      currentPage,
      currentTaskId,
      currentRecipeName,
      currentProjectId,
      currentTodoId,
      currentRecipeAppId,
    } = usePageStore.getState();
    const id =
      currentTaskId ?? currentRecipeName ?? currentProjectId ?? currentTodoId ?? currentRecipeAppId;
    writeLocationRoute(pathForPage(currentPage, id), true);

    const sync = () => {
      const route = parsePath(window.location.hash);
      const state = usePageStore.getState();
      const currentId =
        state.currentTaskId ??
        state.currentRecipeName ??
        state.currentProjectId ??
        state.currentTodoId ??
        state.currentRecipeAppId;
      // 旧名字的地址（`/teaming`）读得出页面，但地址栏要改写成现在的名字，否则人
      // 从这里复制出去的还是旧的那个。
      const canonical = pathForPage(route.page, route.id);
      if (window.location.hash.replace(/^#/, '').split('?')[0] !== canonical) {
        writeLocationRoute(canonical, true);
      }
      // 地址栏说的就是现在这一页时不动手：`switchPage` 刚写完地址也会触发
      // hashchange，再落一次状态等于把同一次跳转做两遍。
      if (state.currentPage === route.page && currentId === route.id) return;
      state.applyRoute(route.page, route.id);
    };

    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
    };
  }, []);
}
