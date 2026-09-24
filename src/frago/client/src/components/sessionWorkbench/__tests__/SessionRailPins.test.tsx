/**
 * 左栏置顶区的用例。
 *
 * 盯五件事：一场都没置顶时什么都不多出来、置顶的那几场单独成区且不在下面重复出现、
 * 整片折得起来且折起来后还看得见有几场、次序照置顶的次序而不是活动时刻、数量不设上限。
 *
 * 名单怎么存、怎么发请求由 `useSessionPins` 那份用例把关，这里把它整个换成替身——左栏
 * 的责任只是"照名单把清单摆成两片"。
 */

import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { TestRail } from './railTestKit';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

/**
 * 界面上的字全部走词表了，用例断言的是中文那一份，所以先把语言切到中文。
 *
 * 这一句顺带把另一件事也核了：`zh.json` 里的字必须与从前写死在组件里的逐字相同，
 * 差一个标点，下面这些断言就红。
 */
beforeAll(async () => {
  await i18n.changeLanguage('zh');
});


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
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByTestId('pinned-header')).toBeNull();
    expect(screen.queryByTestId('rest-header')).toBeNull();
    expect(screen.getAllByTestId('session-item')).toHaveLength(3);
  });

  it('每张卡上都有置顶开关', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getAllByTestId('toggle-pin')).toHaveLength(3);
  });

  it('点图钉把这场交给置顶名单', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getAllByTestId('toggle-pin')[0]);
    expect(pins.toggle).toHaveBeenCalledWith(SID);
  });

  it('点图钉不会顺手把这场会话选中', () => {
    const onSelect = vi.fn();
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId('toggle-pin')[0]);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('置顶的那几场单独成区，排在最前', () => {
    pins.pinned = [OC_SID];
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('pinned-header').textContent).toContain('置顶');
    expect(titles()[0]).toContain(OC_SID);
  });

  it('置顶的那场不在下面再出现一次', () => {
    pins.pinned = [OC_SID];
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
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
    render(<TestRail state={railState(withTimes)} selectedId={null} onSelect={NOOP} />);
    const shown = titles();
    expect(shown[0]).toContain(CX_SID);
    expect(shown[1]).toContain(OC_SID);
  });

  it('折起来之后置顶那几场不再摆出来', () => {
    pins.pinned = [OC_SID];
    pins.collapsed = true;
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(titles().some((t) => t.includes(OC_SID))).toBe(false);
  });

  it('折起来之后仍报得出折掉了几场', () => {
    pins.pinned = [OC_SID, CX_SID];
    pins.collapsed = true;
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    // 不报的话，人看不出自己折掉了什么。
    expect(screen.getByTestId('pinned-header').textContent).toContain('2');
  });

  it('点分区标题就把整片折起来 / 摊开', () => {
    pins.pinned = [OC_SID];
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    const header = screen.getByTestId('pinned-header');
    expect(header.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(header);
    expect(pins.setCollapsed).toHaveBeenCalledWith(true);
  });

  it('置顶数量不设上限', () => {
    const many = Array.from({ length: 120 }, (_, i) => session({ session_id: `ses_${i}` }));
    pins.pinned = many.map((s) => s.session_id);
    render(<TestRail state={railState(many)} selectedId={null} onSelect={NOOP} />);
    // 上限是替人做决定。名单报的是真数，不是截断后的数。
    expect(screen.getByTestId('pinned-header').textContent).toContain('120');
  });

  it('置顶区不跟状态与时间范围走', () => {
    // 人点了「在跑」，清单只剩一场；置顶的那场是「已完成」，它仍该留在置顶区。
    pins.pinned = [OC_SID];
    const state = railState(rows, {
      visible: [rows[0]],
      filter: 'for-you',
      days: 7,
    });
    render(<TestRail state={state} selectedId={null} onSelect={NOOP} />);
    expect(titles().some((t) => t.includes(OC_SID))).toBe(true);
  });

  it('名单里有编号、清单里没那场时就是不显示，也不报错', () => {
    // 会话档案被滚删了。NEVER 因此把编号从名单里踢掉——一次滚删不该清空人的置顶。
    pins.pinned = ['ses_已经被滚删的那场'];
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('pinned-header').textContent).toContain('0');
    expect(screen.getAllByTestId('session-item')).toHaveLength(3);
  });

  it('置顶按钮带字：没置顶的写「置顶」，置顶了写「取消置顶」，悬停说明点了会怎样', () => {
    pins.pinned = [OC_SID];
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    const buttons = screen.getAllByTestId('toggle-pin');
    const labels = buttons.map((b) => b.textContent);
    expect(labels).toContain('置顶');
    expect(labels).toContain('取消置顶');
    const unpin = buttons.find((b) => b.textContent === '取消置顶')!;
    expect(unpin.getAttribute('title')).toBe('取消置顶——放回原来的位置');
    // 不用品牌绿
    expect(buttons.every((b) => !b.className.includes('accent-primary'))).toBe(true);
  });

  it('置顶标题正常字重、正文色，右端写「一直在最上面」，不用绿', () => {
    pins.pinned = [OC_SID];
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    const header = screen.getByTestId('pinned-header');
    expect(header.textContent).toContain('一直在最上面');
    expect(header.outerHTML).not.toContain('text-accent-primary');
    expect(header.className).not.toContain('uppercase');
  });

  it('选中那条在折起的置顶组里：出现「当前会话在下面」，点一下先把置顶组摊开', () => {
    pins.pinned = [OC_SID];
    pins.collapsed = true;
    render(<TestRail state={railState(rows)} selectedId={OC_SID} onSelect={NOOP} />);
    const hint = screen.getByTestId('current-below');
    expect(hint.textContent).toContain('当前会话在下面');
    fireEvent.click(hint);
    expect(pins.setCollapsed).toHaveBeenCalledWith(false);
  });

  it('选中那条就在眼前时不出现提示行', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByTestId('current-below')).toBeNull();
  });
});
