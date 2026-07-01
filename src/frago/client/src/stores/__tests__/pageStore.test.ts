import { beforeEach, describe, expect, it } from 'vitest';
import { usePageStore } from '../pageStore';

function reset() {
  usePageStore.setState({
    currentPage: 'claude_sessions',
    currentTaskId: null,
    currentRecipeName: null,
    currentProjectId: null,
  });
}

describe('pageStore', () => {
  beforeEach(reset);

  it('starts on the claude_sessions homepage with no contextual ids', () => {
    const s = usePageStore.getState();
    expect(s.currentPage).toBe('claude_sessions');
    expect(s.currentTaskId).toBeNull();
    expect(s.currentRecipeName).toBeNull();
    expect(s.currentProjectId).toBeNull();
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

  it('drops a stale detail id when navigating to a non-matching detail page', () => {
    usePageStore.getState().switchPage('task_detail', 't1');
    usePageStore.getState().switchPage('recipe_detail', 'r1');
    const s = usePageStore.getState();
    expect(s.currentTaskId).toBeNull();
    expect(s.currentRecipeName).toBe('r1');
  });
});
