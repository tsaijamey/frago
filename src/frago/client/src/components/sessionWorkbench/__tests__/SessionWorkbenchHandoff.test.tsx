/**
 * 页面级交接（handoff）集成单测：
 * 1. 低上下文普通空闲会话：输入区不再渲染一级交接按钮，从页头「…」二级菜单发起交接；
 * 2. 运行中且挂卡会话（status='running', need_decision=true）：同样可随时从页头菜单交接；
 * 3. 请求进行中再次打开菜单时交接项禁用并显示「交接中…」，不会触发重复 POST。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import type { HandoffLaunch } from '@/hooks/useAgentClients';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const NOW = Date.now();
const MAIN = '11111111-1111-4111-8111-111111111111';
const NEXT = '22222222-2222-4222-8222-222222222222';

const page = vi.hoisted(() => ({
  sessions: [] as WorkbenchSession[],
}));

const mocks = vi.hoisted(() => ({
  handoffSession: vi.fn(),
  begin: vi.fn(),
  reload: vi.fn(async () => {}),
}));

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
      reload: mocks.reload,
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
  useSessionLaunch: () => ({
    launch: null,
    begin: (...a: unknown[]) => mocks.begin(...a),
    dismiss: () => {},
  }),
}));

vi.mock('@/hooks/useAgentClients', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  handoffSession: (...a: unknown[]) => mocks.handoffSession(...a),
}));

vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getTmuxWaiting: async () => ({ sessions: [] }),
  getSessionMarks: async () => ({ version: 1, marks: [] }),
  putSessionMarks: async (_sid: string, body: unknown) => body,
}));

vi.mock('../RecordStream', () => ({
  default: () => <div data-testid="fake-stream" />,
}));

function makeSession(id: string, over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: id,
    family: 'claude-code',
    title: '短对话',
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 60_000,
    last_active_at: NOW - 5_000,
    last_reply_at: NOW - 5_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

function makeLaunch(): HandoffLaunch {
  return {
    handle: NEXT,
    agent: 'claude',
    display_name: 'Claude Code',
    cwd: '/Users/frago/Repos/frago',
    session_id: NEXT,
    error: null,
    finished: false,
    text: '接手上下文',
    old_title: '短对话 #1',
    new_title: '短对话 #2',
  };
}

const fetchMock = vi.fn();

beforeEach(() => {
  mocks.handoffSession.mockReset();
  mocks.begin.mockReset();
  mocks.reload.mockClear();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ viewed: {} }) });
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);
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

function openHeaderMenu(container: HTMLElement) {
  const trigger = container.querySelector(
    'button[data-testid="session-menu-button"][data-variant="header"]'
  );
  expect(trigger).toBeTruthy();
  fireEvent.click(trigger!);
}

describe('SessionWorkbenchPage 交接到新会话', () => {
  it('低上下文普通会话：输入区无一级按钮，页头更多菜单可随时触发交接', async () => {
    page.sessions = [makeSession(MAIN, { status: 'done' })];
    const launch = makeLaunch();
    mocks.handoffSession.mockResolvedValue(launch);

    const view = await mountOn(MAIN);

    expect(screen.queryByTestId('composer-handoff')).toBeNull();

    openHeaderMenu(view.container);
    const item = screen.getByTestId('session-menu-handoff') as HTMLButtonElement;
    expect(item.disabled).toBe(false);

    await act(async () => {
      fireEvent.click(item);
    });

    expect(mocks.handoffSession).toHaveBeenCalledTimes(1);
    expect(mocks.handoffSession).toHaveBeenCalledWith(MAIN);
    await waitFor(() => {
      expect(mocks.begin).toHaveBeenCalledWith(launch, '接手「短对话 #1」');
    });
  });

  it('运行中且挂卡会话（status=running, need_decision=true）也能随时交接', async () => {
    page.sessions = [
      makeSession(MAIN, {
        status: 'running',
        need_decision: true,
      }),
    ];
    mocks.handoffSession.mockResolvedValue(makeLaunch());

    const view = await mountOn(MAIN);
    openHeaderMenu(view.container);

    const item = screen.getByTestId('session-menu-handoff') as HTMLButtonElement;
    expect(item.disabled).toBe(false);

    await act(async () => {
      fireEvent.click(item);
    });

    expect(mocks.handoffSession).toHaveBeenCalledTimes(1);
    expect(mocks.handoffSession).toHaveBeenCalledWith(MAIN);
  });

  it('交接请求进行中禁用菜单项，重复点击不会发出第二次请求', async () => {
    page.sessions = [makeSession(MAIN, { status: 'done' })];
    let resolveLaunch!: (value: HandoffLaunch) => void;
    mocks.handoffSession.mockImplementation(
      () =>
        new Promise<HandoffLaunch>((resolve) => {
          resolveLaunch = resolve;
        })
    );

    const view = await mountOn(MAIN);
    openHeaderMenu(view.container);
    fireEvent.click(screen.getByTestId('session-menu-handoff'));

    expect(mocks.handoffSession).toHaveBeenCalledTimes(1);

    openHeaderMenu(view.container);
    const pendingItem = screen.getByTestId('session-menu-handoff') as HTMLButtonElement;
    expect(pendingItem.disabled).toBe(true);
    expect(pendingItem.textContent).toContain('交接中');
    fireEvent.click(pendingItem);
    expect(mocks.handoffSession).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveLaunch(makeLaunch());
    });
  });
});
