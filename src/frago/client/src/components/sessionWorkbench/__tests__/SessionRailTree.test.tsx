/**
 * 左栏两层清单的用例：主干是主会话，frago 派出去的 worker 折在派活的那一场下面。
 *
 * 盯五件事：worker 默认不占主干、点开才露出来且看得出是从属的、派活那一行报得出条数、
 * 认不出谁派的那些收进单独一区且默认折着、搜索时整棵树摊开。
 *
 * 谁是 worker、谁派的活由服务端判完（每张卡带着 `origin` 与 `parent_session_id`），
 * 这里只核一件事：左栏有没有照着这两个字段把位置摆对。
 */

import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { TestRail, fakeForYou } from './railTestKit';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const BOSS = '7f55e46e-0cc5-4e80-8f4f-1debd649d7b0';
const WORKER_A = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const WORKER_B = '0f3df003-0bae-5de0-b532-2086923afa6e';
const LONER = '0589e94b-e2f1-522c-bd8d-4aea2cb7a373';

const pins = vi.hoisted(() => ({
  pinned: [] as string[],
  collapsed: false,
  toggle: vi.fn(async () => {}),
  setCollapsed: vi.fn(),
}));

vi.mock('@/hooks/useSessionPins', () => ({
  useSessionPins: () => ({
    pinned: pins.pinned,
    isPinned: (id: string) => pins.pinned.includes(id),
    toggle: pins.toggle,
    collapsed: pins.collapsed,
    setCollapsed: pins.setCollapsed,
  }),
}));

/**
 * 窗口化列表在这里换成整列直出。
 *
 * jsdom 量不出视口高度，Virtuoso 只渲染挂载那一刻的那几行，展开之后新长出来的行
 * 一个都不会出现——用例会因此红，而页面上是好的。这一份用例问的是"行摆得对不对"，
 * 窗口化本身由 Virtuoso 自己负责。
 */
vi.mock('react-virtuoso', () => ({
  Virtuoso: ({
    data,
    itemContent,
  }: {
    data: unknown[];
    itemContent: (index: number, row: unknown) => React.ReactNode;
  }) => <div>{(data ?? []).map((row, i) => <div key={i}>{itemContent(i, row)}</div>)}</div>,
}));

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
    filter: 'all',
    setFilter: NOOP,
    days: 0,
    setDays: NOOP,
    counts: { all: rows.length, 'for-you': 0 },
    reload: async () => {},
    ...over,
  };
}

function shownTitles(): string[] {
  return screen.getAllByTestId('session-item').map((el) => el.textContent ?? '');
}

beforeEach(() => {
  pins.pinned = [];
  pins.collapsed = false;
});

/** 一场主会话，底下派了两个 worker。 */
const FAMILY = [
  session({ session_id: BOSS }),
  session({ session_id: WORKER_A, origin: 'worker', parent_session_id: BOSS }),
  session({ session_id: WORKER_B, origin: 'worker', parent_session_id: BOSS }),
];

describe('SessionRail 两层清单', () => {
  it('派出去的 worker 默认不占主干', () => {
    render(<TestRail state={railState(FAMILY)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getAllByTestId('session-item')).toHaveLength(1);
    expect(shownTitles()[0]).toContain(BOSS);
  });

  it('派活那一行长成一叠纸，子会话数「› N」在状态行里（第五轮）', () => {
    render(<TestRail state={railState(FAMILY)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('session-item').getAttribute('data-stacked')).toBe('true');
    const toggle = screen.getByTestId('toggle-workers');
    expect(toggle.textContent).toBe('2');
    expect(toggle.closest('[data-testid=session-status]')).toBeTruthy();
    // 标题那一行不再放三角钮
    expect(screen.getByTestId('session-title').parentElement?.querySelector('[data-testid=toggle-workers]')).toBeNull();
  });

  it('展开之后那一叠就摊平了，不再画成一叠', () => {
    render(<TestRail state={railState(FAMILY)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('toggle-workers'));
    expect(screen.getAllByTestId('session-item')[0].getAttribute('data-stacked')).toBeNull();
  });

  it('条数仍报得出来，只是改用提示文字', () => {
    render(<TestRail state={railState(FAMILY)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('toggle-workers').getAttribute('title')).toContain('2');
  });

  it('点开才露出来，且标成从属', () => {
    render(<TestRail state={railState(FAMILY)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('toggle-workers'));
    const items = screen.getAllByTestId('session-item');
    expect(items).toHaveLength(3);
    // 主会话在最前，两个 worker 紧跟其后且带从属标记。
    expect(items[0].getAttribute('data-nested')).toBeNull();
    expect(items[1].getAttribute('data-nested')).toBe('true');
    expect(items[2].getAttribute('data-nested')).toBe('true');
    expect(items[1].getAttribute('data-origin')).toBe('worker');
  });

  it('点展开钮不会顺手把这场会话选中', () => {
    const onSelect = vi.fn();
    render(<TestRail state={railState(FAMILY)} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId('toggle-workers'));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('再点一下收回去', () => {
    render(<TestRail state={railState(FAMILY)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('toggle-workers'));
    fireEvent.click(screen.getByTestId('toggle-workers'));
    expect(screen.getAllByTestId('session-item')).toHaveLength(1);
  });

  it('没派过 worker 的那几场不长展开钮', () => {
    render(
      <TestRail state={railState([session({ session_id: BOSS })])} selectedId={null} onSelect={NOOP} />
    );
    expect(screen.queryByTestId('toggle-workers')).toBeNull();
  });
});

describe('SessionRail 分支会话不折', () => {
  const BRANCH = '9a1d2c3e-4b5f-4a6b-8c7d-0e1f2a3b4c5d';
  const rows = [
    session({ session_id: BOSS, title: '主线：全局字号' }),
    session({ session_id: WORKER_A, origin: 'worker', parent_session_id: BOSS }),
    session({
      session_id: BRANCH,
      title: '全局字号倍率处理',
      parent_session_id: BOSS,
      relation: { kind: 'branch', closed: false },
    }),
  ];

  it('分支和人开的会话一样摆在主干上，worker 照旧折在原会话下', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    const items = screen.getAllByTestId('session-item');
    expect(items).toHaveLength(2);
    const branch = items.find((el) => el.textContent?.includes('全局字号倍率处理'));
    expect(branch).toBeTruthy();
    expect(branch?.getAttribute('data-nested')).toBeNull();
    // 原会话那一叠只装 worker：条数是 1，不是 2
    expect(screen.getByTestId('toggle-workers').getAttribute('title')).toContain('1');
  });

  it('卡片上写出处，点它切到原会话、不选中分支本身', () => {
    const onSelect = vi.fn();
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={onSelect} />);
    const line = screen.getByTestId('branch-of');
    expect(line.textContent).toContain('分支自 主线：全局字号');
    fireEvent.click(line);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(BOSS);
  });

  it('分支停下等你：进 For you 那一组，不藏在原会话下', () => {
    render(
      <TestRail
        state={railState(rows)}
        selectedId={null}
        onSelect={NOOP}
        forYou={fakeForYou({
          [BRANCH]: { waitingSince: 1_753_800_000_000, words: '保留还是去掉？', unseen: true },
        })}
      />
    );
    expect(screen.getByTestId('for-you-header').textContent).toContain('1');
    const first = screen.getAllByTestId('session-item')[0];
    expect(first.textContent).toContain('全局字号倍率处理');
    expect(first.getAttribute('data-for-you')).toBe('true');
  });

  it('只有 worker 折；原会话被筛掉时分支照样在主干上', () => {
    const state = railState(rows, { visible: rows.filter((s) => s.session_id !== BOSS) });
    render(<TestRail state={state} selectedId={null} onSelect={NOOP} />);
    expect(shownTitles().some((t) => t.includes('全局字号倍率处理'))).toBe(true);
  });
});

describe('SessionRail 认不出谁派的那些 worker', () => {
  const rows = [
    session({ session_id: BOSS }),
    session({ session_id: LONER, origin: 'worker', parent_session_id: null }),
  ];

  it('单独成一区，默认折着', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('workers-header').textContent).toContain('不知道谁派的 worker');
    expect(shownTitles()).toHaveLength(1);
  });

  it('点标题才展开', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('workers-header'));
    expect(shownTitles()).toHaveLength(2);
  });

  it('一个都没有时连标题都不长', () => {
    render(
      <TestRail state={railState([session({ session_id: BOSS })])} selectedId={null} onSelect={NOOP} />
    );
    expect(screen.queryByTestId('workers-header')).toBeNull();
  });

  it('派活的那场被筛掉时，它的 worker 落到这一区，不会凭空消失', () => {
    // 主会话被状态筛掉（visible 里没有它），worker 还在。
    const state = railState(FAMILY, {
      visible: FAMILY.filter((s) => s.session_id !== BOSS),
    });
    render(<TestRail state={state} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('workers-header'));
    expect(screen.getAllByTestId('session-item')).toHaveLength(2);
  });
});
