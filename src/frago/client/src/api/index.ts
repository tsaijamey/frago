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

// ============================================================
// API Ready State
// ============================================================

export async function waitForApi(): Promise<void> {
  if (isPywebviewMode()) {
    await pywebviewApi.waitForPywebview();
  } else {
    await httpApi.waitForApi();
  }
}

export function isApiReady(): boolean {
  if (isPywebviewMode()) {
    return pywebviewApi.isApiReady();
  }
  // HTTP API is always "ready" once page loads
  return true;
}

// ============================================================
// Tasks API
// ============================================================

export async function startAgentTask(
  prompt: string
): Promise<TaskStartResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.startAgentTask(prompt);
  }

  // Start the task - the returned task_id is NOT the Claude session_id
  // Frontend should poll the task list to get the real session_id
  const task = await httpApi.startAgent(prompt);
  return {
    status: 'ok',
    // Don't return task_id - it won't match the Claude session_id
    // The real session_id will appear in the task list after sync
    message: `Started task: ${task.title}`,
  };
}

// ============================================================
// Recipes API
// ============================================================

export async function getRecipes(): Promise<RecipeItem[]> {
  if (isPywebviewMode()) {
    return pywebviewApi.getRecipes();
  }

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
}

export async function refreshRecipes(): Promise<RecipeItem[]> {
  if (isPywebviewMode()) {
    return pywebviewApi.refreshRecipes();
  }

  // HTTP mode - just fetch again
  return getRecipes();
}

export async function getRecipeDetail(name: string): Promise<RecipeDetail> {
  if (isPywebviewMode()) {
    return pywebviewApi.getRecipeDetail(name);
  }

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
}

export async function runRecipe(
  name: string,
  params?: Record<string, unknown>,
): Promise<RecipeRunResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.runRecipe(name, params);
  }

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
}

export async function runRecipeAsync(
  name: string,
  params?: Record<string, unknown>,
  timeout?: number,
): Promise<{ execution_id: string; status: string; poll_url: string }> {
  return httpApi.runRecipeAsync(name, params, timeout);
}

export async function deleteRecipe(
  name: string
): Promise<RecipeDeleteResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.deleteRecipe(name);
  }

  // HTTP API doesn't support delete yet
  return {
    status: 'error',
    message: 'Delete not supported in web service mode',
  };
}

// ============================================================
// Skills API
// ============================================================

export async function getSkills(): Promise<SkillItem[]> {
  if (isPywebviewMode()) {
    return pywebviewApi.getSkills();
  }

  // HTTP API
  const skills = await httpApi.getSkills();
  return skills.map((s) => ({
    name: s.name,
    description: s.description,
    icon: null,  // HTTP API doesn't return icons yet
    file_path: s.file_path ?? '',
  }));
}

export async function refreshSkills(): Promise<SkillItem[]> {
  if (isPywebviewMode()) {
    return pywebviewApi.refreshSkills();
  }

  // HTTP mode - just fetch again
  return getSkills();
}

// ============================================================
// Config API
// ============================================================

export async function getConfig(): Promise<UserConfig> {
  if (isPywebviewMode()) {
    return pywebviewApi.getConfig();
  }

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
}

export async function updateConfig(
  config: Partial<UserConfig>
): Promise<ConfigUpdateResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.updateConfig(config);
  }

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
}

// ============================================================
// System API
// ============================================================

export async function getSystemStatus(): Promise<SystemStatus> {
  if (isPywebviewMode()) {
    return pywebviewApi.getSystemStatus();
  }

  // HTTP API - call real /api/status endpoint
  const status = await httpApi.getServerStatus();
  return {
    cpu_percent: status.cpu_percent ?? 0,
    memory_percent: status.memory_percent ?? 0,
    chrome_connected: status.chrome_connected ?? false,
  };
}

export async function checkConnection(): Promise<ConnectionStatus> {
  if (isPywebviewMode()) {
    return pywebviewApi.checkConnection();
  }

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
}

export async function openPath(
  path: string,
  reveal: boolean = false
): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.openPath(path, reveal);
  }

  return httpApi.openPath(path, reveal);
}

// ============================================================
// Settings API - Main Config Management
// ============================================================

export async function getMainConfig(): Promise<MainConfig> {
  if (isPywebviewMode()) {
    return pywebviewApi.getMainConfig();
  }

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
}

export async function updateMainConfig(
  updates: Partial<MainConfig>
): Promise<MainConfigUpdateResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.updateMainConfig(updates);
  }

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
}

export async function updateAuthMethod(
  authData: AuthUpdateRequest
): Promise<MainConfigUpdateResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.updateAuthMethod(authData);
  }

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
}

export async function openWorkingDirectory(): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.openWorkingDirectory();
  }

  return httpApi.openWorkingDirectory();
}

// ============================================================
// Settings API - Recipe Secrets Management
// ============================================================

export async function getRecipeSecrets(recipeName: string): Promise<RecipeSecretsResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.getRecipeSecrets(recipeName);
  }

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
}

export async function updateRecipeSecrets(
  recipeName: string,
  updates: Record<string, unknown>
): Promise<RecipeSecretsUpdateResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.updateRecipeSecrets(recipeName, updates);
  }

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
}

// ============================================================
// Settings API - GitHub Integration
// ============================================================

export async function checkGhCli(): Promise<GhCliStatus> {
  if (isPywebviewMode()) {
    return pywebviewApi.checkGhCli();
  }

  // HTTP API
  const status = await httpApi.checkGhCli();
  return {
    installed: status.installed,
    authenticated: status.authenticated,
    version: status.version ?? undefined,
    username: status.username ?? undefined,
  };
}

export async function ghAuthLogin(): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.ghAuthLogin();
  }

  // HTTP API
  const result = await httpApi.ghAuthLogin();
  return {
    status: (result.status === 'ok' ? 'ok' : 'error') as 'ok' | 'error',
    error: result.error ?? undefined,
  };
}

// ============================================================
// Tutorial API
// ============================================================

export async function openTutorial(
  tutorialId: string,
  lang: string = 'auto',
  anchor: string = ''
): Promise<TutorialResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.openTutorial(tutorialId, lang, anchor);
  }

  return {
    status: 'error',
    error: 'Tutorial not available in web service mode',
  };
}

// ============================================================
// VSCode Integration API
// ============================================================

export async function checkVSCode(): Promise<{ available: boolean }> {
  if (isPywebviewMode()) {
    return { available: false }; // pywebview mode doesn't support this
  }
  return httpApi.checkVSCode();
}

export async function openConfigInVSCode(): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return { status: 'error', error: 'Not supported in pywebview mode' };
  }
  return httpApi.openConfigInVSCode();
}


// ============================================================
// Claude Code Sessions API
// ============================================================

export type {
  ClaudeSessionHuman,
  ClaudeSessionItem,
  ClaudeSessionsResponse,
  ClaudeSessionMessage,
  ClaudeSessionDetail,
} from './client';

export async function getClaudeSessions(options?: {
  days?: number;
  since?: string;
  until?: string;
}): Promise<httpApi.ClaudeSessionsResponse> {
  if (isPywebviewMode()) {
    throw new Error('Claude sessions API not available in pywebview mode');
  }
  return httpApi.getClaudeSessions(options);
}

export async function getClaudeSessionDetail(
  sid: string,
  limit?: number
): Promise<httpApi.ClaudeSessionDetail> {
  if (isPywebviewMode()) {
    throw new Error('Claude sessions API not available in pywebview mode');
  }
  return httpApi.getClaudeSessionDetail(sid, limit);
}

// ============================================================
// Community Recipes API
// ============================================================

export async function getCommunityRecipes(): Promise<CommunityRecipeItem[]> {
  if (isPywebviewMode()) {
    // pywebview mode - not supported
    return [];
  }

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
}

export async function installCommunityRecipe(
  name: string,
  force: boolean = false
): Promise<CommunityRecipeInstallResponse> {
  if (isPywebviewMode()) {
    return {
      status: 'error',
      error: 'Community recipes not supported in pywebview mode',
    };
  }

  return httpApi.installCommunityRecipe(name, force);
}

export async function updateCommunityRecipe(
  name: string
): Promise<CommunityRecipeInstallResponse> {
  if (isPywebviewMode()) {
    return {
      status: 'error',
      error: 'Community recipes not supported in pywebview mode',
    };
  }

  return httpApi.updateCommunityRecipe(name);
}

export async function uninstallCommunityRecipe(
  name: string
): Promise<CommunityRecipeInstallResponse> {
  if (isPywebviewMode()) {
    return {
      status: 'error',
      error: 'Community recipes not supported in pywebview mode',
    };
  }

  return httpApi.uninstallCommunityRecipe(name);
}

// ============================================================
// Project Files API
// ============================================================

export type {
  ProjectInfo,
  ProjectDetail,
  FileInfo,
  FileOperationResponse,
} from './client';

export async function getProjects(): Promise<httpApi.ProjectInfo[]> {
  if (isPywebviewMode()) {
    return [];
  }
  return httpApi.getProjects();
}

export async function refreshProjects(): Promise<httpApi.ProjectInfo[]> {
  if (isPywebviewMode()) {
    return [];
  }
  return httpApi.refreshProjects();
}

export async function getProject(runId: string): Promise<httpApi.ProjectDetail | null> {
  if (isPywebviewMode()) {
    return null;
  }
  return httpApi.getProject(runId);
}

export async function getProjectFiles(
  runId: string,
  path: string = ''
): Promise<httpApi.FileInfo[]> {
  if (isPywebviewMode()) {
    return [];
  }
  return httpApi.getProjectFiles(runId, path);
}

export function getFileDownloadUrl(runId: string, filePath: string): string {
  return httpApi.getFileDownloadUrl(runId, filePath);
}

export async function openProjectInFileManager(
  runId: string,
  path: string = ''
): Promise<httpApi.FileOperationResponse> {
  if (isPywebviewMode()) {
    return { success: false, message: 'Not supported in pywebview mode' };
  }
  return httpApi.openProjectInFileManager(runId, path);
}

export async function viewProjectFile(
  runId: string,
  path: string
): Promise<httpApi.FileOperationResponse> {
  if (isPywebviewMode()) {
    return { success: false, message: 'Not supported in pywebview mode' };
  }
  return httpApi.viewProjectFile(runId, path);
}

// ============================================================
// Official Resource Sync API
// ============================================================

export type {
  OfficialSyncStatus,
  OfficialSyncResult,
  OfficialSyncResourceResult,
} from './client';

export async function getOfficialSyncStatus(): Promise<httpApi.OfficialSyncStatus> {
  // Official sync is only available in HTTP mode
  if (isPywebviewMode()) {
    return {
      enabled: false,
      last_sync: null,
      last_commit: null,
      repo: '',
      branch: 'main',
    };
  }
  return httpApi.getOfficialSyncStatus();
}

export async function runOfficialSync(): Promise<httpApi.OfficialSyncResult> {
  if (isPywebviewMode()) {
    return {
      status: 'error',
      error: 'Official sync not supported in pywebview mode',
    };
  }
  return httpApi.runOfficialSync();
}

export async function getOfficialSyncResult(): Promise<httpApi.OfficialSyncResult> {
  if (isPywebviewMode()) {
    return { status: 'idle' };
  }
  return httpApi.getOfficialSyncResult();
}

export async function setOfficialSyncEnabled(enabled: boolean): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return {
      status: 'error',
      error: 'Official sync not supported in pywebview mode',
    };
  }
  return httpApi.setOfficialSyncEnabled(enabled);
}

// ============================================================
// Self-Update API
// ============================================================

export type { UpdateStatus } from './client';

export async function startSelfUpdate(): Promise<httpApi.UpdateStatus> {
  if (isPywebviewMode()) {
    return {
      status: 'error',
      progress: 0,
      message: 'Self-update not supported in pywebview mode',
      error: 'Not supported',
    };
  }
  return httpApi.startSelfUpdate();
}

export async function getSelfUpdateStatus(): Promise<httpApi.UpdateStatus> {
  if (isPywebviewMode()) {
    return {
      status: 'idle',
      progress: 0,
      message: '',
      error: null,
    };
  }
  return httpApi.getSelfUpdateStatus();
}

// ============================================================
// GitHub Star API
// ============================================================

export type { StarredStatus, StarResult } from './client';

export async function checkGitHubStarred(): Promise<httpApi.StarredStatus> {
  if (isPywebviewMode()) {
    return {
      status: 'ok',
      is_starred: null,
      gh_configured: false,
    };
  }
  return httpApi.checkGitHubStarred();
}

export async function toggleGitHubStar(star: boolean): Promise<httpApi.StarResult> {
  if (isPywebviewMode()) {
    return {
      status: 'error',
      is_starred: null,
      error: 'Not supported in pywebview mode',
    };
  }
  return httpApi.toggleGitHubStar(star);
}

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

export async function getGuideMeta(lang: string = 'en'): Promise<httpApi.GuideMeta> {
  if (isPywebviewMode()) {
    // Return empty meta in pywebview mode
    return {
      version: '0.0.0',
      last_updated: '',
      languages: [],
      categories: [],
      chapters: [],
    };
  }
  return httpApi.getGuideMeta(lang);
}

export async function getGuideContent(
  lang: string,
  chapterId: string
): Promise<httpApi.GuideContent | null> {
  if (isPywebviewMode()) {
    return null;
  }
  return httpApi.getGuideContent(lang, chapterId);
}

export async function searchGuide(
  query: string,
  lang: string = 'en'
): Promise<httpApi.GuideSearchResponse> {
  if (isPywebviewMode()) {
    return {
      query,
      total: 0,
      results: [],
    };
  }
  return httpApi.searchGuide(query, lang);
}

// ============================================================
// API Profile Management
// ============================================================

export type {
  ProfileItem,
  ProfileListResponse,
  CreateProfileRequest,
  UpdateProfileRequest,
} from './client';

export async function getProfiles(): Promise<httpApi.ProfileListResponse> {
  if (isPywebviewMode()) {
    return { profiles: [], active_profile_id: null };
  }
  return httpApi.getProfiles();
}

export async function createProfile(data: httpApi.CreateProfileRequest): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return { status: 'error', error: 'Not supported in pywebview mode' };
  }
  return httpApi.createProfile(data);
}

export async function updateProfile(id: string, data: httpApi.UpdateProfileRequest): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return { status: 'error', error: 'Not supported in pywebview mode' };
  }
  return httpApi.updateProfile(id, data);
}

export async function deleteProfile(id: string): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return { status: 'error', error: 'Not supported in pywebview mode' };
  }
  return httpApi.deleteProfile(id);
}

export async function activateProfile(id: string): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return { status: 'error', error: 'Not supported in pywebview mode' };
  }
  return httpApi.activateProfile(id);
}

export async function deactivateProfile(): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return { status: 'error', error: 'Not supported in pywebview mode' };
  }
  return httpApi.deactivateProfile();
}

export async function saveCurrentAsProfile(name: string): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return { status: 'error', error: 'Not supported in pywebview mode' };
  }
  return httpApi.saveCurrentAsProfile(name);
}
