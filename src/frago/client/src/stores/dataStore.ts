/**
 * Business data cache (Zustand)
 *
 * Owns: config + the cached domain collections (recipes / community recipes /
 * skills / system status), the data-sync bookkeeping (version / initialized),
 * version & update banners, the GitHub star status, and the actions that
 * refresh / mutate them.
 */

import { create } from 'zustand';
import i18n from '@/i18n';
import type {
  RecipeItem,
  SkillItem,
  UserConfig,
  SystemStatus,
  Theme,
  Language,
  CommunityRecipeItem,
  VersionInfo,
  UpdateStatus,
} from '@/types/pywebview';
import * as api from '@/api';
import { useUIStore } from './uiStore';

export interface DataSlice {
  // Data cache
  config: UserConfig | null;
  recipes: RecipeItem[];
  communityRecipes: CommunityRecipeItem[];
  skills: SkillItem[];
  systemStatus: SystemStatus | null;

  // Data sync state (for WebSocket updates)
  dataVersion: number;
  dataInitialized: boolean;

  // Version info (for update banner)
  versionInfo: VersionInfo | null;

  // Self-update status
  updateStatus: UpdateStatus | null;

  // GitHub Star state
  githubStarStatus: {
    isStarred: boolean | null;
    ghConfigured: boolean;
    isLoading: boolean;
  };

  // Actions
  setTheme: (theme: Theme) => void;
  setLanguage: (language: Language) => void;
  loadConfig: () => Promise<void>;
  loadRecipes: () => Promise<void>;
  loadSkills: () => Promise<void>;
  loadSystemStatus: () => Promise<void>;
  updateConfig: (config: Partial<UserConfig>) => Promise<void>;

  // Data sync actions (for WebSocket push)
  setRecipes: (recipes: RecipeItem[]) => void;
  setCommunityRecipes: (recipes: CommunityRecipeItem[]) => void;
  setSkills: (skills: SkillItem[]) => void;
  loadCommunityRecipes: () => Promise<void>;
  setVersionInfo: (info: VersionInfo) => void;
  setUpdateStatus: (status: UpdateStatus | null) => void;
  setDataFromPush: (data: {
    version?: number;
    recipes?: RecipeItem[];
    communityRecipes?: CommunityRecipeItem[];
    skills?: SkillItem[];
  }) => void;

  // GitHub Star actions
  checkGitHubStar: () => Promise<void>;
  toggleGitHubStar: () => Promise<void>;
}

// Apply theme to DOM and persist to localStorage for FOUC prevention
// Design spec only supports dark theme — force dark regardless of input
function applyTheme(_theme: Theme) {
  const theme: Theme = 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
  // Save to localStorage so index.html can read it before JS loads
  try {
    localStorage.setItem('theme', theme);
  } catch {
    // localStorage not available
  }
}

export const useDataStore = create<DataSlice>((set, get) => ({
  config: null,
  recipes: [],
  communityRecipes: [],
  skills: [],
  systemStatus: null,
  dataVersion: 0,
  dataInitialized: false,
  versionInfo: null,
  updateStatus: null,
  githubStarStatus: {
    isStarred: null,
    ghConfigured: false,
    isLoading: false,
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
    // Save to localStorage for FOUC prevention on next load
    try {
      localStorage.setItem('language', language);
    } catch {
      // localStorage not available
    }
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

      // Sync language with localStorage (same pattern as theme)
      let savedLanguage: Language | null = null;
      try {
        const stored = localStorage.getItem('language');
        if (stored === 'en' || stored === 'zh') {
          savedLanguage = stored;
        }
      } catch {
        // localStorage not available
      }

      if (savedLanguage) {
        // localStorage has value, use it as authoritative
        if (savedLanguage !== config.language) {
          console.log('[Config] Syncing localStorage language to backend:', savedLanguage);
          api.updateConfig({ language: savedLanguage }).catch((err) => {
            console.error('[Config] Failed to sync language to backend:', err);
          });
        }
        // Language already applied during i18n init, no need to changeLanguage again
      } else {
        // No localStorage value, use backend config and save to localStorage
        const language = config.language || 'en';
        if (i18n.language !== language) {
          console.log('[Config] Syncing i18n language:', language);
          i18n.changeLanguage(language);
        }
        try {
          localStorage.setItem('language', language);
        } catch {
          // localStorage not available
        }
      }
    } catch (error) {
      console.error('[Config] Failed to load config:', error);
    }
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
      useUIStore.getState().showToast('Failed to save settings', 'error');
    }
  },

  // Data sync actions (for WebSocket push)
  setRecipes: (recipes) => {
    set({ recipes });
  },

  setCommunityRecipes: (communityRecipes) => {
    set({ communityRecipes });
  },

  setSkills: (skills) => {
    set({ skills });
  },

  setVersionInfo: (versionInfo) => {
    set({ versionInfo });
  },

  setUpdateStatus: (updateStatus) => {
    set({ updateStatus });
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

    const updates: Partial<DataSlice> = {
      dataVersion: newVersion,
      dataInitialized: true,
    };

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

  // GitHub Star actions
  checkGitHubStar: async () => {
    set((state) => ({
      githubStarStatus: { ...state.githubStarStatus, isLoading: true },
    }));
    try {
      const result = await api.checkGitHubStarred();
      set({
        githubStarStatus: {
          isStarred: result.is_starred,
          ghConfigured: result.gh_configured,
          isLoading: false,
        },
      });
    } catch (error) {
      console.error('Failed to check GitHub star status:', error);
      set((state) => ({
        githubStarStatus: { ...state.githubStarStatus, isLoading: false },
      }));
    }
  },

  toggleGitHubStar: async () => {
    const current = get().githubStarStatus;
    if (current.isLoading || !current.ghConfigured) return;

    const newStarred = !current.isStarred;
    // Optimistic update
    set({
      githubStarStatus: { ...current, isStarred: newStarred, isLoading: true },
    });

    try {
      const result = await api.toggleGitHubStar(newStarred);
      set({
        githubStarStatus: {
          ...current,
          isStarred: result.is_starred ?? newStarred,
          isLoading: false,
        },
      });
    } catch (error) {
      console.error('Failed to toggle GitHub star:', error);
      // Revert on error
      set({
        githubStarStatus: { ...current, isLoading: false },
      });
    }
  },
}));
