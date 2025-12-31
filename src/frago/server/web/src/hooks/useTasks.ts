import { useCallback } from 'react';
import { useAppStore } from '@/stores/appStore';
import { usePolling } from './usePolling';

/**
 * Tasks Hook
 *
 * Provides task list polling and task detail loading.
 * Note: Primary data updates come via WebSocket (useDataSync).
 * Polling is kept as a fallback with reduced frequency (30s).
 */
export function useTasks(pollingInterval: number = 30000) {
  const {
    tasks,
    taskDetail,
    isLoading,
    loadTasks,
    openTaskDetail,
    currentPage,
    dataInitialized,
  } = useAppStore();

  // Enable polling only on the task list page, and reduce frequency if data is already synced
  const enabled = currentPage === 'tasks' && !dataInitialized;

  const { trigger: refresh } = usePolling(loadTasks, pollingInterval, enabled);

  const viewDetail = useCallback(
    (sessionId: string) => {
      openTaskDetail(sessionId);
    },
    [openTaskDetail]
  );

  return {
    tasks,
    taskDetail,
    isLoading,
    refresh,
    viewDetail,
  };
}
