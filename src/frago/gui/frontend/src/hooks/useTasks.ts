import { useCallback } from 'react';
import { useAppStore } from '@/stores/appStore';
import { usePolling } from './usePolling';

/**
 * 任务 Hook
 *
 * 提供任务列表轮询和任务详情加载
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

  // 仅在任务列表页面时启用轮询
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
