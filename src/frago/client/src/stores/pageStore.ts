/**
 * Page navigation state (Zustand)
 *
 * Owns: current page + the contextual ids that the active page needs
 * (task / recipe / project / todo). Split out of the former monolithic appStore.
 *
 * 这里同时是**地址的唯一出口**。`switchPage` 落状态的同时把地址栏改掉，所以刷新
 * 一下还停在原处、后退键能退回上一页、某一页可以直接发给别人。反过来那一路（人
 * 按了后退、或手改了地址）走 `applyRoute`：只落状态、不再写回地址，否则一次跳转
 * 会在历史里留下两条记录，后退键要按两下才动。
 */

import { create } from 'zustand';
import { pathForPage, readLocationRoute, writeLocationRoute } from '@/routes';

// Page type - Updated for new admin panel layout
export type PageType =
  | 'live'
  | 'session_workbench'
  | 'dashboard'
  | 'tasks'
  | 'task_detail'
  | 'recipes'
  | 'recipe_detail'
  | 'data_repo'
  | 'todos'
  | 'todo_detail'
  | 'skills'
  | 'guide'
  | 'settings'
  | 'newTask'
  | 'workspace'
  | 'project_detail';

export interface PageSlice {
  currentPage: PageType;
  currentTaskId: string | null;
  currentRecipeName: string | null;
  currentProjectId: string | null;
  currentTodoId: string | null;

  switchPage: (page: PageType, id?: string) => void;
  /** 地址栏变了（前进/后退/手改地址）时用这个落状态，不再写回地址。 */
  applyRoute: (page: PageType, id?: string | null) => void;
}

/** 编号该落进哪个字段，由目标页决定；其余字段一律清空。 */
function idFields(page: PageType, id?: string | null) {
  return {
    currentTaskId: page === 'task_detail' ? id ?? null : null,
    currentRecipeName: page === 'recipe_detail' ? id ?? null : null,
    currentProjectId: page === 'project_detail' ? id ?? null : null,
    currentTodoId: page === 'todo_detail' ? id ?? null : null,
  };
}

const initial = readLocationRoute();

export const usePageStore = create<PageSlice>((set) => ({
  // 开局停在地址栏指着的那一页。地址栏是空的才回会话工作台这个首页——刷新之后
  // 被弹回首页，正是这一行在读地址之前的样子。
  currentPage: initial.page,
  ...idFields(initial.page, initial.id),

  switchPage: (page, id) => {
    set({ currentPage: page, ...idFields(page, id) });
    writeLocationRoute(pathForPage(page, id));
  },

  applyRoute: (page, id) => {
    set({ currentPage: page, ...idFields(page, id) });
  },
}));
