/**
 * 应用全局状态管理 (Zustand)
 */

import { create } from 'zustand';
import type {
  TaskItem,
  TaskDetail,
  RecipeItem,
  SkillItem,
  UserConfig,
  SystemStatus,
  Theme,
} from '@/types/pywebview.d';
import * as api from '@/api/pywebview';

// 页面类型
export type PageType =
  | 'tips'
  | 'tasks'
  | 'task_detail'
  | 'recipes'
  | 'recipe_detail'
  | 'skills'
  | 'settings';

// Toast 类型
export type ToastType = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

// 应用状态
interface AppState {
  // 页面状态
  currentPage: PageType;
  currentTaskId: string | null;
  currentRecipeName: string | null;

  // 数据缓存
  config: UserConfig | null;
  tasks: TaskItem[];
  taskDetail: TaskDetail | null;
  recipes: RecipeItem[];
  skills: SkillItem[];
  systemStatus: SystemStatus | null;

  // UI 状态
  isLoading: boolean;
  toasts: Toast[];

  // Actions
  switchPage: (page: PageType, id?: string) => void;
  setTheme: (theme: Theme) => void;
  loadConfig: () => Promise<void>;
  loadTasks: () => Promise<void>;
  openTaskDetail: (sessionId: string) => Promise<void>;
  setTaskDetail: (detail: TaskDetail) => void;
  loadRecipes: () => Promise<void>;
  loadSkills: () => Promise<void>;
  loadSystemStatus: () => Promise<void>;
  updateConfig: (config: Partial<UserConfig>) => Promise<void>;
  showToast: (message: string, type: ToastType) => void;
  dismissToast: (id: string) => void;
}

// 生成唯一 ID
function generateId(): string {
  return Math.random().toString(36).substring(2, 9);
}

// 应用主题到 DOM
function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
  console.log('[Theme] Applied:', theme, 'data-theme:', document.documentElement.getAttribute('data-theme'));
}

export const useAppStore = create<AppState>((set, get) => ({
  // 初始状态
  currentPage: 'tips',
  currentTaskId: null,
  currentRecipeName: null,
  config: null,
  tasks: [],
  taskDetail: null,
  recipes: [],
  skills: [],
  systemStatus: null,
  isLoading: false,
  toasts: [],

  // 页面切换
  switchPage: (page, id) => {
    set({
      currentPage: page,
      currentTaskId: page === 'task_detail' ? id ?? null : null,
      currentRecipeName: page === 'recipe_detail' ? id ?? null : null,
      taskDetail: page !== 'task_detail' ? null : get().taskDetail,
    });
  },

  // 主题切换
  setTheme: (theme) => {
    console.log('[Theme] setTheme called with:', theme);
    applyTheme(theme);
    const config = get().config;
    if (config) {
      set({ config: { ...config, theme } });
      api.updateConfig({ theme }).then((result) => {
        console.log('[Theme] updateConfig result:', result);
      }).catch((err) => {
        console.error('[Theme] updateConfig failed:', err);
      });
    } else {
      console.warn('[Theme] config is null, cannot persist theme');
    }
  },

  // 加载配置
  loadConfig: async () => {
    try {
      console.log('[Config] Loading config from backend...');
      const config = await api.getConfig();
      console.log('[Config] Loaded:', config);
      set({ config });
      applyTheme(config.theme);
    } catch (error) {
      console.error('[Config] Failed to load config:', error);
    }
  },

  // 加载任务列表
  loadTasks: async () => {
    try {
      const tasks = await api.getTasks();
      set({ tasks: tasks || [] });
    } catch (error) {
      console.error('Failed to load tasks:', error);
    }
  },

  // 打开任务详情
  openTaskDetail: async (sessionId) => {
    set({ isLoading: true, currentPage: 'task_detail', currentTaskId: sessionId });
    try {
      // steps_limit = 0 表示获取全部步骤，便于前端筛选
      const taskDetail = await api.getTaskDetail(sessionId, 0, 0);
      set({ taskDetail, isLoading: false });
    } catch (error) {
      console.error('Failed to load task detail:', error);
      set({ isLoading: false });
      get().showToast('加载任务详情失败', 'error');
    }
  },

  // 更新任务详情（用于加载更多步骤）
  setTaskDetail: (detail) => {
    set({ taskDetail: detail });
  },

  // 加载配方列表
  loadRecipes: async () => {
    try {
      const recipes = await api.getRecipes();
      set({ recipes });
    } catch (error) {
      console.error('Failed to load recipes:', error);
    }
  },

  // 加载技能列表
  loadSkills: async () => {
    try {
      const skills = await api.getSkills();
      set({ skills });
    } catch (error) {
      console.error('Failed to load skills:', error);
    }
  },

  // 加载系统状态
  loadSystemStatus: async () => {
    try {
      const systemStatus = await api.getSystemStatus();
      set({ systemStatus });
    } catch (error) {
      console.error('Failed to load system status:', error);
    }
  },

  // 更新配置
  updateConfig: async (configUpdate) => {
    const currentConfig = get().config;
    if (!currentConfig) return;

    const newConfig = { ...currentConfig, ...configUpdate };
    set({ config: newConfig });

    try {
      await api.updateConfig(configUpdate);
      if (configUpdate.theme) {
        applyTheme(configUpdate.theme);
      }
    } catch (error) {
      console.error('Failed to update config:', error);
      set({ config: currentConfig });
      get().showToast('保存设置失败', 'error');
    }
  },

  // 显示 Toast
  showToast: (message, type) => {
    const id = generateId();
    set((state) => ({
      toasts: [...state.toasts, { id, message, type }],
    }));

    // 自动消失
    setTimeout(() => {
      get().dismissToast(id);
    }, 3000);
  },

  // 关闭 Toast
  dismissToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },
}));
