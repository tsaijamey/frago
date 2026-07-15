/**
 * HTTP API Client for Frago Web Service
 *
 * Provides fetch-based API calls to the FastAPI backend.
 * This replaces pywebview.api when running in web service mode.
 *
 * Type definitions live in `@/types/api`; they are imported here for use in
 * the HTTP signatures and re-exported to preserve the existing import contract
 * (callers do `import type { ... } from '@/api/client'` and via the `api` barrel).
 */

import type {
  ServerInfo,
  ServerStatus,
  RecipeItem,
  TaskItem,
  TaskStep,
  ToolUsageStat,
  TaskSummary,
  TaskDetail,
  TaskListResponse,
  TaskStepsResponse,
  UserConfig,
  SystemDirectories,
  GenerateTitleResponse,
  AgentAttachedStartResponse,
  AgentAttachedInfo,
  SkillItem,
  GhCliStatus,
  APIEndpointConfig,
  MainConfig,
  ApiResponse,
  APIEndpointRequest,
  AuthUpdateRequest,
  RecipeSecretsFieldHttp,
  RecipeSecretsResponseHttp,
  VSCodeStatus,
  RunningTaskSummary,
  RecentTaskSummary,
  QuickRecipeItem,
  DashboardResourceCounts,
  DashboardStatus,
  DashboardData,
  DependencyStatus,
  InitStatus,
  DependencyCheckResult,
  InstallResultSummary,
  ResourceInstallResult,
  DependencyInstallResult,
  InitCompleteResult,
  CommunityRecipeItem,
  CommunityRecipeInstallResponse,
  ProjectInfo,
  ProjectDetail,
  FileInfo,
  FileOperationResponse,
  OfficialSyncStatus,
  OfficialSyncResourceResult,
  OfficialSyncResult,
  UpdateStatus,
  StarredStatus,
  StarResult,
  ProfileItem,
  ProfileListResponse,
  CreateProfileRequest,
  UpdateProfileRequest,
  GuideCategory,
  GuideChapter,
  GuideMeta,
  GuideTocItem,
  GuideContent,
  GuideSearchMatch,
  GuideSearchResult,
  GuideSearchResponse,
  TaskIngestionChannel,
  TaskIngestionGetResponse,
  TaskIngestionPutResponse,
  ClaudeSessionHuman,
  ClaudeSessionItem,
  ClaudeSessionsResponse,
  ClaudeSessionBlock,
  ClaudeSessionMessage,
  ClaudeSessionDetail,
  ClaudeSessionSendResponse,
  PaSessionItem,
  PaSessionsResponse,
  PaSessionSendResponse,
  TokenCalendarResponse,
  TokenDayBucket,
} from '@/types/api';

export type {
  ServerInfo,
  ServerStatus,
  RecipeItem,
  TaskItem,
  TaskStep,
  ToolUsageStat,
  TaskSummary,
  TaskDetail,
  TaskListResponse,
  TaskStepsResponse,
  UserConfig,
  SystemDirectories,
  GenerateTitleResponse,
  AgentAttachedStartResponse,
  AgentAttachedInfo,
  SkillItem,
  GhCliStatus,
  APIEndpointConfig,
  MainConfig,
  ApiResponse,
  APIEndpointRequest,
  AuthUpdateRequest,
  RecipeSecretsFieldHttp,
  RecipeSecretsResponseHttp,
  VSCodeStatus,
  RunningTaskSummary,
  RecentTaskSummary,
  QuickRecipeItem,
  DashboardResourceCounts,
  DashboardStatus,
  DashboardData,
  DependencyStatus,
  InitStatus,
  DependencyCheckResult,
  InstallResultSummary,
  ResourceInstallResult,
  DependencyInstallResult,
  InitCompleteResult,
  CommunityRecipeItem,
  CommunityRecipeInstallResponse,
  ProjectInfo,
  ProjectDetail,
  FileInfo,
  FileOperationResponse,
  OfficialSyncStatus,
  OfficialSyncResourceResult,
  OfficialSyncResult,
  UpdateStatus,
  StarredStatus,
  StarResult,
  ProfileItem,
  ProfileListResponse,
  CreateProfileRequest,
  UpdateProfileRequest,
  GuideCategory,
  GuideChapter,
  GuideMeta,
  GuideTocItem,
  GuideContent,
  GuideSearchMatch,
  GuideSearchResult,
  GuideSearchResponse,
  TaskIngestionChannel,
  TaskIngestionGetResponse,
  TaskIngestionPutResponse,
  ClaudeSessionHuman,
  ClaudeSessionItem,
  ClaudeSessionsResponse,
  ClaudeSessionBlock,
  ClaudeSessionMessage,
  ClaudeSessionDetail,
  ClaudeSessionSendResponse,
  PaSessionItem,
  PaSessionsResponse,
  PaSessionSendResponse,
  TokenCalendarResponse,
  TokenDayBucket,
};

// API base URL - defaults to same origin in production, configurable for dev
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/**
 * HTTP client wrapper with error handling
 */
async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}/api${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
  }

  return response.json();
}

// ============================================================
// System API
// ============================================================

export async function getServerStatus(): Promise<ServerStatus> {
  return fetchApi<ServerStatus>('/status');
}

export async function getServerInfo(): Promise<ServerInfo> {
  return fetchApi<ServerInfo>('/info');
}

export async function getSystemDirectories(): Promise<SystemDirectories> {
  return fetchApi<SystemDirectories>('/system/directories');
}

// ============================================================
// Recipes API
// ============================================================

export async function getRecipes(): Promise<RecipeItem[]> {
  return fetchApi<RecipeItem[]>('/recipes');
}

export async function getRecipe(name: string): Promise<RecipeItem> {
  return fetchApi<RecipeItem>(`/recipes/${encodeURIComponent(name)}`);
}

export async function runRecipe(
  name: string,
  params?: Record<string, unknown>,
  timeout?: number,
): Promise<TaskItem> {
  return fetchApi<TaskItem>(`/recipes/${encodeURIComponent(name)}/run`, {
    method: 'POST',
    body: JSON.stringify({ params, timeout }),
  });
}

export async function runRecipeAsync(
  name: string,
  params?: Record<string, unknown>,
  timeout?: number,
): Promise<{ execution_id: string; status: string; poll_url: string }> {
  return fetchApi(`/recipes/${encodeURIComponent(name)}/run-async`, {
    method: 'POST',
    body: JSON.stringify({ params, timeout }),
  });
}

// ============================================================
// Tasks API
// ============================================================

export async function getTasks(options?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<TaskListResponse> {
  const params = new URLSearchParams();
  if (options?.status) params.set('status', options.status);
  if (options?.limit) params.set('limit', String(options.limit));
  if (options?.offset) params.set('offset', String(options.offset));

  const query = params.toString();
  return fetchApi<TaskListResponse>(`/tasks${query ? `?${query}` : ''}`);
}

export async function getTask(taskId: string): Promise<TaskDetail> {
  return fetchApi<TaskDetail>(`/tasks/${encodeURIComponent(taskId)}`);
}

export async function generateTaskTitle(taskId: string): Promise<GenerateTitleResponse> {
  return fetchApi<GenerateTitleResponse>(
    `/tasks/${encodeURIComponent(taskId)}/generate-title`,
    { method: 'POST' }
  );
}

export async function getTaskSteps(
  taskId: string,
  options?: { limit?: number; offset?: number }
): Promise<TaskStepsResponse> {
  const params = new URLSearchParams();
  if (options?.limit) params.set('limit', String(options.limit));
  if (options?.offset) params.set('offset', String(options.offset));

  const query = params.toString();
  return fetchApi<TaskStepsResponse>(
    `/tasks/${encodeURIComponent(taskId)}/steps${query ? `?${query}` : ''}`
  );
}

// ============================================================
// Agent API
// ============================================================

export async function startAgent(
  prompt: string,
  projectPath?: string
): Promise<TaskItem> {
  return fetchApi<TaskItem>('/agent', {
    method: 'POST',
    body: JSON.stringify({ prompt, project_path: projectPath }),
  });
}

// ============================================================
// Agent Attached API (real-time streaming mode)
// ============================================================

export async function startAgentAttached(
  prompt: string,
  projectPath?: string
): Promise<AgentAttachedStartResponse> {
  return fetchApi<AgentAttachedStartResponse>('/agent/attached', {
    method: 'POST',
    body: JSON.stringify({ prompt, project_path: projectPath }),
  });
}

export async function sendAgentAttachedMessage(
  internalId: string,
  prompt: string
): Promise<{ status: string }> {
  return fetchApi<{ status: string }>(`/agent/attached/${internalId}/message`, {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  });
}

export async function stopAgentAttached(
  internalId: string
): Promise<{ status: string }> {
  return fetchApi<{ status: string }>(`/agent/attached/${internalId}/stop`, {
    method: 'POST',
  });
}

export async function getAgentAttachedInfo(
  internalId: string
): Promise<AgentAttachedInfo> {
  return fetchApi<AgentAttachedInfo>(`/agent/attached/${internalId}/info`);
}

// ============================================================
// Config API
// ============================================================

export async function getConfig(): Promise<UserConfig> {
  return fetchApi<UserConfig>('/config');
}

export async function updateConfig(
  config: Partial<UserConfig>
): Promise<UserConfig> {
  return fetchApi<UserConfig>('/config', {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

// ============================================================
// Skills API
// ============================================================

export async function getSkills(): Promise<SkillItem[]> {
  return fetchApi<SkillItem[]>('/skills');
}

// ============================================================
// Settings API
// ============================================================

export async function checkGhCli(): Promise<GhCliStatus> {
  return fetchApi<GhCliStatus>('/settings/gh-cli');
}

export async function ghAuthLogin(): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/gh-cli/login', { method: 'POST' });
}

export async function getMainConfig(): Promise<MainConfig> {
  return fetchApi<MainConfig>('/settings/main-config');
}

export async function updateMainConfig(updates: Partial<MainConfig>): Promise<MainConfig> {
  return fetchApi<MainConfig>('/settings/main-config', {
    method: 'PUT',
    body: JSON.stringify(updates),
  });
}

export async function updateAuth(request: AuthUpdateRequest): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/update-auth', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function getRecipeSecrets(recipeName: string): Promise<RecipeSecretsResponseHttp> {
  return fetchApi<RecipeSecretsResponseHttp>(`/settings/recipe-secrets/${encodeURIComponent(recipeName)}`);
}

export async function updateRecipeSecrets(recipeName: string, updates: Record<string, unknown>): Promise<ApiResponse> {
  return fetchApi<ApiResponse>(`/settings/recipe-secrets/${encodeURIComponent(recipeName)}`, {
    method: 'PUT',
    body: JSON.stringify({ updates }),
  });
}

export async function openWorkingDirectory(): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/open-working-directory', { method: 'POST' });
}

export async function openPath(path: string, reveal: boolean = false): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/open-path', {
    method: 'POST',
    body: JSON.stringify({ path, reveal }),
  });
}

// ============================================================
// VSCode Integration API
// ============================================================

export async function checkVSCode(): Promise<VSCodeStatus> {
  return fetchApi<VSCodeStatus>('/settings/vscode-status');
}

export async function openConfigInVSCode(): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/open-in-vscode', { method: 'POST' });
}

// ============================================================
// Dashboard API
// ============================================================

export async function getDashboard(): Promise<DashboardData> {
  return fetchApi<DashboardData>('/dashboard');
}

// ============================================================
// API Mode Detection
// ============================================================

/**
 * Check if running in web service mode (HTTP) vs pywebview mode
 */
export function isWebServiceMode(): boolean {
  // If pywebview API is available, we're in pywebview mode
  return !window.pywebview?.api;
}

/**
 * Wait for API to be ready (for compatibility with pywebview pattern)
 */
export async function waitForApi(): Promise<void> {
  // In web service mode, API is always ready
  // Just do a health check
  try {
    await getServerStatus();
  } catch {
    throw new Error('Failed to connect to Frago web service');
  }
}

// ============================================================
// Init API - Web-based frago initialization
// ============================================================

/**
 * Get comprehensive initialization status.
 * Returns dependency status, resource status, and auth configuration.
 */
export async function getInitStatus(): Promise<InitStatus> {
  return fetchApi<InitStatus>('/init/status');
}

/**
 * Run fresh dependency check for Node.js and Claude Code.
 */
export async function checkDependencies(): Promise<DependencyCheckResult> {
  return fetchApi<DependencyCheckResult>('/init/check-deps', { method: 'POST' });
}

/**
 * Install a specific dependency (node or claude-code).
 * Note: Node.js installation on Windows requires manual installation.
 */
export async function installDependency(name: 'node' | 'claude-code'): Promise<DependencyInstallResult> {
  return fetchApi<DependencyInstallResult>(`/init/install-dep/${name}`, { method: 'POST' });
}

/**
 * Install or update resources (commands, skills, recipes).
 */
export async function installResources(forceUpdate: boolean = false): Promise<ResourceInstallResult> {
  return fetchApi<ResourceInstallResult>('/init/install-resources', {
    method: 'POST',
    body: JSON.stringify({ force_update: forceUpdate }),
  });
}

/**
 * Mark initialization as complete.
 * The init wizard will not show again after this.
 */
export async function markInitComplete(): Promise<InitCompleteResult> {
  return fetchApi<InitCompleteResult>('/init/complete', { method: 'POST' });
}

/**
 * Reset initialization status to re-run the wizard.
 */
export async function resetInitStatus(): Promise<InitCompleteResult> {
  return fetchApi<InitCompleteResult>('/init/reset', { method: 'POST' });
}

// ============================================================
// Community Recipes API
// ============================================================

/**
 * Get all community recipes with installation status.
 */
export async function getCommunityRecipes(): Promise<CommunityRecipeItem[]> {
  return fetchApi<CommunityRecipeItem[]>('/community-recipes');
}

/**
 * Get a specific community recipe by name.
 */
export async function getCommunityRecipe(name: string): Promise<CommunityRecipeItem> {
  return fetchApi<CommunityRecipeItem>(`/community-recipes/${encodeURIComponent(name)}`);
}

/**
 * Install a community recipe.
 */
export async function installCommunityRecipe(
  name: string,
  force: boolean = false
): Promise<CommunityRecipeInstallResponse> {
  return fetchApi<CommunityRecipeInstallResponse>(
    `/community-recipes/${encodeURIComponent(name)}/install`,
    {
      method: 'POST',
      body: JSON.stringify({ force }),
    }
  );
}

/**
 * Update an installed community recipe.
 */
export async function updateCommunityRecipe(
  name: string
): Promise<CommunityRecipeInstallResponse> {
  return fetchApi<CommunityRecipeInstallResponse>(
    `/community-recipes/${encodeURIComponent(name)}/update`,
    { method: 'POST' }
  );
}

/**
 * Uninstall an installed community recipe.
 */
export async function uninstallCommunityRecipe(
  name: string
): Promise<CommunityRecipeInstallResponse> {
  return fetchApi<CommunityRecipeInstallResponse>(
    `/community-recipes/${encodeURIComponent(name)}/uninstall`,
    { method: 'POST' }
  );
}

// ============================================================================
// Project Files API
// ============================================================================

/**
 * Get list of all projects.
 */
export async function getProjects(): Promise<ProjectInfo[]> {
  return fetchApi<ProjectInfo[]>('/projects');
}

/**
 * Refresh projects cache and get updated list.
 */
export async function refreshProjects(): Promise<ProjectInfo[]> {
  return fetchApi<ProjectInfo[]>('/projects/refresh', { method: 'POST' });
}

/**
 * Get project details.
 */
export async function getProject(runId: string): Promise<ProjectDetail> {
  return fetchApi<ProjectDetail>(`/projects/${encodeURIComponent(runId)}`);
}

/**
 * List files in a project directory.
 */
export async function getProjectFiles(
  runId: string,
  path: string = ''
): Promise<FileInfo[]> {
  const params = new URLSearchParams();
  if (path) params.set('path', path);
  const query = params.toString();
  return fetchApi<FileInfo[]>(
    `/projects/${encodeURIComponent(runId)}/files${query ? `?${query}` : ''}`
  );
}

/**
 * Get file download URL.
 */
export function getFileDownloadUrl(runId: string, filePath: string): string {
  return `${API_BASE_URL}/api/projects/${encodeURIComponent(runId)}/files/${encodeURIComponent(filePath)}`;
}

/**
 * Open project or file in system file manager.
 */
export async function openProjectInFileManager(
  runId: string,
  path: string = ''
): Promise<FileOperationResponse> {
  const params = new URLSearchParams();
  if (path) params.set('path', path);
  const query = params.toString();
  return fetchApi<FileOperationResponse>(
    `/projects/${encodeURIComponent(runId)}/open${query ? `?${query}` : ''}`,
    { method: 'POST' }
  );
}

/**
 * Open file in frago view.
 */
export async function viewProjectFile(
  runId: string,
  path: string
): Promise<FileOperationResponse> {
  const params = new URLSearchParams({ path });
  return fetchApi<FileOperationResponse>(
    `/projects/${encodeURIComponent(runId)}/view?${params.toString()}`,
    { method: 'POST' }
  );
}

// ============================================================
// Official Resource Sync API
// ============================================================

/**
 * Get official resource sync status and configuration.
 */
export async function getOfficialSyncStatus(): Promise<OfficialSyncStatus> {
  return fetchApi<OfficialSyncStatus>('/settings/official-resource-sync/status');
}

/**
 * Start official resource sync from GitHub.
 */
export async function runOfficialSync(): Promise<OfficialSyncResult> {
  return fetchApi<OfficialSyncResult>('/settings/official-resource-sync/run', {
    method: 'POST',
  });
}

/**
 * Get the result of the current or last official sync operation.
 */
export async function getOfficialSyncResult(): Promise<OfficialSyncResult> {
  return fetchApi<OfficialSyncResult>('/settings/official-resource-sync/result');
}

/**
 * Enable or disable auto-sync on startup.
 */
export async function setOfficialSyncEnabled(enabled: boolean): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/official-resource-sync/enable', {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  });
}

// ============================================================
// Self-Update API
// ============================================================

/**
 * Start self-update process.
 * Initiates `uv tool upgrade frago-cli` and restarts the server.
 */
export async function startSelfUpdate(): Promise<UpdateStatus> {
  return fetchApi<UpdateStatus>('/settings/self-update', { method: 'POST' });
}

/**
 * Get current self-update status.
 */
export async function getSelfUpdateStatus(): Promise<UpdateStatus> {
  return fetchApi<UpdateStatus>('/settings/self-update/status');
}

// ============================================================
// GitHub Star API
// ============================================================

/**
 * Check if user has starred the frago repository.
 */
export async function checkGitHubStarred(): Promise<StarredStatus> {
  return fetchApi<StarredStatus>('/github/starred');
}

/**
 * Star or unstar the frago repository.
 */
export async function toggleGitHubStar(star: boolean): Promise<StarResult> {
  return fetchApi<StarResult>('/github/star', {
    method: 'POST',
    body: JSON.stringify({ star }),
  });
}

// ============================================================
// API Profile Management
// ============================================================

export async function getProfiles(): Promise<ProfileListResponse> {
  return fetchApi<ProfileListResponse>('/settings/profiles');
}

export async function createProfile(data: CreateProfileRequest): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/profiles', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateProfile(id: string, data: UpdateProfileRequest): Promise<ApiResponse> {
  return fetchApi<ApiResponse>(`/settings/profiles/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteProfile(id: string): Promise<ApiResponse> {
  return fetchApi<ApiResponse>(`/settings/profiles/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export async function activateProfile(id: string): Promise<ApiResponse> {
  return fetchApi<ApiResponse>(`/settings/profiles/${encodeURIComponent(id)}/activate`, {
    method: 'POST',
  });
}

export async function deactivateProfile(): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/profiles/deactivate', {
    method: 'POST',
  });
}

export async function saveCurrentAsProfile(name: string): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/profiles/from-current', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

// ============================================================
// Guide API
// ============================================================

/**
 * Get guide metadata including categories and chapters.
 */
export async function getGuideMeta(lang: string = 'en'): Promise<GuideMeta> {
  const params = new URLSearchParams({ lang });
  return fetchApi<GuideMeta>(`/guide/meta?${params.toString()}`);
}

/**
 * Get chapter content by language and chapter ID.
 */
export async function getGuideContent(lang: string, chapterId: string): Promise<GuideContent> {
  const params = new URLSearchParams({ lang, chapter: chapterId });
  return fetchApi<GuideContent>(`/guide/content?${params.toString()}`);
}

/**
 * Search guide content.
 */
export async function searchGuide(query: string, lang: string = 'en'): Promise<GuideSearchResponse> {
  const params = new URLSearchParams({ q: query, lang });
  return fetchApi<GuideSearchResponse>(`/guide/search?${params.toString()}`);
}

// ============================================================
// Task Ingestion API (spec 20260422-channel-config-ui)
// ============================================================

export async function getTaskIngestion(): Promise<TaskIngestionGetResponse> {
  return fetchApi<TaskIngestionGetResponse>('/settings/task-ingestion');
}

export async function putTaskIngestion(
  payload: { enabled: boolean; channels: TaskIngestionChannel[] }
): Promise<TaskIngestionPutResponse> {
  return fetchApi<TaskIngestionPutResponse>('/settings/task-ingestion', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function restartServer(): Promise<{ status: string; message: string }> {
  return fetchApi<{ status: string; message: string }>('/server/restart', {
    method: 'POST',
  });
}

// ============================================================
// Claude Code Sessions API
// ============================================================

export async function getClaudeSessions(options?: {
  days?: number;
  since?: string;
  until?: string;
}): Promise<ClaudeSessionsResponse> {
  const params = new URLSearchParams();
  if (options?.days != null) params.set('days', String(options.days));
  if (options?.since) params.set('since', options.since);
  if (options?.until) params.set('until', options.until);
  const query = params.toString();
  return fetchApi<ClaudeSessionsResponse>(`/claude-sessions${query ? `?${query}` : ''}`);
}

export async function getClaudeSessionDetail(
  sid: string,
  limit: number = 200
): Promise<ClaudeSessionDetail> {
  const params = new URLSearchParams({ limit: String(limit) });
  return fetchApi<ClaudeSessionDetail>(
    `/claude-sessions/${encodeURIComponent(sid)}?${params.toString()}`
  );
}

export async function sendClaudeSessionMessage(
  sid: string,
  text: string,
  images: string[] = []
): Promise<ClaudeSessionSendResponse> {
  return fetchApi<ClaudeSessionSendResponse>(
    `/claude-sessions/${encodeURIComponent(sid)}/send`,
    {
      method: 'POST',
      body: JSON.stringify({ text, images }),
    }
  );
}

export async function getPaSessions(): Promise<PaSessionsResponse> {
  return fetchApi<PaSessionsResponse>('/pa/sessions');
}

export async function sendPaSessionMessage(
  convKey: string,
  text: string,
  images: string[] = []
): Promise<PaSessionSendResponse> {
  return fetchApi<PaSessionSendResponse>('/pa/sessions/send', {
    method: 'POST',
    body: JSON.stringify({ conv_key: convKey, text, images }),
  });
}

export async function getTokenCalendar(month: string): Promise<TokenCalendarResponse> {
  return fetchApi<TokenCalendarResponse>(
    `/claude-sessions/token-calendar?month=${encodeURIComponent(month)}`
  );
}
