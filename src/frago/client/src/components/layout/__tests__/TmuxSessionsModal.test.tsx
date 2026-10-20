/**
 * 本机会话浮窗的三条语义。
 *
 * 盯的是这次补上的两处：清单里标得出当前对话是哪一场；CoreAgent 不在 tmux 里，
 * 但同样进清单，并且能从这里打开它。关闭仍然只属于 tmux 行。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

import i18n from '@/i18n';
import { usePageStore } from '@/stores/appStore';
import type { TmuxSessionsResponse } from '@/types/api';

const CORE_SID = 'core_0123456789abcdef0123456789abcdef';

const fixture = vi.hoisted(() => ({
  data: {
    sessions: [
      {
        name: 'frago-agent-sid-tmux-1',
        label: 'tmux-1',
        session_id: 'sid-tmux-1',
        stop_reason: 'end_turn',
        last_stop_at: '2026-10-19T00:00:00+00:00',
        idle_secs: 7200,
        excerpt: 'tmux 这一场说过的话',
        memory_mb: 100,
        busy: false,
        managed: false,
        kind: 'tmux',
        state: null,
      },
      {
        name: 'core_0123456789abcdef0123456789abcdef',
        label: 'CoreAgent 那一场',
        session_id: 'core_0123456789abcdef0123456789abcdef',
        stop_reason: null,
        last_stop_at: '2026-10-19T00:01:00+00:00',
        idle_secs: 600,
        excerpt: 'CoreAgent 这一场说过的话',
        memory_mb: 300,
        busy: false,
        managed: false,
        kind: 'coreagent',
        state: 'idle',
        directory: '/Users/frago/Repos/frago',
      },
    ],
    total: 2,
    total_memory_mb: 400,
    cleanup_idle_hours: 1,
  } as TmuxSessionsResponse,
}));

vi.mock('@/hooks/useTmuxSessions', () => ({
  useTmuxSessions: () => ({
    data: fixture.data,
    loading: false,
    error: null,
    titles: {
      'sid-tmux-1': 'tmux 会话的真实标题',
      core_0123456789abcdef0123456789abcdef: 'CoreAgent 那一场',
    },
    reload: vi.fn(),
    close: vi.fn(),
    saveThreshold: vi.fn(),
  }),
}));

import TmuxSessionsModal from '../TmuxSessionsModal';

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  usePageStore.setState({ currentPage: 'session_workbench', workbenchSessionId: null });
});

describe('本机会话浮窗', () => {
  it('标出当前对话那一场，CoreAgent 行也在清单里', () => {
    usePageStore.setState({ workbenchSessionId: 'sid-tmux-1' });
    render(<TmuxSessionsModal onClose={() => {}} />);

    expect(screen.getByText('This session')).toBeTruthy();
    expect(screen.getByText('CoreAgent')).toBeTruthy();
    expect(screen.getByText('CoreAgent 那一场')).toBeTruthy();
    // 清单的主角是标题，不是把手里的 uuid。
    expect(screen.getByText('tmux 会话的真实标题')).toBeTruthy();
    // CoreAgent 行没有关闭用的复选框：只有 tmux 那一行有。
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
  });

  it('从 CoreAgent 行打开那一场会话', () => {
    const onClose = vi.fn();
    render(<TmuxSessionsModal onClose={onClose} />);

    const coreRow = screen.getByText('CoreAgent 那一场').closest('.tmux-row');
    expect(coreRow).not.toBeNull();
    fireEvent.click(
      within(coreRow as HTMLElement).getByRole('button', { name: 'Open CoreAgent 那一场' })
    );

    const state = usePageStore.getState();
    expect(state.workbenchSessionId).toBe(CORE_SID);
    expect(state.currentPage).toBe('session_workbench');
    expect(onClose).toHaveBeenCalled();
  });

  it('当前会话不在清单里时把原因说出来', () => {
    usePageStore.setState({ workbenchSessionId: 'sid-not-running' });
    render(<TmuxSessionsModal onClose={() => {}} />);

    expect(screen.getByText(/not in this list/)).toBeTruthy();
    expect(screen.queryByText('This session')).toBeNull();
  });
});
