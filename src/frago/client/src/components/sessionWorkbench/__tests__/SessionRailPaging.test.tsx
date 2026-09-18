/**
 * 左栏分批加载的用例。
 *
 * 时间范围默认不限，本机七百多场会话一次全摆进去，滚动条被压成一道几乎没有长度的细缝，
 * 拖一下滑过几百场。清单因此改成一次放五十场，滚到底续下一批。
 *
 * 盯五件事：第一批只摆五十场、尾巴报得出还剩多少、滚到底续得上、换一个筛选档回到第一批、
 * 置顶那几场不受这一套管。
 */

import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import SessionRail from '../SessionRail';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

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
 * 窗口化列表换成整列直出，另外把尾巴那一块与「滚到底」这个动作接出来。
 *
 * jsdom 量不出视口高度，Virtuoso 自己不会触发滚到底；这一份用例问的是"够不够五十场、
 * 续不续得上"，滚动本身由 Virtuoso 负责。
 */
vi.mock('react-virtuoso', () => ({
  Virtuoso: ({
    data,
    itemContent,
    components,
    endReached,
  }: {
    data: unknown[];
    itemContent: (index: number, row: unknown) => React.ReactNode;
    components?: { Header?: () => React.ReactNode; Footer?: () => React.ReactNode };
    endReached?: (index: number) => void;
  }) => {
    const Footer = components?.Footer;
    return (
      <div>
        {(data ?? []).map((row, i) => (
          <div key={i}>{itemContent(i, row)}</div>
        ))}
        {Footer ? <Footer /> : null}
        <button
          type="button"
          data-testid="scroll-to-end"
          onClick={() => endReached?.(Math.max(0, (data?.length ?? 1) - 1))}
        />
      </div>
    );
  },
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
    status: 'all',
    setStatus: NOOP,
    days: 0,
    setDays: NOOP,
    counts: { all: rows.length, running: 0, error: 0, done: rows.length, idle: 0 },
    reload: async () => {},
    ...over,
  };
}

/** 编号排得出先后，好核对摆出来的是不是前五十场。 */
function trunkOf(n: number): WorkbenchSession[] {
  return Array.from({ length: n }, (_, i) =>
    session({ session_id: `main-${String(i).padStart(3, '0')}` })
  );
}

function shownCount(): number {
  return screen.queryAllByTestId('session-item').length;
}

beforeEach(() => {
  pins.pinned = [];
  pins.collapsed = false;
});

describe('SessionRail 分批加载', () => {
  it('七百多场只先摆五十场', () => {
    render(<SessionRail state={railState(trunkOf(765))} selectedId={null} onSelect={NOOP} />);
    expect(shownCount()).toBe(50);
  });

  it('摆的是最前面那五十场，次序不动', () => {
    render(<SessionRail state={railState(trunkOf(120))} selectedId={null} onSelect={NOOP} />);
    const items = screen.getAllByTestId('session-item');
    expect(items[0].textContent).toContain('main-000');
    expect(items[49].textContent).toContain('main-049');
  });

  it('尾巴上报得出这一刻放了多少、一共多少', () => {
    render(<SessionRail state={railState(trunkOf(765))} selectedId={null} onSelect={NOOP} />);
    const progress = screen.getByTestId('rail-page-progress');
    expect(progress.textContent).toContain('50');
    expect(progress.textContent).toContain('765');
  });

  it('滚到底续上下一批', () => {
    render(<SessionRail state={railState(trunkOf(765))} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('scroll-to-end'));
    expect(shownCount()).toBe(100);
    fireEvent.click(screen.getByTestId('scroll-to-end'));
    expect(shownCount()).toBe(150);
  });

  it('一共不到五十场时，一次摆完且不报进度', () => {
    render(<SessionRail state={railState(trunkOf(12))} selectedId={null} onSelect={NOOP} />);
    expect(shownCount()).toBe(12);
    expect(screen.queryByTestId('rail-page-progress')).toBeNull();
  });

  it('全部摆完之后进度那一行自己收掉', () => {
    render(<SessionRail state={railState(trunkOf(60))} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('rail-page-progress')).toBeTruthy();
    fireEvent.click(screen.getByTestId('scroll-to-end'));
    expect(shownCount()).toBe(60);
    expect(screen.queryByTestId('rail-page-progress')).toBeNull();
  });

  it('换一个筛选档就回到第一批——那几页是上一批会话的进度', () => {
    const rows = trunkOf(765);
    const { rerender } = render(
      <SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />
    );
    fireEvent.click(screen.getByTestId('scroll-to-end'));
    expect(shownCount()).toBe(100);
    rerender(
      <SessionRail state={railState(rows, { status: 'done' })} selectedId={null} onSelect={NOOP} />
    );
    expect(shownCount()).toBe(50);
  });

  it('置顶那几场不受这一套管，排在第几都摆得出来', () => {
    const rows = trunkOf(765);
    pins.pinned = ['main-700'];
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    const titles = screen.getAllByTestId('session-item').map((el) => el.textContent ?? '');
    expect(titles.some((title) => title.includes('main-700'))).toBe(true);
  });
});

describe('SessionRail 分批加载与末尾那一区', () => {
  const rows = [
    ...trunkOf(60),
    ...Array.from({ length: 10 }, (_, i) =>
      session({ session_id: `loner-${i}`, origin: 'worker', parent_session_id: null })
    ),
  ];

  it('折着的时候一条都不占名额，主干照样先摆五十场', () => {
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(shownCount()).toBe(50);
  });

  it('点开那一区就看得见里面的会话，不是一个空标题', () => {
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('workers-header'));
    // 主干 60 场此时也一并摆开：名额提到了主干之后再加一批。
    expect(shownCount()).toBe(70);
  });
});
