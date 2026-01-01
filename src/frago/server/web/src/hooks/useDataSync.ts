/**
 * Data Sync Hook
 *
 * Handles WebSocket data push for real-time updates.
 * Receives initial data on connect and incremental updates thereafter.
 */

import { useCallback } from 'react';
import { useWebSocket } from './useWebSocket';
import { MessageType, type WebSocketMessage } from '@/api/websocket';
import { useAppStore } from '@/stores/appStore';
import type { TaskItem, RecipeItem, SkillItem, CommunityRecipeItem } from '@/types/pywebview';

/**
 * Raw task data from WebSocket (matches backend TaskService format)
 */
interface RawTaskData {
  id: string;
  title: string;
  status: string;
  project_path?: string | null;
  agent_type?: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  step_count?: number;
  tool_call_count?: number;
  source?: string;
}

/**
 * Raw recipe data from WebSocket (matches backend RecipeService format)
 */
interface RawRecipeData {
  name: string;
  description?: string | null;
  category?: string;
  icon?: string | null;
  tags?: string[];
  path?: string | null;
  source?: string | null;
  runtime?: string | null;
}

/**
 * Raw skill data from WebSocket (matches backend SkillService format)
 */
interface RawSkillData {
  name: string;
  description?: string | null;
  icon?: string | null;
  file_path?: string;
}

/**
 * Raw community recipe data from WebSocket
 */
interface RawCommunityRecipeData {
  name: string;
  url: string;
  description?: string | null;
  version?: string | null;
  type?: string;
  runtime?: string | null;
  tags?: string[];
  installed?: boolean;
  installed_version?: string | null;
  has_update?: boolean;
}

/**
 * Transform raw task data from WebSocket to frontend TaskItem format.
 * This mirrors the transformation done in api/index.ts getTasks().
 */
function transformTaskData(raw: RawTaskData): TaskItem {
  return {
    session_id: raw.id,
    name: raw.title,
    status: raw.status as TaskItem['status'],
    started_at: raw.started_at || '',
    ended_at: raw.completed_at || null,
    duration_ms: raw.duration_ms ?? 0,
    step_count: raw.step_count ?? 0,
    tool_call_count: raw.tool_call_count ?? 0,
    last_activity: raw.started_at || '',
    project_path: raw.project_path ?? '',
    source: (raw.source ?? 'unknown') as TaskItem['source'],
  };
}

/**
 * Transform raw recipe data from WebSocket to frontend RecipeItem format.
 * This mirrors the transformation done in api/index.ts getRecipes().
 */
function transformRecipeData(raw: RawRecipeData): RecipeItem {
  return {
    name: raw.name,
    description: raw.description ?? null,
    category: (raw.category ?? 'atomic') as RecipeItem['category'],
    icon: raw.icon ?? null,
    tags: raw.tags ?? [],
    path: raw.path ?? null,
    source: (raw.source ?? null) as RecipeItem['source'],
    runtime: (raw.runtime ?? null) as RecipeItem['runtime'],
  };
}

/**
 * Transform raw skill data from WebSocket to frontend SkillItem format.
 * This mirrors the transformation done in api/index.ts getSkills().
 */
function transformSkillData(raw: RawSkillData): SkillItem {
  return {
    name: raw.name,
    description: raw.description ?? null,
    icon: raw.icon ?? null,
    file_path: raw.file_path ?? '',
  };
}

/**
 * Transform raw community recipe data from WebSocket to frontend format.
 */
function transformCommunityRecipeData(raw: RawCommunityRecipeData): CommunityRecipeItem {
  return {
    name: raw.name,
    url: raw.url,
    description: raw.description ?? null,
    version: raw.version ?? null,
    type: (raw.type ?? 'atomic') as CommunityRecipeItem['type'],
    runtime: raw.runtime ?? null,
    tags: raw.tags ?? [],
    installed: raw.installed ?? false,
    installed_version: raw.installed_version ?? null,
    has_update: raw.has_update ?? false,
  };
}

/**
 * Hook for handling WebSocket data synchronization.
 *
 * This hook:
 * 1. Receives initial data bundle on WebSocket connect
 * 2. Handles incremental updates (tasks, recipes, skills)
 * 3. Updates the global store with pushed data
 */
export function useDataSync() {
  const setDataFromPush = useAppStore((state) => state.setDataFromPush);
  const setTasks = useAppStore((state) => state.setTasks);
  const setRecipes = useAppStore((state) => state.setRecipes);
  const setSkills = useAppStore((state) => state.setSkills);
  const setCommunityRecipes = useAppStore((state) => state.setCommunityRecipes);

  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
      switch (message.type) {
        case MessageType.DATA_INITIAL: {
          // Full data bundle on connect
          const data = message.data as {
            version?: number;
            tasks?: { tasks: RawTaskData[]; total: number };
            recipes?: RawRecipeData[];
            skills?: RawSkillData[];
            community_recipes?: RawCommunityRecipeData[];
          };
          console.log('[useDataSync] Received initial data, version:', data?.version);
          if (data) {
            // Transform all data from raw backend format to frontend format
            const transformedTasks = data.tasks ? {
              tasks: data.tasks.tasks.map(transformTaskData),
              total: data.tasks.total,
            } : undefined;

            const transformedRecipes = data.recipes
              ? data.recipes.map(transformRecipeData)
              : undefined;

            const transformedSkills = data.skills
              ? data.skills.map(transformSkillData)
              : undefined;

            const transformedCommunityRecipes = data.community_recipes
              ? data.community_recipes.map(transformCommunityRecipeData)
              : undefined;

            setDataFromPush({
              version: data.version,
              tasks: transformedTasks,
              recipes: transformedRecipes,
              skills: transformedSkills,
              communityRecipes: transformedCommunityRecipes,
            });
          }
          break;
        }

        case MessageType.DATA_TASKS: {
          // Tasks list updated
          const data = message.data as {
            version?: number;
            data?: { tasks: RawTaskData[]; total: number };
          };
          console.log('[useDataSync] Received tasks update');
          if (data?.data?.tasks) {
            // Transform tasks from raw backend format to frontend format
            const transformedTasks = {
              tasks: data.data.tasks.map(transformTaskData),
              total: data.data.total,
            };

            setDataFromPush({
              version: data.version,
              tasks: transformedTasks,
            });
          }
          break;
        }

        case MessageType.DATA_DASHBOARD: {
          // Dashboard updated - we don't store dashboard in appStore currently
          // Could be extended to store dashboard data if needed
          console.log('[useDataSync] Received dashboard update');
          break;
        }

        case MessageType.DATA_RECIPES: {
          // Recipes list updated
          const data = message.data as {
            version?: number;
            data?: RawRecipeData[];
          };
          console.log('[useDataSync] Received recipes update');
          if (data?.data) {
            const transformedRecipes = data.data.map(transformRecipeData);
            setRecipes(transformedRecipes);
          }
          break;
        }

        case MessageType.DATA_SKILLS: {
          // Skills list updated
          const data = message.data as {
            version?: number;
            data?: RawSkillData[];
          };
          console.log('[useDataSync] Received skills update');
          if (data?.data) {
            const transformedSkills = data.data.map(transformSkillData);
            setSkills(transformedSkills);
          }
          break;
        }

        case MessageType.DATA_COMMUNITY_RECIPES: {
          // Community recipes updated
          const data = message.data as {
            data?: RawCommunityRecipeData[];
            error?: string | null;
          };
          console.log('[useDataSync] Received community recipes update');
          if (data?.data) {
            const transformedRecipes = data.data.map(transformCommunityRecipeData);
            setCommunityRecipes(transformedRecipes);
          }
          break;
        }
      }
    },
    [setDataFromPush, setTasks, setRecipes, setSkills, setCommunityRecipes]
  );

  // Subscribe to data push messages
  const { isConnected } = useWebSocket({
    messageTypes: [
      MessageType.DATA_INITIAL,
      MessageType.DATA_TASKS,
      MessageType.DATA_DASHBOARD,
      MessageType.DATA_RECIPES,
      MessageType.DATA_SKILLS,
      MessageType.DATA_COMMUNITY_RECIPES,
    ],
    onMessage: handleMessage,
  });

  return { isConnected };
}

/**
 * Hook to check if data has been initialized via WebSocket
 */
export function useDataInitialized(): boolean {
  return useAppStore((state) => state.dataInitialized);
}
