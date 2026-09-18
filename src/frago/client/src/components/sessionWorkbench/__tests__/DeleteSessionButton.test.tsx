/**
 * 标题栏那个「删除会话」。
 *
 * 钉住八件事：
 *
 * 1. 按一下只弹确认，一个请求都不出门——看一眼就退出来不该动盘上的东西；
 * 2. 弹窗里先把删的是哪一场摆出来（标题、编号、工作目录）——左栏一行行挨着看，
 *    点错一行是常有的事；
 * 3. 删之前三句话要说全：动的是哪一份记录、删完会怎样、能不能反悔；
 * 4. 站起来确认才真删，删成之后要叫页面重取清单、中栏退回清单态；
 * 5. 这一场还在跑时，说的是"先去按关闭 tmux 会话"，不是把服务端那句原文摆上来；
 * 6. 本机本来就没有这场时，说的是"不用再删"，NEVER 说成没删掉——要的结果已经成立；
 * 7. 引擎自己拒绝的那句话原样摆出来（``Session not found`` 这类），我们转述一次就多
 *    一层失真；
 * 8. **三家会话上都出现**——Claude Code、opencode、codex 都有删除入口。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DeleteSessionButton from '../DeleteSessionButton';
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

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe('DeleteSessionButton', () => {
  it('按一下只弹确认，一个请求都不出门', () => {
    const fetchMock = mockDelete({ ok: true, body: DELETED });
    render(<DeleteSessionButton session={session()} />);

    fireEvent.click(screen.getByTestId('session-delete'));

    expect(screen.getByText('删除会话')).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('弹窗按家族说清动的是哪一份记录', () => {
    mockDelete({ ok: true, body: DELETED });

    const { unmount } = render(<DeleteSessionButton session={session()} />);
    fireEvent.click(screen.getByTestId('session-delete'));
    expect(screen.getByText(/Claude Code 为这一场留下的记录会全部删掉/)).toBeTruthy();
    expect(screen.queryByText(/opencode 为这一场留下的记录会全部删掉/)).toBeNull();
    unmount();

    render(
      <DeleteSessionButton
        session={session({ session_id: OC_SID, family: 'opencode', title: '另一家' })}
      />
    );
    fireEvent.click(screen.getByTestId('session-delete'));
    expect(screen.getByText(/opencode 为这一场留下的记录会全部删掉/)).toBeTruthy();
    expect(screen.queryByText(/Claude Code 为这一场留下的记录会全部删掉/)).toBeNull();
  });

  it('删之前把三句话说全：动的是什么、删完会怎样、能不能反悔', () => {
    mockDelete({ ok: true, body: DELETED });
    render(<DeleteSessionButton session={session()} />);

    fireEvent.click(screen.getByTestId('session-delete'));

    expect(screen.getByText(/Claude Code 为这一场留下的记录会全部删掉/)).toBeTruthy();
    expect(screen.getByText('删完就从会话列表里消失，再也打不开。')).toBeTruthy();
    expect(screen.getByText('这一步不能撤回，删了就找不回来了。')).toBeTruthy();
  });

  it('弹窗里先把删的是哪一场摆出来', () => {
    mockDelete({ ok: true, body: DELETED });
    render(<DeleteSessionButton session={session()} />);

    fireEvent.click(screen.getByTestId('session-delete'));

    expect(screen.getByText('会话工作台 webUI')).toBeTruthy();
    expect(screen.getByText(SID)).toBeTruthy();
    expect(screen.getByText('/Users/frago/Repos/frago')).toBeTruthy();
  });

  it('确认之后才真删，删成之后叫页面重取清单', async () => {
    const fetchMock = mockDelete({ ok: true, body: DELETED });
    const onDeleted = vi.fn();
    render(<DeleteSessionButton session={session()} onDeleted={onDeleted} />);

    fireEvent.click(screen.getByTestId('session-delete'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('session-delete-confirm'));
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain(`/api/workbench/sessions/${SID}`);
    expect((init as RequestInit).method).toBe('DELETE');
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(DELETED));
  });

  it('取消就退出来，一个请求都不发', () => {
    const fetchMock = mockDelete({ ok: true, body: DELETED });
    const onDeleted = vi.fn();
    render(<DeleteSessionButton session={session()} onDeleted={onDeleted} />);

    fireEvent.click(screen.getByTestId('session-delete'));
    fireEvent.click(screen.getByText('取消'));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it('这一场还在跑时，说的是下一步按什么', async () => {
    mockDelete({
      ok: false,
      status: 409,
      body: { detail: '这一场还在跑（frago-agent-xxx），先结束运行再删' },
    });
    const onDeleted = vi.fn();
    render(<DeleteSessionButton session={session()} onDeleted={onDeleted} />);

    fireEvent.click(screen.getByTestId('session-delete'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('session-delete-confirm'));
    });

    await waitFor(() => expect(screen.getByTestId('session-delete-error')).toBeTruthy());
    expect(screen.getByTestId('session-delete-error').textContent).toContain('关闭 tmux 会话');
    // 拒绝就是真的什么都没删，弹窗也不许自己关掉——人正好接着去按「关闭 tmux 会话」。
    expect(onDeleted).not.toHaveBeenCalled();
    expect(screen.getByTestId('session-delete-confirm')).toBeTruthy();
  });

  it('本机已经没有这场时，说的是不用再删，而不是没删掉', async () => {
    mockDelete({
      ok: false,
      status: 404,
      body: { detail: `本机已经找不到这场会话的原始记录了：${SID}` },
    });
    const onDeleted = vi.fn();
    render(<DeleteSessionButton session={session()} onDeleted={onDeleted} />);

    fireEvent.click(screen.getByTestId('session-delete'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('session-delete-confirm'));
    });

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
    render(<DeleteSessionButton session={session()} />);

    fireEvent.click(screen.getByTestId('session-delete'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('session-delete-confirm'));
    });

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
    status: 'all',
    setStatus: () => {},
    days: 0,
    setDays: () => {},
    counts: { all: 0, running: 0, error: 0, done: 0, idle: 0 },
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
  }),
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

  it('Claude Code 的会话上摆着删除按钮', async () => {
    await open([session()]);
    expect(screen.getByTestId('session-delete')).toBeTruthy();
  });

  it('opencode 的会话上同样摆着——三家都能删', async () => {
    await open([session({ session_id: OC_SID, family: 'opencode', title: '另一家' })]);
    expect(screen.getByTestId('session-delete')).toBeTruthy();
  });

  it('codex 的会话上也摆着', async () => {
    await open([session({ session_id: '01a01a98-82e9-7013-b24e-e5e91b03995a', family: 'codex' })]);
    expect(screen.getByTestId('session-delete')).toBeTruthy();
  });

  it('没选会话时删除按钮不出现', async () => {
    page.sessions = [session()];
    const { default: SessionWorkbenchPage } = await import('../SessionWorkbenchPage');
    render(<SessionWorkbenchPage />);
    expect(screen.queryByTestId('session-delete')).toBeNull();
  });
});
