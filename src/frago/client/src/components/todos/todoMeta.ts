/**
 * 事务的状态与优先级各自配一套观感。
 *
 * 单独拎出来是因为清单和详情两处都要用同一套：两边各配一套颜色的话，同一件事务
 * 在清单里是黄的、点进去变成绿的，人会以为点错了。
 */

import type { TodoPriority, TodoStatus } from '@/api';

export interface Tone {
  className: string;
}

export const STATUS_TONE: Record<TodoStatus, Tone> = {
  // 在做的最扎眼——它是"现在正在发生"的那一件。
  doing: { className: 'td-chip--doing' },
  todo: { className: 'td-chip--todo' },
  done: { className: 'td-chip--done' },
  dropped: { className: 'td-chip--dropped' },
};

export const PRIORITY_TONE: Record<TodoPriority, Tone> = {
  high: { className: 'td-chip--high' },
  normal: { className: 'td-chip--normal' },
  low: { className: 'td-chip--low' },
};

/** 状态筛选那一排。`active` 不是存储层的档位，是「还没了结的」——待办加在做。 */
export type StatusFilter = 'active' | TodoStatus | 'all';

export const STATUS_FILTERS: StatusFilter[] = ['active', 'todo', 'doing', 'done', 'dropped', 'all'];

/**
 * 某一档该显示几件。
 *
 * `active` 与 `all` 在服务端的计数表里没有自己的条目，这里由已有的档位加出来——
 * 加法在这一处做完，清单和筛选条不会各算各的。
 */
export function countFor(filter: StatusFilter, counts: Record<string, number>): number {
  if (filter === 'all') return counts.all ?? 0;
  if (filter === 'active') return (counts.todo ?? 0) + (counts.doing ?? 0);
  return counts[filter] ?? 0;
}

/** 这一档收哪些事务。 */
export function matchesFilter(status: TodoStatus, filter: StatusFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'active') return status === 'todo' || status === 'doing';
  return status === filter;
}
