/**
 * 左栏分组区的用例。
 *
 * 盯的是左栏"照分组把主干摆成几区"这一件事：没标签时什么都不多出来、未分组排最前、
 * 标签按最近活动排、默认折起且折着报数、搜索时全摊开、筛过之后空区不长标题、置顶的
 * 不在分区里重复、worker 不长分组按钮、放进分组 / 删标签 / AI 分组各自交给数据源。
 *
 * 分组怎么存、怎么发请求不在这里管，这里把数据源整个换成替身。
 */

import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SessionRail from '../SessionRail';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';
import type { AiJobState, GroupTag } from '@/hooks/useSessionGroups';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const A = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const B = '11b13080-8fc5-6d81-a5bf-978d9392f407';
const C = '22c24191-9ad6-7e92-b6c0-a89ea4a3f518';
const W = '33d352a2-abe7-8fa3-c7d1-b9afb5b4a629';

const IDLE: AiJobState = {
  running: false,
  phase: null,
  done: 0,
  total: 0,
  assigned: 0,
  created_tags: 0,
  error: null,
  finished_at: null,
};

const groups = vi.hoisted(() => ({
  tags: [] as GroupTag[],
  map: {} as Record<string, string>,
  collapsed: {} as Record<string, boolean>,
  aiJob: null as unknown as AiJobState,
  assign: vi.fn(async () => {}),
  createTag: vi.fn(),
  deleteTag: vi.fn(async () => {}),
  runAi: vi.fn(async () => {}),
  toggleCollapsed: vi.fn(),
}));

const pins = vi.hoisted(() => ({ pinned: [] as string[] }));

vi.mock('@/hooks/useSessionPins', () => ({
  useSessionPins: () => ({
    pinned: pins.pinned,
    isPinned: (id: string) => pins.pinned.includes(id),
    toggle: vi.fn(),
    collapsed: false,
    setCollapsed: vi.fn(),
  }),
}));

vi.mock('@/hooks/useSessionGroups', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useSessionGroups')>(
    '@/hooks/useSessionGroups'
  );
  return {
    ...actual,
    useSessionGroups: () => ({
      tags: groups.tags,
      groupOf: (id: string) => groups.map[id] ?? null,
      sizeOf: (tagId: string) => Object.values(groups.map).filter((v) => v === tagId).length,
      assign: groups.assign,
      createTag: groups.createTag,
      deleteTag: groups.deleteTag,
      aiJob: groups.aiJob,
      runAi: groups.runAi,
      isCollapsed: (key: string) => groups.collapsed[key] ?? key !== actual.UNGROUPED,
      toggleCollapsed: groups.toggleCollapsed,
    }),
  };
});

/** 两个标记的替身：哪几场算「没看过」、哪几场算「开在 tmux 里」由用例说了算。 */
const marks = vi.hoisted(() => ({
  unread: new Set<string>(),
  inTmux: new Set<string>(),
  markViewed: vi.fn(),
}));

vi.mock('@/hooks/useSessionViews', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useSessionViews')>(
    '@/hooks/useSessionViews'
  );
  return {
    ...actual,
    useSessionViews: () => ({
      isUnread: (s: WorkbenchSession) => marks.unread.has(s.session_id),
      isInTmux: (s: WorkbenchSession) => marks.inTmux.has(s.session_id),
      markViewed: marks.markViewed,
    }),
  };
});

const NOOP = () => {};

function session(
  over: Partial<WorkbenchSession> & Pick<WorkbenchSession, 'session_id'>
): WorkbenchSession {
  return {
    family: 'claude-code',
    title: `会话 ${over.session_id}`,
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

function railState(
  rows: WorkbenchSession[],
  over: Partial<WorkbenchSessionsState> = {}
): WorkbenchSessionsState {
  return {
    sessions: rows,
    visible: rows,
    loading: false,
    error: null,
    status: 'all',
    setStatus: NOOP,
    days: 0,
    setDays: NOOP,
    counts: { all: rows.length, running: 0, error: 0, done: rows.length, idle: 0 },
    reload: async () => {},
    ...over,
  };
}

function headers(): string[] {
  return screen.queryAllByTestId('group-header').map((el) => el.textContent ?? '');
}

function titles(): string[] {
  return screen.queryAllByTestId('session-item').map((el) => el.textContent ?? '');
}

// 清单按最后活动时刻倒序：A 最新，C 最旧。
const rows = [
  session({ session_id: A, last_active_at: 1_753_900_000_000 }),
  session({ session_id: B, last_active_at: 1_753_800_000_000 }),
  session({ session_id: C, last_active_at: 1_753_700_000_000 }),
];

beforeEach(() => {
  groups.tags = [];
  groups.map = {};
  groups.collapsed = {};
  groups.aiJob = IDLE;
  groups.assign.mockClear();
  groups.createTag.mockClear();
  groups.deleteTag.mockClear();
  groups.runAi.mockClear();
  groups.toggleCollapsed.mockClear();
  pins.pinned = [];
  marks.unread = new Set();
  marks.inTmux = new Set();
  marks.markViewed.mockClear();
});

describe('SessionRail 分组区', () => {
  it('一个标签都没有时不长分区标题，清单照旧', () => {
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(headers()).toEqual([]);
    expect(titles()).toHaveLength(3);
  });

  it('未分组排最前，标签按组里最近一场的活动时刻排', () => {
    groups.tags = [
      { id: 't_old', name: '旧主题', source: 'human' },
      { id: 't_new', name: '新主题', source: 'ai' },
    ];
    groups.map = { [B]: 't_new', [C]: 't_old' };
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    const shown = headers();
    expect(shown[0]).toContain('未分组');
    expect(shown[1]).toContain('新主题');
    expect(shown[2]).toContain('旧主题');
  });

  it('标签默认折起：组里的会话不摆出来，标题上报数', () => {
    groups.tags = [{ id: 't1', name: '会话页', source: 'human' }];
    groups.map = { [B]: 't1', [C]: 't1' };
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(titles()).toHaveLength(1);
    expect(titles()[0]).toContain(A);
    expect(headers()[1]).toContain('2');
  });

  it('摊开的标签摆出组里的会话', () => {
    groups.tags = [{ id: 't1', name: '会话页', source: 'human' }];
    groups.map = { [B]: 't1' };
    groups.collapsed = { t1: false };
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(titles().some((t) => t.includes(B))).toBe(true);
  });

  it('点分区标题交给数据源去折 / 摊', () => {
    groups.tags = [{ id: 't1', name: '会话页', source: 'human' }];
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getAllByTestId('group-header')[1]);
    expect(groups.toggleCollapsed).toHaveBeenCalledWith('t1');
  });

  it('筛状态、时间范围时空标签照样摆出来', () => {
    groups.tags = [{ id: 't_empty', name: '刚建的', source: 'human' }];
    render(
      <SessionRail
        state={railState(rows, { status: 'running', days: 1 })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(headers().some((h) => h.includes('刚建的'))).toBe(true);
  });

  it('置顶的那场不在分区里再出现一次', () => {
    groups.tags = [{ id: 't1', name: '会话页', source: 'human' }];
    groups.map = { [A]: 't1' };
    groups.collapsed = { t1: false };
    pins.pinned = [A];
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(titles().filter((t) => t.includes(A))).toHaveLength(1);
    expect(screen.queryByTestId('rest-header')).toBeNull();
  });

  it('点「放进分组」挑一个标签，交给数据源', async () => {
    groups.tags = [{ id: 't1', name: '会话页', source: 'human' }];
    const onSelect = vi.fn();
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId('pick-group')[0]);
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('group-option'));
    await waitFor(() => expect(groups.assign).toHaveBeenCalledWith(A, 't1'));
  });

  it('在浮层里新建标签就把这场放进去', async () => {
    groups.createTag.mockResolvedValue({ id: 't_new', name: '新主题', source: 'human' });
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getAllByTestId('pick-group')[0]);
    const input = screen.getByTestId('group-new-input');
    fireEvent.change(input, { target: { value: '新主题' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(groups.assign).toHaveBeenCalledWith(A, 't_new'));
    expect(groups.createTag).toHaveBeenCalledWith('新主题');
  });

  it('worker 不长「放进分组」按钮', () => {
    const withWorker = [...rows, session({ session_id: W, origin: 'worker' })];
    render(<SessionRail state={railState(withWorker)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getAllByTestId('pick-group')).toHaveLength(3);
  });

  it('删标签要先确认', async () => {
    groups.tags = [{ id: 't1', name: '会话页', source: 'human' }];
    groups.map = { [B]: 't1' };
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('group-delete'));
    expect(groups.deleteTag).not.toHaveBeenCalled();
    expect(screen.getByText(/里面的 1 场会话回到未分组/)).toBeTruthy();
    fireEvent.click(screen.getByTestId('group-delete-confirm'));
    await waitFor(() => expect(groups.deleteTag).toHaveBeenCalledWith('t1'));
  });

  it('按 AI 分组交给数据源，在跑时报进度', () => {
    const { unmount } = render(
      <SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />
    );
    fireEvent.click(screen.getByTestId('group-ai'));
    expect(groups.runAi).toHaveBeenCalled();
    unmount();
    groups.aiJob = { ...IDLE, running: true, phase: 'assign', done: 120, total: 300 };
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('group-ai-status').textContent).toContain('120 / 300');
    expect((screen.getByTestId('group-ai') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('SessionRail 的两个标记', () => {
  it('没看过的那一场，卡上长一个绿圈', () => {
    marks.unread = new Set([B]);
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    const ringed = screen.getByTestId('session-unread').closest('[data-testid=session-item]');
    expect(ringed?.textContent).toContain(B);
    expect(screen.getAllByTestId('session-unread')).toHaveLength(1);
  });

  it('开在 tmux 里的那一场，卡外面长一圈流光', () => {
    marks.inTmux = new Set([A]);
    const { container } = render(
      <SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />
    );
    const framed = container.querySelectorAll('[data-live-edge="border"]');
    expect(framed).toHaveLength(1);
    expect(framed[0].textContent).toContain(A);
  });

  it('折起来的分区标题替组里那几场说这两件事', () => {
    groups.tags = [{ id: 't1', name: '会话页', source: 'human' }];
    groups.map = { [B]: 't1', [C]: 't1' };
    marks.unread = new Set([B]);
    marks.inTmux = new Set([C]);
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    // 组是折着的，里面的卡一张都不在页面上，所以这两件事只能由标题说。
    expect(screen.queryAllByTestId('session-item')).toHaveLength(1);
    expect(screen.getByTestId('group-unread')).toBeTruthy();
    expect(screen.getByTestId('group-in-tmux').textContent).toContain('会话页');
  });

  it('摊开之后标题不再画那圈边，改由组里的卡自己画', () => {
    groups.tags = [{ id: 't1', name: '会话页', source: 'human' }];
    groups.map = { [C]: 't1' };
    groups.collapsed = { t1: false };
    marks.inTmux = new Set([C]);
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByTestId('group-in-tmux')).toBeNull();
    const framed = document.querySelectorAll('[data-live-edge="border"]');
    expect(framed).toHaveLength(1);
    expect(framed[0].textContent).toContain(C);
  });

  it('点开一场会话就记一笔「看过了」', () => {
    const onSelect = vi.fn();
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId('session-item')[0]);
    expect(marks.markViewed).toHaveBeenCalledWith(A);
    expect(onSelect).toHaveBeenCalledWith(A);
  });
});
