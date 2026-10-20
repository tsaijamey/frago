/**
 * 详情页头右侧「…」菜单里的复制续接命令。
 *
 * 卡片与页头共用同一份菜单；页头此前没接复制动作，所以这一项不出现。这里钉住页面把
 * 续接命令接上：复制出来的是带客户端信息的命令，不是裸会话 ID。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const MAIN = '11111111-1111-4111-8111-111111111111';
const page = vi.hoisted(() => ({ sessions: [] as WorkbenchSession[] }));

vi.mock('@/hooks/useWorkbenchSessions', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/hooks/useWorkbenchSessions')>();
  return {
    ...real,
    useWorkbenchSessions: () => ({
      sessions: page.sessions,
      visible: page.sessions,
      todaySessions: page.sessions,
      loading: false,
      error: null,
      filter: 'all',
      setFilter: () => {},
      counts: { all: page.sessions.length, 'for-you': 0 },
      reload: async () => {},
    }),
  };
});

vi.mock('@/hooks/useWorkbenchRecords', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useWorkbenchRecords: (sid: string | null) => ({
    records: [],
    recordsSessionId: sid,
    loading: false,
    loadingOlder: false,
    hasOlder: false,
    error: null,
    loadOlder: async () => {},
    reload: async () => {},
    awaitingAgent: false,
    outbound: [],
    deliveredAt: null,
    markSent: () => 'out-1',
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
  getTmuxWaiting: async () => ({ sessions: [] }),
}));

vi.mock('../RecordStream', () => ({
  default: () => <div data-testid="fake-stream" />,
}));

function session(id: string): WorkbenchSession {
  const now = Date.now();
  return {
    session_id: id,
    family: 'claude-code',
    title: `title ${id.slice(0, 4)}`,
    directory: '/Users/frago/Repos/frago',
    created_at: now - 3_600_000,
    last_active_at: now - 60_000,
    last_reply_at: now - 60_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
  };
}

beforeEach(() => {
  page.sessions = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => ({ viewed: {} }) }))
  );
});

afterEach(async () => {
  vi.unstubAllGlobals();
  const { usePageStore } = await import('@/stores/pageStore');
  usePageStore.getState().setWorkbenchSessionId(null);
});

async function mountOn(sid: string) {
  const { usePageStore } = await import('@/stores/pageStore');
  usePageStore.getState().setWorkbenchSessionId(sid);
  const { default: SessionWorkbenchPage } = await import('../SessionWorkbenchPage');
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(<SessionWorkbenchPage />);
  });
  return view;
}

describe('详情页头的复制续接命令', () => {
  it('菜单里有这一项，点下去复制带客户端信息的命令', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    page.sessions = [session(MAIN)];
    const view = await mountOn(MAIN);

    const headerMenu = view.container.querySelector(
      'button[data-testid="session-menu-button"][data-variant="header"]'
    );
    expect(headerMenu).toBeTruthy();
    fireEvent.click(headerMenu!);

    expect(screen.getByTestId('copy-resume').textContent).toBe('复制续接命令');
    await act(async () => {
      fireEvent.click(screen.getByTestId('copy-resume'));
    });

    expect(writeText).toHaveBeenCalledWith(`claude --resume ${MAIN}`);
  });

  it('菜单里没有复制裸会话 ID 的项', async () => {
    page.sessions = [session(MAIN)];
    const view = await mountOn(MAIN);

    const headerMenu = view.container.querySelector(
      'button[data-testid="session-menu-button"][data-variant="header"]'
    );
    fireEvent.click(headerMenu!);

    expect(screen.queryByTestId('copy-session-id')).toBeNull();
  });
});
