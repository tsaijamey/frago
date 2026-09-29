/**
 * 页面这一层接上「会话分支」（spec 20260928-webui-session-branch）。
 *
 * 盯的是页面自己的承诺：起分支页面不跳、输入框上方一行说分支去了哪、点「打开」才切过去、
 * 切走就撤；分支会话里「带回主线」切回原会话、按引用格式填进去、不自动发出，发出成功才
 * 收口；原会话不在清单里时不给这颗按钮；主线上手动收口走同一个服务端动作。
 *
 * 记录流换成一个替身：划选、量位置那一套在 SelectionQuote / RecordStream 自己的用例里钉，
 * 这里只看页面把它们交出来的动作接到了哪里。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { WorkbenchMark } from '@/hooks/useSessionMarks';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const NOW = Date.now();
const MAIN = '11111111-1111-4111-8111-111111111111';
const CHILD = '22222222-2222-4222-8222-222222222222';

const page = vi.hoisted(() => ({
  sessions: [] as WorkbenchSession[],
  records: {} as Record<string, WorkbenchRecord[]>,
}));

const api = vi.hoisted(() => ({
  startBranch: vi.fn(),
  closeBranch: vi.fn(),
  getSessionMarks: vi.fn(),
  putSessionMarks: vi.fn(),
}));

vi.mock('@/hooks/useWorkbenchSessions', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/hooks/useWorkbenchSessions')>();
  return {
    ...real,
    useWorkbenchSessions: () => ({
      sessions: page.sessions,
      visible: page.sessions,
      loading: false,
      error: null,
      filter: 'all',
      setFilter: () => {},
      days: 0,
      setDays: () => {},
      counts: { all: page.sessions.length, 'for-you': 0 },
      reload: async () => {},
    }),
  };
});

vi.mock('@/hooks/useWorkbenchRecords', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useWorkbenchRecords: (sid: string | null) => ({
    records: (sid && page.records[sid]) || [],
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
  startBranch: (...a: unknown[]) => api.startBranch(...a),
  closeBranch: (...a: unknown[]) => api.closeBranch(...a),
  getSessionMarks: (...a: unknown[]) => api.getSessionMarks(...a),
  putSessionMarks: (...a: unknown[]) => api.putSessionMarks(...a),
}));

/** 记录流替身：三颗按钮各代表一种从记录流交出来的动作。 */
vi.mock('../RecordStream', () => ({
  default: (props: {
    onBranch?: (anchor: { record_id: string; text: string; occurrence: number }, note: string) => void;
    onCloseBranch?: (mark: WorkbenchMark) => void;
    onOpenBranch?: (child: string) => void;
    marks?: WorkbenchMark[];
  }) => (
    <div data-testid="fake-stream">
      <button
        type="button"
        data-testid="fake-branch"
        onClick={() => props.onBranch?.({ record_id: 'r1', text: '那个报错', occurrence: 0 }, '要不要查')}
      />
      <button
        type="button"
        data-testid="fake-close"
        onClick={() => {
          const m = props.marks?.find((x) => x.kind === 'branch');
          if (m) props.onCloseBranch?.(m);
        }}
      />
      <span data-testid="fake-marks">
        {(props.marks ?? []).map((m) => `${m.id}:${m.closed ? 'closed' : 'open'}`).join(',')}
      </span>
    </div>
  ),
}));

function session(id: string, over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: id,
    family: 'claude-code',
    title: `title ${id.slice(0, 4)}`,
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 3_600_000,
    last_active_at: NOW - 60_000,
    last_reply_at: NOW - 60_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

function say(sid: string, id: string, text: string): WorkbenchRecord {
  return {
    id,
    session_id: sid,
    group_id: null,
    seq: 1,
    ts: NOW - 60_000,
    kind: 'agent.say',
    agent_path: [],
    payload: { text },
    raw_available: false,
  };
}

const branchMark = (closed = false): WorkbenchMark => ({
  id: 'mk_b',
  kind: 'branch',
  record_id: 'r1',
  text: '那个报错',
  occurrence: 0,
  note: '要不要查',
  used: false,
  created_at: 1,
  used_at: null,
  child_session_id: CHILD,
  closed,
});

const fetchMock = vi.fn();

beforeEach(() => {
  api.startBranch.mockReset();
  api.closeBranch.mockReset();
  api.getSessionMarks.mockReset();
  api.putSessionMarks.mockReset();
  api.getSessionMarks.mockResolvedValue({ version: 1, marks: [] });
  api.putSessionMarks.mockImplementation(async (_sid: string, body: unknown) => body);
  api.closeBranch.mockResolvedValue({
    parent_session_id: MAIN,
    child_session_id: CHILD,
    closed_at: 1,
    closed_by: 'manual',
    mark_updated: true,
  });
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).endsWith('/send')) {
      return { ok: true, json: async () => ({ sid: MAIN, status: 'done', text: 'ok' }) };
    }
    return { ok: true, json: async () => ({ viewed: {} }) };
  });
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);
  page.records = {};
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
  await act(async () => {
    render(<SessionWorkbenchPage />);
  });
  return usePageStore;
}

describe('起分支', () => {
  it('页面不跳，输入框上方说分支去了哪；点「打开」才切过去', async () => {
    page.sessions = [session(MAIN)];
    api.startBranch.mockResolvedValue({
      handle: CHILD,
      agent: 'claude',
      display_name: 'Claude Code',
      cwd: '/x',
      session_id: CHILD,
      error: null,
      finished: false,
      text: '…',
      title: '要不要查',
      recorded: true,
      mark_saved: true,
      mark_id: 'mk_b',
    });
    const store = await mountOn(MAIN);
    await act(async () => {
      fireEvent.click(screen.getByTestId('fake-branch'));
    });
    expect(api.startBranch).toHaveBeenCalledWith(MAIN, {
      record_id: 'r1',
      text: '那个报错',
      occurrence: 0,
      note: '要不要查',
    });
    await waitFor(() =>
      expect(screen.getByTestId('composer-notice').textContent).toContain('已在新会话处理：要不要查')
    );
    expect(store.getState().workbenchSessionId).toBe(MAIN);
    // 起完取回主线的分支标注（虚线要画上）
    expect(api.getSessionMarks).toHaveBeenCalledTimes(2);

    await act(async () => {
      fireEvent.click(screen.getByTestId('composer-notice-action'));
    });
    expect(store.getState().workbenchSessionId).toBe(CHILD);
    // 切走了，那一行就撤
    expect(screen.queryByTestId('composer-notice')).toBeNull();
  });

  it('起失败：那一行换成失败原因', async () => {
    page.sessions = [session(MAIN)];
    api.startBranch.mockRejectedValue(new Error('记录没了'));
    await mountOn(MAIN);
    await act(async () => {
      fireEvent.click(screen.getByTestId('fake-branch'));
    });
    const notice = await screen.findByTestId('composer-notice');
    expect(notice.getAttribute('data-tone')).toBe('error');
    expect(notice.textContent).toContain('分支没起来：记录没了');
  });

  it('关系账没记上：说关联没记上', async () => {
    page.sessions = [session(MAIN)];
    api.startBranch.mockResolvedValue({
      handle: CHILD,
      agent: 'claude',
      display_name: 'Claude Code',
      cwd: '/x',
      session_id: CHILD,
      error: null,
      finished: false,
      text: '…',
      title: '要不要查',
      recorded: false,
      mark_saved: false,
      mark_id: null,
    });
    await mountOn(MAIN);
    await act(async () => {
      fireEvent.click(screen.getByTestId('fake-branch'));
    });
    await waitFor(() =>
      expect(screen.getByTestId('composer-notice').textContent).toContain('关联没记上')
    );
  });

  it('点关闭，那一行就撤', async () => {
    page.sessions = [session(MAIN)];
    api.startBranch.mockRejectedValue(new Error('x'));
    await mountOn(MAIN);
    await act(async () => {
      fireEvent.click(screen.getByTestId('fake-branch'));
    });
    await screen.findByTestId('composer-notice');
    fireEvent.click(screen.getByTestId('composer-notice-dismiss'));
    expect(screen.queryByTestId('composer-notice')).toBeNull();
  });
});

describe('带回主线', () => {
  const branchSessions = () => [
    session(MAIN),
    session(CHILD, { parent_session_id: MAIN, relation: { kind: 'branch', closed: false } }),
  ];

  it('切回原会话、按引用格式填进去、不自动发出；发出成功才收口', async () => {
    page.sessions = branchSessions();
    page.records[CHILD] = [say(CHILD, 'a1', '查过了，是代理超时')];
    const store = await mountOn(CHILD);

    await act(async () => {
      fireEvent.click(screen.getByTestId('composer-bring-back'));
    });
    expect(store.getState().workbenchSessionId).toBe(MAIN);
    const input = (await screen.findByTestId('composer-input')) as HTMLTextAreaElement;
    await waitFor(() => expect(input.value).toBe('"""\n查过了，是代理超时\n"""\n>>> '));
    // 没有自动发出
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/send'))).toBe(false);
    expect(api.closeBranch).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.change(input, { target: { value: `${input.value}那就不查了` } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('composer-send'));
    });
    await waitFor(() => expect(api.closeBranch).toHaveBeenCalledWith(MAIN, CHILD, 'bring-back'));
  });

  it('填了没发就切走：不收口', async () => {
    page.sessions = [...branchSessions(), session('33333333-3333-4333-8333-333333333333')];
    page.records[CHILD] = [say(CHILD, 'a1', '结论')];
    const store = await mountOn(CHILD);
    await act(async () => {
      fireEvent.click(screen.getByTestId('composer-bring-back'));
    });
    await act(async () => {
      store.getState().setWorkbenchSessionId('33333333-3333-4333-8333-333333333333');
    });
    await act(async () => {
      store.getState().setWorkbenchSessionId(MAIN);
    });
    const input = (await screen.findByTestId('composer-input')) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: '"""\n结论\n"""\n>>> 好' } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('composer-send'));
    });
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/send'))).toBe(true)
    );
    expect(api.closeBranch).not.toHaveBeenCalled();
  });

  it('原会话不在清单里：不给这颗按钮', async () => {
    page.sessions = [
      session(CHILD, { parent_session_id: MAIN, relation: { kind: 'branch', closed: false } }),
    ];
    await mountOn(CHILD);
    expect(screen.queryByTestId('composer-bring-back')).toBeNull();
  });

  it('不是分支会话：不给这颗按钮', async () => {
    page.sessions = [
      session(MAIN),
      session(CHILD, { parent_session_id: MAIN, origin: 'worker', relation: { kind: 'dispatch', closed: false } }),
    ];
    await mountOn(CHILD);
    expect(screen.queryByTestId('composer-bring-back')).toBeNull();
  });
});

describe('手动收口', () => {
  it('走同一个服务端动作，改完取回主线的分支标注', async () => {
    page.sessions = [session(MAIN)];
    api.getSessionMarks.mockResolvedValueOnce({ version: 1, marks: [branchMark(false)] });
    api.getSessionMarks.mockResolvedValue({ version: 1, marks: [branchMark(true)] });
    await mountOn(MAIN);
    await waitFor(() => expect(screen.getByTestId('fake-marks').textContent).toBe('mk_b:open'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('fake-close'));
    });
    expect(api.closeBranch).toHaveBeenCalledWith(MAIN, CHILD, 'manual');
    await waitFor(() => expect(screen.getByTestId('fake-marks').textContent).toBe('mk_b:closed'));
  });
});
