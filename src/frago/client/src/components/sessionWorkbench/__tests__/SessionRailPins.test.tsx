/**
 * 左栏置顶区的用例。
 *
 * 盯五件事：一场都没置顶时什么都不多出来、置顶的那几场单独成区且不在下面重复出现、
 * 整片折得起来且折起来后还看得见有几场、次序照置顶的次序而不是活动时刻、数量不设上限。
 *
 * 名单怎么存、怎么发请求由 `useSessionPins` 那份用例把关，这里把它整个换成替身——左栏
 * 的责任只是"照名单把清单摆成两片"。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import SessionRail from '../SessionRail';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const OC_SID = 'ses_058288655ffeYMxYC1AZKCcv56';
const CX_SID = '01a01a98-82e9-7013-b24e-e5e91b03995a';

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
    searched: rows,
    loading: false,
    error: null,
    search: '',
    setSearch: NOOP,
    status: 'all',
    setStatus: NOOP,
    days: 0,
    setDays: NOOP,
    counts: { all: rows.length, running: 0, error: 0, done: rows.length, idle: 0 },
    content: { query: '', matches: new Map(), searching: false, warnings: [], error: null },
    reload: async () => {},
    ...over,
  };
}

function titles(): string[] {
  return screen.getAllByTestId('session-item').map((el) => el.textContent ?? '');
}

beforeEach(() => {
  pins.pinned = [];
  pins.collapsed = false;
  pins.toggle.mockClear();
  pins.setCollapsed.mockClear();
});

describe('SessionRail 置顶区', () => {
  const rows = [session({ session_id: SID }), session({ session_id: OC_SID }), session({ session_id: CX_SID })];

  it('一场都没置顶时不长分区标题', () => {
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByTestId('pinned-header')).toBeNull();
    expect(screen.queryByTestId('rest-header')).toBeNull();
    expect(screen.getAllByTestId('session-item')).toHaveLength(3);
  });

  it('每张卡上都有置顶开关', () => {
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getAllByTestId('toggle-pin')).toHaveLength(3);
  });

  it('点图钉把这场交给置顶名单', () => {
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getAllByTestId('toggle-pin')[0]);
    expect(pins.toggle).toHaveBeenCalledWith(SID);
  });

  it('点图钉不会顺手把这场会话选中', () => {
    const onSelect = vi.fn();
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId('toggle-pin')[0]);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('置顶的那几场单独成区，排在最前', () => {
    pins.pinned = [OC_SID];
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('pinned-header').textContent).toContain('置顶');
    expect(titles()[0]).toContain(OC_SID);
  });

  it('置顶的那场不在下面再出现一次', () => {
    pins.pinned = [OC_SID];
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(titles().filter((t) => t.includes(OC_SID))).toHaveLength(1);
    expect(screen.getByTestId('rest-header').textContent).toContain('2');
  });

  it('置顶区的次序照置顶的次序，不按活动时刻重排', () => {
    // 名单里 codex 那场在前，可它的活动时刻比另一场旧——置顶区要听名单的。
    pins.pinned = [CX_SID, OC_SID];
    const withTimes = [
      session({ session_id: SID }),
      session({ session_id: OC_SID, last_active_at: 1_753_900_000_000 }),
      session({ session_id: CX_SID, last_active_at: 1_753_100_000_000 }),
    ];
    render(<SessionRail state={railState(withTimes)} selectedId={null} onSelect={NOOP} />);
    const shown = titles();
    expect(shown[0]).toContain(CX_SID);
    expect(shown[1]).toContain(OC_SID);
  });

  it('折起来之后置顶那几场不再摆出来', () => {
    pins.pinned = [OC_SID];
    pins.collapsed = true;
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(titles().some((t) => t.includes(OC_SID))).toBe(false);
  });

  it('折起来之后仍报得出折掉了几场', () => {
    pins.pinned = [OC_SID, CX_SID];
    pins.collapsed = true;
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    // 不报的话，人看不出自己折掉了什么。
    expect(screen.getByTestId('pinned-header').textContent).toContain('2');
  });

  it('点分区标题就把整片折起来 / 摊开', () => {
    pins.pinned = [OC_SID];
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    const header = screen.getByTestId('pinned-header');
    expect(header.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(header);
    expect(pins.setCollapsed).toHaveBeenCalledWith(true);
  });

  it('置顶数量不设上限', () => {
    const many = Array.from({ length: 120 }, (_, i) => session({ session_id: `ses_${i}` }));
    pins.pinned = many.map((s) => s.session_id);
    render(<SessionRail state={railState(many)} selectedId={null} onSelect={NOOP} />);
    // 上限是替人做决定。名单报的是真数，不是截断后的数。
    expect(screen.getByTestId('pinned-header').textContent).toContain('120');
  });

  it('置顶区不跟状态与时间范围走', () => {
    // 人点了「在跑」，清单只剩一场；置顶的那场是「已完成」，它仍该留在置顶区。
    pins.pinned = [OC_SID];
    const state = railState(rows, {
      visible: [rows[0]],
      searched: rows,
      status: 'running',
      days: 7,
    });
    render(<SessionRail state={state} selectedId={null} onSelect={NOOP} />);
    expect(titles().some((t) => t.includes(OC_SID))).toBe(true);
  });

  it('置顶区跟着搜索走', () => {
    // 这一刻人在找某一场，置顶区摆出搜不着的那几场只会答非所问。
    pins.pinned = [OC_SID];
    const state = railState(rows, { visible: [rows[0]], searched: [rows[0]], search: '找某一场' });
    render(<SessionRail state={state} selectedId={null} onSelect={NOOP} />);
    expect(titles().some((t) => t.includes(OC_SID))).toBe(false);
  });

  it('名单里有编号、清单里没那场时就是不显示，也不报错', () => {
    // 会话档案被滚删了。NEVER 因此把编号从名单里踢掉——一次滚删不该清空人的置顶。
    pins.pinned = ['ses_已经被滚删的那场'];
    render(<SessionRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('pinned-header').textContent).toContain('0');
    expect(screen.getAllByTestId('session-item')).toHaveLength(3);
  });
});
