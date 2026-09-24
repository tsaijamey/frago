/**
 * 页面这一层接上真的 `useForYou`：终端清单报出一场在等你，左栏挂上、页头写出等了多久。
 *
 * 其余数据源换成替身，For you 这一路（取终端清单 → 对上会话 → 交给清单与页头）用真的，
 * 顺带把「For you 判定经一格状态交给清单」那一圈钉住——那里要是互相叫醒，页面会卡死。
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

const NOW = Date.now();
const SID = 'waiting-one';

const page = vi.hoisted(() => ({ sessions: [] as WorkbenchSession[] }));

vi.mock('@/hooks/useWorkbenchSessions', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/hooks/useWorkbenchSessions')>();
  return {
    ...real,
    useWorkbenchSessions: (isForYou: (id: string) => boolean = () => false) => ({
      sessions: page.sessions,
      visible: page.sessions,
      loading: false,
      error: null,
      filter: 'all',
      setFilter: () => {},
      days: 0,
      setDays: () => {},
      counts: {
        all: page.sessions.length,
        'for-you': page.sessions.filter((s) => isForYou(s.session_id)).length,
      },
      reload: async () => {},
    }),
  };
});

vi.mock('@/hooks/useWorkbenchRecords', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useWorkbenchRecords: () => ({
    records: [],
    recordsSessionId: null,
    loading: false,
    loadingOlder: false,
    hasOlder: false,
    error: null,
    loadOlder: async () => {},
    reload: async () => {},
    awaitingAgent: false,
    outbound: [],
    deliveredAt: null,
    markSent: () => 'out-0',
    clearSent: () => {},
    settleSent: () => {},
    trails: [],
  }),
}));

vi.mock('@/hooks/useSessionLaunch', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useSessionLaunch: () => ({ launch: null, begin: () => {}, dismiss: () => {} }),
}));

vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getTmuxWaiting: async () => ({
    sessions: [
      {
        name: `frago-agent-${SID}`,
        session_id: SID,
        client_alive: true,
        awaiting_input: true,
        stop_reason: 'end_turn',
        last_stop_at: new Date(NOW - 44 * 60_000).toISOString(),
        closing_text: 'Reply with one letter for the hook item: A or B.',
      },
    ],
  }),
}));

function session(id: string, over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: id,
    family: 'claude-code',
    title: `title ${id}`,
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 3_600_000,
    last_active_at: NOW - 44 * 60_000,
    last_reply_at: NOW - 44 * 60_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('页面接上 For you', () => {
  it('终端报出在等你的那一场：左栏挂 For you 并加重，页头写 For you · waiting', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, json: async () => ({ viewed: {} }) })) as unknown as typeof fetch
    );
    page.sessions = [session(SID), session('other')];
    const { usePageStore } = await import('@/stores/pageStore');
    usePageStore.getState().setWorkbenchSessionId(SID);
    const { default: SessionWorkbenchPage } = await import('../SessionWorkbenchPage');
    await act(async () => {
      render(<SessionWorkbenchPage />);
    });

    await waitFor(() =>
      expect(document.querySelectorAll('[data-for-you="true"]')).toHaveLength(1)
    );
    const chip = screen.getAllByTestId('for-you-chip')[0];
    expect(chip.getAttribute('data-emphasis')).toBe('pick-one');
    expect(screen.getByTestId('for-you-words').textContent).toContain('A or B');
    expect(screen.getByTestId('list-filter-for-you').textContent).toContain('1');
    expect(screen.getByTestId('head-status').textContent).toContain('For you · waiting 44 min');
    usePageStore.getState().setWorkbenchSessionId(null);
  });
});
