/**
 * Application Global State Management (Zustand)
 */

import { create } from 'zustand';
import i18n from '@/i18n';
import type {
  TaskItem,
  TaskDetail,
  RecipeItem,
  SkillItem,
  UserConfig,
  SystemStatus,
  Theme,
  Language,
  CommunityRecipeItem,
} from '@/types/pywebview';
import type { ConsoleMessage } from '@/types/console';
import * as api from '@/api';

// Page type - Updated for new admin panel layout
export type PageType =
  | 'dashboard'
  | 'tasks'
  | 'task_detail'
  | 'recipes'
  | 'recipe_detail'
  | 'skills'
  | 'sync'
  | 'secrets'
  | 'settings'
  | 'console'
  | 'workspace'
  | 'project_detail';

// Sidebar storage key for localStorage
const SIDEBAR_COLLAPSED_KEY = 'frago-sidebar-collapsed';

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
  currentProjectId: string | null;

  // Sidebar state
  sidebarCollapsed: boolean;

  // Data cache
  config: UserConfig | null;
  tasks: TaskItem[];
  taskDetail: TaskDetail | null;
  recipes: RecipeItem[];
  communityRecipes: CommunityRecipeItem[];
  skills: SkillItem[];
  systemStatus: SystemStatus | null;

  // UI state
  isLoading: boolean;
  toasts: Toast[];

  // Data sync state (for WebSocket updates)
  dataVersion: number;
  dataInitialized: boolean;

  // Console state (persisted across navigation)
  consoleSessionId: string | null;
  consoleMessages: ConsoleMessage[];
  consoleIsRunning: boolean;
  consoleScrollPosition: number;

  // Actions
  switchPage: (page: PageType, id?: string) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setTheme: (theme: Theme) => void;
  setLanguage: (language: Language) => void;
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

  // Data sync actions (for WebSocket push)
  setTasks: (tasks: TaskItem[]) => void;
  setRecipes: (recipes: RecipeItem[]) => void;
  setCommunityRecipes: (recipes: CommunityRecipeItem[]) => void;
  setSkills: (skills: SkillItem[]) => void;
  loadCommunityRecipes: () => Promise<void>;
  setDataFromPush: (data: {
    version?: number;
    tasks?: { tasks: TaskItem[]; total: number };
    recipes?: RecipeItem[];
    communityRecipes?: CommunityRecipeItem[];
    skills?: SkillItem[];
  }) => void;

  // Console actions
  setConsoleSessionId: (id: string | null) => void;
  addConsoleMessage: (message: ConsoleMessage) => void;
  updateLastConsoleMessage: (update: Partial<ConsoleMessage>) => void;
  updateConsoleMessageByToolCallId: (toolCallId: string, update: Partial<ConsoleMessage>) => void;
  setConsoleMessages: (messages: ConsoleMessage[]) => void;
  setConsoleIsRunning: (running: boolean) => void;
  setConsoleScrollPosition: (position: number) => void;
  clearConsole: () => void;
}

// Generate unique ID
function generateId(): string {
  return Math.random().toString(36).substring(2, 9);
}

// Apply theme to DOM and persist to localStorage for FOUC prevention
function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
  // Save to localStorage so index.html can read it before JS loads
  try {
    localStorage.setItem('theme', theme);
  } catch {
    // localStorage not available
  }
}

// Helper to get initial sidebar state from localStorage
function getInitialSidebarCollapsed(): boolean {
  try {
    const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    return stored === 'true';
  } catch {
    return false;
  }
}

export const useAppStore = create<AppState>((set, get) => ({
  // Initial state - default to 'tasks' page per spec
  currentPage: 'tasks',
  currentTaskId: null,
  currentRecipeName: null,
  currentProjectId: null,
  sidebarCollapsed: getInitialSidebarCollapsed(),
  config: null,
  tasks: [],
  taskDetail: null,
  recipes: [],
  communityRecipes: [],
  skills: [],
  systemStatus: null,
  isLoading: false,
  toasts: [],
  dataVersion: 0,
  dataInitialized: false,

  // Console initial state
  consoleSessionId: null,
  consoleMessages: [],
  consoleIsRunning: false,
  consoleScrollPosition: 0,

  // Page switching
  switchPage: (page, id) => {
    set({
      currentPage: page,
      currentTaskId: page === 'task_detail' ? id ?? null : null,
      currentRecipeName: page === 'recipe_detail' ? id ?? null : null,
      currentProjectId: page === 'project_detail' ? id ?? null : null,
      taskDetail: page !== 'task_detail' ? null : get().taskDetail,
    });
  },

  // Toggle sidebar collapsed state
  toggleSidebar: () => {
    const newCollapsed = !get().sidebarCollapsed;
    set({ sidebarCollapsed: newCollapsed });
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(newCollapsed));
    } catch {
      // localStorage not available
    }
  },

  // Set sidebar collapsed state directly
  setSidebarCollapsed: (collapsed) => {
    set({ sidebarCollapsed: collapsed });
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
    } catch {
      // localStorage not available
    }
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

  // Language switching
  setLanguage: (language) => {
    console.log('[Language] setLanguage called with:', language);
    i18n.changeLanguage(language);
    const config = get().config;
    if (config) {
      set({ config: { ...config, language } });
      api.updateConfig({ language }).then((result) => {
        console.log('[Language] updateConfig result:', result);
      }).catch((err) => {
        console.error('[Language] updateConfig failed:', err);
      });
    } else {
      console.warn('[Language] config is null, cannot persist language');
    }
  },

  // Load config
  loadConfig: async () => {
    try {
      console.log('[Config] Loading config from backend...');
      const config = await api.getConfig();
      console.log('[Config] Loaded:', config);
      set({ config });

      // Preserve localStorage theme preference (user's local choice is authoritative)
      let savedTheme: Theme | null = null;
      try {
        const stored = localStorage.getItem('theme');
        if (stored === 'dark' || stored === 'light') {
          savedTheme = stored;
        }
      } catch {
        // localStorage not available
      }

      if (savedTheme) {
        // If localStorage has a valid theme, use it and sync to backend if different
        if (savedTheme !== config.theme) {
          console.log('[Config] Syncing localStorage theme to backend:', savedTheme);
          applyTheme(savedTheme);
          api.updateConfig({ theme: savedTheme }).catch((err) => {
            console.error('[Config] Failed to sync theme to backend:', err);
          });
        } else {
          applyTheme(config.theme);
        }
      } else {
        // No localStorage theme, use backend value
        applyTheme(config.theme);
      }

      // Sync i18n language with config
      const language = config.language || 'en';
      if (i18n.language !== language) {
        console.log('[Config] Syncing i18n language:', language);
        i18n.changeLanguage(language);
      }
    } catch (error) {
      console.error('[Config] Failed to load config:', error);
    }
  },

  // Load task list
  loadTasks: async () => {
    try {
      const config = get().config;
      const generateTitles = config?.ai_title_enabled ?? false;
      const tasks = await api.getTasks({ generateTitles });
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

  // Data sync actions (for WebSocket push)
  setTasks: (tasks) => {
    set({ tasks });
  },

  setRecipes: (recipes) => {
    set({ recipes });
  },

  setCommunityRecipes: (communityRecipes) => {
    set({ communityRecipes });
  },

  setSkills: (skills) => {
    set({ skills });
  },

  loadCommunityRecipes: async () => {
    try {
      const communityRecipes = await api.getCommunityRecipes();
      set({ communityRecipes });
    } catch (error) {
      console.error('Failed to load community recipes:', error);
    }
  },

  setDataFromPush: (data) => {
    const currentVersion = get().dataVersion;
    const newVersion = data.version ?? currentVersion + 1;

    // Ignore older versions
    if (newVersion < currentVersion) {
      console.log('[DataSync] Ignoring older data version', newVersion, '<', currentVersion);
      return;
    }

    const updates: Partial<AppState> = {
      dataVersion: newVersion,
      dataInitialized: true,
    };

    if (data.tasks) {
      updates.tasks = data.tasks.tasks;
    }
    if (data.recipes) {
      updates.recipes = data.recipes;
    }
    if (data.communityRecipes) {
      updates.communityRecipes = data.communityRecipes;
    }
    if (data.skills) {
      updates.skills = data.skills;
    }

    console.log('[DataSync] Applying pushed data, version:', newVersion);
    set(updates);
  },

  // Console actions
  setConsoleSessionId: (id) => {
    set({ consoleSessionId: id });
  },

  addConsoleMessage: (message) => {
    set((state) => ({
      consoleMessages: [...state.consoleMessages, message],
    }));
  },

  updateLastConsoleMessage: (update) => {
    set((state) => {
      const messages = state.consoleMessages;
      if (messages.length === 0) return state;
      const last = messages[messages.length - 1];
      return {
        consoleMessages: [...messages.slice(0, -1), { ...last, ...update }],
      };
    });
  },

  updateConsoleMessageByToolCallId: (toolCallId, update) => {
    set((state) => ({
      consoleMessages: state.consoleMessages.map((msg) =>
        msg.tool_call_id === toolCallId ? { ...msg, ...update } : msg
      ),
    }));
  },

  setConsoleMessages: (messages) => {
    set({ consoleMessages: messages });
  },

  setConsoleIsRunning: (running) => {
    set({ consoleIsRunning: running });
  },

  setConsoleScrollPosition: (position) => {
    set({ consoleScrollPosition: position });
  },

  clearConsole: () => {
    set({
      consoleSessionId: null,
      consoleMessages: [],
      consoleIsRunning: false,
      consoleScrollPosition: 0,
    });
  },
}));
