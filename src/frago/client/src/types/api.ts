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
  browser_available: boolean;
  browser_connected: boolean;
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

export interface GhRateLimit {
  limit: number;
  remaining: number;
  used: number;
  reset_in_seconds: number;
  authenticated: boolean;
}

export interface GhCliStatus {
  installed: boolean;
  /** A usable credential exists. Stays true offline — see `verified`. */
  authenticated: boolean;
  version?: string | null;
  username?: string | null;
  /** GitHub confirmed the credential just now. False + authenticated = could not reach GitHub. */
  verified?: boolean;
  verify_error?: string | null;
  /** Present only while nobody is logged in — the 60-per-hour anonymous budget. */
  rate_limit?: GhRateLimit | null;
}

/** How this machine would install gh, decided before anything runs. */
export interface GhInstallPlan {
  /** "brew" | "winget" | "binary" — the last means frago downloads the release itself. */
  method: string;
  /** The equivalent command, for users who would rather run it themselves. Empty for "binary". */
  command: string;
  /** True when the result lands outside the shell PATH and the user needs a hint to fix that. */
  needs_path_hint: boolean;
  manual_url: string;
}

export interface GhInstallStartResult {
  status: string;
  already_running: boolean;
  method?: string | null;
}

export interface GhInstallStatus {
  status: 'idle' | 'running' | 'success' | 'error';
  method?: string | null;
  message: string;
  error?: string | null;
  log: string[];
  /** Shell line that puts frago's own gh install on the user's PATH. */
  path_hint?: string | null;
}

/** The one-time code GitHub wants typed into github.com/login/device. */
export interface GhDeviceLogin {
  status: string;
  code?: string | null;
  url?: string | null;
  error?: string | null;
}

export interface GhDeviceLoginStatus {
  status: string;
  completed: boolean;
  authenticated: boolean;
  username?: string | null;
  error?: string | null;
}

// ---- 数据仓库 (~/.frago backed up to the user's own private repo) ----

export interface PendingFile {
  path: string;
  status: 'modified' | 'added' | 'deleted' | 'renamed' | 'copied' | 'conflicted' | 'untracked';
}

/** Pending count for one top-level area. What makes five figures of files legible. */
export interface AreaCount {
  area: string;
  count: number;
}

export interface LastCommit {
  sha: string;
  subject: string;
  committed_at: string;
}

export interface DataRepoStatus {
  /** False when ~/.frago is not a git repository yet — a setup state, not an error. */
  configured: boolean;
  repo_path: string;
  remote_url?: string | null;
  branch?: string | null;
  /** Commits made locally but never pushed, and the reverse. */
  ahead: number;
  behind: number;
  pending_total: number;
  counts: Record<string, number>;
  rollup: AreaCount[];
  /** A capped sample of paths — see `truncated`. */
  files: PendingFile[];
  truncated: boolean;
  last_commit?: LastCommit | null;
  error?: string | null;
}

export interface ExcludedCategory {
  key: string;
  title: string;
  examples: string[];
  why: string;
}

export interface IncludedArea {
  path: string;
  note: string;
}

export interface DataRepoPolicy {
  excluded: ExcludedCategory[];
  included: IncludedArea[];
}

export interface SyncTask {
  task_id?: string | null;
  session_id?: string | null;
  pid?: number | null;
  mode?: string | null;
  instruction?: string | null;
  started_at?: string | null;
}

export interface SyncStartResult {
  status: string;
  already_running: boolean;
  task?: SyncTask | null;
  error?: string | null;
}

export interface SyncRunStatus {
  running: boolean;
  task?: SyncTask | null;
}

export interface SyncPrompt {
  prompt: string;
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

/** Global cli-agent core preference (spec 20260725-opencode-core-support). */
export interface AgentCoreSettings {
  agent_core: string;
  /** Which cores are installed on this machine — the backend decides, never the UI. */
  available: Record<string, boolean>;
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
  browser_connected: boolean;
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
  /** Absent means nothing frago does is blocked by this being missing. Node.js
   *  is the case: the agent CLIs ship as native binaries now, so npm — and
   *  therefore Node — is one install route among several, not a prerequisite. */
  optional?: boolean;
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

/**
 * A built-in endpoint, served by the backend so this file never has to
 * transcribe the provider table again. Earlier copies drifted: the Tencent
 * endpoints were missing from every picker, and the model names shown next to
 * each provider had gone stale.
 */
export interface EndpointPreset {
  id: string;
  display_name: string;
  base_url: string;
  default_model: string;
  sonnet_model: string;
  haiku_model: string;
}

export interface EndpointPresetListResponse {
  presets: EndpointPreset[];
}

/**
 * What supplies a connection's credential.
 *
 * - `endpoint` — an Anthropic-protocol endpoint plus a key frago holds.
 * - `official` — the CLI's own subscription login. Built in, never saved,
 *   never deleted; it is what a role falls back to when nothing is bound.
 * - `vendor_cli` — a vendor's own CLI on its own account (CodeBuddy). frago
 *   has no key to hand it, so what the connection carries is which core to
 *   run and which model to ask it for.
 */
// workbuddy: frago-core calling the WorkBuddy gateway on the WorkBuddy client's own
// login. No key is stored; it can serve the light agent and the observer only.
export type ConnectionKind = 'endpoint' | 'official' | 'vendor_cli' | 'workbuddy';

export interface ProfileItem {
  id: string;
  name: string;
  kind: ConnectionKind;
  endpoint_type: string;
  api_key_masked: string;
  url?: string | null;
  /** vendor_cli only: which core this connection runs. */
  agent_type?: string | null;
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
  /** Which agent CLIs the active profile was written into. */
  active_targets: string[];
  /** What the worker role is bound to; null means the plain subscription. */
  worker_profile_id?: string | null;
}

/**
 * The roles that consume a connection. `main` and `worker` run on an agent CLI;
 * `lightagent` (the hook's review passes) and `observer` (the session page's side
 * panel) are served by frago-core, which can only call a connection that carries
 * its own key or borrows the WorkBuddy login.
 */
export type ConnectionRole = 'main' | 'worker' | 'lightagent' | 'observer';

/**
 * A core that runs on its own account rather than on a key frago holds.
 *
 * These are the cores a vendor_cli connection can name. The list is derived
 * from the driver registry — a CLI that takes no frago profile is exactly a
 * CLI whose credential is its own.
 */
export interface VendorCore {
  agent_type: string;
  display_name: string;
  installed: boolean;
  path?: string | null;
  /** Candidates for the model field, not a whitelist. */
  known_models: string[];
  /** Why it takes no frago profile, in the driver's own words. */
  reason?: string | null;
}

/** One role and the connection it is running on right now. */
export interface RoleBinding {
  role: ConnectionRole;
  /** null means nothing bound: the subscription for main and worker, the
   *  fallback for the light agent, not running for the observer. */
  profile_id: string | null;
  /** null only for an unbound observer — it runs on nothing. */
  connection: ProfileItem | null;
  /** main only: the agent CLIs this connection was written into. */
  targets: string[];
}

export interface ConnectionsResponse {
  /** Every bindable connection, subscription first. */
  connections: ProfileItem[];
  bindings: RoleBinding[];
  vendor_cores: VendorCore[];
}

/** One WorkBuddy model as the last probe found it. */
export interface WorkBuddyModel {
  id: string;
  name: string;
  /** On the catalog WorkBuddy hands out. Not being there does not mean unusable. */
  listed: boolean;
  ok: boolean;
  /** Which of the gateway's two doors this model answers at. */
  wire?: 'openai' | 'anthropic' | null;
  first_ms?: number | null;
  /** Thinks before it answers: slower, and it spends the budget doing so. */
  thinks: boolean;
  error?: string | null;
}

/** What a WorkBuddy connection can be pointed at. */
export interface WorkBuddyModelsResponse {
  /** Whether the WorkBuddy client is logged in on this machine. */
  logged_in: boolean;
  probed_at: string | null;
  models: WorkBuddyModel[];
}

/**
 * One agent CLI's standing as a place to activate a profile.
 *
 * Unofferable ones are listed too, disabled and with their reason — a checkbox
 * that is simply absent reads as an oversight rather than a decision.
 */
export interface ActivationTarget {
  agent_type: string;
  display_name: string;
  /** Whether frago can translate a profile into this CLI's config at all. */
  supported: boolean;
  installed: boolean;
  selectable: boolean;
  path?: string | null;
  unsupported_reason?: string | null;
}

export interface ActivationTargetListResponse {
  targets: ActivationTarget[];
  /** Used when the caller names none — Claude Code, as activation always meant. */
  default_targets: string[];
}

export interface CreateProfileRequest {
  name: string;
  kind?: ConnectionKind;
  endpoint_type: string;
  /** Empty for a vendor CLI: its credential is that CLI's own login. */
  api_key?: string;
  url?: string | null;
  agent_type?: string | null;
  default_model?: string | null;
  sonnet_model?: string | null;
  haiku_model?: string | null;
}

/**
 * Only the keys present are touched, and an empty string clears that field —
 * that is how a model override gets removed. `api_key` is the exception: it is
 * never prefilled in the form, so blank there means "keep the saved key".
 */
export interface UpdateProfileRequest {
  name?: string;
  kind?: ConnectionKind;
  endpoint_type?: string;
  api_key?: string;
  url?: string | null;
  agent_type?: string | null;
  default_model?: string | null;
  sonnet_model?: string | null;
  haiku_model?: string | null;
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

/** 一档订阅额度。`resets_at` 是 Claude Code 的原话，带着人自己的时区名。 */
export interface ClaudeUsageBucket {
  percent: number;
  resets_at: string | null;
  /** 型号那一档才有：Fable / Opus / … */
  label?: string | null;
}

/**
 * 本机 Claude Code 的订阅额度。`available` 为假就是这台机器答不出这件事——没装
 * Claude Code，或者用的是 API key 而不是订阅。
 */
export interface ClaudeUsage {
  available: boolean;
  session: ClaudeUsageBucket | null;
  week_all: ClaudeUsageBucket | null;
  week_model: ClaudeUsageBucket | null;
  checked_at: string | null;
  error: string | null;
}

/**
 * 本机一场 tmux agent 会话。
 *
 * `idle_secs` 说的是「自最后一次把话说完起过了多久」，不是 tmux 那边的活动时间——
 * 后者被 claude 界面自己的重绘推着走，实测同一批会话两个口径能差出四个多小时。
 * 判不出来（找不到记录、这一轮还没说完）为 null，界面显示「—」而不是编一个 0。
 */
export interface TmuxSessionItem {
  /** tmux 会话名，关闭时点的就是它 */
  name: string;
  /** 去掉 frago-agent- 前缀后那截，界面上显示的名字 */
  label: string;
  session_id: string | null;
  stop_reason: string | null;
  last_stop_at: string | null;
  idle_secs: number | null;
  /** 最后一段回答的截取，够认出这是哪一场会话 */
  excerpt: string;
  memory_mb: number;
  /** 此刻仍在干活（转轮在转，或派出去的后台 shell 没回来）——不许批量关 */
  busy: boolean;
  /** 归工作台那个会话池管 */
  managed: boolean;
}

export interface TmuxSessionsResponse {
  sessions: TmuxSessionItem[];
  total: number;
  total_memory_mb: number;
  /** 「闲了多久算该清」的门槛，小时。跟后台自动回收那条线是两回事 */
  cleanup_idle_hours: number;
}

export interface CloseTmuxSessionResult {
  name: string;
  ok: boolean;
  via: string;
  error: string | null;
}

export interface CloseTmuxSessionsResponse {
  results: CloseTmuxSessionResult[];
  closed: number;
  failed: number;
}

/** 左下角那个数字：只有个数和内存，不带任何一场会话的内容。 */
export interface TmuxSessionsCount {
  total: number;
  total_memory_mb: number;
}

/**
 * 环境仪表盘的一格。
 *
 * 两个版本号都可能为空，含义不同：`current` 空是这台机器上没装，`latest` 空是外面
 * 没有可查的版本源（WorkBuddy 只发桌面版）。界面两种都画成「—」，但前者要标成缺失。
 */
export interface EnvironmentItem {
  id: string;
  name: string;
  /** frago 本体 / 必装 / 选装 / agent 命令行，决定它排在哪一组 */
  group: 'frago' | 'required' | 'optional' | 'agent';
  required: boolean;
  installed: boolean;
  current: string | null;
  latest: string | null;
  outdated: boolean;
}

export interface EnvironmentResponse {
  items: EnvironmentItem[];
  os: string;
  /** frago 自己从哪儿装的：local 本地构建、index 索引、unknown */
  frago_source: 'local' | 'index' | 'unknown' | string;
  /** 外面那批版本号上次问到的时间，unix 秒 */
  checked_at: number | null;
}

/**
 * 一样东西这一轮升级到哪一步了。
 *
 * 五档：pending 排着队、running 正在跑、ok 升成了、skipped 不用升、failed 没升成。
 * `message` 是给人看的那句结论，失败时它说的是卡在哪。
 */
export interface EnvironmentUpgradeItemState {
  state: 'pending' | 'running' | 'ok' | 'skipped' | 'failed' | string;
  message: string;
  before: string | null;
  after: string | null;
}

export interface EnvironmentUpgradeResponse {
  /** 提交时才有意义：已经有一批在跑时为 false，返回的是那一批的进度 */
  accepted: boolean;
  running: boolean;
  order: string[];
  items: Record<string, EnvironmentUpgradeItemState>;
  started_at: number | null;
  finished_at: number | null;
}
