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
  MainConfig,
  MainConfigUpdateResponse,
  AuthUpdateRequest,
  EnvVarsResponse,
  EnvVarsUpdateResponse,
  RecipeEnvRequirement,
  GhCliStatus,
  ApiResponse,
  CreateRepoResponse,
  SyncResponse,
} from '@/types/pywebview.d';

// 等待 pywebview 就绪
let readyPromise: Promise<PyWebviewApi> | null = null;

// 检查 API 是否完全就绪（方法已注入）
function isApiFullyReady(): boolean {
  const api = window.pywebview?.api;
  // 检查关键方法是否存在
  return !!(api && typeof api.get_config === 'function');
}

export function waitForPywebview(): Promise<PyWebviewApi> {
  if (readyPromise) return readyPromise;

  readyPromise = new Promise((resolve) => {
    const checkAndResolve = () => {
      if (isApiFullyReady()) {
        const api = window.pywebview!.api;
        console.log('[pywebview] API fully ready, methods:', Object.keys(api));
        resolve(api);
        return true;
      }
      return false;
    };

    // 立即检查
    if (checkAndResolve()) return;

    // 轮询检查（pywebview 方法注入可能有延迟）
    const pollInterval = setInterval(() => {
      if (checkAndResolve()) {
        clearInterval(pollInterval);
      }
    }, 50);

    // 同时监听 pywebviewready 事件
    const handleReady = () => {
      console.log('[pywebview] pywebviewready event fired');
      // 事件触发后也需要轮询，因为方法可能还没注入完
      setTimeout(() => {
        if (checkAndResolve()) {
          clearInterval(pollInterval);
        }
      }, 100);
      window.removeEventListener('pywebviewready', handleReady);
    };

    window.addEventListener('pywebviewready', handleReady);

    // 超时保护（10秒）
    setTimeout(() => {
      clearInterval(pollInterval);
      if (!isApiFullyReady()) {
        console.error('[pywebview] API not ready after 10s timeout');
      }
    }, 10000);
  });

  return readyPromise;
}

// 获取 API (可能为 undefined)
export function getApi(): PyWebviewApi | undefined {
  return window.pywebview?.api;
}

// 检查 API 是否就绪（方法已注入）
export function isApiReady(): boolean {
  return isApiFullyReady();
}

// ============================================================
// Tasks API
// ============================================================

export async function getTasks(
  limit?: number,
  status?: TaskStatus
): Promise<TaskItem[]> {
  const api = await waitForPywebview();
  // pywebview 需要显式传参，不传 undefined
  return api.get_tasks(limit ?? 50, status);
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

export async function continueAgentTask(
  sessionId: string,
  prompt: string
): Promise<TaskStartResponse> {
  const api = await waitForPywebview();
  return api.continue_agent_task(sessionId, prompt);
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

// ============================================================
// Settings API - 主配置管理
// ============================================================

export async function getMainConfig(): Promise<MainConfig> {
  const api = await waitForPywebview();
  return api.get_main_config();
}

export async function updateMainConfig(
  updates: Partial<MainConfig>
): Promise<MainConfigUpdateResponse> {
  const api = await waitForPywebview();
  return api.update_main_config(updates);
}

export async function updateAuthMethod(
  authData: AuthUpdateRequest
): Promise<MainConfigUpdateResponse> {
  const api = await waitForPywebview();
  return api.update_auth_method(authData);
}

export async function openWorkingDirectory(): Promise<ApiResponse> {
  const api = await waitForPywebview();
  return api.open_working_directory();
}

// ============================================================
// Settings API - 环境变量管理
// ============================================================

export async function getEnvVars(): Promise<EnvVarsResponse> {
  const api = await waitForPywebview();
  return api.get_env_vars();
}

export async function updateEnvVars(
  updates: Record<string, string | null>
): Promise<EnvVarsUpdateResponse> {
  const api = await waitForPywebview();
  return api.update_env_vars(updates);
}

export async function getRecipeEnvRequirements(): Promise<RecipeEnvRequirement[]> {
  const api = await waitForPywebview();
  return api.get_recipe_env_requirements();
}

// ============================================================
// Settings API - GitHub 集成
// ============================================================

export async function checkGhCli(): Promise<GhCliStatus> {
  const api = await waitForPywebview();
  return api.check_gh_cli();
}

export async function ghAuthLogin(): Promise<ApiResponse> {
  const api = await waitForPywebview();
  return api.gh_auth_login();
}

export async function createSyncRepo(
  repoName: string,
  privateRepo: boolean = true
): Promise<CreateRepoResponse> {
  const api = await waitForPywebview();
  return api.create_sync_repo(repoName, privateRepo);
}

export async function runFirstSync(): Promise<SyncResponse> {
  const api = await waitForPywebview();
  return api.run_first_sync();
}

export async function getSyncResult(): Promise<SyncResponse> {
  const api = await waitForPywebview();
  return api.get_sync_result();
}
