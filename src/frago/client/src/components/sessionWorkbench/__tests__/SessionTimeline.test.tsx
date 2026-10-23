/**
 * 用量日历与 Timeline 合一浮窗测试：
 * - 首先展示日历网格与每日 token 用量；
 * - 点击日期单元格后切换为左侧竖排顺序日期（[n, n+3] 个）+ 右侧 Timeline；
 * - 右上角多组 Tag 关键词输入框按会话标题或用户自定义标题交叉筛选（允许跨日期）；
 * - 窗口档位、父子分组、捡回今天、选中与关闭。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import SessionTimeline from '../SessionTimeline';
import {
  MAX_VISIBLE_DATE_CELLS,
  MIN_VISIBLE_DATE_CELLS,
  toDateKey,
} from '../tokenCalendarUtils';

vi.mock('@/api', () => ({
  getTokenCalendar: vi.fn(async (month: string) => ({
    month,
    days: {
      [`${month}-15`]: {
        input: 100_000,
        output: 50_000,
        cache_creation: 0,
        cache_read: 0,
        total: 150_000,
      },
    },
    month_total: {
      input: 1_000_000,
      output: 500_000,
      cache_creation: 0,
      cache_read: 0,
      total: 1_500_000,
    },
  })),
}));

/**
 * jsdom 没有布局，真正的 Virtuoso 量不出视口，档位切换后一行都不渲染。
 * 用例里换成「把 data 全部摆出来」的替身。
 */
vi.mock('react-virtuoso', () => ({
  Virtuoso: ({
    data,
    itemContent,
    scrollerRef,
  }: {
    data: unknown[];
    itemContent: (index: number, item: unknown) => ReactNode;
    scrollerRef?: (ref: HTMLElement | null) => void;
  }) => (
    <div ref={(el) => scrollerRef?.(el)}>
      {data.map((item, index) => (
        <div key={index}>{itemContent(index, item)}</div>
      ))}
    </div>
  ),
}));

import type { SessionTodayState } from '@/hooks/useSessionToday';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

function session(
  over: Partial<WorkbenchSession> & { session_id: string }
): WorkbenchSession {
  const now = Date.now();
  return {
    family: 'claude-code',
    title: over.session_id,
    directory: '/tmp',
    created_at: now - HOUR,
    last_active_at: now,
    last_reply_at: now - 10 * 60_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

function todayState(over: Partial<SessionTodayState> = {}): SessionTodayState {
  return {
    picked: [],
    isPicked: () => false,
    toggle: vi.fn(async () => {}),
    today: toDateKey(new Date()),
    refresh: vi.fn(async () => {}),
    ...over,
  };
}

function ids(): string[] {
  return screen
    .queryAllByTestId('timeline-lane')
    .map((el) => el.getAttribute('data-session-id') ?? '');
}

function renderTimeline(
  sessions: WorkbenchSession[],
  opts: {
    today?: SessionTodayState;
    onSelect?: (id: string) => void;
    onClose?: () => void;
    initialDate?: string | null;
  } = {}
) {
  return render(
    <SessionTimeline
      sessions={sessions}
      selectedId={null}
      today={opts.today ?? todayState()}
      onSelect={opts.onSelect ?? (() => {})}
      onClose={opts.onClose ?? (() => {})}
      initialDate={opts.initialDate ?? null}
    />
  );
}

describe('SessionTimeline (Merged Token Calendar & Timeline)', () => {
  it('首先展示日历网格，点击日期单元格后左侧展示 [n, n+3] 个顺序日期、右侧展示 Timeline', async () => {
    const now = Date.now();
    const todayKey = toDateKey(new Date(now));
    const sToday = session({
      session_id: 'today-sess',
      created_at: now - 2 * HOUR,
      last_reply_at: now - HOUR,
    });

    renderTimeline([sToday]);

    // 1. 初始展示月历网格，尚未展开右侧 Timeline
    expect(screen.getByTestId('timeline-calendar-grid')).toBeTruthy();
    expect(screen.queryByTestId('timeline-pane')).toBeNull();
    await waitFor(() => {
      expect(screen.getByTestId('calendar-month-total').textContent).toContain('1.5M');
    });
    const currentMonth = todayKey.slice(0, 7);
    const activeTokenCell = screen.getByTestId(`calendar-cell-${currentMonth}-15`);
    expect(activeTokenCell.textContent).toContain('150K');
    expect(activeTokenCell.textContent).toContain('100K');
    expect(activeTokenCell.textContent).toContain('50K');
    const emptyDayKey = todayKey.endsWith('-02') ? `${currentMonth}-03` : `${currentMonth}-02`;
    expect(screen.getByTestId(`calendar-cell-${emptyDayKey}`).textContent).not.toContain('—');

    // 2. 点击今天的日期单元格，切换为左竖排日期 + 右 Timeline
    fireEvent.click(screen.getByTestId(`calendar-cell-${todayKey}`));
    expect(screen.queryByTestId('timeline-calendar-grid')).toBeNull();
    expect(screen.getByTestId('timeline-date-rail')).toBeTruthy();
    expect(screen.getByTestId('timeline-pane')).toBeTruthy();

    // 左侧竖排日期个数严格在 [n, n+3] 之间，且按日期顺序排列
    const dayCells = screen.getAllByTestId('timeline-day-cell');
    expect(dayCells.length).toBeGreaterThanOrEqual(MIN_VISIBLE_DATE_CELLS);
    expect(dayCells.length).toBeLessThanOrEqual(MAX_VISIBLE_DATE_CELLS);
    const renderedDates = dayCells.map((el) => el.getAttribute('data-date') ?? '');
    expect(renderedDates).toContain(todayKey);
    const sortedDates = [...renderedDates].sort();
    expect(renderedDates).toEqual(sortedDates);

    // 点击左栏里另一个可见日期卡片，卡片原地高亮，左栏日期列表绝不跳动或自动居中
    const anotherCell = dayCells.find((el) => el.getAttribute('data-date') !== todayKey) ?? dayCells[0];
    const anotherDate = anotherCell.getAttribute('data-date') ?? '';
    fireEvent.click(anotherCell);
    const afterClickDates = screen
      .getAllByTestId('timeline-day-cell')
      .map((el) => el.getAttribute('data-date') ?? '');
    expect(afterClickDates).toEqual(renderedDates);
    expect(
      screen
        .getAllByTestId('timeline-day-cell')
        .find((el) => el.getAttribute('data-date') === anotherDate)
        ?.getAttribute('aria-pressed')
    ).toBe('true');

    // 切回今天，右侧 Timeline 展示了今天的会话
    const todayRailCell = screen
      .getAllByTestId('timeline-day-cell')
      .find((el) => el.getAttribute('data-date') === todayKey);
    if (todayRailCell) fireEvent.click(todayRailCell);
    expect(ids()).toContain('today-sess');

    // 3. 点「返回月历」回到全月网格
    fireEvent.click(screen.getByTestId('timeline-back-calendar'));
    expect(screen.getByTestId('timeline-calendar-grid')).toBeTruthy();
  });

  it('分栏模式下档位显式摆出，从 24h 切到 7d / 30d 能看到对应跨度的会话', async () => {
    const now = Date.now();
    const todayKey = toDateKey(new Date(now));
    const fresh = session({
      session_id: 'fresh',
      created_at: now - HOUR,
      last_reply_at: now - 10 * 60_000,
    });
    const twoDays = session({
      session_id: 'two-days',
      created_at: now - 2 * DAY,
      last_reply_at: now - 2 * DAY + HOUR,
    });
    const tenDays = session({
      session_id: 'ten-days',
      created_at: now - 10 * DAY,
      last_reply_at: now - 10 * DAY + HOUR,
    });
    renderTimeline([fresh, twoDays, tenDays], { initialDate: todayKey });

    // 点选日期进来默认聚焦当天，切到 7d 档位能看到两天前的会话
    fireEvent.click(screen.getByTestId('timeline-span-168'));
    expect(ids()).toContain('fresh');
    expect(ids()).toContain('two-days');
    expect(ids()).not.toContain('ten-days');

    // 切到 30 天，十天前的那场进来
    fireEvent.click(screen.getByTestId('timeline-span-720'));
    await waitFor(() => expect(ids()).toContain('ten-days'));
    expect(screen.getByTestId('timeline-span-all')).toBeTruthy();
  });

  it('右上角多组 Tag 关键词输入框支持按会话标题与用户自定义标题跨日期交叉筛选', async () => {
    const now = Date.now();
    const s1 = session({
      session_id: 's1',
      title: '用户自定义：重构日历组件',
      custom_title: '用户自定义：重构日历组件',
      raw_title: 'Merge token calendar button with timeline',
      created_at: now - HOUR,
      last_reply_at: now - 10 * 60_000,
    });
    const s2 = session({
      session_id: 's2',
      title: '十天前的日历与 timeline 讨论',
      created_at: now - 10 * DAY,
      last_reply_at: now - 10 * DAY + HOUR,
    });
    const s3 = session({
      session_id: 's3',
      title: '只提到日历但没有另一个词',
      created_at: now - 2 * HOUR,
      last_reply_at: now - HOUR,
    });

    // 从初始日历态打开
    renderTimeline([s1, s2, s3]);
    expect(screen.getByTestId('timeline-calendar-grid')).toBeTruthy();

    const input = screen.getByTestId('timeline-filter-input');
    // 输入第一组 Tag "日历" 并回车
    fireEvent.change(input, { target: { value: '日历' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    // 自动切入跨日期分栏视图，s1、s2、s3 都含"日历"
    await waitFor(() => {
      expect(screen.getByTestId('timeline-pane')).toBeTruthy();
    });
    expect(ids()).toEqual(expect.arrayContaining(['s1', 's2', 's3']));

    // 再输入第二组 Tag "timeline" 并回车，交叉出同时含"日历"与"timeline"的会话（s1 靠自定义标题+原会话标题命中，s2 跨日期命中，s3 被排除）
    fireEvent.change(input, { target: { value: 'timeline' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      expect(ids()).toContain('s1');
      expect(ids()).toContain('s2');
      expect(ids()).not.toContain('s3');
    });
    expect(screen.getAllByTestId('timeline-filter-tag')).toHaveLength(2);
  });

  it('worker 紧跟在派活的那场下面，组内相邻', () => {
    const now = Date.now();
    const todayKey = toDateKey(new Date(now));
    const parent = session({
      session_id: 'p',
      created_at: now - 2 * HOUR,
      last_reply_at: now - HOUR,
    });
    const other = session({
      session_id: 'o',
      created_at: now - 90 * 60_000,
      last_reply_at: now - 80 * 60_000,
    });
    const kid = session({
      session_id: 'k',
      created_at: now - 50 * 60_000,
      last_reply_at: now - 40 * 60_000,
      origin: 'worker',
      parent_session_id: 'p',
    });
    renderTimeline([parent, other, kid], { initialDate: todayKey });
    expect(ids()).toEqual(['p', 'k', 'o']);
  });

  it('点「Today」把这场交给名单，不选中会话', () => {
    const now = Date.now();
    const todayKey = toDateKey(new Date(now));
    const s = session({
      session_id: 's1',
      created_at: now - 2 * HOUR,
      last_reply_at: now - HOUR,
    });
    const toggle = vi.fn(async () => {});
    const onSelect = vi.fn();
    renderTimeline([s], { today: todayState({ toggle }), onSelect, initialDate: todayKey });

    fireEvent.click(screen.getByTestId('timeline-today-s1'));
    expect(toggle).toHaveBeenCalledWith('s1');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('右端留出未来空白：现在线不贴在最右边，按钮不压今天结束的短条', () => {
    const now = Date.now();
    const todayKey = toDateKey(new Date(now));
    const s = session({
      session_id: 'short',
      created_at: now - 10 * 60_000,
      last_reply_at: now - 60_000,
    });
    renderTimeline([s], { initialDate: todayKey });
    const left = screen.getByTestId('timeline-now').style.left;
    const pct = Number(left.match(/([\d.]+)%/)?.[1]);
    expect(pct).toBeGreaterThan(85);
    expect(pct).toBeLessThan(96);
  });

  it('点一行打开那场会话', () => {
    const onSelect = vi.fn();
    const s = session({ session_id: 's1' });
    renderTimeline([s], { onSelect, initialDate: toDateKey(new Date()) });
    fireEvent.click(screen.getByTestId('timeline-lane'));
    expect(onSelect).toHaveBeenCalledWith('s1');
  });

  it('Esc 关闭', () => {
    const onClose = vi.fn();
    renderTimeline([session({ session_id: 's1' })], { onClose });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
