/**
 * PyWebview API TypeScript Type Definitions
 *
 * Defines all methods and return types exposed by window.pywebview.api.
 * Keep in sync with the Python backend fragoGuiApi class.
 */

// ============================================================
// Base Types
// ============================================================

export type TaskStatus = 'running' | 'completed' | 'error' | 'cancelled';

export type StepType =
  | 'user_message'
  | 'assistant_message'
  | 'tool_call'
  | 'tool_result'
  | 'system_event';

export type RecipeCategory = 'atomic' | 'workflow';

export type RecipeSource = 'User' | 'Project' | 'System';

export type RecipeRuntime = 'js' | 'python' | 'shell';

export type Theme = 'dark' | 'light';

export type Language = 'en' | 'zh';

export type ToastType = 'info' | 'success' | 'warning' | 'error';

// ============================================================
// Data Models
// ============================================================

export type SessionSource = 'terminal' | 'web' | 'unknown';

export interface TaskItem {
  session_id: string;
  name: string;
  status: TaskStatus;
  started_at: string;
  ended_at: string | null;
  duration_ms: number;
  step_count: number;
  tool_call_count: number;
  last_activity: string;
  project_path: string;
  source: SessionSource;
}

export interface TaskStep {
  step_id: number;
  type: StepType;
  timestamp: string;
  content: string;
  tool_name: string | null;
  tool_status: string | null;
  tool_call_id?: string;
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
  session_id: string;
  name: string;
  status: TaskStatus;
  started_at: string;
  ended_at: string | null;
  duration_ms: number;
  project_path: string;
  step_count: number;
  tool_call_count: number;
  user_message_count: number;
  assistant_message_count: number;
  steps: TaskStep[];
  steps_total: number;
  steps_offset: number;
  has_more_steps: boolean;
  summary: TaskSummary | null;
  error?: string;
}

export interface TaskStepsResponse {
  steps: TaskStep[];
  total: number;
  offset: number;
  has_more: boolean;
  error?: string;
}

export interface RecipeItem {
  name: string;
  description: string | null;
  category: RecipeCategory;
  icon: string | null;
  tags: string[];
  path: string | null;
  source: RecipeSource | null;
  runtime: RecipeRuntime | null;
}

export interface RecipeInput {
  type: string;
  required: boolean;
  default?: string | number | boolean;
  description?: string;
}

export interface RecipeOutput {
  type: string;
  description?: string;
}

export interface RecipeDetail extends RecipeItem {
  metadata_content: string | null;
  recipe_dir: string | null;
  // Rich metadata fields
  version?: string;
  base_dir?: string;
  script_path?: string;
  metadata_path?: string;
  use_cases?: string[];
  output_targets?: string[];
  inputs?: Record<string, RecipeInput>;
  outputs?: Record<string, RecipeOutput>;
  dependencies?: string[];
  env?: Record<string, unknown>;
  source_code?: string;
}

// ============================================================
// Community Recipe Types
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

export interface SkillItem {
  name: string;
  description: string | null;
  icon: string | null;
  file_path: string;
}

export interface UserConfig {
  theme: Theme;
  language: Language;
  show_system_status: boolean;
  confirm_on_exit: boolean;
  auto_scroll_output: boolean;
  max_history_items: number;
  ai_title_enabled: boolean;
  shortcuts: Record<string, string>;
}

export interface SystemStatus {
  cpu_percent: number;
  memory_percent: number;
  chrome_connected: boolean;
}

export interface ConnectionStatus {
  connected: boolean;
  message: string;
}

// ============================================================
// Settings Page Related Types (Main Config, Environment Variables, GitHub)
// ============================================================

export interface APIEndpoint {
  type: 'deepseek' | 'aliyun' | 'kimi' | 'minimax' | 'custom';
  url?: string;
  api_key: string;
  default_model?: string;  // Maps to ANTHROPIC_MODEL
  sonnet_model?: string;   // Maps to ANTHROPIC_DEFAULT_SONNET_MODEL
  haiku_model?: string;    // Maps to ANTHROPIC_DEFAULT_HAIKU_MODEL
}

export interface MainConfig {
  schema_version: string;
  // Dependency information
  node_version?: string;
  node_path?: string;
  npm_version?: string;
  claude_code_version?: string;
  claude_code_path?: string;
  // Authentication configuration
  auth_method: 'official' | 'custom';
  api_endpoint?: APIEndpoint;
  // Optional features
  ccr_enabled: boolean;
  ccr_config_path?: string;
  sync_repo_url?: string;
  // Working directory (read-only, calculated by backend)
  working_directory_display?: string;
  // Resource status
  resources_installed: boolean;
  resources_version?: string;
  last_resource_update?: string;
  // Metadata
  created_at: string;
  updated_at: string;
  init_completed: boolean;
}

export interface EnvVarsResponse {
  vars: Record<string, string>;
  file_exists: boolean;
}

export interface RecipeEnvRequirement {
  recipe_name: string;
  var_name: string;
  required: boolean;
  description: string;
  configured: boolean;
}

export interface GhCliStatus {
  installed: boolean;
  version?: string;
  authenticated: boolean;
  username?: string;
}

export interface MainConfigUpdateResponse {
  status: 'ok' | 'error';
  config?: MainConfig;
  error?: string;
}

export interface AuthUpdateRequest {
  auth_method: 'official' | 'custom';
  api_endpoint?: APIEndpoint;
}

export interface EnvVarsUpdateResponse {
  status: 'ok' | 'error';
  vars?: Record<string, string>;
  error?: string;
}

export interface CreateRepoResponse {
  status: 'ok' | 'error';
  repo_url?: string;
  error?: string;
}

export interface SyncResponse {
  status: 'ok' | 'error' | 'running' | 'idle';
  message?: string;
  output?: string;
  error?: string;
  success?: boolean;
  local_changes?: number;
  remote_updates?: number;
  pushed_to_remote?: boolean;
  conflicts?: string[];
  warnings?: string[];
  is_public_repo?: boolean;
}

export interface RepoVisibilityResponse {
  status: 'ok' | 'error';
  visibility?: 'public' | 'private';
  is_public?: boolean;
  error?: string;
}

export interface GithubRepo {
  name: string;
  full_name: string;
  private: boolean;
  ssh_url: string;
  description: string | null;
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

// ============================================================
// API Response Types
// ============================================================

export interface ApiResponse<T = void> {
  status: 'ok' | 'error';
  error?: string;
  message?: string;
  data?: T;
}

export interface RecipeRunResponse {
  status: 'ok' | 'error';
  output: string | null;
  error: string | null;
}

export interface ConfigUpdateResponse {
  status: 'ok' | 'error';
  config?: UserConfig;
  error?: string;
}

export interface TaskStartResponse {
  status: 'ok' | 'error';
  task_id?: string;
  message?: string;
  error?: string;
}

export interface RecipeDeleteResponse {
  status: 'ok' | 'error';
  message?: string;
}

export interface TutorialResponse {
  status: 'ok' | 'error';
  tutorial_id?: string;
  lang?: string;
  error?: string;
}

// ============================================================
// PyWebview API Interface
// ============================================================

export interface PyWebviewApi {
  // ============================================================
  // Tasks API (011-gui-tasks-redesign)
  // ============================================================

  /**
   * Get task list
   * @param limit Maximum number to return (1-100, default 50)
   * @param status Filter by status (optional)
   */
  get_tasks(limit?: number, status?: TaskStatus): Promise<TaskItem[]>;

  /**
   * Get task details
   * @param session_id Session ID
   * @param steps_limit Step count limit (1-100, default 50)
   * @param steps_offset Step offset (default 0)
   */
  get_task_detail(
    session_id: string,
    steps_limit?: number,
    steps_offset?: number
  ): Promise<TaskDetail>;

  /**
   * Get task steps with pagination
   * @param session_id Session ID
   * @param offset Offset
   * @param limit Count limit (1-100, default 50)
   */
  get_task_steps(
    session_id: string,
    offset?: number,
    limit?: number
  ): Promise<TaskStepsResponse>;

  /**
   * Start agent task
   * @param prompt Task description
   */
  start_agent_task(prompt: string): Promise<TaskStartResponse>;

  /**
   * Continue conversation in specified session
   * @param session_id Session ID
   * @param prompt New prompt
   */
  continue_agent_task(session_id: string, prompt: string): Promise<TaskStartResponse>;

  // ============================================================
  // Recipes API
  // ============================================================

  /**
   * Get recipe list
   */
  get_recipes(): Promise<RecipeItem[]>;

  /**
   * Refresh recipe list
   */
  refresh_recipes(): Promise<RecipeItem[]>;

  /**
   * Get recipe details
   * @param name Recipe name
   */
  get_recipe_detail(name: string): Promise<RecipeDetail>;

  /**
   * Execute recipe
   * @param name Recipe name
   * @param params Parameters (optional)
   */
  run_recipe(
    name: string,
    params?: Record<string, unknown>
  ): Promise<RecipeRunResponse>;

  /**
   * Delete recipe (user-level only)
   * @param name Recipe name
   */
  delete_recipe(name: string): Promise<RecipeDeleteResponse>;

  // ============================================================
  // Skills API
  // ============================================================

  /**
   * Get skill list
   */
  get_skills(): Promise<SkillItem[]>;

  /**
   * Refresh skill list
   */
  refresh_skills(): Promise<SkillItem[]>;

  // ============================================================
  // Config API
  // ============================================================

  /**
   * Get user configuration (GUI config)
   */
  get_config(): Promise<UserConfig>;

  /**
   * Update user configuration (GUI config)
   * @param config Config update
   */
  update_config(config: Partial<UserConfig>): Promise<ConfigUpdateResponse>;

  // ============================================================
  // Settings API - Main Config Management
  // ============================================================

  /**
   * Get main config (~/.frago/config.json)
   */
  get_main_config(): Promise<MainConfig>;

  /**
   * Update main config
   * @param updates Partial update dictionary
   */
  update_main_config(updates: Partial<MainConfig>): Promise<MainConfigUpdateResponse>;

  /**
   * Update authentication method and API endpoint
   * @param auth_data Authentication config
   */
  update_auth_method(auth_data: AuthUpdateRequest): Promise<MainConfigUpdateResponse>;

  /**
   * Open working directory in file manager
   */
  open_working_directory(): Promise<ApiResponse>;

  // ============================================================
  // Settings API - Environment Variables Management
  // ============================================================

  /**
   * Get user-level environment variables (~/.frago/.env)
   */
  get_env_vars(): Promise<EnvVarsResponse>;

  /**
   * Batch update environment variables
   * @param updates Update dictionary, value=null means delete
   */
  update_env_vars(
    updates: Record<string, string | null>
  ): Promise<EnvVarsUpdateResponse>;

  /**
   * Scan all Recipe environment variable requirements
   */
  get_recipe_env_requirements(): Promise<RecipeEnvRequirement[]>;

  // ============================================================
  // Settings API - GitHub Integration
  // ============================================================

  /**
   * Check gh CLI installation and login status
   */
  check_gh_cli(): Promise<GhCliStatus>;

  /**
   * Execute gh auth login in external terminal
   */
  gh_auth_login(): Promise<ApiResponse>;

  /**
   * Create GitHub repo and configure in config.json
   * @param repo_name Repository name
   * @param private_repo Whether it's a private repo
   */
  create_sync_repo(repo_name: string, private_repo?: boolean): Promise<CreateRepoResponse>;

  /**
   * Execute frago sync (background thread)
   */
  run_first_sync(): Promise<SyncResponse>;

  /**
   * Get sync result (polling)
   */
  get_sync_result(): Promise<SyncResponse>;

  /**
   * Check sync repository visibility
   */
  check_sync_repo_visibility(): Promise<RepoVisibilityResponse>;

  /**
   * List user's GitHub repositories
   * @param limit Maximum number to return (default 100)
   */
  list_user_repos(limit?: number): Promise<ListReposResponse>;

  /**
   * Select existing repo as sync repo
   * @param repo_url Repository URL (SSH or HTTPS format, will be converted to HTTPS)
   */
  select_existing_repo(repo_url: string): Promise<SelectRepoResponse>;

  // ============================================================
  // System API
  // ============================================================

  /**
   * Get system status
   */
  get_system_status(): Promise<SystemStatus>;

  /**
   * Check Chrome connection status
   */
  check_connection(): Promise<ConnectionStatus>;

  /**
   * Open file or directory
   * @param path File or directory path
   * @param reveal Whether to reveal in Finder instead of opening
   */
  open_path(path: string, reveal?: boolean): Promise<ApiResponse>;

  // ============================================================
  // Legacy API (preserved for compatibility)
  // ============================================================

  /**
   * Get command history
   * @param limit Maximum number to return
   * @param offset Offset
   */
  get_history(limit?: number, offset?: number): Promise<unknown[]>;

  /**
   * Clear history
   */
  clear_history(): Promise<{ status: string; cleared_count: number }>;

  /**
   * Get task status (legacy)
   */
  get_task_status(): Promise<{
    status: string;
    task_id: string | null;
    progress: number;
    error: string | null;
  }>;

  /**
   * Run agent (legacy)
   */
  run_agent(prompt: string): Promise<string>;

  /**
   * Cancel agent task (legacy)
   */
  cancel_agent(): Promise<{ status: string; message: string }>;

  // ============================================================
  // Tutorial API
  // ============================================================

  /**
   * Open tutorial demo window
   * @param tutorial_id Tutorial ID, such as "intro", "guide", "best-practices", "videos"
   * @param lang Language, "auto" for auto-detect, "zh" for Chinese, "en" for English
   * @param anchor Anchor ID, used to jump to specific position on page, such as "concepts"
   */
  open_tutorial(tutorial_id: string, lang?: string, anchor?: string): Promise<TutorialResponse>;
}

// ============================================================
// Global Type Declarations
// ============================================================

declare global {
  interface Window {
    pywebview?: {
      api: PyWebviewApi;
      state?: unknown;
    };
  }
}

export {};
