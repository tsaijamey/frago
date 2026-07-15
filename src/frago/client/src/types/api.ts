/**
 * HTTP API type definitions (matching server models).
 *
 * Extracted from `api/client.ts` so the client module holds only HTTP logic.
 * `api/client.ts` re-exports these to preserve the existing import contract
 * (`import type { ... } from '@/api/client'` and the unified `api` barrel).
 */

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

export interface SystemDirectories {
  home: string;
  cwd: string | null;
}

export interface GenerateTitleResponse {
  status: 'ok' | 'error';
  title?: string;
  error?: string;
}

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

export interface SkillItem {
  name: string;
  description: string | null;
  file_path: string | null;
}

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

export interface VSCodeStatus {
  available: boolean;  // True only if VSCode installed AND settings.json exists
}

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

export interface UpdateStatus {
  status: 'idle' | 'updating' | 'restarting' | 'completed' | 'error';
  progress: number;
  message: string;
  error: string | null;
}

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

export interface ClaudeSessionBlock {
  type: 'text' | 'thinking' | 'tool_use' | 'tool_result' | 'image';
  text?: string;
  // tool_use
  name?: string;
  tool_input?: unknown;
  tool_id?: string | null;
  // tool_result
  content?: string;
  is_error?: boolean;
}

export interface ClaudeSessionMessage {
  role: 'user' | 'assistant';
  text: string;
  blocks?: ClaudeSessionBlock[];
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
  // Phase 1: transcript_completion probe — whether the latest turn finished
  // (collapse the progress bar) or is still streaming / tool-using.
  done?: boolean;
  stop_reason?: string | null;
  // Marker (terminal record uuid). The composer records it before sending and
  // polls until done with a *changed* marker, so a stale prior-turn done can't
  // collapse the progress bar before the new reply lands.
  last_uuid?: string | null;
}

export interface ClaudeSessionSendResponse {
  sid: string;
  // "ready" → warm session hit, forwarded immediately;
  // "activating" → cold start, tmux claude is being resumed/rebuilt.
  status: 'ready' | 'activating' | string;
  text: string;
}

// PA (Primary Agent) resident sessions — the conversations PA itself is
// holding open (one per conv_key, e.g. a Feishu chat), distinct from the
// general ~/.claude/projects scan above. `sid` is the same uuid5-derived
// claude session id the resident tmux session and transcript watcher use,
// so it lines up with /api/claude-sessions/{sid} and `claude --resume`.
export interface PaSessionItem {
  conv_key: string;
  channel: string;
  group_name: string;
  sid: string;
  resume_command: string;
}

export interface PaSessionsResponse {
  sessions: PaSessionItem[];
}

export interface PaSessionSendResponse {
  sid: string;
  status: 'ready' | 'activating' | string;
  msg_id: string;
}

export interface TokenDayBucket {
  input: number;
  output: number;
  cache_creation: number;
  cache_read: number;
  total: number;
}

export interface TokenCalendarResponse {
  month: string;
  days: Record<string, TokenDayBucket>;
  month_total: TokenDayBucket;
  computed_at: string;
}
