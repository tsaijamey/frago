/**
 * Sidebar 十入口基线测试：
 * - 固定 10 个常驻一级入口（Sessions / Desktop / Pairs / Employees / Recipes / Todos / Schedules / Data / Files / Settings）
 * - 禁止暴露任何已冻结路由（guide / workspace / skills / new / dashboard / tasks / task_detail）
 * - 支持 Recipes 与 Files 下挂载已钉住子项，选中态使用中性样式类 rail-item--active
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import Sidebar, { NAV_ITEMS, isNavItemActive } from '../Sidebar';
import { usePageStore } from '@/stores/pageStore';
import { useRecipeAppPins } from '@/stores/recipeAppPins';
import { useFilePins } from '@/stores/filePins';
import i18n from '@/i18n';

vi.mock('@/hooks/useClaudeUsage', () => ({
  useClaudeUsage: () => null,
}));

vi.mock('@/hooks/useTmuxSessions', () => ({
  useTmuxSessionCount: () => ({ total: 0, totalMemoryMb: 0 }),
}));

vi.mock('@/hooks/useEnvironment', () => ({
  countAttention: () => 0,
  useEnvironment: () => ({ data: null, loading: false, reload: vi.fn() }),
  useEnvironmentUpgrade: () => ({ busy: false, start: vi.fn() }),
}));

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  localStorage.setItem('sidebar-expanded', '1');
  usePageStore.setState({
    currentPage: 'session_workbench',
    currentTaskId: null,
    currentRecipeName: null,
    currentProjectId: null,
    currentTodoId: null,
    currentScheduleId: null,
    currentRecipeAppId: null,
  });
  useRecipeAppPins.setState({ pins: [] });
  useFilePins.setState({ pins: [], activePath: null, pendingTarget: null });
});

describe('Sidebar 十入口基线', () => {
  it('严格暴露 10 个一级入口且不含已冻结路由', () => {
    expect(NAV_ITEMS.map((item) => item.id)).toEqual([
      'session_workbench',
      'desktop',
      'vibe_teaming',
      'employees',
      'recipes',
      'todos',
      'schedules',
      'data_repo',
      'files',
      'settings',
    ]);

    const frozen = ['guide', 'workspace', 'skills', 'new', 'dashboard', 'tasks', 'task_detail'];
    for (const id of frozen) {
      expect(NAV_ITEMS.some((item) => item.id === id)).toBe(false);
    }

    render(<Sidebar />);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    for (const expectedLabel of [
      'Sessions',
      'Desktop',
      'Pairs',
      'Employees',
      'Recipes',
      'Todos',
      'Schedules',
      'Data',
      'Files',
      'Settings',
    ]) {
      expect(nav.textContent).toContain(expectedLabel);
    }
  });

  it('选中态只落中性 rail-item--active，Recipes 下可挂载已钉住应用子项', () => {
    useRecipeAppPins.setState({ pins: ['daily_briefing'] });
    render(<Sidebar />);

    const recipesBtn = screen.getByTitle('Recipes');
    fireEvent.click(recipesBtn);

    expect(usePageStore.getState().currentPage).toBe('recipes');
    expect(recipesBtn.className).toContain('rail-item--active');
    expect(isNavItemActive('recipes', 'recipe_detail')).toBe(true);

    const pinnedBtn = screen.getByTitle('daily briefing');
    fireEvent.click(pinnedBtn);
    expect(usePageStore.getState().currentPage).toBe('recipe_app');
    expect(usePageStore.getState().currentRecipeAppId).toBe('daily_briefing');
  });
});
