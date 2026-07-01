import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useUIStore } from '../uiStore';
import type { ConsoleMessage } from '@/types/console';

function reset() {
  localStorage.clear();
  useUIStore.setState({
    sidebarCollapsed: false,
    isLoading: false,
    toasts: [],
    agentAttachedId: null,
    consoleInternalId: null,
    consoleSessionId: null,
    consoleMessages: [],
    consoleIsRunning: false,
    consoleScrollPosition: 0,
  });
}

function msg(overrides: Partial<ConsoleMessage> = {}): ConsoleMessage {
  return {
    type: 'assistant',
    content: 'hello',
    timestamp: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('uiStore — toasts', () => {
  beforeEach(() => {
    reset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('pushes a toast with a generated id and the given message/type', () => {
    useUIStore.getState().showToast('saved', 'success');
    const toasts = useUIStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].message).toBe('saved');
    expect(toasts[0].type).toBe('success');
    expect(toasts[0].id).toBeTruthy();
  });

  it('appends multiple toasts in order with distinct ids', () => {
    useUIStore.getState().showToast('a', 'info');
    useUIStore.getState().showToast('b', 'error');
    const toasts = useUIStore.getState().toasts;
    expect(toasts.map((t) => t.message)).toEqual(['a', 'b']);
    expect(toasts[0].id).not.toBe(toasts[1].id);
  });

  it('auto-dismisses a toast after 3s', () => {
    useUIStore.getState().showToast('temp', 'info');
    expect(useUIStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(3000);
    expect(useUIStore.getState().toasts).toHaveLength(0);
  });

  it('dismissToast removes only the matching id', () => {
    useUIStore.getState().showToast('a', 'info');
    useUIStore.getState().showToast('b', 'info');
    const [first] = useUIStore.getState().toasts;
    useUIStore.getState().dismissToast(first.id);
    const remaining = useUIStore.getState().toasts;
    expect(remaining).toHaveLength(1);
    expect(remaining[0].message).toBe('b');
  });
});

describe('uiStore — sidebar', () => {
  beforeEach(reset);

  it('toggleSidebar flips the flag and persists to localStorage', () => {
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarCollapsed).toBe(true);
    expect(localStorage.getItem('frago-sidebar-collapsed')).toBe('true');
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarCollapsed).toBe(false);
    expect(localStorage.getItem('frago-sidebar-collapsed')).toBe('false');
  });

  it('setSidebarCollapsed sets the flag directly and persists', () => {
    useUIStore.getState().setSidebarCollapsed(true);
    expect(useUIStore.getState().sidebarCollapsed).toBe(true);
    expect(localStorage.getItem('frago-sidebar-collapsed')).toBe('true');
  });
});

describe('uiStore — agent attached id', () => {
  beforeEach(reset);

  it('sets and clears the attached session id', () => {
    useUIStore.getState().setAgentAttachedId('sess-1');
    expect(useUIStore.getState().agentAttachedId).toBe('sess-1');
    useUIStore.getState().setAgentAttachedId(null);
    expect(useUIStore.getState().agentAttachedId).toBeNull();
  });
});

describe('uiStore — console slice', () => {
  beforeEach(reset);

  it('persists console ids to localStorage and removes them when nulled', () => {
    useUIStore.getState().setConsoleInternalId('iid');
    useUIStore.getState().setConsoleSessionId('sid');
    expect(localStorage.getItem('frago_console_internal_id')).toBe('iid');
    expect(localStorage.getItem('frago_console_session_id')).toBe('sid');
    useUIStore.getState().setConsoleInternalId(null);
    expect(localStorage.getItem('frago_console_internal_id')).toBeNull();
  });

  it('addConsoleMessage appends to the queue', () => {
    useUIStore.getState().addConsoleMessage(msg({ content: 'one' }));
    useUIStore.getState().addConsoleMessage(msg({ content: 'two' }));
    expect(useUIStore.getState().consoleMessages.map((m) => m.content)).toEqual(['one', 'two']);
  });

  it('updateLastConsoleMessage merges into the last entry', () => {
    useUIStore.getState().addConsoleMessage(msg({ content: 'a', done: false }));
    useUIStore.getState().addConsoleMessage(msg({ content: 'b', done: false }));
    useUIStore.getState().updateLastConsoleMessage({ content: 'b-updated', done: true });
    const messages = useUIStore.getState().consoleMessages;
    expect(messages[0].content).toBe('a');
    expect(messages[1].content).toBe('b-updated');
    expect(messages[1].done).toBe(true);
  });

  it('updateLastConsoleMessage is a no-op on an empty queue', () => {
    useUIStore.getState().updateLastConsoleMessage({ content: 'x' });
    expect(useUIStore.getState().consoleMessages).toEqual([]);
  });

  it('updateConsoleMessageByToolCallId updates only the matching message', () => {
    useUIStore.getState().setConsoleMessages([
      msg({ type: 'tool_call', tool_call_id: 't1', content: 'a' }),
      msg({ type: 'tool_call', tool_call_id: 't2', content: 'b' }),
    ]);
    useUIStore.getState().updateConsoleMessageByToolCallId('t2', { content: 'b-done' });
    const messages = useUIStore.getState().consoleMessages;
    expect(messages[0].content).toBe('a');
    expect(messages[1].content).toBe('b-done');
  });

  it('clearConsole resets the slice and clears localStorage', () => {
    useUIStore.getState().setConsoleInternalId('iid');
    useUIStore.getState().setConsoleSessionId('sid');
    useUIStore.getState().addConsoleMessage(msg());
    useUIStore.getState().setConsoleIsRunning(true);
    useUIStore.getState().setConsoleScrollPosition(42);

    useUIStore.getState().clearConsole();

    const s = useUIStore.getState();
    expect(s.consoleInternalId).toBeNull();
    expect(s.consoleSessionId).toBeNull();
    expect(s.consoleMessages).toEqual([]);
    expect(s.consoleIsRunning).toBe(false);
    expect(s.consoleScrollPosition).toBe(0);
    expect(localStorage.getItem('frago_console_internal_id')).toBeNull();
    expect(localStorage.getItem('frago_console_session_id')).toBeNull();
  });
});
