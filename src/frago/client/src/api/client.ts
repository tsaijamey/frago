/**
 * HTTP API Client for Frago Web Service
 *
 * Provides fetch-based API calls to the FastAPI backend.
 * This replaces pywebview.api when running in web service mode.
 */

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
// Type Definitions (matching server models)
// ============================================================

export interface ServerInfo {
  name: string;
  version: string;
  status: string;
  uptime_seconds: number;
  api_version: string;
  features: string[];
}

export interface ServerStatus {
  cpu_percent: number;
  memory_percent: number;
  chrome_available: boolean;
  chrome_connected: boolean;
  projects_count: number;
  tasks_running: number;
}

export interface RecipeItem {
  name: string;
  description: string | null;
  category: string;
  icon: string | null;
  tags: string[];
  path: string | null;
  source: string | null;
  runtime: string | null;
}

export interface TaskItem {
  id: string;
  title: string;
  status: string;
  project_path: string | null;
  agent_type: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  step_count: number;
  tool_call_count: number;
  source: string;  // terminal, web, or unknown
}

export interface TaskStep {
  timestamp: string;
  type: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'system';
  content: string;
  tool_name: string | null;
  tool_call_id: string | null;
  tool_result: string | null;
}

export interface ToolUsageStat {
  name: string;
  count: number;
}

export interface TaskSummary {
  total_duration_ms: number;
  user_message_count: number;
  assistant_message_count: number;
  tool_call_count: number;
  tool_success_count: number;
  tool_error_count: number;
  most_used_tools: ToolUsageStat[];
}

export interface TaskDetail {
  id: string;
  title: string;
  status: string;
  project_path: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  step_count: number;
  tool_call_count: number;
  steps: TaskStep[];
  steps_total: number;
  steps_offset: number;
  has_more_steps: boolean;
  summary: TaskSummary | null;
}

export interface TaskListResponse {
  tasks: TaskItem[];
  total: number;
}

export interface TaskStepsResponse {
  steps: TaskStep[];
  total: number;
  has_more: boolean;
}

export interface UserConfig {
  theme: string;
  language: string;
  show_system_status: boolean;
  confirm_on_exit: boolean;
  auto_scroll_output: boolean;
  max_history_items: number;
  shortcuts: Record<string, string>;
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

export interface SystemDirectories {
  home: string;
  cwd: string | null;
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

export interface GenerateTitleResponse {
  status: 'ok' | 'error';
  title?: string;
  error?: string;
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

export interface AgentAttachedStartResponse {
  session_id: string | null;  // Real Claude session ID, comes later via WebSocket
  internal_id: string;  // Internal ID for API calls
  status: string;
  project_path: string;
}

export interface AgentAttachedInfo {
  internal_id: string;
  session_id: string | null;
  project_path: string;
  attached: boolean;
  running: boolean;
}

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

export interface SkillItem {
  name: string;
  description: string | null;
  file_path: string | null;
}

export async function getSkills(): Promise<SkillItem[]> {
  return fetchApi<SkillItem[]>('/skills');
}

// ============================================================
// Settings API
// ============================================================

export interface GhCliStatus {
  installed: boolean;
  authenticated: boolean;
  version?: string | null;
  username?: string | null;
}

export interface APIEndpointConfig {
  type: string;
  url?: string | null;
  api_key: string;
  default_model?: string | null;
  sonnet_model?: string | null;
  haiku_model?: string | null;
}

export interface MainConfig {
  working_directory: string;
  auth_method: string;
  api_endpoint?: APIEndpointConfig | null;
  resources_installed: boolean;
  resources_version?: string | null;
  init_completed: boolean;
}

export interface ApiResponse {
  status: 'ok' | 'error';
  message?: string;
  error?: string;
}

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

export interface APIEndpointRequest {
  type: string;
  api_key: string;
  url?: string;
  default_model?: string;
  sonnet_model?: string;
  haiku_model?: string;
}

export interface AuthUpdateRequest {
  auth_method: 'official' | 'custom';
  api_endpoint?: APIEndpointRequest;
}

export async function updateAuth(request: AuthUpdateRequest): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/update-auth', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export interface RecipeSecretsFieldHttp {
  key: string;
  type: string;
  required: boolean;
  description: string;
  has_value: boolean;
  default?: unknown;
}

export interface RecipeSecretsResponseHttp {
  recipe_name: string;
  fields: RecipeSecretsFieldHttp[];
  is_ref: boolean;
  ref_target: string | null;
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

export interface VSCodeStatus {
  available: boolean;  // True only if VSCode installed AND settings.json exists
}

export async function checkVSCode(): Promise<VSCodeStatus> {
  return fetchApi<VSCodeStatus>('/settings/vscode-status');
}

export async function openConfigInVSCode(): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/open-in-vscode', { method: 'POST' });
}

// ============================================================
// Dashboard API
// ============================================================

export interface RunningTaskSummary {
  id: string;
  name: string | null;
  project_path: string;
  started_at: string;
  elapsed_seconds: number;
  current_step: string | null;
  step_count: number;
}

export interface RecentTaskSummary {
  id: string;
  name: string | null;
  status: string;
  duration_ms: number | null;
  ended_at: string | null;
  error_summary: string | null;
}

export interface QuickRecipeItem {
  name: string;
  description: string | null;
  runtime: string | null;
  run_count: number;
  last_used: string | null;
}

export interface DashboardResourceCounts {
  tasks: number;
  recipes: number;
  skills: number;
}

export interface DashboardStatus {
  chrome_connected: boolean;
  tab_count: number;
  error_count: number;
  last_synced_at: string | null;
}

export interface DashboardData {
  running_tasks: RunningTaskSummary[];
  recent_tasks: RecentTaskSummary[];
  quick_recipes: QuickRecipeItem[];
  resource_counts: DashboardResourceCounts;
  system_status: DashboardStatus;
}

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

export interface DependencyStatus {
  name: string;
  installed: boolean;
  version: string | null;
  path: string | null;
  version_sufficient: boolean;
  required_version: string;
  error: string | null;
  install_guide: string;
}

export interface InitStatus {
  init_completed: boolean;
  node: DependencyStatus;
  claude_code: DependencyStatus;
  resources_installed: boolean;
  resources_version: string | null;
  resources_update_available: boolean;
  current_frago_version: string;
  auth_configured: boolean;
  auth_method: string | null;
  resources_info: {
    commands?: { installed: number; available: number; path: string; files: string[] };
    skills?: { installed: number; available: number; path: string };
    recipes?: { installed: number; available: number; path: string };
    frago_version?: string;
  };
}

export interface DependencyCheckResult {
  node: DependencyStatus;
  claude_code: DependencyStatus;
  all_satisfied: boolean;
}

export interface InstallResultSummary {
  installed: number;
  skipped: number;
  errors: string[];
}

export interface ResourceInstallResult {
  status: 'ok' | 'partial' | 'error';
  commands: InstallResultSummary;
  skills: InstallResultSummary;
  recipes: InstallResultSummary;
  total_installed: number;
  total_skipped: number;
  errors: string[];
  frago_version: string | null;
  message: string | null;
}

export interface DependencyInstallResult {
  status: 'ok' | 'error';
  message: string;
  requires_restart: boolean;
  warning: string | null;
  install_guide: string | null;
  error_code: string | null;
  details: string | null;
}

export interface InitCompleteResult {
  status: 'ok' | 'error';
  message: string;
  init_completed: boolean;
}

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

export interface CommunityRecipeItem {
  name: string;
  url: string;
  description: string | null;
  version: string | null;
  type: 'atomic' | 'workflow';
  runtime: string | null;
  tags: string[];
  installed: boolean;
  installed_version: string | null;
  has_update: boolean;
}

export interface CommunityRecipeInstallResponse {
  status: 'ok' | 'error';
  recipe_name?: string;
  message?: string;
  error?: string;
}

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
 * Project info from the API.
 */
export interface ProjectInfo {
  run_id: string;
  theme_description: string;
  created_at: string;
  last_accessed: string;
  status: string;
}

/**
 * Detailed project info.
 */
export interface ProjectDetail extends ProjectInfo {
  file_count: number;
  total_size: number;
  subdirectories: string[];
}

/**
 * File info from the API.
 */
export interface FileInfo {
  name: string;
  path: string;
  is_directory: boolean;
  size: number;
  modified: string;
  mime_type: string | null;
}

/**
 * Response for open/view operations.
 */
export interface FileOperationResponse {
  success: boolean;
  message: string;
  url?: string;
}

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

export interface OfficialSyncStatus {
  enabled: boolean;
  last_sync: string | null;
  last_commit: string | null;
  repo: string;
  branch: string;
}

export interface OfficialSyncResourceResult {
  type: string;
  files_synced: number;
  dirs_synced: number;
  items: string[];
  error?: string;
}

export interface OfficialSyncResult {
  status: 'ok' | 'running' | 'idle' | 'error' | 'partial';
  started_at?: string;
  completed_at?: string;
  commit?: string;
  commands?: OfficialSyncResourceResult;
  skills?: OfficialSyncResourceResult;
  error?: string;
  message?: string;
}

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

export interface UpdateStatus {
  status: 'idle' | 'updating' | 'restarting' | 'completed' | 'error';
  progress: number;
  message: string;
  error: string | null;
}

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

export interface StarredStatus {
  status: 'ok' | 'error';
  is_starred: boolean | null;
  gh_configured: boolean;
  error?: string;
}

export interface StarResult {
  status: 'ok' | 'error';
  is_starred: boolean | null;
  error?: string;
}

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

export interface ProfileItem {
  id: string;
  name: string;
  endpoint_type: string;
  api_key_masked: string;
  url?: string | null;
  default_model?: string | null;
  sonnet_model?: string | null;
  haiku_model?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProfileListResponse {
  profiles: ProfileItem[];
  active_profile_id: string | null;
}

export interface CreateProfileRequest {
  name: string;
  endpoint_type: string;
  api_key: string;
  url?: string;
  default_model?: string;
  sonnet_model?: string;
  haiku_model?: string;
}

export interface UpdateProfileRequest {
  name?: string;
  endpoint_type?: string;
  api_key?: string;
  url?: string;
  default_model?: string;
  sonnet_model?: string;
  haiku_model?: string;
}

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

export interface GuideCategory {
  id: string;
  title: {
    en: string;
    'zh-CN': string;
  };
  description: {
    en: string;
    'zh-CN': string;
  };
  order: number;
  icon: string;
}

export interface GuideChapter {
  id: string;
  category: string;
  order: number;
  files: {
    en: string;
    'zh-CN': string;
  };
  question_count: number;
}

export interface GuideMeta {
  version: string;
  last_updated: string;
  languages: string[];
  categories: GuideCategory[];
  chapters: GuideChapter[];
}

export interface GuideTocItem {
  level: number;
  title: string;
  anchor: string;
}

export interface GuideContent {
  id: string;
  title: string;
  category: string;
  content: string;
  metadata: {
    version: string;
    last_updated: string;
    tags: string[];
    order: number;
  };
  toc: GuideTocItem[];
}

export interface GuideSearchMatch {
  question: string;
  snippet: string;
  anchor: string;
}

export interface GuideSearchResult {
  chapter_id: string;
  chapter_title: string;
  matches: GuideSearchMatch[];
}

export interface GuideSearchResponse {
  query: string;
  total: number;
  results: GuideSearchResult[];
}

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

export interface TaskIngestionChannel {
  name: string;
  poll_recipe: string;
  notify_recipe: string;
  poll_interval_seconds: number;
  poll_timeout_seconds: number;
}

export interface TaskIngestionGetResponse {
  enabled: boolean;
  channels: TaskIngestionChannel[];
  available_recipes: string[];
  restart_supported: boolean;
}

export interface TaskIngestionPutResponse {
  status: string;
  requires_restart: boolean;
  message?: string;
}

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

export type ClaudeSessionHuman = 'human' | 'maybe' | 'agent';

export interface ClaudeSessionItem {
  sid: string;
  human: ClaudeSessionHuman;
  human_reason: string;
  name: string | null;
  title: string | null;
  recap: string | null;
  ai_title: string | null;
  last_prompt: string | null;
  first_user_preview: string;
  first_user_full: string;
  last_assistant_preview: string;
  first_interaction_at: string | null;
  first_interaction_ts: number | null;
  last_interaction_at: string | null;
  last_interaction_ts: number | null;
  cwd: string | null;
  branch: string | null;
  project: string;
  n_user_messages: number;
  n_assistant_messages: number;
  resume_command: string;
}

export interface ClaudeSessionsResponse {
  scanned_at: string;
  range: {
    since: string | null;
    until: string | null;
    since_ts: number;
    until_ts: number;
  };
  projects_root: string;
  scanned_files: number;
  matched_sessions: number;
  sessions: ClaudeSessionItem[];
}

export interface ClaudeSessionMessage {
  role: 'user' | 'assistant';
  text: string;
  timestamp: string | null;
}

export interface ClaudeSessionDetail {
  sid: string;
  path: string;
  total_messages: number;
  returned_messages: number;
  truncated: boolean;
  messages: ClaudeSessionMessage[];
  resume_command: string;
}

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
