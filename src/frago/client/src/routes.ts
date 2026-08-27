/**
 * 地址与页面的对应关系。
 *
 * 在这之前界面没有地址一说：点进配方详情，地址栏还停在首页，刷一下就被弹回会话
 * 工作台；想把某一页发给别人，只能发一句"你自己点进去"。这份表把每一页配上一个
 * 地址，刷新、前进后退、收藏、分享才成立。
 *
 * 走的是 `#` 后面那一截，不是真实路径。原因是这套界面同时要在浏览器里（http://）
 * 和桌面壳里（file://）跑，打包时资源路径是相对的（vite `base: './'`）——真实路径
 * 一深，`./assets/x.js` 就会去 `/todos/assets/x.js` 找，两边一起白屏。`#` 后面的
 * 内容不参与资源寻址，两种壳里表现一致。
 */

import type { PageType } from '@/stores/pageStore';

/** 地址栏里没有内容时落在哪一页。 */
export const HOME_PAGE: PageType = 'session_workbench';

/**
 * 每一页占地址的哪一段。
 *
 * 详情页与它的清单页共用同一段（`/recipes` 与 `/recipes/<名字>`），因为它们本来
 * 就是同一件东西的两个深浅——分成两段会让地址读起来像两个不相干的地方。
 */
const PAGE_SEGMENT: Record<PageType, string> = {
  live: 'live',
  session_workbench: 'sessions',
  dashboard: 'dashboard',
  tasks: 'tasks',
  task_detail: 'tasks',
  recipes: 'recipes',
  recipe_detail: 'recipes',
  data_repo: 'data',
  todos: 'todos',
  todo_detail: 'todos',
  skills: 'skills',
  guide: 'guide',
  settings: 'settings',
  newTask: 'new',
  workspace: 'workspace',
  project_detail: 'workspace',
};

/** 某一段后面再跟一个编号时，落到哪一页。 */
const DETAIL_PAGE: Record<string, PageType> = {
  tasks: 'task_detail',
  recipes: 'recipe_detail',
  todos: 'todo_detail',
  workspace: 'project_detail',
};

/** 某一段单独出现时（后面没有编号），落到哪一页。 */
const LIST_PAGE: Record<string, PageType> = (() => {
  const table: Record<string, PageType> = {};
  // 反向查表时详情页会与清单页争同一段。清单页赢：`/recipes` 该是清单，不是一个
  // 缺了编号的详情。
  for (const [page, segment] of Object.entries(PAGE_SEGMENT) as [PageType, string][]) {
    if (DETAIL_PAGE[segment] === page) continue;
    table[segment] = page;
  }
  return table;
})();

export interface Route {
  page: PageType;
  /** 详情页的编号；清单页为 null。 */
  id: string | null;
}

/** 这一页的地址是什么，形如 `/recipes/my-recipe`。 */
export function pathForPage(page: PageType, id?: string | null): string {
  const segment = PAGE_SEGMENT[page] ?? PAGE_SEGMENT[HOME_PAGE];
  return id ? `/${segment}/${encodeURIComponent(id)}` : `/${segment}`;
}

/**
 * 把一截地址读成页面。
 *
 * 认不出来的一律回首页，NEVER 渲染一张空白页：地址是人手敲的、是从聊天记录里粘
 * 来的，敲错一个字母就白屏，比回到首页糟得多。
 */
export function parsePath(raw: string): Route {
  const cleaned = raw.replace(/^#/, '').split('?')[0];
  const parts = cleaned.split('/').filter(Boolean).map((part) => {
    try {
      return decodeURIComponent(part);
    } catch {
      // 地址里有半截百分号编码。原样留着，让它去认段名，认不出就回首页。
      return part;
    }
  });

  if (parts.length === 0) return { page: HOME_PAGE, id: null };

  const [segment, ...rest] = parts;
  const id = rest.join('/');

  if (id) {
    const detail = DETAIL_PAGE[segment];
    if (detail) return { page: detail, id };
    // 这一段本来就没有详情页（`/settings/什么什么`）。当清单页处理，别把多出来的
    // 那截当编号塞进去。
  }

  const list = LIST_PAGE[segment];
  if (list) return { page: list, id: null };

  return { page: HOME_PAGE, id: null };
}

/** 地址栏现在指着哪一页。 */
export function readLocationRoute(): Route {
  if (typeof window === 'undefined') return { page: HOME_PAGE, id: null };
  return parsePath(window.location.hash);
}

/**
 * 把地址栏改成这一页。
 *
 * 已经指着同一页时什么都不做——重复的记录会让后退键退不动，人会以为界面卡了。
 */
export function writeLocationRoute(path: string, replace = false): void {
  if (typeof window === 'undefined') return;
  const target = `#${path}`;
  if (window.location.hash === target) return;
  const url = `${window.location.pathname}${window.location.search}${target}`;
  if (replace) {
    window.history.replaceState(null, '', url);
  } else {
    window.history.pushState(null, '', url);
  }
}
