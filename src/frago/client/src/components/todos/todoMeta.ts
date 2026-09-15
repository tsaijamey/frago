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

// ── 分类 ────────────────────────────────────────────────────────────────

/** 与存储层同一个上限。界面先挡一道，免得人填满 21 行才被服务端退回。 */
export const MAX_CATEGORIES = 20;

/** 「未分类」的保留字，与命令行 `--category none` 同一个词。 */
export const UNCATEGORIZED = 'none';

/** 分类筛选：`all` 不筛，`none` 只看未分类，其余是分类 id。 */
export type CategoryFilter = string;

/**
 * 这件事务落在哪个分类上；未分类或引用了已删分类的都答 null。
 *
 * 已删分类的 id 还留在事务文件里，但排序已经把它当未分类排了——显示若还挂着旧名字，
 * 人会以为它排错了位置。
 */
export function effectiveCategory(
  category: string | null,
  categories: { id: string }[]
): string | null {
  return category && categories.some((c) => c.id === category) ? category : null;
}

export function matchesCategory(
  category: string | null,
  filter: CategoryFilter,
  categories: { id: string }[]
): boolean {
  if (filter === 'all') return true;
  const effective = effectiveCategory(category, categories);
  return filter === UNCATEGORIZED ? effective === null : effective === filter;
}

/**
 * 按状态重算一份计数表，形状与服务端的 `counts` 一致。
 *
 * 状态和分类两排筛选，各自的计数都在「对方筛过、自己没筛」的样本上算：选了「工作」
 * 之后状态那排报的是工作里各档几件；来回点状态，状态那排的数不跳。
 */
export function countStatuses(todos: { status: TodoStatus }[]): Record<string, number> {
  const counts: Record<string, number> = { all: todos.length, todo: 0, doing: 0, done: 0, dropped: 0 };
  for (const todo of todos) counts[todo.status] = (counts[todo.status] ?? 0) + 1;
  return counts;
}

/** 编辑分类清单时的一行。`isNew` 的那行 id 还能改，已有的 id 锁死——事务引用的就是它。 */
export interface CategoryDraft {
  /** 只给 React 认行用。新加的行 id 还没填，挪动时不能拿 id 或下标当 key。 */
  key: string;
  id: string;
  name: string;
  isNew: boolean;
}

const CATEGORY_ID_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

export type CategoryDraftError = 'tooMany' | 'emptyName' | 'badId' | 'reservedId' | 'duplicateId';

/** 与存储层 `categories.validate` 同一套规矩；返回第一处问题和它在第几行。 */
export function validateCategoryDraft(
  rows: CategoryDraft[]
): { error: CategoryDraftError; index: number } | null {
  if (rows.length > MAX_CATEGORIES) return { error: 'tooMany', index: MAX_CATEGORIES };
  const seen = new Set<string>();
  for (let i = 0; i < rows.length; i++) {
    const id = rows[i].id.trim();
    if (id === UNCATEGORIZED) return { error: 'reservedId', index: i };
    if (!CATEGORY_ID_RE.test(id)) return { error: 'badId', index: i };
    if (seen.has(id)) return { error: 'duplicateId', index: i };
    if (!rows[i].name.trim()) return { error: 'emptyName', index: i };
    seen.add(id);
  }
  return null;
}

/** 把第 index 行往上（-1）或往下（+1）挪一格；到头了原样返回。 */
export function moveRow<T>(rows: T[], index: number, delta: -1 | 1): T[] {
  const target = index + delta;
  if (target < 0 || target >= rows.length) return rows;
  const next = rows.slice();
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
