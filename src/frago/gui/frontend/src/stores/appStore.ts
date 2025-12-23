/**
 * Application Global State Management (Zustand)
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
import * as api from '@/api';

// Page type
export type PageType =
  | 'tips'
  | 'tasks'
  | 'task_detail'
  | 'recipes'
  | 'recipe_detail'
  | 'skills'
  | 'settings';

// Toast type
export type ToastType = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

// Application state
interface AppState {
  // Page state
  currentPage: PageType;
  currentTaskId: string | null;
  currentRecipeName: string | null;

  // Data cache
  config: UserConfig | null;
  tasks: TaskItem[];
  taskDetail: TaskDetail | null;
  recipes: RecipeItem[];
  skills: SkillItem[];
  systemStatus: SystemStatus | null;

  // UI state
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

// Generate unique ID
function generateId(): string {
  return Math.random().toString(36).substring(2, 9);
}

// Apply theme to DOM
function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
  console.log('[Theme] Applied:', theme, 'data-theme:', document.documentElement.getAttribute('data-theme'));
}

export const useAppStore = create<AppState>((set, get) => ({
  // Initial state
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

  // Page switching
  switchPage: (page, id) => {
    set({
      currentPage: page,
      currentTaskId: page === 'task_detail' ? id ?? null : null,
      currentRecipeName: page === 'recipe_detail' ? id ?? null : null,
      taskDetail: page !== 'task_detail' ? null : get().taskDetail,
    });
  },

  // Theme switching
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

  // Load config
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

  // Load task list
  loadTasks: async () => {
    try {
      const tasks = await api.getTasks();
      set({ tasks: tasks || [] });
    } catch (error) {
      console.error('Failed to load tasks:', error);
    }
  },

  // Open task detail
  openTaskDetail: async (sessionId) => {
    set({ isLoading: true, currentPage: 'task_detail', currentTaskId: sessionId });
    try {
      // steps_limit = 0 means get all steps for frontend filtering
      const taskDetail = await api.getTaskDetail(sessionId, 0, 0);
      set({ taskDetail, isLoading: false });
    } catch (error) {
      console.error('Failed to load task detail:', error);
      set({ isLoading: false });
      get().showToast('Failed to load task details', 'error');
    }
  },

  // Update task detail (for loading more steps)
  setTaskDetail: (detail) => {
    set({ taskDetail: detail });
  },

  // Load recipe list
  loadRecipes: async () => {
    try {
      const recipes = await api.getRecipes();
      set({ recipes });
    } catch (error) {
      console.error('Failed to load recipes:', error);
    }
  },

  // Load skill list
  loadSkills: async () => {
    try {
      const skills = await api.getSkills();
      set({ skills });
    } catch (error) {
      console.error('Failed to load skills:', error);
    }
  },

  // Load system status
  loadSystemStatus: async () => {
    try {
      const systemStatus = await api.getSystemStatus();
      set({ systemStatus });
    } catch (error) {
      console.error('Failed to load system status:', error);
    }
  },

  // Update config
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
      get().showToast('Failed to save settings', 'error');
    }
  },

  // Show toast
  showToast: (message, type) => {
    const id = generateId();
    set((state) => ({
      toasts: [...state.toasts, { id, message, type }],
    }));

    // Auto dismiss
    setTimeout(() => {
      get().dismissToast(id);
    }, 3000);
  },

  // Dismiss toast
  dismissToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },
}));
