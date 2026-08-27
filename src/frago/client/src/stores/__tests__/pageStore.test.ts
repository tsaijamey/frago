import { beforeEach, describe, expect, it } from 'vitest';
import { usePageStore } from '../pageStore';

function reset() {
  usePageStore.setState({
    currentPage: 'session_workbench',
    currentTaskId: null,
    currentRecipeName: null,
    currentProjectId: null,
    currentTodoId: null,
  });
  window.location.hash = '';
}

describe('pageStore', () => {
  beforeEach(reset);

  it('starts on the session homepage with no contextual ids', () => {
    const s = usePageStore.getState();
    expect(s.currentPage).toBe('session_workbench');
    expect(s.currentTaskId).toBeNull();
    expect(s.currentRecipeName).toBeNull();
    expect(s.currentProjectId).toBeNull();
    expect(s.currentTodoId).toBeNull();
  });

  it('switches to a plain page and clears all contextual ids', () => {
    usePageStore.setState({ currentTaskId: 'old' });
    usePageStore.getState().switchPage('settings');
    const s = usePageStore.getState();
    expect(s.currentPage).toBe('settings');
    expect(s.currentTaskId).toBeNull();
    expect(s.currentRecipeName).toBeNull();
    expect(s.currentProjectId).toBeNull();
  });

  it('routes the id into currentTaskId for task_detail only', () => {
    usePageStore.getState().switchPage('task_detail', 't1');
    const s = usePageStore.getState();
    expect(s.currentPage).toBe('task_detail');
    expect(s.currentTaskId).toBe('t1');
    expect(s.currentRecipeName).toBeNull();
    expect(s.currentProjectId).toBeNull();
  });

  it('routes the id into currentRecipeName for recipe_detail only', () => {
    usePageStore.getState().switchPage('recipe_detail', 'my-recipe');
    const s = usePageStore.getState();
    expect(s.currentRecipeName).toBe('my-recipe');
    expect(s.currentTaskId).toBeNull();
    expect(s.currentProjectId).toBeNull();
  });

  it('routes the id into currentProjectId for project_detail only', () => {
    usePageStore.getState().switchPage('project_detail', 'p9');
    const s = usePageStore.getState();
    expect(s.currentProjectId).toBe('p9');
    expect(s.currentTaskId).toBeNull();
    expect(s.currentRecipeName).toBeNull();
  });

  it('coerces a missing id to null for detail pages', () => {
    usePageStore.getState().switchPage('task_detail');
    expect(usePageStore.getState().currentTaskId).toBeNull();
  });

  it('routes the id into currentTodoId for todo_detail only', () => {
    usePageStore.getState().switchPage('todo_detail', '20260627-x');
    const s = usePageStore.getState();
    expect(s.currentTodoId).toBe('20260627-x');
    expect(s.currentRecipeName).toBeNull();
    expect(s.currentProjectId).toBeNull();
  });

  it('drops a stale detail id when navigating to a non-matching detail page', () => {
    usePageStore.getState().switchPage('task_detail', 't1');
    usePageStore.getState().switchPage('recipe_detail', 'r1');
    const s = usePageStore.getState();
    expect(s.currentTaskId).toBeNull();
    expect(s.currentRecipeName).toBe('r1');
  });

  // —— 地址栏这一头 ——
  // 在这之前界面没有地址一说：点进详情地址栏还停在首页，刷一下就被弹回来。

  it('每次跳转都把地址栏改成这一页', () => {
    usePageStore.getState().switchPage('todos');
    expect(window.location.hash).toBe('#/todos');
    usePageStore.getState().switchPage('recipe_detail', 'my-recipe');
    expect(window.location.hash).toBe('#/recipes/my-recipe');
  });

  it('地址栏驱动的那一路只落状态，不再写回地址', () => {
    // 写回去会在历史里留下第二条记录，后退键要按两下才动。
    window.location.hash = '#/todos/20260627-x';
    usePageStore.getState().applyRoute('todo_detail', '20260627-x');
    expect(usePageStore.getState().currentTodoId).toBe('20260627-x');
    expect(window.location.hash).toBe('#/todos/20260627-x');
  });

  it('已经停在这一页时不再往历史里塞一条', () => {
    usePageStore.getState().switchPage('settings');
    const before = window.history.length;
    usePageStore.getState().switchPage('settings');
    expect(window.history.length).toBe(before);
  });
});
