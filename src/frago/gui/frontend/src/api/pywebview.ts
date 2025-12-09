/**
 * pywebview API 封装层
 *
 * 提供类型安全的 API 调用和 pywebview 就绪状态检测
 */

import type {
  PyWebviewApi,
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
} from '@/types/pywebview.d';

// 等待 pywebview 就绪
let readyPromise: Promise<PyWebviewApi> | null = null;

export function waitForPywebview(): Promise<PyWebviewApi> {
  if (readyPromise) return readyPromise;

  readyPromise = new Promise((resolve) => {
    if (window.pywebview?.api) {
      resolve(window.pywebview.api);
      return;
    }

    const handleReady = () => {
      if (window.pywebview?.api) {
        window.removeEventListener('pywebviewready', handleReady);
        resolve(window.pywebview.api);
      }
    };

    window.addEventListener('pywebviewready', handleReady);
  });

  return readyPromise;
}

// 获取 API (可能为 undefined)
export function getApi(): PyWebviewApi | undefined {
  return window.pywebview?.api;
}

// 检查 API 是否就绪
export function isApiReady(): boolean {
  return !!window.pywebview?.api;
}

// ============================================================
// Tasks API
// ============================================================

export async function getTasks(
  limit?: number,
  status?: TaskStatus
): Promise<TaskItem[]> {
  const api = await waitForPywebview();
  return api.get_tasks(limit, status);
}

export async function getTaskDetail(
  sessionId: string,
  stepsLimit?: number,
  stepsOffset?: number
): Promise<TaskDetail> {
  const api = await waitForPywebview();
  return api.get_task_detail(sessionId, stepsLimit, stepsOffset);
}

export async function getTaskSteps(
  sessionId: string,
  offset?: number,
  limit?: number
): Promise<TaskStepsResponse> {
  const api = await waitForPywebview();
  return api.get_task_steps(sessionId, offset, limit);
}

export async function startAgentTask(
  prompt: string
): Promise<TaskStartResponse> {
  const api = await waitForPywebview();
  return api.start_agent_task(prompt);
}

// ============================================================
// Recipes API
// ============================================================

export async function getRecipes(): Promise<RecipeItem[]> {
  const api = await waitForPywebview();
  return api.get_recipes();
}

export async function refreshRecipes(): Promise<RecipeItem[]> {
  const api = await waitForPywebview();
  return api.refresh_recipes();
}

export async function getRecipeDetail(name: string): Promise<RecipeDetail> {
  const api = await waitForPywebview();
  return api.get_recipe_detail(name);
}

export async function runRecipe(
  name: string,
  params?: Record<string, unknown>
): Promise<RecipeRunResponse> {
  const api = await waitForPywebview();
  return api.run_recipe(name, params);
}

export async function deleteRecipe(
  name: string
): Promise<RecipeDeleteResponse> {
  const api = await waitForPywebview();
  return api.delete_recipe(name);
}

// ============================================================
// Skills API
// ============================================================

export async function getSkills(): Promise<SkillItem[]> {
  const api = await waitForPywebview();
  return api.get_skills();
}

export async function refreshSkills(): Promise<SkillItem[]> {
  const api = await waitForPywebview();
  return api.refresh_skills();
}

// ============================================================
// Config API
// ============================================================

export async function getConfig(): Promise<UserConfig> {
  const api = await waitForPywebview();
  return api.get_config();
}

export async function updateConfig(
  config: Partial<UserConfig>
): Promise<ConfigUpdateResponse> {
  const api = await waitForPywebview();
  return api.update_config(config);
}

// ============================================================
// System API
// ============================================================

export async function getSystemStatus(): Promise<SystemStatus> {
  const api = await waitForPywebview();
  return api.get_system_status();
}

export async function checkConnection(): Promise<ConnectionStatus> {
  const api = await waitForPywebview();
  return api.check_connection();
}
