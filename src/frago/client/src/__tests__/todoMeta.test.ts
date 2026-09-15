import { describe, expect, it } from 'vitest';
import {
  MAX_CATEGORIES,
  countStatuses,
  effectiveCategory,
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
