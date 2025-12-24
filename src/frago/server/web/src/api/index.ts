/**
 * Unified API Layer
 *
 * Automatically selects between pywebview API and HTTP API based on runtime environment.
 * This provides a seamless transition from pywebview to web service mode.
 */

import * as pywebviewApi from './pywebview';
import * as httpApi from './client';
import type {
  TaskItem,
  TaskDetail,
  TaskStepsResponse,
  TaskStatus,
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
  EnvVarsResponse,
  EnvVarsUpdateResponse,
  RecipeEnvRequirement,
  GhCliStatus,
  ApiResponse,
  CreateRepoResponse,
  SyncResponse,
  RepoVisibilityResponse,
  ListReposResponse,
  SelectRepoResponse,
  TutorialResponse,
} from '@/types/pywebview.d';

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

export async function getTasks(
  limit?: number,
  status?: TaskStatus
): Promise<TaskItem[]> {
  if (isPywebviewMode()) {
    return pywebviewApi.getTasks(limit, status);
  }

  // HTTP API - convert response format
  const response = await httpApi.getTasks({
    limit,
    status: status ?? undefined,
  });

  // Map HTTP response to pywebview format
  return response.tasks.map((t) => ({
    session_id: t.id,
    name: t.title,
    status: t.status as TaskStatus,
    started_at: t.started_at,
    ended_at: t.completed_at,
    duration_ms: t.duration_ms ?? 0,
    step_count: 0, // Not available in list response
    tool_call_count: 0, // Not available in list response
    last_activity: t.started_at,
    project_path: t.project_path ?? '',
  }));
}

export async function getTaskDetail(
  sessionId: string,
  stepsLimit?: number,
  stepsOffset?: number
): Promise<TaskDetail> {
  if (isPywebviewMode()) {
    return pywebviewApi.getTaskDetail(sessionId, stepsLimit, stepsOffset);
  }

  // HTTP API
  const task = await httpApi.getTask(sessionId);

  return {
    session_id: task.id,
    name: task.title,
    status: task.status as TaskStatus,
    started_at: '', // Not in current response
    ended_at: null,
    duration_ms: task.summary?.total_duration_ms ?? 0,
    project_path: '',
    step_count: task.steps.length,
    tool_call_count: task.summary?.tool_call_count ?? 0,
    user_message_count: task.summary?.user_message_count ?? 0,
    assistant_message_count: task.summary?.assistant_message_count ?? 0,
    steps: task.steps.map((s, i) => ({
      step_id: i,
      type: s.type as TaskDetail['steps'][0]['type'],
      timestamp: s.timestamp,
      content: s.content,
      tool_name: s.tool_name,
      tool_status: null,
    })),
    steps_total: task.steps.length,
    steps_offset: stepsOffset ?? 0,
    has_more_steps: false,
    summary: task.summary
      ? {
          total_duration_ms: task.summary.total_duration_ms,
          user_message_count: task.summary.user_message_count,
          assistant_message_count: task.summary.assistant_message_count,
          tool_call_count: task.summary.tool_call_count,
          tool_success_count: task.summary.tool_success_count,
          tool_error_count: task.summary.tool_error_count,
          most_used_tools: task.summary.most_used_tools,
        }
      : null,
  };
}

export async function getTaskSteps(
  sessionId: string,
  offset?: number,
  limit?: number
): Promise<TaskStepsResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.getTaskSteps(sessionId, offset, limit);
  }

  const response = await httpApi.getTaskSteps(sessionId, { offset, limit });

  return {
    steps: response.steps.map((s, i) => ({
      step_id: i + (offset ?? 0),
      type: s.type as TaskStepsResponse['steps'][0]['type'],
      timestamp: s.timestamp,
      content: s.content,
      tool_name: s.tool_name,
      tool_status: null,
    })),
    total: response.total,
    offset: offset ?? 0,
    has_more: response.has_more,
  };
}

export async function startAgentTask(
  prompt: string
): Promise<TaskStartResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.startAgentTask(prompt);
  }

  const task = await httpApi.startAgent(prompt);
  return {
    status: 'ok',
    task_id: task.id,
    message: `Started task: ${task.title}`,
  };
}

export async function continueAgentTask(
  sessionId: string,
  prompt: string
): Promise<TaskStartResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.continueAgentTask(sessionId, prompt);
  }

  // HTTP API doesn't support continue yet - start new task
  const task = await httpApi.startAgent(prompt);
  return {
    status: 'ok',
    task_id: task.id,
    message: `Started new task (continue not supported in web mode): ${task.title}`,
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

  const recipe = await httpApi.getRecipe(name);
  return {
    name: recipe.name,
    description: recipe.description,
    category: recipe.category as RecipeDetail['category'],
    icon: recipe.icon,
    tags: recipe.tags,
    path: recipe.path,
    source: recipe.source as RecipeDetail['source'],
    runtime: recipe.runtime as RecipeDetail['runtime'],
    metadata_content: null,
    recipe_dir: null,
  };
}

export async function runRecipe(
  name: string,
  params?: Record<string, unknown>
): Promise<RecipeRunResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.runRecipe(name, params);
  }

  try {
    await httpApi.runRecipe(name, params);
    return {
      status: 'ok',
      output: 'Recipe started',
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
    font_size: config.font_size,
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
        font_size: updated.font_size,
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

  // HTTP API - return mock system status
  return {
    cpu_percent: 0,
    memory_percent: 0,
    chrome_connected: false,
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

  // HTTP API can't open paths on client
  return {
    status: 'error',
    error: 'Cannot open paths in web service mode',
  };
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
    auth_method: (config.auth_method === 'api_key' ? 'custom' : 'official') as MainConfig['auth_method'],
    ccr_enabled: false,
    sync_repo_url: config.sync_repo ?? undefined,
    working_directory_display: config.working_directory,
    resources_installed: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    init_completed: true,
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
      backendUpdates.auth_method = updates.auth_method === 'custom' ? 'api_key' : 'official';
    }
    if (updates.sync_repo_url !== undefined) {
      backendUpdates.sync_repo = updates.sync_repo_url;
    }

    const config = await httpApi.updateMainConfig(backendUpdates);
    return {
      status: 'ok',
      config: {
        schema_version: '1.0',
        auth_method: (config.auth_method === 'api_key' ? 'custom' : 'official') as MainConfig['auth_method'],
        ccr_enabled: false,
        sync_repo_url: config.sync_repo ?? undefined,
        working_directory_display: config.working_directory,
        resources_installed: true,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
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

  // HTTP API - update auth_method through main config
  return updateMainConfig({ auth_method: authData.auth_method });
}

export async function openWorkingDirectory(): Promise<ApiResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.openWorkingDirectory();
  }

  return {
    status: 'error',
    error: 'Cannot open working directory in web service mode',
  };
}

// ============================================================
// Settings API - Environment Variables Management
// ============================================================

export async function getEnvVars(): Promise<EnvVarsResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.getEnvVars();
  }

  // HTTP API
  const result = await httpApi.getEnvVars();
  return {
    vars: result.vars,
    file_exists: result.file_exists,
  };
}

export async function updateEnvVars(
  updates: Record<string, string | null>
): Promise<EnvVarsUpdateResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.updateEnvVars(updates);
  }

  // HTTP API
  try {
    const result = await httpApi.updateEnvVars(updates);
    return {
      status: 'ok',
      vars: result.vars,
    };
  } catch (error) {
    return {
      status: 'error',
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export async function getRecipeEnvRequirements(): Promise<RecipeEnvRequirement[]> {
  if (isPywebviewMode()) {
    return pywebviewApi.getRecipeEnvRequirements();
  }

  // HTTP API
  const requirements = await httpApi.getRecipeEnvRequirements();
  return requirements.map((r) => ({
    recipe_name: '',  // Not available from simple API
    var_name: r.name,
    description: r.description ?? '',
    required: r.required,
    configured: false,  // Will need to check against env vars
  }));
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

export async function createSyncRepo(
  repoName: string,
  privateRepo: boolean = true
): Promise<CreateRepoResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.createSyncRepo(repoName, privateRepo);
  }

  return {
    status: 'error',
    error: 'Sync repo creation not available in web service mode',
  };
}

export async function runFirstSync(): Promise<SyncResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.runFirstSync();
  }

  return {
    status: 'error',
    error: 'Sync not available in web service mode',
  };
}

export async function getSyncResult(): Promise<SyncResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.getSyncResult();
  }

  return {
    status: 'error',
    error: 'Sync not available in web service mode',
  };
}

export async function checkSyncRepoVisibility(): Promise<RepoVisibilityResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.checkSyncRepoVisibility();
  }

  return {
    status: 'error',
    error: 'Sync repo visibility check not available in web service mode',
  };
}

export async function listUserRepos(limit?: number): Promise<ListReposResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.listUserRepos(limit);
  }

  return {
    status: 'error',
    error: 'Repo listing not available in web service mode',
  };
}

export async function selectExistingRepo(sshUrl: string): Promise<SelectRepoResponse> {
  if (isPywebviewMode()) {
    return pywebviewApi.selectExistingRepo(sshUrl);
  }

  return {
    status: 'error',
    error: 'Repo selection not available in web service mode',
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
// Dashboard API
// ============================================================

export interface DashboardData {
  server: {
    running: boolean;
    uptime_seconds: number;
    started_at: string | null;
  };
  recent_activity: Array<{
    id: string;
    type: string;
    title: string;
    status: string;
    timestamp: string;
  }>;
  resource_counts: {
    tasks: number;
    recipes: number;
    skills: number;
  };
}

export async function getDashboard(): Promise<DashboardData> {
  if (isPywebviewMode()) {
    // pywebview mode - dashboard not supported, return mock data
    return {
      server: { running: true, uptime_seconds: 0, started_at: null },
      recent_activity: [],
      resource_counts: { tasks: 0, recipes: 0, skills: 0 },
    };
  }

  // HTTP mode - fetch from dashboard API
  return httpApi.getDashboard();
}
