/**
 * pywebview API Wrapper
 *
 * Provides type-safe API calls and pywebview ready state detection
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
  RepoVisibilityResponse,
  ListReposResponse,
  SelectRepoResponse,
  TutorialResponse,
} from '@/types/pywebview.d';

// Wait for pywebview ready
let readyPromise: Promise<PyWebviewApi> | null = null;

// Check if API is fully ready (methods injected)
function isApiFullyReady(): boolean {
  const api = window.pywebview?.api;
  // Check if key methods exist
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

    // Check immediately
    if (checkAndResolve()) return;

    // Poll check (pywebview method injection may be delayed)
    const pollInterval = setInterval(() => {
      if (checkAndResolve()) {
        clearInterval(pollInterval);
      }
    }, 50);

    // Also listen to pywebviewready event
    const handleReady = () => {
      console.log('[pywebview] pywebviewready event fired');
      // Need to poll after event because methods may not be injected yet
      setTimeout(() => {
        if (checkAndResolve()) {
          clearInterval(pollInterval);
        }
      }, 100);
      window.removeEventListener('pywebviewready', handleReady);
    };

    window.addEventListener('pywebviewready', handleReady);

    // Timeout protection (10 seconds)
    setTimeout(() => {
      clearInterval(pollInterval);
      if (!isApiFullyReady()) {
        console.error('[pywebview] API not ready after 10s timeout');
      }
    }, 10000);
  });

  return readyPromise;
}

// Get API (may be undefined)
export function getApi(): PyWebviewApi | undefined {
  return window.pywebview?.api;
}

// Check if API is ready (methods injected)
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
  // pywebview requires explicit parameters, do not pass undefined
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

export async function openPath(
  path: string,
  reveal: boolean = false
): Promise<ApiResponse> {
  const api = await waitForPywebview();
  return api.open_path(path, reveal);
}

// ============================================================
// Settings API - Main Config Management
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
// Settings API - Environment Variables Management
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
// Settings API - GitHub Integration
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

export async function checkSyncRepoVisibility(): Promise<RepoVisibilityResponse> {
  const api = await waitForPywebview();
  return api.check_sync_repo_visibility();
}

export async function listUserRepos(limit?: number): Promise<ListReposResponse> {
  const api = await waitForPywebview();
  return api.list_user_repos(limit);
}

export async function selectExistingRepo(sshUrl: string): Promise<SelectRepoResponse> {
  const api = await waitForPywebview();
  return api.select_existing_repo(sshUrl);
}

// ============================================================
// Tutorial API
// ============================================================

export async function openTutorial(
  tutorialId: string,
  lang: string = 'auto',
  anchor: string = ''
): Promise<TutorialResponse> {
  const api = await waitForPywebview();
  return api.open_tutorial(tutorialId, lang, anchor);
}
