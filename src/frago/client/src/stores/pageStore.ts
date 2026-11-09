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
import type { PendingLaunch } from '@/hooks/useAgentClients';

// Page type - Updated for new admin panel layout
export type PageType =
  | 'live'
  | 'session_workbench'
  | 'desktop'
  | 'vibe_teaming'
  | 'employees'
  | 'dashboard'
  | 'tasks'
  | 'task_detail'
  | 'recipes'
  | 'recipe_detail'
  | 'recipe_app'
  | 'data_repo'
  | 'todos'
  | 'todo_detail'
  | 'schedules'
  | 'schedule_detail'
  | 'skills'
  | 'guide'
  | 'files'
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
  currentScheduleId: string | null;
  /** 右侧正开着的配方页面：`<配方名>`，非默认槽位时是 `<配方名>/<槽位>`。 */
  currentRecipeAppId: string | null;
  /**
   * 虚拟桌面绑定的导演会话编号（由「创建配方」传入，用于展开右下角导演对话面板）。
   * 不随切页清空，切去会话页再切回桌面页时仍保持同一场导演连接。
   */
  desktopSessionId: string | null;
  /**
   * 会话页上正选着哪一场。
   *
   * 放在这里而不在会话页自己身上：会话页一切走（去配方、去待办）就整个卸掉，记在页面
   * 里的选中跟着没了，回来又得在长清单里重找一遍。它不跟着 `switchPage` 清空，
   * 也不写进地址——离开会话页不等于不看那一场了。
   */
  workbenchSessionId: string | null;
  /**
   * 跨页（如从员工页）发起的新建会话把手与第一句话。
   * 切进 `session_workbench` 后由 `SessionWorkbenchPage` 接手交给 `useSessionLaunch`（左栏启动卡 + 中栏启动面板）。
   */
  pendingWorkbenchLaunch: { launch: PendingLaunch; text: string } | null;

  switchPage: (page: PageType, id?: string) => void;
  /** 地址栏变了（前进/后退/手改地址）时用这个落状态，不再写回地址。 */
  applyRoute: (page: PageType, id?: string | null) => void;
  setWorkbenchSessionId: (id: string | null) => void;
  setDesktopSessionId: (id: string | null) => void;
  launchWorkbenchSession: (launch: PendingLaunch, text: string) => void;
  consumePendingWorkbenchLaunch: () => { launch: PendingLaunch; text: string } | null;
}

/** 编号该落进哪个字段，由目标页决定；其余字段一律清空。 */
function idFields(page: PageType, id?: string | null) {
  return {
    currentTaskId: page === 'task_detail' ? id ?? null : null,
    currentRecipeName: page === 'recipe_detail' ? id ?? null : null,
    currentProjectId: page === 'project_detail' ? id ?? null : null,
    currentTodoId: page === 'todo_detail' ? id ?? null : null,
    currentScheduleId: page === 'schedule_detail' ? id ?? null : null,
    currentRecipeAppId: page === 'recipe_app' ? id ?? null : null,
  };
}

/** 当前页面对应的地址栏编号（含 `session_workbench` 下的 `workbenchSessionId`）。 */
export function activeRouteId(
  state: Pick<
    PageSlice,
    | 'currentPage'
    | 'workbenchSessionId'
    | 'currentTaskId'
    | 'currentRecipeName'
    | 'currentProjectId'
    | 'currentTodoId'
    | 'currentScheduleId'
    | 'currentRecipeAppId'
  >
): string | null {
  switch (state.currentPage) {
    case 'session_workbench':
      return state.workbenchSessionId;
    case 'task_detail':
      return state.currentTaskId;
    case 'recipe_detail':
      return state.currentRecipeName;
    case 'project_detail':
      return state.currentProjectId;
    case 'todo_detail':
      return state.currentTodoId;
    case 'schedule_detail':
      return state.currentScheduleId;
    case 'recipe_app':
      return state.currentRecipeAppId;
    default:
      return null;
  }
}

const initial = readLocationRoute();

function createDesktopSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `core_${crypto.randomUUID().replace(/-/g, '')}`;
  }
  return `core_${Math.random().toString(16).slice(2, 14)}${Date.now().toString(16)}`;
}

export const usePageStore = create<PageSlice>((set, get) => ({
  // 开局停在地址栏指着的那一页。地址栏是空的才回会话工作台这个首页——刷新之后
  // 被弹回首页，正是这一行在读地址之前的样子。
  currentPage: initial.page,
  ...idFields(initial.page, initial.id),
  desktopSessionId: createDesktopSessionId(),
  workbenchSessionId: initial.page === 'session_workbench' ? initial.id : null,
  pendingWorkbenchLaunch: null,

  switchPage: (page, id) => {
    const nextWorkbenchSessionId =
      page === 'session_workbench' && id !== undefined
        ? id || null
        : get().workbenchSessionId;
    set((state) => ({
      currentPage: page,
      ...idFields(page, id),
      workbenchSessionId: nextWorkbenchSessionId,
      desktopSessionId:
        page === 'desktop' && id !== undefined ? id || null : state.desktopSessionId,
    }));
    const routeId =
      page === 'desktop'
        ? undefined
        : page === 'session_workbench'
          ? nextWorkbenchSessionId
          : id;
    writeLocationRoute(pathForPage(page, routeId));
  },

  applyRoute: (page, id) => {
    set((state) => ({
      currentPage: page,
      ...idFields(page, id),
      workbenchSessionId:
        page === 'session_workbench' ? (id ?? null) : state.workbenchSessionId,
    }));
  },

  setWorkbenchSessionId: (id) => {
    set({ workbenchSessionId: id });
    if (get().currentPage === 'session_workbench') {
      writeLocationRoute(pathForPage('session_workbench', id));
    }
  },
  setDesktopSessionId: (id) => set({ desktopSessionId: id }),

  launchWorkbenchSession: (launch, text) => {
    const nextSessionId = launch.session_id ?? null;
    set({
      currentPage: 'session_workbench',
      ...idFields('session_workbench'),
      workbenchSessionId: nextSessionId,
      pendingWorkbenchLaunch: { launch, text },
    });
    writeLocationRoute(pathForPage('session_workbench', nextSessionId));
  },

  consumePendingWorkbenchLaunch: () => {
    const pending = get().pendingWorkbenchLaunch;
    if (pending) set({ pendingWorkbenchLaunch: null });
    return pending;
  },
}));
