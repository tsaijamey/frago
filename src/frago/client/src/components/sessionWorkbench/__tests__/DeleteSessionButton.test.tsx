/**
 * 「…」菜单里的 Delete session（动作与报错说法在 `DeleteSessionButton.tsx`）。
 *
 * 钉住这几件事：
 *
 * 1. 点菜单项只换到确认那一段，一个请求都不出门——看一眼就退出来不该动盘上的东西；
 * 2. 这一项是报错红，确认键同样红底；确认那一段说清删掉什么、能不能反悔；
 * 3. 确认才真删，删成之后叫页面重取清单、中栏退回清单态；
 * 4. 这一场还在跑时，说的是"先在同一个菜单里关 tmux"，不是把服务端那句原文摆上来；
 * 5. 本机本来就没有这场时，说的是"不用再删"，NEVER 说成没删掉——要的结果已经成立；
 * 6. 引擎自己拒绝的那句话原样摆出来（``Session not found`` 这类），我们转述一次就多
 *    一层失真；
 * 7. **三家会话上都出现**——页头只剩一个「…」，没有单独的关 tmux 与删除按钮。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SessionMenu from '../SessionMenu';
import i18n from '@/i18n';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const OC_SID = 'ses_058288655ffeYMxYC1AZKCcv56';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function session(over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: SID,
    family: 'claude-code',
    title: '会话工作台 webUI',
    directory: '/Users/frago/Repos/frago',
    created_at: 1_753_700_000_000,
    last_active_at: 1_753_800_000_000,
    last_reply_at: null,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

const DELETED = {
  sid: SID,
  family: 'claude-code',
  removed: [`原始记录 /Users/frago/.claude/projects/-Users-frago-Repos-frago/${SID}.jsonl`],
  warnings: [],
};

function mockDelete(response: { ok: boolean; status?: number; body: unknown }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: response.ok,
    status: response.status ?? 200,
    json: async () => response.body,
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function openDelete(onDeleted?: () => void, over: Partial<WorkbenchSession> = {}) {
  render(<SessionMenu session={session(over)} pinned={false} inTmux={false} onDeleted={onDeleted} />);
  fireEvent.click(screen.getByTestId('session-menu-button'));
  fireEvent.click(screen.getByTestId('session-menu-delete'));
}

async function confirmDelete() {
  await act(async () => {
    fireEvent.click(screen.getByTestId('session-delete-confirm'));
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe('Delete session（菜单项）', () => {
  it('点菜单项只换到确认那一段，一个请求都不出门', () => {
    const fetchMock = mockDelete({ ok: true, body: DELETED });
    openDelete();

    expect(screen.getByText('删除这场会话？')).toBeTruthy();
    expect(screen.getByText('它的记录和标注都会删掉，不能撤回。')).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('菜单项与确认键都是报错红', () => {
    mockDelete({ ok: true, body: DELETED });
    render(<SessionMenu session={session()} pinned={false} inTmux={false} />);
    fireEvent.click(screen.getByTestId('session-menu-button'));
    expect(screen.getByTestId('session-menu-delete').className).toContain('text-[var(--accent-error)]');
    expect(screen.getByTestId('session-menu-delete').className).toContain('bg-[var(--accent-error-10)]');
    fireEvent.click(screen.getByTestId('session-menu-delete'));
    expect(screen.getByTestId('session-delete-confirm').className).toContain('bg-accent-error');
  });

  it('确认之后才真删，删成之后叫页面重取清单', async () => {
    const fetchMock = mockDelete({ ok: true, body: DELETED });
    const onDeleted = vi.fn();
    openDelete(onDeleted);
    await confirmDelete();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain(`/api/workbench/sessions/${SID}`);
    expect((init as RequestInit).method).toBe('DELETE');
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(DELETED));
    expect(screen.queryByTestId('session-menu')).toBeNull();
  });

  it('取消就退出来，一个请求都不发', () => {
    const fetchMock = mockDelete({ ok: true, body: DELETED });
    const onDeleted = vi.fn();
    openDelete(onDeleted);
    fireEvent.click(screen.getByText('取消'));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(screen.queryByTestId('session-menu')).toBeNull();
  });

  it('这一场还在跑时，说的是下一步按什么', async () => {
    mockDelete({
      ok: false,
      status: 409,
      body: { detail: '这一场还在跑（frago-agent-xxx），先结束运行再删' },
    });
    const onDeleted = vi.fn();
    openDelete(onDeleted);
    await confirmDelete();

    await waitFor(() => expect(screen.getByTestId('session-delete-error')).toBeTruthy());
    expect(screen.getByTestId('session-delete-error').textContent).toContain('关闭 tmux 会话');
    // 拒绝就是真的什么都没删，确认那一段也不许自己收掉——人正好在同一个菜单里先关 tmux。
    expect(onDeleted).not.toHaveBeenCalled();
    expect(screen.getByTestId('session-delete-confirm')).toBeTruthy();
  });

  it('本机已经没有这场时，说的是不用再删，而不是没删掉', async () => {
    mockDelete({
      ok: false,
      status: 404,
      body: { detail: `本机已经找不到这场会话的原始记录了：${SID}` },
    });
    openDelete(vi.fn());
    await confirmDelete();

    await waitFor(() => expect(screen.getByTestId('session-delete-error')).toBeTruthy());
    const text = screen.getByTestId('session-delete-error').textContent ?? '';
    // 要的结果已经成立，NEVER 把它说成一次失败，也别把服务端那句内部说法摆给人看。
    expect(text).toContain('不用再删');
    expect(text).not.toContain('原始记录');
  });

  it('引擎自己拒绝时，把那句话原样摆出来', async () => {
    mockDelete({
      ok: false,
      status: 500,
      body: { detail: 'opencode 没删掉：Session not found' },
    });
    openDelete(undefined, { session_id: OC_SID, family: 'opencode' });
    await confirmDelete();

    await waitFor(() => expect(screen.getByTestId('session-delete-error')).toBeTruthy());
    // 拒绝的理由只有引擎知道，转述一次就多一层失真。
    expect(screen.getByTestId('session-delete-error').textContent).toContain(
      'Session not found'
    );
  });
});

// ── 页面头部那一行 ────────────────────────────────────────────────────
const page = vi.hoisted(() => ({
  sessions: [] as unknown[],
}));

// 只换掉取数那一支，其余（状态档位的说法、清单条的判据）照用真模块——整块替换会把
// STATUS_LABEL_KEY 这类同住一个文件的常量一起吞掉，左栏一渲染就炸。
vi.mock('@/hooks/useWorkbenchSessions', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useWorkbenchSessions: () => ({
    sessions: page.sessions,
    visible: page.sessions,
    loading: false,
    error: null,
    filter: 'all',
    setFilter: () => {},
    days: 0,
    setDays: () => {},
    counts: { all: 0, 'for-you': 0 },
    reload: async () => {},
  }),
}));

vi.mock('@/hooks/useWorkbenchRecords', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useWorkbenchRecords: () => ({
    records: [],
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

// For you 与已看记录都要问服务端；头部这几条用例不关心它们。
// 替身必须每次交出同一个对象：真的那两个都记忆化过，页面拿「For you 变了没有」去更新清单
// 的判定，每渲染一次换一个新对象会让页面一直重渲染下去。
const stable = vi.hoisted(() => ({
  forYou: {
    infoOf: () => null,
    count: 0,
    closable: [],
    rows: [],
    suppress: () => {},
    refresh: () => {},
  },
  views: {
    viewedAt: () => undefined,
    isInTmux: () => false,
    markViewed: () => {},
  },
}));

vi.mock('@/hooks/useForYou', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useForYou: () => stable.forYou,
}));

vi.mock('@/hooks/useSessionViews', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useSessionViews: () => stable.views,
}));

vi.mock('@/hooks/useSessionLaunch', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useSessionLaunch: () => ({ launch: null, begin: () => {}, dismiss: () => {} }),
}));

describe('会话详情的头部', () => {
  async function open(sessions: WorkbenchSession[]) {
    page.sessions = sessions;
    const { default: SessionWorkbenchPage } = await import('../SessionWorkbenchPage');
    render(<SessionWorkbenchPage />);
    await act(async () => {
      fireEvent.click(screen.getAllByTestId('session-item')[0]);
    });
  }

  function headerMenu() {
    const btn = screen
      .getAllByTestId('session-menu-button')
      .find((el) => el.dataset.variant === 'header');
    if (!btn) throw new Error('页头没有「…」');
    return btn;
  }

  it('页头没有单独的关 tmux 与删除按钮，只有一个「…」', async () => {
    await open([session({ in_tmux: true })]);
    expect(screen.queryByTestId('session-stop-run')).toBeNull();
    expect(screen.queryByTestId('session-delete')).toBeNull();
    expect(headerMenu()).toBeTruthy();
  });

  it('页头与卡片是同一份菜单：同样三段', async () => {
    await open([session({ in_tmux: true })]);
    fireEvent.click(headerMenu());
    const sections = screen.getAllByTestId('session-menu-section').map((el) => el.dataset.section);
    expect(sections).toEqual(['organize', 'tmux', 'delete']);
    expect(screen.getByTestId('session-menu-pin')).toBeTruthy();
    expect(screen.getByTestId('session-menu-group')).toBeTruthy();
  });

  it('不在 tmux 里：页头菜单没有 Close tmux session', async () => {
    await open([session()]);
    fireEvent.click(headerMenu());
    expect(screen.queryByTestId('session-menu-close')).toBeNull();
  });

  it('三家都能删：opencode、codex 的会话上同样有 Delete session', async () => {
    await open([session({ session_id: OC_SID, family: 'opencode', title: '另一家' })]);
    fireEvent.click(headerMenu());
    expect(screen.getByTestId('session-menu-delete')).toBeTruthy();
  });

  it('codex 的会话上也有', async () => {
    await open([session({ session_id: '01a01a98-82e9-7013-b24e-e5e91b03995a', family: 'codex' })]);
    fireEvent.click(headerMenu());
    expect(screen.getByTestId('session-menu-delete')).toBeTruthy();
  });

  it('没选会话时页头没有「…」', async () => {
    page.sessions = [session()];
    const { default: SessionWorkbenchPage } = await import('../SessionWorkbenchPage');
    render(<SessionWorkbenchPage />);
    expect(
      screen.queryAllByTestId('session-menu-button').filter((el) => el.dataset.variant === 'header')
    ).toEqual([]);
  });
});
