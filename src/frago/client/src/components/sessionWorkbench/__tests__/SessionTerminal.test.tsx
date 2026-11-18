/**
 * SessionTerminal 空状态与双主题契约单测。
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '@/i18n';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import type { SessionTerminalSnapshot } from '@/types/api';
import terminalSource from '../SessionTerminal.tsx?raw';

const mockGetSessionTerminal = vi.fn();
const mockCloseTmuxSessions = vi.fn();

vi.mock('../../../api', () => ({
  getSessionTerminal: (...args: unknown[]) => mockGetSessionTerminal(...args),
  closeTmuxSessions: (...args: unknown[]) => mockCloseTmuxSessions(...args),
}));

import {
  buildTerminalSnippet,
  lastActivityTs,
  resolveTerminalEmptyState,
  SessionTerminal,
} from '../SessionTerminal';

const NOW = 1_776_000_000_000;

function makeSession(over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: '11111111-2222-4333-8444-555555555555',
    family: 'claude-code',
    title: '排查终端空状态',
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 3600_000,
    last_active_at: NOW - 600_000,
    last_reply_at: NOW - 600_000,
    agent_paths: [],
    status: 'idle',
    digest_done: '已经完成初步核对',
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    relation: null,
    in_tmux: false,
    tmux_name: null,
    alive: false,
    ...over,
  };
}

function makeSnapshot(over: Partial<SessionTerminalSnapshot> = {}): SessionTerminalSnapshot {
  return {
    session_id: '11111111-2222-4333-8444-555555555555',
    alive: false,
    tmux_name: null,
    pane_command: '',
    client_alive: false,
    busy: false,
    memory_mb: 0,
    source: 'none',
    content: '',
    hosting_mode: 'unmounted',
    resumable: true,
    unmount_reason: 'not_mounted',
    ...over,
  };
}

describe('SessionTerminal 空状态与本体映射', () => {
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeAll(async () => {
    await i18n.changeLanguage('zh');
  });

  beforeEach(() => {
    mockGetSessionTerminal.mockReset();
    mockCloseTmuxSessions.mockReset();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    writeText.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('源码中禁止在空态使用硬编码深黑底或失效 Tailwind 色板类', () => {
    const src = terminalSource;
    expect(src).not.toMatch(/emerald-|amber-|red-/);
    expect(src).not.toMatch(/\bborder-border(?!-)|\bborder-border-hover\b/);
    expect(src).not.toMatch(/var\([^)]+\)\/\d+/);
    // #0d1117 仅允许出现在有内容终端屏条件块内，不得包在最外层空态
    const matches = src.match(/bg-\[#0d1117\]/g) ?? [];
    expect(matches).toHaveLength(1);
  });

  it('resolveTerminalEmptyState 覆盖后台无头运行、待启动、已结束、待命与异常五种语义', () => {
    const baseSession = makeSession();
    expect(
      resolveTerminalEmptyState({
        session: baseSession,
        snapshot: makeSnapshot({ hosting_mode: 'headless_subprocess' }),
        sessionRunning: false,
        recordCounts: { all: 4, talk: 2 },
      }).kind
    ).toBe('headless_running');

    expect(
      resolveTerminalEmptyState({
        session: baseSession,
        snapshot: makeSnapshot(),
        usage: { model: '<synthetic>', context: null, total: null },
        recordCounts: { all: 2, talk: 0 },
      }).kind
    ).toBe('never_started');

    expect(
      resolveTerminalEmptyState({
        session: makeSession({ status: 'done' }),
        snapshot: makeSnapshot(),
        recordCounts: { all: 6, talk: 4 },
      }).kind
    ).toBe('completed');

    const errSpec = resolveTerminalEmptyState({
      session: makeSession({ status: 'error', digest_stuck: 'API 401' }),
      snapshot: makeSnapshot(),
      recordCounts: { all: 5, talk: 3 },
    });
    expect(errSpec.kind).toBe('dormant');
    expect(errSpec.tone).toBe('error');
    expect(errSpec.errorSummary).toBe('API 401');
  });

  it('buildTerminalSnippet 在无历史时降级为目录命令，CoreAgent 不重复拼 --cwd', () => {
    const claude = makeSession({ directory: '/tmp/my dir' });
    expect(buildTerminalSnippet(claude, true)).toEqual({
      mode: 'resume',
      command: "cd '/tmp/my dir' && claude --resume 11111111-2222-4333-8444-555555555555",
    });
    expect(buildTerminalSnippet(claude, false)).toEqual({
      mode: 'cd',
      command: "cd '/tmp/my dir'",
    });

    const core = makeSession({
      session_id: 'core_abc123',
      family: 'coreagent',
      directory: '/Users/frago/Repos/frago',
    });
    expect(buildTerminalSnippet(core, true)).toEqual({
      mode: 'resume',
      command: 'frago-core --resume core_abc123 --cwd /Users/frago/Repos/frago',
    });
  });

  it('待命空态下不渲染黑色屏幕与无意义的「自动贴底」，完整展示元数据与引导动作', async () => {
    mockGetSessionTerminal.mockResolvedValue(makeSnapshot());
    const onSwitchToTalk = vi.fn();
    const onFocusComposer = vi.fn();

    render(
      <SessionTerminal
        sessionId="11111111-2222-4333-8444-555555555555"
        open
        session={makeSession()}
        usage={null}
        recordCounts={{ all: 12, talk: 5 }}
        onSwitchToTalk={onSwitchToTalk}
        onFocusComposer={onFocusComposer}
      />
    );

    const card = await screen.findByText('实时终端已关闭，会话处于待命状态');
    expect(card).toBeTruthy();
    expect(document.querySelector('[data-terminal-screen]')).toBeNull();
    // 空状态下不渲染「自动贴底」按钮
    expect(screen.queryByText('自动贴底')).toBeNull();

    // 元数据诚实降级
    const grid = screen.getByTestId('terminal-session-snapshot');
    expect(grid.textContent).toContain('Claude Code');
    expect(grid.textContent).toContain('模型未记录');
    expect(grid.textContent).toContain('12 条记录 · 5 条对话');
    expect(grid.textContent).toContain('上下文 未记录');
    expect(grid.textContent).toContain('11111111');

    // 三大引导动作闭环
    fireEvent.click(screen.getByTestId('terminal-empty-focus-composer'));
    expect(onFocusComposer).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('terminal-empty-copy-cmd'));
    expect(writeText).toHaveBeenCalledWith(
      'cd /Users/frago/Repos/frago && claude --resume 11111111-2222-4333-8444-555555555555'
    );

    fireEvent.click(screen.getByTestId('terminal-empty-switch-talk'));
    expect(onSwitchToTalk).toHaveBeenCalledTimes(1);
  });

  it('后台无头运行态主推「切回对话」，不可续接态诚实提示并隐藏 --resume 命令', async () => {
    mockGetSessionTerminal.mockResolvedValue(
      makeSnapshot({ hosting_mode: 'headless_subprocess', unmount_reason: 'headless_running' })
    );

    const { rerender } = render(
      <SessionTerminal
        sessionId="core_1"
        open
        session={makeSession({ session_id: 'core_1', family: 'coreagent', status: 'running' })}
        sessionRunning
        recordCounts={{ all: 4, talk: 2 }}
        onSwitchToTalk={vi.fn()}
        onFocusComposer={vi.fn()}
      />
    );

    expect(await screen.findByTestId('terminal-empty-primary-talk')).toBeTruthy();
    expect(screen.getByTestId('terminal-empty-pill').textContent).toContain('后台运行中');

    mockGetSessionTerminal.mockResolvedValue(
      makeSnapshot({ hosting_mode: 'unmounted', resumable: false, unmount_reason: 'session_gone' })
    );
    rerender(
      <SessionTerminal
        sessionId="ses_gone"
        open
        session={makeSession({ session_id: 'ses_gone', family: 'opencode', status: 'idle' })}
        recordCounts={{ all: 3, talk: 1 }}
        onSwitchToTalk={vi.fn()}
        onFocusComposer={vi.fn()}
      />
    );

    expect(await screen.findByTestId('terminal-empty-unresumable')).toBeTruthy();
    expect(screen.getByTestId('terminal-empty-unresumable').textContent).toContain(
      '原始会话记录已不在本机磁盘上'
    );
    // 不可续接时不生成 --resume 命令
    expect(screen.getByText('cd /Users/frago/Repos/frago')).toBeTruthy();
    expect(screen.queryByTestId('terminal-empty-focus-composer')).toBeNull();
  });

  it('在空态下底部发消息唤醒会话后，自动轮询捕获新拉起的 tmux 屏幕', async () => {
    vi.useFakeTimers();
    mockGetSessionTerminal
      .mockResolvedValueOnce(makeSnapshot())
      .mockResolvedValueOnce(makeSnapshot())
      .mockResolvedValueOnce(
        makeSnapshot({
          alive: true,
          source: 'tmux',
          hosting_mode: 'tmux',
          tmux_name: 'frago-agent-11111111-2222-4333-8444-555555555555',
          content: '\x1b[32mResumed live session\x1b[0m',
        })
      );

    const { rerender } = render(
      <SessionTerminal
        sessionId="11111111-2222-4333-8444-555555555555"
        open
        session={makeSession()}
        sessionRunning={false}
        recordCounts={{ all: 4, talk: 2 }}
      />
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(mockGetSessionTerminal).toHaveBeenCalledTimes(1);

    // 用户在底部输入框发送消息，sessionRunning 变为 true
    rerender(
      <SessionTerminal
        sessionId="11111111-2222-4333-8444-555555555555"
        open
        session={makeSession()}
        sessionRunning
        recordCounts={{ all: 4, talk: 2 }}
      />
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(mockGetSessionTerminal).toHaveBeenCalledTimes(2);

    // 2 秒轮询捕获到新起的 tmux 屏幕
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(mockGetSessionTerminal).toHaveBeenCalledTimes(3);
    const screenEl = document.querySelector('[data-terminal-screen]');
    expect(screenEl?.textContent).toContain('Resumed live session');
  });

  it('从 Progress 切换到 Terminal 首帧与请求在途期间展示加载态，不抢跑闪现无 tmux 诊断卡', async () => {
    let resolveFetch!: (val: SessionTerminalSnapshot) => void;
    mockGetSessionTerminal.mockReturnValue(
      new Promise<SessionTerminalSnapshot>((r) => {
        resolveFetch = r;
      })
    );
    const onAliveChange = vi.fn();

    render(
      <SessionTerminal
        sessionId="d3bfe101-011a-4a25-b3e9-7ab2b667947a"
        open
        session={makeSession({
          session_id: 'd3bfe101-011a-4a25-b3e9-7ab2b667947a',
          family: 'agy',
          status: 'running',
          in_tmux: true,
        })}
        sessionRunning
        recordCounts={{ all: 803, talk: 149 }}
        onAliveChange={onAliveChange}
      />
    );

    // 挂载首帧与请求返回前：必须显示加载胶囊与加载指示，严禁闪现空状态诊断卡
    expect(screen.getByTestId('terminal-loading-pill')).toBeTruthy();
    expect(screen.getByTestId('terminal-initial-loading')).toBeTruthy();
    expect(document.querySelector('[data-terminal-empty]')).toBeNull();
    expect(screen.queryByTestId('terminal-empty-pill')).toBeNull();

    // 接口返回未挂载快照后，同帧通知外层熄灭绿点并展示待命诊断卡
    await act(async () => {
      resolveFetch(makeSnapshot({ session_id: 'd3bfe101-011a-4a25-b3e9-7ab2b667947a', alive: false, hosting_mode: 'unmounted' }));
      await Promise.resolve();
    });

    expect(onAliveChange).toHaveBeenCalledWith(false);
    expect(document.querySelector('[data-terminal-empty]')?.getAttribute('data-empty-kind')).toBe(
      'dormant'
    );
  });

  it('活跃 tmux 窗格即使屏幕内容为空也渲染终端屏幕，不误入无 tmux 诊断卡片', async () => {
    mockGetSessionTerminal.mockResolvedValue(
      makeSnapshot({
        alive: true,
        source: 'tmux',
        hosting_mode: 'tmux',
        tmux_name: 'frago-agent-11111111-2222-4333-8444-555555555555',
        content: '',
      })
    );

    render(
      <SessionTerminal
        sessionId="11111111-2222-4333-8444-555555555555"
        open
        session={makeSession({ in_tmux: true, status: 'running' })}
        sessionRunning
        recordCounts={{ all: 10, talk: 4 }}
      />
    );

    expect(await screen.findByText('tmux 运行中')).toBeTruthy();
    expect(document.querySelector('[data-terminal-screen]')).toBeTruthy();
    expect(document.querySelector('[data-terminal-empty]')).toBeNull();
  });

  it('hosting_mode=unmounted 且无前端在途回合时不假阳性报 headless_running，且 lastActivityTs 取最新活动时刻', () => {
    const staleRunningSession = makeSession({
      session_id: 'd3bfe101-011a-4a25-b3e9-7ab2b667947a',
      family: 'agy',
      status: 'running',
      in_tmux: true,
      last_reply_at: NOW - 14 * 60_000,
      last_active_at: NOW - 4 * 60_000,
    });

    // 最近活跃时间应取较新的 last_active_at（4 分钟前）而非 last_reply_at（14 分钟前）
    expect(lastActivityTs(staleRunningSession)).toBe(NOW - 4 * 60_000);

    // 后端实测 unmounted 时，不应因陈旧 status='running' 或等待 worker 而假阳性报 headless_running
    const spec = resolveTerminalEmptyState({
      session: staleRunningSession,
      snapshot: makeSnapshot({ alive: false, hosting_mode: 'unmounted' }),
      sessionRunning: true,
      awaitingTurn: false,
      recordCounts: { all: 803, talk: 149 },
    });
    expect(spec.kind).toBe('dormant');

    // 当用户刚在底部发送消息（awaitingTurn=true）且非陈旧 tmux 状态时，允许提示后台拉起/运行中
    const wakingSpec = resolveTerminalEmptyState({
      session: makeSession({ in_tmux: false, status: 'idle' }),
      snapshot: makeSnapshot({ alive: false, hosting_mode: 'unmounted' }),
      sessionRunning: true,
      awaitingTurn: true,
      recordCounts: { all: 12, talk: 5 },
    });
    expect(wakingSpec.kind).toBe('headless_running');
  });
});
