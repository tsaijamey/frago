/**
 * PyWebview API TypeScript 类型定义
 *
 * 定义 window.pywebview.api 暴露的所有方法和返回类型。
 * 与 Python 后端 fragoGuiApi 类保持同步。
 */

// ============================================================
// 基础类型
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

export type ToastType = 'info' | 'success' | 'warning' | 'error';

// ============================================================
// 数据模型
// ============================================================

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
}

export interface TaskStep {
  step_id: number;
  type: StepType;
  timestamp: string;
  content: string;
  tool_name: string | null;
  tool_status: string | null;
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

export interface RecipeDetail extends RecipeItem {
  metadata_content: string | null;
  recipe_dir: string | null;
}

export interface SkillItem {
  name: string;
  description: string | null;
  icon: string | null;
  file_path: string;
}

export interface UserConfig {
  theme: Theme;
  font_size: number;
  show_system_status: boolean;
  confirm_on_exit: boolean;
  auto_scroll_output: boolean;
  max_history_items: number;
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
// Settings 页面相关类型（主配置、环境变量、GitHub）
// ============================================================

export interface APIEndpoint {
  type: 'deepseek' | 'aliyun' | 'kimi' | 'minimax' | 'custom';
  url?: string;
  api_key: string;
}

export interface MainConfig {
  schema_version: string;
  // 依赖信息
  node_version?: string;
  node_path?: string;
  npm_version?: string;
  claude_code_version?: string;
  claude_code_path?: string;
  // 认证配置
  auth_method: 'official' | 'custom';
  api_endpoint?: APIEndpoint;
  // 可选功能
  ccr_enabled: boolean;
  ccr_config_path?: string;
  working_directory?: string;
  sync_repo_url?: string;
  // 资源状态
  resources_installed: boolean;
  resources_version?: string;
  last_resource_update?: string;
  // 元数据
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
  status: 'ok' | 'error' | 'running';
  message?: string;
  output?: string;
  error?: string;
}

// ============================================================
// API 响应类型
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

// ============================================================
// PyWebview API 接口
// ============================================================

export interface PyWebviewApi {
  // ============================================================
  // Tasks API（011-gui-tasks-redesign）
  // ============================================================

  /**
   * 获取任务列表
   * @param limit 最大返回数量（1-100，默认 50）
   * @param status 筛选状态（可选）
   */
  get_tasks(limit?: number, status?: TaskStatus): Promise<TaskItem[]>;

  /**
   * 获取任务详情
   * @param session_id 会话 ID
   * @param steps_limit 步骤数量限制（1-100，默认 50）
   * @param steps_offset 步骤偏移量（默认 0）
   */
  get_task_detail(
    session_id: string,
    steps_limit?: number,
    steps_offset?: number
  ): Promise<TaskDetail>;

  /**
   * 分页获取任务步骤
   * @param session_id 会话 ID
   * @param offset 偏移量
   * @param limit 数量限制（1-100，默认 50）
   */
  get_task_steps(
    session_id: string,
    offset?: number,
    limit?: number
  ): Promise<TaskStepsResponse>;

  /**
   * 启动 agent 任务
   * @param prompt 任务描述
   */
  start_agent_task(prompt: string): Promise<TaskStartResponse>;

  /**
   * 在指定会话中继续对话
   * @param session_id 会话 ID
   * @param prompt 新的提示词
   */
  continue_agent_task(session_id: string, prompt: string): Promise<TaskStartResponse>;

  // ============================================================
  // Recipes API
  // ============================================================

  /**
   * 获取配方列表
   */
  get_recipes(): Promise<RecipeItem[]>;

  /**
   * 刷新配方列表
   */
  refresh_recipes(): Promise<RecipeItem[]>;

  /**
   * 获取配方详情
   * @param name 配方名称
   */
  get_recipe_detail(name: string): Promise<RecipeDetail>;

  /**
   * 执行配方
   * @param name 配方名称
   * @param params 参数（可选）
   */
  run_recipe(
    name: string,
    params?: Record<string, unknown>
  ): Promise<RecipeRunResponse>;

  /**
   * 删除配方（仅用户级）
   * @param name 配方名称
   */
  delete_recipe(name: string): Promise<RecipeDeleteResponse>;

  // ============================================================
  // Skills API
  // ============================================================

  /**
   * 获取技能列表
   */
  get_skills(): Promise<SkillItem[]>;

  /**
   * 刷新技能列表
   */
  refresh_skills(): Promise<SkillItem[]>;

  // ============================================================
  // Config API
  // ============================================================

  /**
   * 获取用户配置（GUI 配置）
   */
  get_config(): Promise<UserConfig>;

  /**
   * 更新用户配置（GUI 配置）
   * @param config 配置更新
   */
  update_config(config: Partial<UserConfig>): Promise<ConfigUpdateResponse>;

  // ============================================================
  // Settings API - 主配置管理
  // ============================================================

  /**
   * 获取主配置（~/.frago/config.json）
   */
  get_main_config(): Promise<MainConfig>;

  /**
   * 更新主配置
   * @param updates 部分更新字典
   */
  update_main_config(updates: Partial<MainConfig>): Promise<MainConfigUpdateResponse>;

  /**
   * 更新认证方式和 API 端点
   * @param auth_data 认证配置
   */
  update_auth_method(auth_data: AuthUpdateRequest): Promise<MainConfigUpdateResponse>;

  /**
   * 在文件管理器中打开工作目录
   */
  open_working_directory(): Promise<ApiResponse>;

  // ============================================================
  // Settings API - 环境变量管理
  // ============================================================

  /**
   * 获取用户级环境变量（~/.frago/.env）
   */
  get_env_vars(): Promise<EnvVarsResponse>;

  /**
   * 批量更新环境变量
   * @param updates 更新字典，value=null 表示删除
   */
  update_env_vars(
    updates: Record<string, string | null>
  ): Promise<EnvVarsUpdateResponse>;

  /**
   * 扫描所有 Recipe 的环境变量需求
   */
  get_recipe_env_requirements(): Promise<RecipeEnvRequirement[]>;

  // ============================================================
  // Settings API - GitHub 集成
  // ============================================================

  /**
   * 检查 gh CLI 安装和登录状态
   */
  check_gh_cli(): Promise<GhCliStatus>;

  /**
   * 在外部终端执行 gh auth login
   */
  gh_auth_login(): Promise<ApiResponse>;

  /**
   * 创建 GitHub 仓库并配置到 config.json
   * @param repo_name 仓库名称
   * @param private_repo 是否私有仓库
   */
  create_sync_repo(repo_name: string, private_repo?: boolean): Promise<CreateRepoResponse>;

  /**
   * 执行 frago sync（后台线程）
   */
  run_first_sync(): Promise<SyncResponse>;

  /**
   * 获取 sync 结果（轮询）
   */
  get_sync_result(): Promise<SyncResponse>;

  // ============================================================
  // System API
  // ============================================================

  /**
   * 获取系统状态
   */
  get_system_status(): Promise<SystemStatus>;

  /**
   * 检查 Chrome 连接状态
   */
  check_connection(): Promise<ConnectionStatus>;

  // ============================================================
  // Legacy API（保留兼容性）
  // ============================================================

  /**
   * 获取命令历史
   * @param limit 最大返回数量
   * @param offset 偏移量
   */
  get_history(limit?: number, offset?: number): Promise<unknown[]>;

  /**
   * 清空历史记录
   */
  clear_history(): Promise<{ status: string; cleared_count: number }>;

  /**
   * 获取任务状态（旧版）
   */
  get_task_status(): Promise<{
    status: string;
    task_id: string | null;
    progress: number;
    error: string | null;
  }>;

  /**
   * 运行 agent（旧版）
   */
  run_agent(prompt: string): Promise<string>;

  /**
   * 取消 agent 任务（旧版）
   */
  cancel_agent(): Promise<{ status: string; message: string }>;
}

// ============================================================
// 全局类型声明
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
