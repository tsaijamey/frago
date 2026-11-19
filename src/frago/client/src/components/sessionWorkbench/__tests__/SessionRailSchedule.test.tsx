import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { TestRail } from './railTestKit';
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
  const now = Date.now();
  return {
    family: 'claude-code',
    title: `会话 ${over.session_id}`,
    directory: '/Users/frago/Repos/frago',
    created_at: now - 30 * 60_000,
    last_active_at: now - 10 * 60_000,
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

function railState(
  sessions: WorkbenchSession[],
  visible: WorkbenchSession[],
  over: Partial<WorkbenchSessionsState> = {}
): WorkbenchSessionsState {
  return {
    sessions,
    visible,
    todaySessions: visible,
    loading: false,
    error: null,
    filter: 'all',
    setFilter: NOOP,
    counts: { all: visible.length, 'for-you': 0 },
    reload: async () => {},
    ...over,
  };
}

beforeEach(() => {
  pins.pinned = [];
  pins.collapsed = false;
});

describe('SessionRail 定时任务分组 (20261010)', () => {
  it('定时任务（local_ops / schedule）集中收进可折叠「定时任务」分组，用户手动会话（含带 schedule 字样标题）绝不混入', () => {
    const manualPlain = session({
      session_id: 'manual-1',
      title: '排查工作台列表渲染问题',
    });
    const manualTitledSchedule = session({
      session_id: 'manual-2',
      title: '讨论 schedule 分组方案',
      origin: 'human',
      local_ops: false,
    });
    const localOpsCron = session({
      session_id: 'core_sched_1',
      family: 'coreagent',
      title: '每日巡检任务',
      local_ops: true,
    });
    const originCron = session({
      session_id: 'sched_2',
      title: '周报汇总定时任务',
      origin: 'schedule' as WorkbenchSession['origin'],
    });

    // 模拟真实 withinToday 行为：local_ops 已被从 visible 过滤掉，但仍存在于 sessions 中
    const all = [manualPlain, manualTitledSchedule, localOpsCron, originCron];
    const visible = [manualPlain, manualTitledSchedule, originCron];

    render(
      <TestRail
        state={railState(all, visible)}
        selectedId={null}
        onSelect={NOOP}
      />
    );

    // 主干仅显示人工会话
    const initialTexts = screen.getAllByTestId('session-item').map((el) => el.textContent ?? '');
    expect(initialTexts).toHaveLength(2);
    expect(initialTexts.some((t) => t.includes('排查工作台列表渲染问题'))).toBe(true);
    expect(initialTexts.some((t) => t.includes('讨论 schedule 分组方案'))).toBe(true);
    expect(screen.queryByText('每日巡检任务')).toBeNull();
    expect(screen.queryByText('周报汇总定时任务')).toBeNull();

    // 存在「定时任务」折叠标题，数量为 2
    const header = screen.getByTestId('schedules-header');
    expect(header.textContent).toContain('定时任务');
    expect(header.textContent).toContain('2');
    expect(header.getAttribute('aria-expanded')).toBe('false');

    // 点击展开后，两场定时任务会话集中在分组内显示
    fireEvent.click(header);
    expect(header.getAttribute('aria-expanded')).toBe('true');
    const expandedTexts = screen.getAllByTestId('session-item').map((el) => el.textContent ?? '');
    expect(expandedTexts).toHaveLength(4);
    expect(expandedTexts.some((t) => t.includes('每日巡检任务'))).toBe(true);
    expect(expandedTexts.some((t) => t.includes('周报汇总定时任务'))).toBe(true);
  });

  it('选中某场定时任务会话时自动展开「定时任务」分组，保证当前会话在左栏立即可见', () => {
    const manual = session({ session_id: 'manual-1', title: '人工会话' });
    const cron = session({
      session_id: 'core_sched_selected',
      family: 'coreagent',
      title: '当前选中的定时任务',
      local_ops: true,
    });

    render(
      <TestRail
        state={railState([manual, cron], [manual])}
        selectedId="core_sched_selected"
        onSelect={NOOP}
      />
    );

    const header = screen.getByTestId('schedules-header');
    expect(header.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('当前选中的定时任务')).toBeTruthy();
  });
});
