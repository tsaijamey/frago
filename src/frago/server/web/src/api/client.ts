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
  type: string;
  content: string;
  tool_name: string | null;
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
  show_system_status: boolean;
  confirm_on_exit: boolean;
  auto_scroll_output: boolean;
  max_history_items: number;
  ai_title_enabled: boolean;
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
  timeout?: number
): Promise<TaskItem> {
  return fetchApi<TaskItem>(`/recipes/${encodeURIComponent(name)}/run`, {
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
  generateTitles?: boolean;
}): Promise<TaskListResponse> {
  const params = new URLSearchParams();
  if (options?.status) params.set('status', options.status);
  if (options?.limit) params.set('limit', String(options.limit));
  if (options?.offset) params.set('offset', String(options.offset));
  if (options?.generateTitles) params.set('generate_titles', 'true');

  const query = params.toString();
  return fetchApi<TaskListResponse>(`/tasks${query ? `?${query}` : ''}`);
}

export async function getTask(taskId: string): Promise<TaskDetail> {
  return fetchApi<TaskDetail>(`/tasks/${encodeURIComponent(taskId)}`);
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

export interface AgentContinueResponse {
  status: 'ok' | 'error';
  message?: string;
  error?: string;
}

/**
 * Continue conversation in an existing Claude session.
 *
 * @param sessionId - The Claude session_id (from task list), NOT the web task_id
 * @param prompt - The continuation prompt
 */
export async function continueAgent(
  sessionId: string,
  prompt: string
): Promise<AgentContinueResponse> {
  return fetchApi<AgentContinueResponse>(
    `/agent/${encodeURIComponent(sessionId)}/continue`,
    {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }
  );
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
  sync_repo?: string | null;
  resources_installed: boolean;
  resources_version?: string | null;
  init_completed: boolean;
}

export interface EnvVarsResponse {
  vars: Record<string, string>;
  file_exists: boolean;
}

export interface RecipeEnvRequirement {
  name: string;
  description?: string | null;
  required: boolean;
  configured: boolean;
  recipe_name?: string | null;
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

export async function getEnvVars(): Promise<EnvVarsResponse> {
  return fetchApi<EnvVarsResponse>('/settings/env-vars');
}

export async function updateEnvVars(updates: Record<string, string | null>): Promise<EnvVarsResponse> {
  return fetchApi<EnvVarsResponse>('/settings/env-vars', {
    method: 'PUT',
    body: JSON.stringify({ updates }),
  });
}

export async function getRecipeEnvRequirements(): Promise<RecipeEnvRequirement[]> {
  return fetchApi<RecipeEnvRequirement[]>('/settings/recipe-env-requirements');
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

export interface HourlyActivity {
  hour: string;
  session_count: number;
  tool_call_count: number;
  completed_count: number;
}

export interface ActivityStats {
  total_sessions: number;
  completed_sessions: number;
  running_sessions: number;
  error_sessions: number;
  total_tool_calls: number;
  total_steps: number;
}

export interface ActivityOverview {
  hourly_distribution: HourlyActivity[];
  stats: ActivityStats;
}

export interface DashboardData {
  server: {
    running: boolean;
    uptime_seconds: number;
    started_at: string | null;
  };
  activity_overview: ActivityOverview;
  resource_counts: {
    tasks: number;
    recipes: number;
    skills: number;
  };
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
// Multi-Device Sync API
// ============================================================

export interface GithubRepo {
  name: string;
  full_name: string;
  description: string | null;
  private: boolean;
  ssh_url: string;
  url: string;
}

export interface CreateRepoResponse {
  status: 'ok' | 'error';
  repo_url?: string;
  error?: string;
}

export interface ListReposResponse {
  status: 'ok' | 'error';
  repos?: GithubRepo[];
  error?: string;
}

export interface SelectRepoResponse {
  status: 'ok' | 'error';
  repo_url?: string;
  error?: string;
}

export interface RepoVisibilityResponse {
  status: 'ok' | 'error';
  is_public?: boolean;
  error?: string;
}

export interface SyncResponse {
  status: 'ok' | 'error' | 'running' | 'idle';
  success?: boolean;
  output?: string;
  error?: string;
  message?: string;
  local_changes?: number;
  remote_updates?: number;
  pushed_to_remote?: boolean;
  conflicts?: string[];
  warnings?: string[];
  is_public_repo?: boolean;
}

export async function createSyncRepo(repoName: string, privateRepo: boolean = true): Promise<CreateRepoResponse> {
  return fetchApi<CreateRepoResponse>('/sync/create-repo', {
    method: 'POST',
    body: JSON.stringify({ repo_name: repoName, private: privateRepo }),
  });
}

export async function listUserRepos(limit: number = 100): Promise<ListReposResponse> {
  return fetchApi<ListReposResponse>(`/sync/repos?limit=${limit}`);
}

export async function selectExistingRepo(repoUrl: string): Promise<SelectRepoResponse> {
  return fetchApi<SelectRepoResponse>('/sync/select-repo', {
    method: 'POST',
    body: JSON.stringify({ repo_url: repoUrl }),
  });
}

export async function checkSyncRepoVisibility(): Promise<RepoVisibilityResponse> {
  return fetchApi<RepoVisibilityResponse>('/sync/repo-visibility');
}

export async function runSync(): Promise<SyncResponse> {
  return fetchApi<SyncResponse>('/sync/run', { method: 'POST' });
}

export async function getSyncStatus(): Promise<SyncResponse> {
  return fetchApi<SyncResponse>('/sync/status');
}

// ============================================================
// Console API
// ============================================================

export interface ConsoleMessage {
  type: string;
  content: string;
  timestamp: string;
  tool_name?: string;
  tool_call_id?: string;
  metadata?: Record<string, any>;
}

export interface ConsoleStartResponse {
  session_id: string;
  status: string;
  project_path: string;
  auto_approve: boolean;
}

export interface ConsoleHistoryResponse {
  messages: ConsoleMessage[];
  total: number;
  has_more: boolean;
}

export async function startConsoleSession(
  prompt: string,
  projectPath?: string,
  autoApprove: boolean = true
): Promise<ConsoleStartResponse> {
  return fetchApi<ConsoleStartResponse>('/console/start', {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      project_path: projectPath,
      auto_approve: autoApprove
    })
  });
}

export async function sendConsoleMessage(sessionId: string, message: string): Promise<{ status: string }> {
  return fetchApi<{ status: string }>(`/console/${sessionId}/message`, {
    method: 'POST',
    body: JSON.stringify({ message })
  });
}

export async function stopConsoleSession(sessionId: string): Promise<{ status: string }> {
  return fetchApi<{ status: string }>(`/console/${sessionId}/stop`, {
    method: 'POST'
  });
}

export async function getConsoleHistory(
  sessionId: string,
  limit: number = 100,
  offset: number = 0
): Promise<ConsoleHistoryResponse> {
  return fetchApi<ConsoleHistoryResponse>(
    `/console/${sessionId}/history?limit=${limit}&offset=${offset}`
  );
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
    commands?: { installed: number; path: string; files: string[] };
    recipes?: { installed: number; path: string };
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
