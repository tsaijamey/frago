/**
 * DirectiveMenu — 会话输入框内 `/`（Skill）与 `@`（Employee）共用的指令候选浮层与触发解析器。
 *
 * 所有会话输入框（NewSessionModal、Session Detail Composer、SelectionQuote 分支/暂存浮窗）
 * 均通过 PromptComposerBox 复用本组件：
 * - 统一触发判定：`directiveQuery` 同时识别行首或空白后的 `/query` 与 `@query`；
 * - 统一候选列表渲染、键盘上下移动、Enter/Tab 挑中、Esc 收起、鼠标悬停与落点方向（above/below）。
 */

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { EmployeeItem, SkillItem } from '@/types/api';
import { truncateChars } from '@/utils/skillBlocks';

export const SKILL_MENU_DESC_CHARS = 60;
export const EMPLOYEE_MENU_DESC_CHARS = 60;

export type DirectiveTrigger = '/' | '@';

export interface DirectiveMatch {
  trigger: DirectiveTrigger;
  start: number;
  query: string;
}

/**
 * 光标前是不是正在敲一条 `/`（skill）或 `@`（employee）指令。
 *
 * 只认「行首或空白后面紧跟着 `/` 或 `@`，且到光标之间没有空白、也没有再次出现 `/` 或 `@`」——
 * 这样敲路径 `src/frago` 或邮箱 `a@b.com` 时不会误弹菜单。
 */
export function directiveQuery(text: string, caret: number = text.length): DirectiveMatch | null {
  const before = text.slice(0, caret);
  const hit = /(^|\s)([/@])([^\s/@]*)$/.exec(before);
  if (!hit) return null;
  const trigger = hit[2] as DirectiveTrigger;
  const start = hit.index + hit[1].length;
  return { trigger, start, query: hit[3] };
}

/** 光标前是不是正在敲 `/skill` 指令（基于统一 `directiveQuery` 派生）。 */
export function slashQuery(
  text: string,
  caret: number = text.length
): { start: number; query: string } | null {
  const hit = directiveQuery(text, caret);
  if (!hit || hit.trigger !== '/') return null;
  return { start: hit.start, query: hit.query };
}

/** 光标前是不是正在敲 `@employee` 指令（基于统一 `directiveQuery` 派生）。 */
export function mentionQuery(
  text: string,
  caret: number = text.length
): { start: number; query: string } | null {
  const hit = directiveQuery(text, caret);
  if (!hit || hit.trigger !== '@') return null;
  return { start: hit.start, query: hit.query };
}

export function truncateDirectiveDesc(text: string, max = SKILL_MENU_DESC_CHARS): string {
  return truncateChars(text, max);
}

/**
 * 按名字和说明筛选 `/` skill 清单：
 * 名字前缀命中的排最前（rank 0），其次是冒号后短名前缀命中（rank 1），
 * 再次是名字包含（rank 2），最后是说明包含（rank 3）。
 */
export function filterSkills(skills: SkillItem[], query: string): SkillItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...skills].sort((a, b) => a.name.localeCompare(b.name));

  const scored: { item: SkillItem; rank: number }[] = [];
  for (const item of skills) {
    const name = item.name.toLowerCase();
    const colon = name.indexOf(':');
    const tail = colon >= 0 ? name.slice(colon + 1) : '';
    const desc = (item.description || '').toLowerCase();
    let rank = -1;
    if (name.startsWith(q)) rank = 0;
    else if (tail && tail.startsWith(q)) rank = 1;
    else if (name.includes(q)) rank = 2;
    else if (desc.includes(q)) rank = 3;
    if (rank >= 0) scored.push({ item, rank });
  }
  return scored
    .sort((a, b) => a.rank - b.rank || a.item.name.localeCompare(b.item.name))
    .map((s) => s.item);
}

/**
 * 按岗位编号、名称、职责说明筛选 `@` employee 清单：
 * 编号或名称前缀命中的排最前，其次是编号或名称包含，最后是职责说明或内核名包含。
 */
export function filterEmployees(employees: EmployeeItem[], query: string): EmployeeItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...employees];

  const scored: { item: EmployeeItem; rank: number }[] = [];
  for (const item of employees) {
    const id = item.member_post_id.toLowerCase();
    const title = (item.title || '').toLowerCase();
    const scope = (item.work_scope || item.description || '').toLowerCase();
    const kernel = (item.agent_kernel || '').toLowerCase();
    if (id.startsWith(q) || title.startsWith(q)) {
      scored.push({ item, rank: 0 });
    } else if (id.includes(q) || title.includes(q)) {
      scored.push({ item, rank: 1 });
    } else if (scope.includes(q) || kernel.includes(q)) {
      scored.push({ item, rank: 2 });
    }
  }
  return scored.sort((a, b) => a.rank - b.rank).map((s) => s.item);
}

export interface DirectiveMenuEntry<T = unknown> {
  key: string;
  trigger: DirectiveTrigger;
  name: string;
  title?: string | null;
  badge?: string | null;
  description?: string | null;
  raw: T;
}

export interface DirectiveMenuProps<T = unknown> {
  trigger: DirectiveTrigger;
  entries: DirectiveMenuEntry<T>[];
  activeIndex: number;
  placement?: 'above' | 'below';
  titleText?: string;
  testId: string;
  itemTestId: string;
  emptyTestId: string;
  emptyText: string;
  onSelect: (entry: DirectiveMenuEntry<T>) => void;
  onHover: (index: number) => void;
}

export default function DirectiveMenu<T = unknown>({
  trigger,
  entries,
  activeIndex,
  placement = 'above',
  titleText,
  testId,
  itemTestId,
  emptyTestId,
  emptyText,
  onSelect,
  onHover,
}: DirectiveMenuProps<T>) {
  const { t } = useTranslation();
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list || typeof list.querySelector !== 'function') return;
    const row = list.querySelector<HTMLElement>(`[data-idx="${activeIndex}"]`);
    if (row && typeof row.scrollIntoView === 'function') {
      row.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  const positionClass =
    placement === 'below' ? 'top-full mt-1.5' : 'bottom-full mb-1.5';

  if (entries.length === 0) {
    return (
      <div
        data-testid={emptyTestId}
        data-directive-trigger={trigger}
        className={`absolute inset-x-0 z-20 rounded-[10px] border border-border-color bg-bg-primary px-3 py-2 text-[12px] text-text-muted shadow-md ${positionClass}`}
      >
        {emptyText || t('workbench.skills.noMatch')}
      </div>
    );
  }

  return (
    <div
      ref={listRef}
      role="listbox"
      aria-label={titleText || (trigger === '@' ? t('workbench.employees.menuTitle') : t('workbench.skills.menuTitle'))}
      data-testid={testId}
      data-directive-trigger={trigger}
      className={`absolute inset-x-0 z-20 max-h-60 overflow-y-auto rounded-[10px] border border-border-color bg-bg-primary py-1 shadow-md ${positionClass}`}
    >
      {titleText ? (
        <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-text-dim">
          {titleText}
        </div>
      ) : null}
      {entries.map((entry, idx) => {
        const active = idx === activeIndex;
        const desc = entry.description ? truncateDirectiveDesc(entry.description) : '';
        return (
          <button
            key={entry.key}
            type="button"
            role="option"
            aria-selected={active}
            data-idx={idx}
            data-testid={itemTestId}
            data-skill={trigger === '/' ? entry.key : undefined}
            data-employee={trigger === '@' ? entry.key : undefined}
            data-directive-key={entry.key}
            onMouseEnter={() => onHover(idx)}
            onMouseDown={(e) => {
              // 留住输入框的焦点，别让失焦先一步关掉菜单。
              e.preventDefault();
              onSelect(entry);
            }}
            className={`flex w-full items-baseline gap-2.5 px-3 py-1.5 text-left text-[12px] transition-colors ${
              active ? 'bg-bg-hover text-text-primary' : 'text-text-secondary hover:bg-bg-subtle'
            }`}
          >
            <span className="shrink-0 font-mono text-[12px] font-medium text-text-primary">
              <span className="text-text-muted">{entry.trigger}</span>
              {entry.name}
            </span>
            {entry.title && entry.title !== entry.name && (
              <span className="shrink-0 font-medium text-text-primary">{entry.title}</span>
            )}
            {entry.badge && (
              <span className="shrink-0 rounded bg-bg-secondary px-1.5 py-0.5 font-mono text-[10px] uppercase text-text-muted">
                {entry.badge}
              </span>
            )}
            {desc ? (
              <span className="min-w-0 flex-1 truncate text-[11px] text-text-muted">{desc}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
