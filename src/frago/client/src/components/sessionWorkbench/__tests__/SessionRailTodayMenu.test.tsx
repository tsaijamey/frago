/**
 * 左栏卡片「…」菜单里的「从今天移出」。
 *
 * 今天从 timeline 捡回来的会话，原先只有 timeline 的悬停按钮能放下，卡片菜单里找不到；
 * 主人在 2026-10-19 指出这一点。这里盯三件事：只有捡回来的那几场才长这一项、点下去把
 * 编号交给今天的名单、以及点它不会顺手选中会话。
 */

import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { TestRail } from './railTestKit';
import type { SessionTodayState } from '@/hooks/useSessionToday';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const pinsState = vi.hoisted(() => ({ pinned: [] as string[] }));

vi.mock('@/hooks/useSessionPins', () => ({
  useSessionPins: () => ({
    pinned: pinsState.pinned,
    isPinned: (id: string) => pinsState.pinned.includes(id),
    toggle: vi.fn(async () => {}),
    collapsed: false,
    setCollapsed: vi.fn(),
  }),
}));

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const OTHER = 'ses_058288655ffeYMxYC1AZKCcv56';

function session(
  sessionId: string,
  over: Partial<WorkbenchSession> = {}
): WorkbenchSession {
  return {
    session_id: sessionId,
    family: 'claude-code',
    title: `会话 ${sessionId}`,
    directory: '/Users/frago/Repos/frago',
    created_at: 1_753_700_000_000,
    last_active_at: 1_753_800_000_000,
    last_reply_at: 1_753_800_000_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

function railState(rows: WorkbenchSession[]): WorkbenchSessionsState {
  return {
    sessions: rows,
    visible: rows,
    todaySessions: rows,
    loading: false,
    error: null,
    filter: 'all',
    setFilter: () => {},
    counts: { all: rows.length, 'for-you': 0 },
    reload: async () => {},
  };
}

let toggle: ReturnType<typeof vi.fn>;

function fakeToday(picked: string[]): SessionTodayState {
  return {
    picked,
    isPicked: (id) => picked.includes(id),
    toggle: toggle as SessionTodayState['toggle'],
    today: '2026-10-19',
    refresh: async () => {},
  };
}

beforeEach(() => {
  toggle = vi.fn(async () => {});
  pinsState.pinned = [];
});

describe('卡片「…」菜单里的「从今天移出」', () => {
  it('只有今天捡回来的那场长这一项', () => {
    render(
      <TestRail
        state={railState([session(SID), session(OTHER)])}
        selectedId={null}
        onSelect={() => {}}
        today={fakeToday([SID])}
      />
    );
    const buttons = screen.getAllByTestId('session-menu-button');

    fireEvent.click(buttons[0]);
    expect(screen.getByTestId('session-menu-remove-today').textContent).toBe('从今天放下');
    fireEvent.click(screen.getByTestId('session-menu-remove-today'));

    fireEvent.click(buttons[1]);
    expect(screen.queryByTestId('session-menu-remove-today')).toBeNull();
  });

  it('点下去把这场编号交给今天的名单，菜单随之收起', async () => {
    render(
      <TestRail
        state={railState([session(SID)])}
        selectedId={null}
        onSelect={() => {}}
        today={fakeToday([SID])}
      />
    );
    fireEvent.click(screen.getByTestId('session-menu-button'));
    fireEvent.click(screen.getByTestId('session-menu-remove-today'));

    expect(toggle).toHaveBeenCalledWith(SID);
    await waitFor(() => expect(screen.queryByTestId('session-menu')).toBeNull());
  });

  it('点它不会顺手选中这场会话', () => {
    const onSelect = vi.fn();
    render(
      <TestRail
        state={railState([session(SID)])}
        selectedId={null}
        onSelect={onSelect}
        today={fakeToday([SID])}
      />
    );
    fireEvent.click(screen.getByTestId('session-menu-button'));
    fireEvent.click(screen.getByTestId('session-menu-remove-today'));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('捡回的 worker 以顶层卡摆在「今天捡回」里，不落进折起的 worker 区', () => {
    render(
      <TestRail
        state={railState([
          session(SID, { origin: 'worker' }),
          session(OTHER),
        ])}
        selectedId={null}
        onSelect={() => {}}
        today={fakeToday([SID])}
      />
    );
    const header = screen.getByTestId('picked-header');
    expect(header.textContent).toContain('今天捡回');
    expect(header.textContent).toContain('1');
    expect(
      screen
        .getAllByTestId('session-item')
        .some((el) => (el.textContent ?? '').includes(SID))
    ).toBe(true);
    // 捡回之后不再归「不知道谁派的 worker」——那块默认折起，归进去等于没捡。
    expect(screen.queryByTestId('workers-header')).toBeNull();
  });

  it('「今天捡回」区摆在 Pinned 下方', () => {
    pinsState.pinned = [OTHER];
    render(
      <TestRail
        state={railState([session(SID), session(OTHER)])}
        selectedId={null}
        onSelect={() => {}}
        today={fakeToday([SID])}
      />
    );
    const pinned = screen.getByTestId('pinned-header');
    const picked = screen.getByTestId('picked-header');
    expect(
      pinned.compareDocumentPosition(picked) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    // 置顶的那场只在 Pinned 里有一张，不在「今天捡回」里重复。
    expect(picked.textContent).toContain('1');
  });

  it('不传今天的名单（只读场景）就没有这一项', () => {
    render(
      <TestRail
        state={railState([session(SID)])}
        selectedId={null}
        onSelect={() => {}}
      />
    );
    fireEvent.click(screen.getByTestId('session-menu-button'));
    expect(screen.queryByTestId('session-menu-remove-today')).toBeNull();
  });
});
