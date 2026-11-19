import type { ObserverTaskItem } from '@/hooks/useSessionObserver';

/** 归一化后属于「已完结」语义的状态集合（覆盖前后端及历史笔记中的常见写法）。 */
const COMPLETED_STATUS_EXACT = new Set([
  'done',
  'completed',
  'complete',
  'finished',
  'closed',
  'resolved',
  'archived',
  '已办结',
  '已完成',
  '已完结',
  '已收口',
  '已归档',
  '完结',
  '完成',
]);

const COMPLETED_STATUS_MARKERS = ['✅', '已完成', '已完结', '已办结', '已收口', '已归档'];

/** 判断某条事项是否已完结（仅用于前端展示折叠，绝不改动底层任务数据）。 */
export function isCompletedWatcherTask(
  task: Pick<ObserverTaskItem, 'status'> | { status?: string | null }
): boolean {
  const raw = typeof task?.status === 'string' ? task.status.trim() : '';
  if (!raw) return false;
  const lower = raw.toLowerCase();
  if (COMPLETED_STATUS_EXACT.has(lower) || COMPLETED_STATUS_EXACT.has(raw)) {
    return true;
  }
  return COMPLETED_STATUS_MARKERS.some((marker) => raw.includes(marker));
}

export interface TasksOverviewPartition {
  /** 是否满足长列表自动折叠条件（有可折叠的历史完结行）。 */
  canCollapse: boolean;
  /** 默认状态下被自动折叠隐藏的已完结 Tx 行（按原序）。 */
  hiddenCompletedTasks: ObserverTaskItem[];
  /** 默认状态下始终保持可见的行（进行中/待拍板/阻塞，或全完结时的保底最新行）。 */
  visibleTasks: ObserverTaskItem[];
  /** 用于渐变区域展示的「最近一条被折叠旧 Tx」，直观提示上方仍有历史完结行。 */
  peekTask: ObserverTaskItem | null;
  /** 被折叠项的编号范围摘要，例如 `T1–T5` 或 `T1、T3`。 */
  hiddenIdSummary: string;
}

/** 生成折叠编号摘要（连续 `T1..T5` 收成 `T1–T5`，离散超过 3 个收成 `T1…T7`）。 */
export function formatCollapsedTaskIdsSummary(tasks: readonly ObserverTaskItem[]): string {
  const ids = tasks.map((t) => (typeof t.id === 'string' ? t.id.trim() : '')).filter(Boolean);
  if (ids.length === 0) return '';
  if (ids.length === 1) return ids[0];

  const nums = ids.map((id) => {
    const match = /^T(\d+)$/i.exec(id);
    return match ? Number.parseInt(match[1], 10) : null;
  });
  const allSequential =
    nums.every((n): n is number => n !== null) &&
    nums.every((n, i) => i === 0 || n === nums[i - 1] + 1);
  if (allSequential) {
    return `${ids[0]}–${ids[ids.length - 1]}`;
  }
  if (ids.length <= 3) {
    return ids.join('、');
  }
  return `${ids[0]} … ${ids[ids.length - 1]}`;
}

/** 全表均已完结时，保底保留可见的最近完结事项条数，避免表格空壳化。 */
const ALL_DONE_KEEP_RECENT = 2;

/**
 * 将「事项总控表 · Tasks Overview」拆分为「折叠的已完结旧 Tx」与「主显行」。
 *
 * 触发规则：
 * 1. 当存在活跃/未完结事项（在办 / 待拍板 / 阻塞）时：
 *    - 只要已完结事项 >= 2 条，或总行数 >= 4 且至少有 1 条已完结事项，即自动折叠全部已完结行。
 * 2. 当全表所有事项均已完结时：
 *    - 若总行数 >= 4，保留最近 2 条完结行直接可见，折叠更早的完结行；
 *    - 若总行数 <= 3，短表直接完整展示，避免无意义折叠。
 */
export function partitionTasksForOverview(
  tasks: readonly ObserverTaskItem[]
): TasksOverviewPartition {
  if (!tasks.length) {
    return {
      canCollapse: false,
      hiddenCompletedTasks: [],
      visibleTasks: [],
      peekTask: null,
      hiddenIdSummary: '',
    };
  }

  const completed: ObserverTaskItem[] = [];
  const active: ObserverTaskItem[] = [];
  for (const task of tasks) {
    if (isCompletedWatcherTask(task)) {
      completed.push(task);
    } else {
      active.push(task);
    }
  }

  if (completed.length === 0) {
    return {
      canCollapse: false,
      hiddenCompletedTasks: [],
      visibleTasks: [...tasks],
      peekTask: null,
      hiddenIdSummary: '',
    };
  }

  let hiddenCompletedTasks: ObserverTaskItem[] = [];
  let visibleTasks: ObserverTaskItem[] = [];

  if (active.length > 0) {
    const shouldFold = completed.length >= 2 || tasks.length >= 4;
    if (!shouldFold) {
      return {
        canCollapse: false,
        hiddenCompletedTasks: [],
        visibleTasks: [...tasks],
        peekTask: null,
        hiddenIdSummary: '',
      };
    }
    hiddenCompletedTasks = completed;
    visibleTasks = active;
  } else {
    if (tasks.length < 4 || completed.length <= ALL_DONE_KEEP_RECENT) {
      return {
        canCollapse: false,
        hiddenCompletedTasks: [],
        visibleTasks: [...tasks],
        peekTask: null,
        hiddenIdSummary: '',
      };
    }
    const splitAt = completed.length - ALL_DONE_KEEP_RECENT;
    hiddenCompletedTasks = completed.slice(0, splitAt);
    visibleTasks = completed.slice(splitAt);
  }

  const peekTask = hiddenCompletedTasks[hiddenCompletedTasks.length - 1] ?? null;
  return {
    canCollapse: hiddenCompletedTasks.length > 0,
    hiddenCompletedTasks,
    visibleTasks,
    peekTask,
    hiddenIdSummary: formatCollapsedTaskIdsSummary(hiddenCompletedTasks),
  };
}
