import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n';
import TodoPage from '../TodoPage';

const getTodos = vi.fn();
const switchPage = vi.fn();
const setWorkbenchSessionId = vi.fn();

vi.mock('@/api', () => ({
  getTodos: () => getTodos(),
  composeTodo: vi.fn(),
  dropTodo: vi.fn(),
  updateTodoCategories: vi.fn(),
}));

vi.mock('@/stores/pageStore', () => ({
  usePageStore: (selector: (s: unknown) => unknown) =>
    selector({
      currentTodoId: null,
      switchPage,
      setWorkbenchSessionId,
    }),
}));

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  getTodos.mockResolvedValue({
    categories: [{ id: 'work', name: 'Work' }],
    todos: [
      {
        id: 'todo_normal',
        title: 'Normal doing task',
        status: 'doing',
        priority: 'high',
        category: 'work',
        summary: 'Routine work',
        context: '',
        tags: ['routine'],
        steps: [],
        sessions: [],
        created: '2026-10-13T09:00:00Z',
        updated: new Date().toISOString(),
      },
      {
        id: 'todo_blocked',
        title: 'Waiting on upstream fix',
        status: 'todo',
        priority: 'normal',
        category: 'work',
        summary: 'Needs review',
        context: '',
        tags: ['blocked'],
        steps: [],
        sessions: ['sess-1'],
        created: '2026-10-10T09:00:00Z',
        updated: '2026-10-10T09:00:00Z',
      },
    ],
  });
});

describe('P2-4 TodoPage 中性默认态与阻塞告警一步处理', () => {
  it('常规 doing 行保持中性，仅阻塞任务带 .tdp-row--blocked 与 .fix-btn.warn', async () => {
    render(<TodoPage />);

    const normalRow = await screen.findByTestId('todo-row-todo_normal');
    const blockedRow = screen.getByTestId('todo-row-todo_blocked');

    expect(normalRow.className).not.toContain('tdp-row--blocked');
    expect(screen.queryByTestId('todo-attention-todo_normal')).toBeNull();

    expect(blockedRow.className).toContain('tdp-row--blocked');
    expect(screen.getByTestId('todo-attention-todo_blocked')).toBeTruthy();

    const fixBtn = screen.getByTestId('todo-fix-todo_blocked');
    expect(fixBtn.className).toContain('fix-btn');
    expect(fixBtn.className).toContain('warn');

    fireEvent.click(fixBtn);
    await waitFor(() => {
      expect(setWorkbenchSessionId).toHaveBeenCalledWith('sess-1');
      expect(switchPage).toHaveBeenCalledWith('session_workbench');
    });
  });
});
