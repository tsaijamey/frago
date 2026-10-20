/**
 * Timeline 浮窗：窗口、分组、捡回今天、选中与关闭。
 *
 * 尺寸量不出来（jsdom 没有布局）不影响这些用例：条的位置是像素，但**哪几场在窗口里、
 * 以什么次序摆、按钮改哪一份名单**都是纯数据判据，这里盯的就是这几条。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import SessionTimeline from '../SessionTimeline';

/**
 * jsdom 没有布局，真正的 Virtuoso 量不出视口，档位切换后一行都不渲染。
 * 用例里换成「把 data 全部摆出来」的替身：虚拟化本身由真实界面的实测把关，
 * 这里只盯「哪些会话进了窗口、以什么次序摆」。
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
    today: '2026-10-19',
    refresh: vi.fn(async () => {}),
    ...over,
  };
}

function ids(): string[] {
  return screen
    .getAllByTestId('timeline-lane')
    .map((el) => el.getAttribute('data-session-id') ?? '');
}

function renderTimeline(
  sessions: WorkbenchSession[],
  opts: {
    today?: SessionTodayState;
    onSelect?: (id: string) => void;
    onClose?: () => void;
  } = {}
) {
  return render(
    <SessionTimeline
      sessions={sessions}
      selectedId={null}
      today={opts.today ?? todayState()}
      onSelect={opts.onSelect ?? (() => {})}
      onClose={opts.onClose ?? (() => {})}
    />
  );
}

describe('SessionTimeline', () => {
  it('刚打开是最近 7 天；档位显式摆出，切到 30 天能看到十天前的会话', async () => {
    const now = Date.now();
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
    renderTimeline([fresh, twoDays, tenDays]);
    // 默认 7 天：两天前的在，十天前的不在。
    expect(ids()).toContain('fresh');
    expect(ids()).toContain('two-days');
    expect(ids()).not.toContain('ten-days');
    expect(screen.getByTestId('timeline-span-168').getAttribute('aria-pressed')).toBe('true');

    // 档位是显式的：点 30 天，十天前的那场进来。
    fireEvent.click(screen.getByTestId('timeline-span-720'));
    expect(screen.getByTestId('timeline-span-720').getAttribute('aria-pressed')).toBe('true');
    await waitFor(() => expect(ids()).toContain('ten-days'));
    expect(screen.getByTestId('timeline-span-all')).toBeTruthy();
  });

  it('worker 紧跟在派活的那场下面，组内相邻', () => {
    const now = Date.now();
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
    renderTimeline([parent, other, kid]);
    expect(ids()).toEqual(['p', 'k', 'o']);
  });

  it('点「Today」把这场交给名单，不选中会话', () => {
    const now = Date.now();
    const s = session({
      session_id: 's1',
      created_at: now - 2 * HOUR,
      last_reply_at: now - HOUR,
    });
    const toggle = vi.fn(async () => {});
    const onSelect = vi.fn();
    renderTimeline([s], { today: todayState({ toggle }), onSelect });

    fireEvent.click(screen.getByTestId('timeline-today-s1'));
    expect(toggle).toHaveBeenCalledWith('s1');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('右端留出未来空白：现在线不贴在最右边，按钮不压今天结束的短条', () => {
    const now = Date.now();
    const s = session({
      session_id: 'short',
      created_at: now - 10 * 60_000,
      last_reply_at: now - 60_000,
    });
    renderTimeline([s]);
    const left = screen.getByTestId('timeline-now').style.left;
    const pct = Number(left.match(/([\d.]+)%/)?.[1]);
    // 7 天窗口留 8%（约 13.4 小时）的未来空白，「现在」落在 93% 左右。
    expect(pct).toBeGreaterThan(85);
    expect(pct).toBeLessThan(96);
  });

  it('点一行打开那场会话', () => {
    const onSelect = vi.fn();
    const s = session({ session_id: 's1' });
    renderTimeline([s], { onSelect });
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
