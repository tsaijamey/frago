import { describe, expect, it } from 'vitest';
import type { TodoPriority } from '@/api';
import {
  MAX_CATEGORIES,
  countStatuses,
  effectiveCategory,
  formatRowDate,
  groupTodos,
  matchesCategory,
  moveRow,
  validateCategoryDraft,
  type CategoryDraft,
} from '@/components/todos/todoMeta';

const cats = [{ id: 'family' }, { id: 'work' }];

const row = (id: string, name = id): CategoryDraft => ({ key: id, id, name, isNew: false });

describe('todo categories', () => {
  it('treats a removed category id as uncategorized', () => {
    expect(effectiveCategory('work', cats)).toBe('work');
    expect(effectiveCategory('hobby', cats)).toBeNull();
    expect(effectiveCategory(null, cats)).toBeNull();
  });

  it('filters by category, with none catching orphans', () => {
    expect(matchesCategory('work', 'all', cats)).toBe(true);
    expect(matchesCategory('work', 'work', cats)).toBe(true);
    expect(matchesCategory('work', 'family', cats)).toBe(false);
    expect(matchesCategory('hobby', 'none', cats)).toBe(true);
    expect(matchesCategory(null, 'none', cats)).toBe(true);
    expect(matchesCategory('work', 'none', cats)).toBe(false);
  });

  it('counts statuses in the same shape as the server', () => {
    expect(countStatuses([{ status: 'todo' }, { status: 'done' }, { status: 'todo' }])).toEqual({
      all: 3,
      todo: 2,
      doing: 0,
      done: 1,
      dropped: 0,
    });
  });

  it('moves rows and stops at the ends', () => {
    const rows = ['a', 'b', 'c'];
    expect(moveRow(rows, 1, -1)).toEqual(['b', 'a', 'c']);
    expect(moveRow(rows, 2, 1)).toBe(rows);
    expect(moveRow(rows, 0, -1)).toBe(rows);
  });

  it('validates the draft like the store does', () => {
    expect(validateCategoryDraft([row('family', '家庭'), row('work', '工作')])).toBeNull();
    expect(validateCategoryDraft([row('a'), row('a')])).toEqual({ error: 'duplicateId', index: 1 });
    expect(validateCategoryDraft([row('Bad Id')])).toEqual({ error: 'badId', index: 0 });
    expect(validateCategoryDraft([row('none')])).toEqual({ error: 'reservedId', index: 0 });
    expect(validateCategoryDraft([row('a', '  ')])).toEqual({ error: 'emptyName', index: 0 });
    const many = Array.from({ length: MAX_CATEGORIES + 1 }, (_, i) => row(`c${i}`));
    expect(validateCategoryDraft(many)?.error).toBe('tooMany');
  });
});

describe('todo sections', () => {
  const named = [
    { id: 'family', name: '家庭' },
    { id: 'work', name: '工作' },
  ];
  const todo = (id: string, category: string | null, priority: TodoPriority) => ({ id, category, priority });

  it('cuts groups by category and sections by priority without reordering', () => {
    const input = [
      todo('a', 'family', 'high'),
      todo('b', 'family', 'high'),
      todo('c', 'family', 'normal'),
      todo('d', 'family', 'low'),
      todo('e', 'work', 'normal'),
      todo('f', 'hobby', 'high'),
      todo('g', null, 'low'),
    ];
    const groups = groupTodos(input, named, '未分类');

    expect(groups.map((g) => [g.id, g.name, g.count])).toEqual([
      ['family', '家庭', 4],
      ['work', '工作', 1],
      ['none', '未分类', 2],
    ]);
    expect(groups[0].sections.map((s) => [s.priority, s.todos.map((t) => t.id)])).toEqual([
      ['high', ['a', 'b']],
      ['normal', ['c']],
      ['low', ['d']],
    ]);
    // 删掉的分类 hobby 落进未分类，和真未分类的并成一组
    expect(groups[2].sections.map((s) => s.priority)).toEqual(['high', 'low']);
    // 只切不排：拍平后与输入同序
    expect(groups.flatMap((g) => g.sections.flatMap((s) => s.todos))).toEqual(input);
    for (const g of groups) expect(g.count).toBe(g.sections.reduce((n, s) => n + s.todos.length, 0));
  });

  it('emits no groups for an empty list', () => {
    expect(groupTodos([], named, '未分类')).toEqual([]);
  });

  it('shortens the date only within the current year', () => {
    const today = new Date(2026, 8, 24);
    expect(formatRowDate('2026-08-31', today)).toBe('08-31');
    expect(formatRowDate('2025-12-30', today)).toBe('2025-12-30');
  });
});
