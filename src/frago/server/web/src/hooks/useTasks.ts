import { useCallback } from 'react';
import { useAppStore } from '@/stores/appStore';
import { usePolling } from './usePolling';

/**
 * Tasks Hook
 *
 * Provides task list polling and task detail loading
 */
export function useTasks(pollingInterval: number = 3000) {
  const {
    tasks,
    taskDetail,
    isLoading,
    loadTasks,
    openTaskDetail,
    currentPage,
  } = useAppStore();

  // Enable polling only on the task list page
  const enabled = currentPage === 'tasks';

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
