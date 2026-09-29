/**
 * 配方卡底那一行的取数：守的是「标识名与来源不上卡、空运行时不占位、标签截到 3 个、
 * 两种类型各有文案」这几条，不是具体长什么样。
 */

import { describe, expect, it } from 'vitest';
import type { RecipeItem } from '@/types/pywebview';
import { CARD_TAG_LIMIT, recipeCardMeta } from '../recipeMeta';

const t = (key: string) => ({ 'recipes.workflow': 'Workflow', 'recipes.atomic': 'Atomic' })[key] ?? key;

const recipe = (over: Partial<RecipeItem> = {}): RecipeItem => ({
  name: 'cdp_list_tabs_and_select_target',
  description: 'List tabs',
  category: 'atomic',
  icon: null,
  tags: ['chrome', 'cdp', 'tabs', 'debug'],
  path: null,
  source: 'User',
  runtime: 'python',
  ...over,
});

describe('recipeCardMeta', () => {
  it('不带出标识名与来源', () => {
    const meta = recipeCardMeta(recipe(), t);
    const text = JSON.stringify(meta);
    expect(text).not.toContain('cdp_list_tabs_and_select_target');
    expect(text).not.toContain('User');
    expect(Object.keys(meta).sort()).toEqual(['kindLabel', 'runtime', 'tags']);
  });

  it('没有运行时时这一项是 null，不产出空串', () => {
    expect(recipeCardMeta(recipe({ runtime: null }), t).runtime).toBeNull();
  });

  it('标签至多 3 个，按原顺序取前几个', () => {
    const meta = recipeCardMeta(recipe(), t);
    expect(CARD_TAG_LIMIT).toBe(3);
    expect(meta.tags).toEqual(['chrome', 'cdp', 'tabs']);
    expect(recipeCardMeta(recipe({ tags: [] }), t).tags).toEqual([]);
  });

  it('两种类型各给各的文案', () => {
    expect(recipeCardMeta(recipe({ category: 'workflow' }), t).kindLabel).toBe('Workflow');
    expect(recipeCardMeta(recipe({ category: 'atomic' }), t).kindLabel).toBe('Atomic');
  });
});
