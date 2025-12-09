/**
 * PyWebview API TypeScript 类型定义
 *
 * 定义 window.pywebview.api 暴露的所有方法和返回类型。
 * 与 Python 后端 FragoGuiApi 类保持同步。
 */

// ============================================================
// 基础类型
// ============================================================

export type TaskStatus = 'running' | 'completed' | 'error' | 'cancelled';

export type StepType =
  | 'user_message'
  | 'assistant_message'
  | 'tool_use'
  | 'tool_result'
  | 'system';

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
   * 获取用户配置
   */
  get_config(): Promise<UserConfig>;

  /**
   * 更新用户配置
   * @param config 配置更新
   */
  update_config(config: Partial<UserConfig>): Promise<ConfigUpdateResponse>;

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
