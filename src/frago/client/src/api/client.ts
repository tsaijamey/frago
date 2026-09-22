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
  RecipeFolder,
  RecipeFoldersPayload,
  TaskItem,
  TaskStep,
  ToolUsageStat,
  TaskSummary,
  TaskDetail,
  TaskListResponse,
  TaskStepsResponse,
  UserConfig,
  DirectoryListing,
  SystemDirectories,
  GenerateTitleResponse,
  AgentAttachedStartResponse,
  AgentAttachedInfo,
  SkillItem,
  GhCliStatus,
  GhInstallPlan,
  GhInstallStartResult,
  GhInstallStatus,
  GhDeviceLogin,
  GhDeviceLoginStatus,
  PendingFile,
  AreaCount,
  LastCommit,
  DataRepoStatus,
  ExcludedCategory,
  IncludedArea,
  DataRepoPolicy,
  SyncTask,
  SyncStartResult,
  SyncRunStatus,
  SyncPrompt,
  APIEndpointConfig,
  MainConfig,
  ApiResponse,
  APIEndpointRequest,
  AuthUpdateRequest,
  AgentCoreSettings,
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
  EndpointPreset,
  EndpointPresetListResponse,
  ProfileItem,
  ProfileListResponse,
  ConnectionsResponse,
  ConnectionKind,
  ConnectionRole,
  WorkBuddyModel,
  WorkBuddyModelsResponse,
  RoleBinding,
  VendorCore,
  ActivationTarget,
  ActivationTargetListResponse,
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
  PaSessionItem,
  PaSessionsResponse,
  PaSessionSendResponse,
  TokenCalendarResponse,
  TokenDayBucket,
  ClaudeUsage,
  ClaudeUsageBucket,
  TmuxSessionsResponse,
  TmuxSessionsCount,
  CloseTmuxSessionsResponse,
  EnvironmentResponse,
  EnvironmentUpgradeResponse,
} from '@/types/api';

export type {
  ServerInfo,
  ServerStatus,
  RecipeItem,
  RecipeFolder,
  RecipeFoldersPayload,
  TaskItem,
  TaskStep,
  ToolUsageStat,
  TaskSummary,
  TaskDetail,
  TaskListResponse,
  TaskStepsResponse,
  UserConfig,
  DirectoryListing,
  SystemDirectories,
  GenerateTitleResponse,
  AgentAttachedStartResponse,
  AgentAttachedInfo,
  SkillItem,
  GhCliStatus,
  GhInstallPlan,
  GhInstallStartResult,
  GhInstallStatus,
  GhDeviceLogin,
  GhDeviceLoginStatus,
  PendingFile,
  AreaCount,
  LastCommit,
  DataRepoStatus,
  ExcludedCategory,
  IncludedArea,
  DataRepoPolicy,
  SyncTask,
  SyncStartResult,
  SyncRunStatus,
  SyncPrompt,
  APIEndpointConfig,
  MainConfig,
  ApiResponse,
  APIEndpointRequest,
  AuthUpdateRequest,
  AgentCoreSettings,
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
  EndpointPreset,
  EndpointPresetListResponse,
  ProfileItem,
  ProfileListResponse,
  ConnectionsResponse,
  ConnectionKind,
  ConnectionRole,
  WorkBuddyModel,
  WorkBuddyModelsResponse,
  RoleBinding,
  VendorCore,
  ActivationTarget,
  ActivationTargetListResponse,
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
  PaSessionItem,
  PaSessionsResponse,
  PaSessionSendResponse,
  TokenCalendarResponse,
  TokenDayBucket,
  ClaudeUsage,
  ClaudeUsageBucket,
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

/**
 * 一层一层翻目录，挑工作目录用。留空从家目录起。
 *
 * 路径走不通时服务端会把人放回家目录，而不是抛错——挑目录的人打错一个字就看到一句
 * 报错、清单整个消失，还不如把他放回一个一定走得通的地方。
 */
export async function browseDirectories(path = ''): Promise<DirectoryListing> {
  const query = path ? `?path=${encodeURIComponent(path)}` : '';
  return fetchApi<DirectoryListing>(`/system/directories/browse${query}`);
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

// ── 文件夹 ──────────────────────────────────────────────────────────────
//
// 每一条写操作都回整张表：摆图标这件事一次动好几处（从原文件夹拿出来、放进新的、
// 顺序跟着变），各自回各自那一块的话，界面得自己把几块拼回去，拼错了就是图标凭空
// 多一个少一个。整张回来最省事，表也就几十行。

export async function getRecipeFolders(): Promise<RecipeFoldersPayload> {
  return fetchApi<RecipeFoldersPayload>('/recipes/folders');
}

export async function createRecipeFolder(body: {
  id: string;
  name_zh?: string;
  name_en?: string;
  icon?: string;
  recipes?: string[];
}): Promise<RecipeFoldersPayload> {
  return fetchApi<RecipeFoldersPayload>('/recipes/folders', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function updateRecipeFolder(
  id: string,
  body: { name_zh?: string; name_en?: string; icon?: string; position?: number },
): Promise<RecipeFoldersPayload> {
  return fetchApi<RecipeFoldersPayload>(`/recipes/folders/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export async function deleteRecipeFolder(id: string): Promise<RecipeFoldersPayload> {
  return fetchApi<RecipeFoldersPayload>(`/recipes/folders/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

/** 把几张配方放进 `folder`，`null` 表示拿出来回到未分类。 */
export async function assignRecipeFolder(
  recipes: string[],
  folder: string | null,
): Promise<RecipeFoldersPayload> {
  return fetchApi<RecipeFoldersPayload>('/recipes/folders/assign', {
    method: 'POST',
    body: JSON.stringify({ recipes, folder }),
  });
}

/** 配方页面的地址。开发模式下接口在另一个端口，页面也得跟着去那边取。 */
export function recipeAppUrl(name: string, slot?: string | null): string {
  const base = `${API_BASE_URL}/app/${encodeURIComponent(name)}/`;
  return slot && slot !== 'default' ? `${base}?key=${encodeURIComponent(slot)}` : base;
}

/** 告诉服务端：它推过来的那个「打开配方页面」这边已经打开了。 */
export async function ackRecipeAppShow(requestId: string): Promise<void> {
  await fetchApi(`/recipe-apps/ack/${encodeURIComponent(requestId)}`, { method: 'POST' });
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

/** 一次运行现在的样子：状态，以及跑完之后配方交回来的结果。 */
export interface RecipeExecution {
  id: string;
  status: string;
  data?: unknown;
  error?: { message?: string } | string | null;
}

export async function getExecution(executionId: string): Promise<RecipeExecution> {
  return fetchApi<RecipeExecution>(`/executions/${encodeURIComponent(executionId)}`);
}

/**
 * 在图形界面里创建配方：起一场「导演」会话，回的地址指向虚拟桌面（带人类输入行）。
 * 人在那扇窗口里看着 worker 在终端里写配方、页面在浏览器窗口里长出来，中途还能追加需求。
 */
export async function forgeRecipe(body: {
  requirement: string;
  page: boolean;
  name?: string;
}): Promise<{ session_id: string; desktop_url: string; recipe_name: string | null }> {
  return fetchApi('/recipes/forge', {
    method: 'POST',
    body: JSON.stringify(body),
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
// Todos API — `frago todo` 的事务
// ============================================================

/** 一件事务。字段与 `frago todo show` 输出的 JSON 逐字对齐。 */
export interface TodoItem {
  id: string;
  title: string;
  summary: string | null;
  status: TodoStatus;
  priority: TodoPriority;
  tags: string[];
  /**
   * 分类 id，未分类为 null。可能引用了已从分类清单里删掉的 id——字段原样保留，
   * 显示和排序都按未分类算。
   */
  category: string | null;
  created: string;
  updated: string;
  done_at: string | null;
  /** 弃置的日期与理由。只有 `frago todo drop` 写得出，没弃置过的是 null。 */
  dropped_at: string | null;
  drop_reason: string | null;
  context: string | null;
  steps: string[];
  done_when: string[];
  links: string[];
  /** 这件事在哪几场会话里被谈过，早的在前——顺着 id 能回到当时的原话。 */
  sessions: string[];
}

export type TodoStatus = 'todo' | 'doing' | 'done' | 'dropped';
export type TodoPriority = 'low' | 'normal' | 'high';

export interface TodoListResponse {
  todos: TodoItem[];
  /** 每一档各有几件，外加 `all`。按状态筛选之前算，所以筛来筛去这组数不变。 */
  counts: Record<string, number>;
  /** 分类清单，按名次先后。清单里的位置就是排序时的名次，不映射到高中低。 */
  categories: TodoCategory[];
}

export interface TodoCategory {
  /** 稳定 id，事务文件里存的是它；改显示名不动它。 */
  id: string;
  name: string;
  /** 从 1 数的名次。 */
  position: number;
}

export interface TodoCategoriesResponse {
  categories: TodoCategory[];
  /** 每个分类 id 被几件事务引用（含已不在清单里的 id）。 */
  usage: Record<string, number>;
}

export interface TodoQuery {
  status?: TodoStatus;
  priority?: TodoPriority;
  tag?: string;
  /** 分类 id；`none` 为未分类。 */
  category?: string;
}

export async function getTodos(query: TodoQuery = {}): Promise<TodoListResponse> {
  const params = new URLSearchParams();
  if (query.status) params.set('status', query.status);
  if (query.priority) params.set('priority', query.priority);
  if (query.tag) params.set('tag', query.tag);
  if (query.category) params.set('category', query.category);
  const qs = params.toString();
  return fetchApi<TodoListResponse>(`/todos${qs ? `?${qs}` : ''}`);
}

export async function getTodo(todoId: string): Promise<TodoItem> {
  return fetchApi<TodoItem>(`/todos/${encodeURIComponent(todoId)}`);
}

/**
 * 整张替换分类清单，数组顺序即名次。
 *
 * 这是 config.json 里的一段配置，不是事务文件——事务本身仍只走命令行写。
 */
export async function updateTodoCategories(
  categories: { id: string; name: string }[]
): Promise<TodoCategoriesResponse> {
  return fetchApi<TodoCategoriesResponse>('/todos/categories', {
    method: 'PUT',
    body: JSON.stringify({ categories }),
  });
}

/** agent 替人建完事务之后的回话。 */
export interface TodoComposeResponse {
  /** 落到哪件事务上。agent 跑完却一件都没落下时为 null。 */
  todo_id: string | null;
  /** 新建的还是追加到已有那件上的——描述的事情已经有一条时，规矩要求它追加。 */
  created: boolean;
  /** agent 自己的说法，原样展示。 */
  message: string;
  /** 它实际敲下去的那条命令。看得见执行了什么，这个按钮才不是黑箱。 */
  command: string[] | null;
}

/**
 * 把一句话交给 agent，让它写成一件像样的事务。
 *
 * 这一路会真的起一个模型跑几轮，十几秒是常态——调用方必须有等待态。
 */
export async function composeTodo(description: string): Promise<TodoComposeResponse> {
  return fetchApi<TodoComposeResponse>('/todos', {
    method: 'POST',
    body: JSON.stringify({ description }),
  });
}

/** 弃置一件事务之后的回话。 */
export interface TodoDropResponse {
  /** 弃置之后那件事务的全貌，界面直接拿它把详情换成新的样子。 */
  todo: TodoItem;
  /** 服务端替人敲下的那条命令，摆出来给人看。 */
  command: string[];
}

/**
 * 把一件事务弃置掉：这件不做了，`reason` 说清为什么。
 *
 * 理由是必填的，而且一个字不差地记进事务文件——半年后有人翻到这条，第一个问题就是
 * 「当初为什么不做了」。服务端不写文件，它去跑 `frago todo drop`，规矩长在那条命令上：
 * 已经弃置过的不许再弃置一次，那会把当初的判断悄悄换掉。
 */
export async function dropTodo(todoId: string, reason: string): Promise<TodoDropResponse> {
  return fetchApi<TodoDropResponse>(`/todos/${encodeURIComponent(todoId)}/drop`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

// ============================================================
// Schedules API — `frago schedule` 的定时任务
// ============================================================

/** 一次执行。配方和命令型写得全；自然语言型由 PA 回填，只有时间和状态。 */
export interface ScheduleHistoryEntry {
  triggered_at: string | null;
  status: string | null;
  kind?: string | null;
  exit_code?: number | null;
  duration_ms?: number | null;
  error?: string;
  /** 这一次是人手点的「立即跑」，不是按周期触发的。 */
  manual?: boolean;
  notified?: boolean;
  notify_status?: string | null;
  notify_reason?: string | null;
  task_id?: string | null;
  /**
   * 自然语言任务这一趟 CoreAgent 开的那场会话。会话页据此摆出整场过程——中途执行了
   * 哪些命令、哪些被拦下。命令与配方不起 agent，恒为空。
   */
  session_id?: string | null;
  /** CoreAgent 最后答的那句话。过长会在服务端截断。 */
  answer?: string | null;
}

/** 一条定时任务。字段取自 ~/.frago/schedules.json，外加服务端现算的 next_run_at 与 running。 */
export interface ScheduleItem {
  id: string;
  name: string;
  /** command / recipe 由 frago 自己执行；prompt 交给 PA。 */
  kind: 'command' | 'recipe' | 'prompt' | string;
  prompt: string | null;
  recipe: string | null;
  command: string | null;
  cwd: string | null;
  /** prompt 型：CoreAgent 读的说明书（~/.frago/coreagent/ 下的文件名）。 */
  instructions: string | null;
  /** prompt 型：只允许这些工具调用（Claude Code 权限规则写法）；空数组 = 不限制。 */
  allowed_tools: string[];
  /** prompt 型：禁止的工具调用，命中即拒，优先于允许。 */
  disallowed_tools: string[];
  params: Record<string, unknown>;
  interval_seconds: number | null;
  cron: string | null;
  overlap: string;
  timeout: number;
  start_at: string | null;
  end_at: string | null;
  enabled: boolean;
  created_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_success_at: string | null;
  consecutive_failures: number;
  run_count: number;
  notify: { on: string; to: string | null; context: Record<string, unknown> };
  /** 最近 50 次，早的在前。 */
  history: ScheduleHistoryEntry[];
  /** 停用的任务为 null。 */
  next_run_at: string | null;
  /** 上一次触发还没结束。 */
  running: boolean;
}

export interface ScheduleListResponse {
  schedules: ScheduleItem[];
  /** 调度器没在跑时，「下次运行」一条都不会兑现。 */
  scheduler_running: boolean;
}

export interface ScheduleRunResponse {
  status: string;
  id: string;
  kind: string;
  triggered_at: string;
}

export interface ScheduleComposeResponse {
  /** agent 跑完却没建出任何一条时为 null。 */
  schedule_id: string | null;
  message: string;
  /** 它实际敲下去的那条 `frago schedule add`。 */
  command: string[] | null;
}

export async function getSchedules(): Promise<ScheduleListResponse> {
  return fetchApi<ScheduleListResponse>('/schedules');
}

export async function toggleSchedule(id: string): Promise<ScheduleItem> {
  return fetchApi<ScheduleItem>(`/schedules/${encodeURIComponent(id)}/toggle`, { method: 'POST' });
}

/** 立即跑一次。接口不等执行结束，结果要靠刷新执行记录看。 */
export async function runSchedule(id: string): Promise<ScheduleRunResponse> {
  return fetchApi<ScheduleRunResponse>(`/schedules/${encodeURIComponent(id)}/run`, {
    method: 'POST',
  });
}

export async function removeSchedule(id: string): Promise<void> {
  await fetchApi<unknown>(`/schedules/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/** 把一句话交给 agent 建成定时任务。会真的起一个模型跑几轮，调用方必须有等待态。 */
export async function composeSchedule(description: string): Promise<ScheduleComposeResponse> {
  return fetchApi<ScheduleComposeResponse>('/schedules', {
    method: 'POST',
    body: JSON.stringify({ description }),
  });
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

// ---- 数据仓库 ----

export async function getDataRepoStatus(limit?: number): Promise<DataRepoStatus> {
  const query = limit === undefined ? '' : `?limit=${limit}`;
  return fetchApi<DataRepoStatus>(`/data-repo/status${query}`);
}

export async function getDataRepoPolicy(): Promise<DataRepoPolicy> {
  return fetchApi<DataRepoPolicy>('/data-repo/policy');
}

export async function getDataRepoSyncPrompt(
  mode: string,
  instruction?: string
): Promise<SyncPrompt> {
  const params = new URLSearchParams({ mode });
  if (instruction) params.set('instruction', instruction);
  return fetchApi<SyncPrompt>(`/data-repo/sync/prompt?${params.toString()}`);
}

export async function startDataRepoSync(
  mode: string,
  instruction?: string
): Promise<SyncStartResult> {
  return fetchApi<SyncStartResult>('/data-repo/sync', {
    method: 'POST',
    body: JSON.stringify({ mode, instruction: instruction ?? null }),
  });
}

export async function getDataRepoSyncStatus(): Promise<SyncRunStatus> {
  return fetchApi<SyncRunStatus>('/data-repo/sync/status');
}

export async function getGhInstallPlan(): Promise<GhInstallPlan> {
  return fetchApi<GhInstallPlan>('/settings/gh-cli/install-plan');
}

export async function startGhInstall(): Promise<GhInstallStartResult> {
  return fetchApi<GhInstallStartResult>('/settings/gh-cli/install', { method: 'POST' });
}

export async function getGhInstallStatus(): Promise<GhInstallStatus> {
  return fetchApi<GhInstallStatus>('/settings/gh-cli/install/status');
}

export async function startGhDeviceLogin(): Promise<GhDeviceLogin> {
  return fetchApi<GhDeviceLogin>('/settings/gh-cli/login/web', { method: 'POST' });
}

export async function getGhDeviceLoginStatus(): Promise<GhDeviceLoginStatus> {
  return fetchApi<GhDeviceLoginStatus>('/settings/gh-cli/login/web/status');
}

export async function cancelGhDeviceLogin(): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/gh-cli/login/web/cancel', { method: 'POST' });
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

export async function getAgentCore(): Promise<AgentCoreSettings> {
  return fetchApi<AgentCoreSettings>('/settings/agent-core');
}

export async function updateAgentCore(agentCore: string): Promise<AgentCoreSettings> {
  return fetchApi<AgentCoreSettings>('/settings/agent-core', {
    method: 'PUT',
    body: JSON.stringify({ agent_core: agentCore }),
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

export async function openPath(path: string, reveal: boolean = false): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/open-path', {
    method: 'POST',
    body: JSON.stringify({ path, reveal }),
  });
}

// ============================================================
// Prompting Capability API (static rules + LightAgent)
// ============================================================

/** Which of the four LightAgent states the backend resolved to. */
export type LightAgentStatus = 'enabled' | 'disabled' | 'not_configured' | 'no_key';

export interface HookReviewStatus {
  /** The switch as persisted in ~/.frago/config.json -> hook_review.enabled. */
  enabled: boolean;
  /** FRAGO_REVIEW=off is present in the server's environment — a session-scoped
   *  override that beats the persisted switch. */
  env_off: boolean;
  static_rules: {
    available: boolean;
    /** null when the rule set could not be counted — render "in effect" with no number. */
    count: number | null;
  };
  lightagent: {
    status: LightAgentStatus;
    profile_name: string | null;
    model: string | null;
    detail: string | null;
  };
}

export async function getHookReviewStatus(): Promise<HookReviewStatus> {
  return fetchApi<HookReviewStatus>('/settings/hook-review');
}

export async function setHookReviewEnabled(enabled: boolean): Promise<HookReviewStatus> {
  return fetchApi<HookReviewStatus>('/settings/hook-review', {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
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

/** The built-in endpoint table. Single source of truth lives in the backend. */
export async function getEndpointPresets(): Promise<EndpointPresetListResponse> {
  return fetchApi<EndpointPresetListResponse>('/settings/endpoint-presets');
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

/** The agent CLIs a profile can be activated on, and why the others can't. */
export async function getActivationTargets(): Promise<ActivationTargetListResponse> {
  return fetchApi<ActivationTargetListResponse>('/settings/profiles/targets');
}

/**
 * Activate a profile on the given agent CLIs.
 *
 * Omitting `targets` keeps the historical behavior — Claude Code only.
 */
export async function activateProfile(id: string, targets?: string[]): Promise<ApiResponse> {
  return fetchApi<ApiResponse>(`/settings/profiles/${encodeURIComponent(id)}/activate`, {
    method: 'POST',
    body: JSON.stringify({ targets: targets ?? null }),
  });
}

export async function deactivateProfile(): Promise<ApiResponse> {
  return fetchApi<ApiResponse>('/settings/profiles/deactivate', {
    method: 'POST',
  });
}

/**
 * Every bindable connection, plus what each role runs on now.
 *
 * One round trip rather than three: the two role rows have to agree with each
 * other and with the list they pick from, and loading them separately showed a
 * half-updated pair after every change.
 */
export async function getConnections(): Promise<ConnectionsResponse> {
  return fetchApi<ConnectionsResponse>('/settings/connections');
}

/**
 * Point one role at one connection.
 *
 * `targets` is main-only: binding main writes the connection into those agent
 * CLIs' own configuration. Binding worker writes nothing anywhere — it is read
 * when `frago agent` opens a session.
 */
export async function bindRole(
  role: ConnectionRole,
  profileId: string,
  targets?: string[],
): Promise<ApiResponse> {
  return fetchApi<ApiResponse>(`/settings/connections/bindings/${encodeURIComponent(role)}`, {
    method: 'PUT',
    body: JSON.stringify({ profile_id: profileId, targets: targets ?? null }),
  });
}

/**
 * What a WorkBuddy connection can be pointed at: the models the last probe found
 * answering, and whether the WorkBuddy client is logged in here. Re-probing is
 * `frago-core models probe-workbuddy`.
 */
export async function getWorkbuddyModels(): Promise<WorkBuddyModelsResponse> {
  return fetchApi<WorkBuddyModelsResponse>('/settings/workbuddy-models');
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

/**
 * 本机 Claude Code 的订阅额度。读的是服务端每十分钟探一次的缓存，请求本身不跑 claude。
 */
export async function getClaudeUsage(): Promise<ClaudeUsage> {
  return fetchApi<ClaudeUsage>('/system/claude-usage');
}

export async function getTokenCalendar(month: string): Promise<TokenCalendarResponse> {
  return fetchApi<TokenCalendarResponse>(
    `/claude-sessions/token-calendar?month=${encodeURIComponent(month)}`
  );
}

/**
 * 清点本机全部 frago tmux 会话。
 *
 * `excerptChars` 决定每行那段正文截多长——够不够认出「这是哪一场会话」由界面按自己
 * 的行宽决定，服务端不写死。
 */
export async function getTmuxSessions(excerptChars = 160): Promise<TmuxSessionsResponse> {
  return fetchApi<TmuxSessionsResponse>(`/system/tmux-sessions?excerpt_chars=${excerptChars}`);
}

/** 逐条点名关闭。服务端一条失败继续下一条，结果逐条回报。 */
export async function closeTmuxSessions(names: string[]): Promise<CloseTmuxSessionsResponse> {
  return fetchApi<CloseTmuxSessionsResponse>('/system/tmux-sessions/close', {
    method: 'POST',
    body: JSON.stringify({ names }),
  });
}

/** 改「闲了多久算该清」的门槛并落盘；返回按新门槛重新清点的结果。 */
export async function setTmuxCleanupThreshold(hours: number): Promise<TmuxSessionsResponse> {
  return fetchApi<TmuxSessionsResponse>('/system/tmux-sessions/threshold', {
    method: 'PUT',
    body: JSON.stringify({ cleanup_idle_hours: hours }),
  });
}

/** 只数个数和内存——左下角那个数字每分钟问一次的就是它，不读任何记录。 */
export async function getTmuxSessionCount(): Promise<TmuxSessionsCount> {
  return fetchApi<TmuxSessionsCount>('/system/tmux-sessions/count');
}

/**
 * 跑 frago 需要的每样东西，本机装的是哪一版、外面出到哪一版。
 *
 * 默认读服务端的缓存（外面的版本号六小时一轮），所以侧边栏那颗按钮每次加载页面问一遍
 * 不会真的打十来次跨境请求。`refresh` 为真才当场重问。
 */
export async function getEnvironment(refresh = false): Promise<EnvironmentResponse> {
  return fetchApi<EnvironmentResponse>(`/system/environment${refresh ? '?refresh=true' : ''}`);
}

/**
 * 把点名的那几样升到最新。服务端派 agent 去干，一样一样按顺序跑。
 *
 * 立刻返回，不等升完——一样东西可能要下载几百 MB。进度问下面那条。
 */
export async function startEnvironmentUpgrade(ids: string[]): Promise<EnvironmentUpgradeResponse> {
  return fetchApi<EnvironmentUpgradeResponse>('/system/environment/upgrade', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}

/** 这一批升级到哪一步了。 */
export async function getEnvironmentUpgradeStatus(): Promise<EnvironmentUpgradeResponse> {
  return fetchApi<EnvironmentUpgradeResponse>('/system/environment/upgrade');
}
