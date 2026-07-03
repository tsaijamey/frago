/**
 * Unified API Layer
 *
 * Automatically selects between pywebview API and HTTP API based on runtime environment.
 * This provides a seamless transition from pywebview to web service mode.
 */

import * as pywebviewApi from './pywebview';
import * as httpApi from './client';
import type {
  RecipeItem,
  RecipeDetail,
  RecipeRunResponse,
  SkillItem,
  UserConfig,
  ConfigUpdateResponse,
  SystemStatus,
  ConnectionStatus,
  TaskStartResponse,
  RecipeDeleteResponse,
  MainConfig,
  MainConfigUpdateResponse,
  AuthUpdateRequest,
  APIEndpoint,
  RecipeSecretsResponse,
  RecipeSecretsUpdateResponse,
  GhCliStatus,
  ApiResponse,
  TutorialResponse,
  CommunityRecipeItem,
  CommunityRecipeInstallResponse,
} from '@/types/pywebview';
import { localISOString } from '@/utils/time';

// ============================================================
// Mode Detection
// ============================================================

/**
 * Check if pywebview API is available
 */
function isPywebviewMode(): boolean {
  return typeof window !== 'undefined' && !!window.pywebview?.api;
}

/**
 * Get current API mode
 */
export function getApiMode(): 'pywebview' | 'http' {
  return isPywebviewMode() ? 'pywebview' : 'http';
}

/**
 * Dual-mode proxy: pick the http or pywebview implementation at call time.
 *
 * Replaces the repeated `if (isPywebviewMode()) ... else ...` branch that used
 * to appear in every exported function. Behavior is identical: the pywebview
 * implementation runs in pywebview mode, the http implementation otherwise.
 */
function withMode<A extends unknown[], T>(
  httpFn: (...args: A) => T,
  pywebviewFn: (...args: A) => T,
): (...args: A) => T {
  return (...args: A) => (isPywebviewMode() ? pywebviewFn(...args) : httpFn(...args));
}

// ============================================================
// API Ready State
// ============================================================

export const waitForApi = withMode(
  (): Promise<void> => httpApi.waitForApi(),
  async (): Promise<void> => { await pywebviewApi.waitForPywebview(); },
);

export const isApiReady = withMode(
  // HTTP API is always "ready" once page loads
  (): boolean => true,
  (): boolean => pywebviewApi.isApiReady(),
);

// ============================================================
// Tasks API
// ============================================================

export const startAgentTask = withMode(
  async (prompt: string): Promise<TaskStartResponse> => {
    // Start the task - the returned task_id is NOT the Claude session_id
    // Frontend should poll the task list to get the real session_id
    const task = await httpApi.startAgent(prompt);
    return {
      status: 'ok',
      // Don't return task_id - it won't match the Claude session_id
      // The real session_id will appear in the task list after sync
      message: `Started task: ${task.title}`,
    };
  },
  (prompt: string): Promise<TaskStartResponse> => pywebviewApi.startAgentTask(prompt),
);

// ============================================================
// Recipes API
// ============================================================

export const getRecipes = withMode(
  async (): Promise<RecipeItem[]> => {
    const recipes = await httpApi.getRecipes();
    return recipes.map((r) => ({
      name: r.name,
      description: r.description,
      category: r.category as RecipeItem['category'],
      icon: r.icon,
      tags: r.tags,
      path: r.path,
      source: r.source as RecipeItem['source'],
      runtime: r.runtime as RecipeItem['runtime'],
    }));
  },
  (): Promise<RecipeItem[]> => pywebviewApi.getRecipes(),
);

export const refreshRecipes = withMode(
  // HTTP mode - just fetch again
  (): Promise<RecipeItem[]> => getRecipes(),
  (): Promise<RecipeItem[]> => pywebviewApi.refreshRecipes(),
);

export const getRecipeDetail = withMode(
  async (name: string): Promise<RecipeDetail> => {
    // HTTP API returns extended recipe data
    const recipe = await httpApi.getRecipe(name) as unknown as Record<string, unknown>;
    return {
      name: recipe.name as string,
      description: recipe.description as string | null,
      category: ((recipe.type || recipe.category) as RecipeDetail['category']) || 'atomic',
      icon: (recipe.icon as string) || null,
      tags: (recipe.tags as string[]) || [],
      path: (recipe.path || recipe.script_path) as string | null,
      source: recipe.source as RecipeDetail['source'],
      runtime: recipe.runtime as RecipeDetail['runtime'],
      metadata_content: null,
      recipe_dir: (recipe.base_dir as string) || null,
      // Rich metadata fields
      version: recipe.version as string | undefined,
      base_dir: recipe.base_dir as string | undefined,
      script_path: recipe.script_path as string | undefined,
      metadata_path: recipe.metadata_path as string | undefined,
      use_cases: recipe.use_cases as string[] | undefined,
      output_targets: recipe.output_targets as string[] | undefined,
      inputs: recipe.inputs as RecipeDetail['inputs'],
      outputs: recipe.outputs as RecipeDetail['outputs'],
      dependencies: recipe.dependencies as string[] | undefined,
      env: recipe.env as Record<string, unknown> | undefined,
      source_code: recipe.source_code as string | undefined,
      flow: recipe.flow as RecipeDetail['flow'],
    };
  },
  (name: string): Promise<RecipeDetail> => pywebviewApi.getRecipeDetail(name),
);

export const runRecipe = withMode(
  async (
    name: string,
    params?: Record<string, unknown>,
  ): Promise<RecipeRunResponse> => {
    try {
      await httpApi.runRecipe(name, params);
      return {
        status: 'ok',
        output: 'Recipe completed',
        error: null,
      };
    } catch (error) {
      return {
        status: 'error',
        output: null,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  },
  (
    name: string,
    params?: Record<string, unknown>,
  ): Promise<RecipeRunResponse> => pywebviewApi.runRecipe(name, params),
);

export async function runRecipeAsync(
  name: string,
  params?: Record<string, unknown>,
  timeout?: number,
): Promise<{ execution_id: string; status: string; poll_url: string }> {
  return httpApi.runRecipeAsync(name, params, timeout);
}

export const deleteRecipe = withMode(
  // HTTP API doesn't support delete yet
  (_name: string): Promise<RecipeDeleteResponse> => Promise.resolve({
    status: 'error',
    message: 'Delete not supported in web service mode',
  }),
  (name: string): Promise<RecipeDeleteResponse> => pywebviewApi.deleteRecipe(name),
);

// ============================================================
// Skills API
// ============================================================

export const getSkills = withMode(
  async (): Promise<SkillItem[]> => {
    // HTTP API
    const skills = await httpApi.getSkills();
    return skills.map((s) => ({
      name: s.name,
      description: s.description,
      icon: null,  // HTTP API doesn't return icons yet
      file_path: s.file_path ?? '',
    }));
  },
  (): Promise<SkillItem[]> => pywebviewApi.getSkills(),
);

export const refreshSkills = withMode(
  // HTTP mode - just fetch again
  (): Promise<SkillItem[]> => getSkills(),
  (): Promise<SkillItem[]> => pywebviewApi.refreshSkills(),
);

// ============================================================
// Config API
// ============================================================

export const getConfig = withMode(
  async (): Promise<UserConfig> => {
    const config = await httpApi.getConfig();
    return {
      theme: config.theme as UserConfig['theme'],
      language: (config.language || 'en') as UserConfig['language'],
      show_system_status: config.show_system_status,
      confirm_on_exit: config.confirm_on_exit,
      auto_scroll_output: config.auto_scroll_output,
      max_history_items: config.max_history_items,
      shortcuts: config.shortcuts,
    };
  },
  (): Promise<UserConfig> => pywebviewApi.getConfig(),
);

export const updateConfig = withMode(
  async (
    config: Partial<UserConfig>
  ): Promise<ConfigUpdateResponse> => {
    try {
      const updated = await httpApi.updateConfig(config);
      return {
        status: 'ok',
        config: {
          theme: updated.theme as UserConfig['theme'],
          language: (updated.language || 'en') as UserConfig['language'],
          show_system_status: updated.show_system_status,
          confirm_on_exit: updated.confirm_on_exit,
          auto_scroll_output: updated.auto_scroll_output,
          max_history_items: updated.max_history_items,
          shortcuts: updated.shortcuts,
        },
      };
    } catch (error) {
      return {
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
      };
    }
  },
  (config: Partial<UserConfig>): Promise<ConfigUpdateResponse> => pywebviewApi.updateConfig(config),
);

// ============================================================
// System API
// ============================================================

export const getSystemStatus = withMode(
  async (): Promise<SystemStatus> => {
    // HTTP API - call real /api/status endpoint
    const status = await httpApi.getServerStatus();
    return {
      cpu_percent: status.cpu_percent ?? 0,
      memory_percent: status.memory_percent ?? 0,
      chrome_connected: status.chrome_connected ?? false,
    };
  },
  (): Promise<SystemStatus> => pywebviewApi.getSystemStatus(),
);

export const checkConnection = withMode(
  async (): Promise<ConnectionStatus> => {
    try {
      await httpApi.getServerStatus();
      return {
        connected: true,
        message: 'Connected to Frago web service',
      };
    } catch {
      return {
        connected: false,
        message: 'Failed to connect to Frago web service',
      };
    }
  },
  (): Promise<ConnectionStatus> => pywebviewApi.checkConnection(),
);

export const openPath = withMode(
  (
    path: string,
    reveal: boolean = false
  ): Promise<ApiResponse> => httpApi.openPath(path, reveal),
  (
    path: string,
    reveal: boolean = false
  ): Promise<ApiResponse> => pywebviewApi.openPath(path, reveal),
);

// ============================================================
// Settings API - Main Config Management
// ============================================================

export const getMainConfig = withMode(
  async (): Promise<MainConfig> => {
    // HTTP API
    const config = await httpApi.getMainConfig();
    return {
      schema_version: '1.0',
      auth_method: config.auth_method as MainConfig['auth_method'],
      api_endpoint: config.api_endpoint ? {
        type: config.api_endpoint.type as APIEndpoint['type'],
        url: config.api_endpoint.url ?? undefined,
        api_key: config.api_endpoint.api_key,
        default_model: config.api_endpoint.default_model ?? undefined,
        sonnet_model: config.api_endpoint.sonnet_model ?? undefined,
        haiku_model: config.api_endpoint.haiku_model ?? undefined,
      } : undefined,
      ccr_enabled: false,
      working_directory_display: config.working_directory,
      resources_installed: config.resources_installed,
      resources_version: config.resources_version ?? undefined,
      init_completed: config.init_completed,
      created_at: localISOString(),
      updated_at: localISOString(),
    };
  },
  (): Promise<MainConfig> => pywebviewApi.getMainConfig(),
);

export const updateMainConfig = withMode(
  async (
    updates: Partial<MainConfig>
  ): Promise<MainConfigUpdateResponse> => {
    // HTTP API
    try {
      // Map frontend fields to backend fields
      const backendUpdates: Record<string, string | undefined> = {};
      if (updates.auth_method) {
        // Pass through directly: backend accepts 'official' or 'custom'
        backendUpdates.auth_method = updates.auth_method;
      }

      const config = await httpApi.updateMainConfig(backendUpdates);
      return {
        status: 'ok',
        config: {
          schema_version: '1.0',
          auth_method: config.auth_method as MainConfig['auth_method'],
          ccr_enabled: false,
          working_directory_display: config.working_directory,
          resources_installed: true,
          created_at: localISOString(),
          updated_at: localISOString(),
          init_completed: true,
        },
      };
    } catch (error) {
      return {
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
      };
    }
  },
  (updates: Partial<MainConfig>): Promise<MainConfigUpdateResponse> => pywebviewApi.updateMainConfig(updates),
);

export const updateAuthMethod = withMode(
  async (
    authData: AuthUpdateRequest
  ): Promise<MainConfigUpdateResponse> => {
    // HTTP API - use dedicated auth update endpoint that creates ~/.claude/settings.json
    try {
      const result = await httpApi.updateAuth({
        auth_method: authData.auth_method,
        api_endpoint: authData.api_endpoint ? {
          type: authData.api_endpoint.type,
          api_key: authData.api_endpoint.api_key,
          url: authData.api_endpoint.url,
          default_model: authData.api_endpoint.default_model,
          sonnet_model: authData.api_endpoint.sonnet_model,
          haiku_model: authData.api_endpoint.haiku_model,
        } : undefined,
      });

      if (result.status === 'ok') {
        // Reload config to get updated state
        const config = await httpApi.getMainConfig();
        return {
          status: 'ok',
          config: {
            schema_version: '1.0',
            auth_method: config.auth_method as MainConfig['auth_method'],
            api_endpoint: config.api_endpoint ? {
              type: config.api_endpoint.type as APIEndpoint['type'],
              url: config.api_endpoint.url ?? undefined,
              api_key: config.api_endpoint.api_key,
              default_model: config.api_endpoint.default_model ?? undefined,
              sonnet_model: config.api_endpoint.sonnet_model ?? undefined,
              haiku_model: config.api_endpoint.haiku_model ?? undefined,
            } : undefined,
            ccr_enabled: false,
            working_directory_display: config.working_directory,
            resources_installed: config.resources_installed,
            created_at: localISOString(),
            updated_at: localISOString(),
            init_completed: config.init_completed,
          },
        };
      } else {
        return {
          status: 'error',
          error: result.error || 'Failed to update auth',
        };
      }
    } catch (error) {
      return {
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
      };
    }
  },
  (authData: AuthUpdateRequest): Promise<MainConfigUpdateResponse> => pywebviewApi.updateAuthMethod(authData),
);

export const openWorkingDirectory = withMode(
  (): Promise<ApiResponse> => httpApi.openWorkingDirectory(),
  (): Promise<ApiResponse> => pywebviewApi.openWorkingDirectory(),
);

// ============================================================
// Settings API - Recipe Secrets Management
// ============================================================

export const getRecipeSecrets = withMode(
  async (recipeName: string): Promise<RecipeSecretsResponse> => {
    // HTTP API
    const result = await httpApi.getRecipeSecrets(recipeName);
    return {
      recipe_name: result.recipe_name,
      fields: result.fields.map((f) => ({
        key: f.key,
        type: f.type,
        required: f.required,
        description: f.description,
        has_value: f.has_value,
        default: f.default,
      })),
      is_ref: result.is_ref,
      ref_target: result.ref_target,
    };
  },
  (recipeName: string): Promise<RecipeSecretsResponse> => pywebviewApi.getRecipeSecrets(recipeName),
);

export const updateRecipeSecrets = withMode(
  async (
    recipeName: string,
    updates: Record<string, unknown>
  ): Promise<RecipeSecretsUpdateResponse> => {
    // HTTP API
    try {
      const result = await httpApi.updateRecipeSecrets(recipeName, updates);
      return {
        status: result.status,
        message: result.message,
      };
    } catch (error) {
      return {
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
      };
    }
  },
  (
    recipeName: string,
    updates: Record<string, unknown>
  ): Promise<RecipeSecretsUpdateResponse> => pywebviewApi.updateRecipeSecrets(recipeName, updates),
);

// ============================================================
// Settings API - GitHub Integration
// ============================================================

export const checkGhCli = withMode(
  async (): Promise<GhCliStatus> => {
    // HTTP API
    const status = await httpApi.checkGhCli();
    return {
      installed: status.installed,
      authenticated: status.authenticated,
      version: status.version ?? undefined,
      username: status.username ?? undefined,
    };
  },
  (): Promise<GhCliStatus> => pywebviewApi.checkGhCli(),
);

export const ghAuthLogin = withMode(
  async (): Promise<ApiResponse> => {
    // HTTP API
    const result = await httpApi.ghAuthLogin();
    return {
      status: (result.status === 'ok' ? 'ok' : 'error') as 'ok' | 'error',
      error: result.error ?? undefined,
    };
  },
  (): Promise<ApiResponse> => pywebviewApi.ghAuthLogin(),
);

// ============================================================
// Tutorial API
// ============================================================

export const openTutorial = withMode(
  (
    _tutorialId: string,
    _lang: string = 'auto',
    _anchor: string = ''
  ): Promise<TutorialResponse> => Promise.resolve({
    status: 'error',
    error: 'Tutorial not available in web service mode',
  }),
  (
    tutorialId: string,
    lang: string = 'auto',
    anchor: string = ''
  ): Promise<TutorialResponse> => pywebviewApi.openTutorial(tutorialId, lang, anchor),
);

// ============================================================
// VSCode Integration API
// ============================================================

export const checkVSCode = withMode(
  (): Promise<{ available: boolean }> => httpApi.checkVSCode(),
  (): Promise<{ available: boolean }> => Promise.resolve({ available: false }), // pywebview mode doesn't support this
);

export const openConfigInVSCode = withMode(
  (): Promise<ApiResponse> => httpApi.openConfigInVSCode(),
  (): Promise<ApiResponse> => Promise.resolve({ status: 'error', error: 'Not supported in pywebview mode' }),
);


// ============================================================
// Claude Code Sessions API
// ============================================================

export type {
  ClaudeSessionHuman,
  ClaudeSessionItem,
  ClaudeSessionsResponse,
  ClaudeSessionMessage,
  ClaudeSessionBlock,
  ClaudeSessionDetail,
  ClaudeSessionSendResponse,
  TokenCalendarResponse,
  TokenDayBucket,
} from './client';

export const getClaudeSessions = withMode(
  (options?: {
    days?: number;
    since?: string;
    until?: string;
  }): Promise<httpApi.ClaudeSessionsResponse> => httpApi.getClaudeSessions(options),
  (_options?: {
    days?: number;
    since?: string;
    until?: string;
  }): Promise<httpApi.ClaudeSessionsResponse> => {
    throw new Error('Claude sessions API not available in pywebview mode');
  },
);

export const getClaudeSessionDetail = withMode(
  (
    sid: string,
    limit?: number
  ): Promise<httpApi.ClaudeSessionDetail> => httpApi.getClaudeSessionDetail(sid, limit),
  (
    _sid: string,
    _limit?: number
  ): Promise<httpApi.ClaudeSessionDetail> => {
    throw new Error('Claude sessions API not available in pywebview mode');
  },
);

export const getTokenCalendar = withMode(
  (month: string): Promise<httpApi.TokenCalendarResponse> => httpApi.getTokenCalendar(month),
  (_month: string): Promise<httpApi.TokenCalendarResponse> => {
    throw new Error('Claude sessions API not available in pywebview mode');
  },
);

export const sendClaudeSessionMessage = withMode(
  (
    sid: string,
    text: string
  ): Promise<httpApi.ClaudeSessionSendResponse> => httpApi.sendClaudeSessionMessage(sid, text),
  (
    _sid: string,
    _text: string
  ): Promise<httpApi.ClaudeSessionSendResponse> => {
    throw new Error('Claude sessions API not available in pywebview mode');
  },
);

// ============================================================
// Community Recipes API
// ============================================================

export const getCommunityRecipes = withMode(
  async (): Promise<CommunityRecipeItem[]> => {
    const recipes = await httpApi.getCommunityRecipes();
    return recipes.map((r) => ({
      name: r.name,
      url: r.url,
      description: r.description,
      version: r.version,
      type: r.type,
      runtime: r.runtime,
      tags: r.tags,
      installed: r.installed,
      installed_version: r.installed_version,
      has_update: r.has_update,
    }));
  },
  // pywebview mode - not supported
  (): Promise<CommunityRecipeItem[]> => Promise.resolve([]),
);

export const installCommunityRecipe = withMode(
  (
    name: string,
    force: boolean = false
  ): Promise<CommunityRecipeInstallResponse> => httpApi.installCommunityRecipe(name, force),
  (
    _name: string,
    _force: boolean = false
  ): Promise<CommunityRecipeInstallResponse> => Promise.resolve({
    status: 'error',
    error: 'Community recipes not supported in pywebview mode',
  }),
);

export const updateCommunityRecipe = withMode(
  (
    name: string
  ): Promise<CommunityRecipeInstallResponse> => httpApi.updateCommunityRecipe(name),
  (
    _name: string
  ): Promise<CommunityRecipeInstallResponse> => Promise.resolve({
    status: 'error',
    error: 'Community recipes not supported in pywebview mode',
  }),
);

export const uninstallCommunityRecipe = withMode(
  (
    name: string
  ): Promise<CommunityRecipeInstallResponse> => httpApi.uninstallCommunityRecipe(name),
  (
    _name: string
  ): Promise<CommunityRecipeInstallResponse> => Promise.resolve({
    status: 'error',
    error: 'Community recipes not supported in pywebview mode',
  }),
);

// ============================================================
// Project Files API
// ============================================================

export type {
  ProjectInfo,
  ProjectDetail,
  FileInfo,
  FileOperationResponse,
} from './client';

export const getProjects = withMode(
  (): Promise<httpApi.ProjectInfo[]> => httpApi.getProjects(),
  (): Promise<httpApi.ProjectInfo[]> => Promise.resolve([]),
);

export const refreshProjects = withMode(
  (): Promise<httpApi.ProjectInfo[]> => httpApi.refreshProjects(),
  (): Promise<httpApi.ProjectInfo[]> => Promise.resolve([]),
);

export const getProject = withMode(
  (runId: string): Promise<httpApi.ProjectDetail | null> => httpApi.getProject(runId),
  (_runId: string): Promise<httpApi.ProjectDetail | null> => Promise.resolve(null),
);

export const getProjectFiles = withMode(
  (
    runId: string,
    path: string = ''
  ): Promise<httpApi.FileInfo[]> => httpApi.getProjectFiles(runId, path),
  (
    _runId: string,
    _path: string = ''
  ): Promise<httpApi.FileInfo[]> => Promise.resolve([]),
);

export function getFileDownloadUrl(runId: string, filePath: string): string {
  return httpApi.getFileDownloadUrl(runId, filePath);
}

export const openProjectInFileManager = withMode(
  (
    runId: string,
    path: string = ''
  ): Promise<httpApi.FileOperationResponse> => httpApi.openProjectInFileManager(runId, path),
  (
    _runId: string,
    _path: string = ''
  ): Promise<httpApi.FileOperationResponse> => Promise.resolve({ success: false, message: 'Not supported in pywebview mode' }),
);

export const viewProjectFile = withMode(
  (
    runId: string,
    path: string
  ): Promise<httpApi.FileOperationResponse> => httpApi.viewProjectFile(runId, path),
  (
    _runId: string,
    _path: string
  ): Promise<httpApi.FileOperationResponse> => Promise.resolve({ success: false, message: 'Not supported in pywebview mode' }),
);

// ============================================================
// Official Resource Sync API
// ============================================================

export type {
  OfficialSyncStatus,
  OfficialSyncResult,
  OfficialSyncResourceResult,
} from './client';

export const getOfficialSyncStatus = withMode(
  (): Promise<httpApi.OfficialSyncStatus> => httpApi.getOfficialSyncStatus(),
  // Official sync is only available in HTTP mode
  (): Promise<httpApi.OfficialSyncStatus> => Promise.resolve({
    enabled: false,
    last_sync: null,
    last_commit: null,
    repo: '',
    branch: 'main',
  }),
);

export const runOfficialSync = withMode(
  (): Promise<httpApi.OfficialSyncResult> => httpApi.runOfficialSync(),
  (): Promise<httpApi.OfficialSyncResult> => Promise.resolve({
    status: 'error',
    error: 'Official sync not supported in pywebview mode',
  }),
);

export const getOfficialSyncResult = withMode(
  (): Promise<httpApi.OfficialSyncResult> => httpApi.getOfficialSyncResult(),
  (): Promise<httpApi.OfficialSyncResult> => Promise.resolve({ status: 'idle' }),
);

export const setOfficialSyncEnabled = withMode(
  (enabled: boolean): Promise<ApiResponse> => httpApi.setOfficialSyncEnabled(enabled),
  (_enabled: boolean): Promise<ApiResponse> => Promise.resolve({
    status: 'error',
    error: 'Official sync not supported in pywebview mode',
  }),
);

// ============================================================
// Self-Update API
// ============================================================

export type { UpdateStatus } from './client';

export const startSelfUpdate = withMode(
  (): Promise<httpApi.UpdateStatus> => httpApi.startSelfUpdate(),
  (): Promise<httpApi.UpdateStatus> => Promise.resolve({
    status: 'error',
    progress: 0,
    message: 'Self-update not supported in pywebview mode',
    error: 'Not supported',
  }),
);

export const getSelfUpdateStatus = withMode(
  (): Promise<httpApi.UpdateStatus> => httpApi.getSelfUpdateStatus(),
  (): Promise<httpApi.UpdateStatus> => Promise.resolve({
    status: 'idle',
    progress: 0,
    message: '',
    error: null,
  }),
);

// ============================================================
// GitHub Star API
// ============================================================

export type { StarredStatus, StarResult } from './client';

export const checkGitHubStarred = withMode(
  (): Promise<httpApi.StarredStatus> => httpApi.checkGitHubStarred(),
  (): Promise<httpApi.StarredStatus> => Promise.resolve({
    status: 'ok',
    is_starred: null,
    gh_configured: false,
  }),
);

export const toggleGitHubStar = withMode(
  (star: boolean): Promise<httpApi.StarResult> => httpApi.toggleGitHubStar(star),
  (_star: boolean): Promise<httpApi.StarResult> => Promise.resolve({
    status: 'error',
    is_starred: null,
    error: 'Not supported in pywebview mode',
  }),
);

// ============================================================
// Guide API
// ============================================================

export type {
  GuideMeta,
  GuideCategory,
  GuideChapter,
  GuideContent,
  GuideTocItem,
  GuideSearchResponse,
  GuideSearchResult,
  GuideSearchMatch,
} from './client';

export const getGuideMeta = withMode(
  (lang: string = 'en'): Promise<httpApi.GuideMeta> => httpApi.getGuideMeta(lang),
  // Return empty meta in pywebview mode
  (_lang: string = 'en'): Promise<httpApi.GuideMeta> => Promise.resolve({
    version: '0.0.0',
    last_updated: '',
    languages: [],
    categories: [],
    chapters: [],
  }),
);

export const getGuideContent = withMode(
  (
    lang: string,
    chapterId: string
  ): Promise<httpApi.GuideContent | null> => httpApi.getGuideContent(lang, chapterId),
  (
    _lang: string,
    _chapterId: string
  ): Promise<httpApi.GuideContent | null> => Promise.resolve(null),
);

export const searchGuide = withMode(
  (
    query: string,
    lang: string = 'en'
  ): Promise<httpApi.GuideSearchResponse> => httpApi.searchGuide(query, lang),
  (
    query: string,
    _lang: string = 'en'
  ): Promise<httpApi.GuideSearchResponse> => Promise.resolve({
    query,
    total: 0,
    results: [],
  }),
);

// ============================================================
// API Profile Management
// ============================================================

export type {
  ProfileItem,
  ProfileListResponse,
  CreateProfileRequest,
  UpdateProfileRequest,
} from './client';

export const getProfiles = withMode(
  (): Promise<httpApi.ProfileListResponse> => httpApi.getProfiles(),
  (): Promise<httpApi.ProfileListResponse> => Promise.resolve({ profiles: [], active_profile_id: null }),
);

export const createProfile = withMode(
  (data: httpApi.CreateProfileRequest): Promise<ApiResponse> => httpApi.createProfile(data),
  (_data: httpApi.CreateProfileRequest): Promise<ApiResponse> => Promise.resolve({ status: 'error', error: 'Not supported in pywebview mode' }),
);

export const updateProfile = withMode(
  (id: string, data: httpApi.UpdateProfileRequest): Promise<ApiResponse> => httpApi.updateProfile(id, data),
  (_id: string, _data: httpApi.UpdateProfileRequest): Promise<ApiResponse> => Promise.resolve({ status: 'error', error: 'Not supported in pywebview mode' }),
);

export const deleteProfile = withMode(
  (id: string): Promise<ApiResponse> => httpApi.deleteProfile(id),
  (_id: string): Promise<ApiResponse> => Promise.resolve({ status: 'error', error: 'Not supported in pywebview mode' }),
);

export const activateProfile = withMode(
  (id: string): Promise<ApiResponse> => httpApi.activateProfile(id),
  (_id: string): Promise<ApiResponse> => Promise.resolve({ status: 'error', error: 'Not supported in pywebview mode' }),
);

export const deactivateProfile = withMode(
  (): Promise<ApiResponse> => httpApi.deactivateProfile(),
  (): Promise<ApiResponse> => Promise.resolve({ status: 'error', error: 'Not supported in pywebview mode' }),
);

export const saveCurrentAsProfile = withMode(
  (name: string): Promise<ApiResponse> => httpApi.saveCurrentAsProfile(name),
  (_name: string): Promise<ApiResponse> => Promise.resolve({ status: 'error', error: 'Not supported in pywebview mode' }),
);
