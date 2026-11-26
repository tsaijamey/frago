import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import DecisionInboxView from '../DecisionInboxView';
import { TestRail, fakeForYou } from './railTestKit';
import { useDecisionInbox } from '@/hooks/useDecisionInbox';
import { usePageStore } from '@/stores/pageStore';
import type {
  DecisionInboxCounts,
  DecisionInboxItem,
  DecisionInboxListResponse,
  DecisionInboxMutationResponse,
} from '@/types/api';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

const wsHandlers = vi.hoisted(() => new Map<string, Set<(msg: unknown) => void>>());

const apiMocks = vi.hoisted(() => ({
  getDecisionInbox: vi.fn(),
  resolveDecisionItem: vi.fn(),
  rejectDecisionItem: vi.fn(),
  snoozeDecisionItem: vi.fn(),
  unsnoozeDecisionItem: vi.fn(),
  undoDecisionItem: vi.fn(),
}));

vi.mock('@/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/api')>();
  return {
    ...real,
    getDecisionInbox: apiMocks.getDecisionInbox,
    resolveDecisionItem: apiMocks.resolveDecisionItem,
    rejectDecisionItem: apiMocks.rejectDecisionItem,
    snoozeDecisionItem: apiMocks.snoozeDecisionItem,
    unsnoozeDecisionItem: apiMocks.unsnoozeDecisionItem,
    undoDecisionItem: apiMocks.undoDecisionItem,
  };
});

vi.mock('@/api/websocket', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/api/websocket')>();
  return {
    ...real,
    getWebSocketClient: () => ({
      on: (type: string, cb: (msg: unknown) => void) => {
        let bucket = wsHandlers.get(type);
        if (!bucket) {
          bucket = new Set();
          wsHandlers.set(type, bucket);
        }
        bucket.add(cb);
        return () => {
          bucket?.delete(cb);
        };
      },
    }),
  };
});

vi.mock('@/hooks/useSessionPins', () => ({
  useSessionPins: () => ({
    pinned: [],
    isPinned: () => false,
    toggle: vi.fn(async () => {}),
    collapsed: false,
    setCollapsed: vi.fn(),
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

const NOW_SEC = Math.floor(Date.now() / 1000);

function makeItem(
  over: Partial<DecisionInboxItem> & Pick<DecisionInboxItem, 'proposal_id'>
): DecisionInboxItem {
  const source = over.source ?? 'schedule';
  const risk = over.risk ?? 'medium';
  return {
    source,
    source_label: source === 'schedule' ? '定时任务' : '会话待拍板',
    status: 'pending',
    title: `决策 ${over.proposal_id}`,
    summary: `摘要 ${over.proposal_id}`,
    risk,
    risk_label: risk === 'high' ? '高风险' : risk === 'low' ? '低风险' : '中风险',
    action_type: 'single-choice',
    irreversible: false,
    options: [
      { key: 'A', label: '方案 A', effect: '执行 A', reversible: true },
      { key: 'B', label: '方案 B', effect: '执行 B', reversible: true },
    ],
    recommended: 'A',
    selected_opt: null,
    why: '推荐 A 风险最低',
    multi: false,
    suggestion: null,
    suggestions: [],
    draft: null,
    session_id: 'ses-101',
    schedule_id: source === 'schedule' ? 'sch-1' : null,
    schedule_name: source === 'schedule' ? '每日巡检' : null,
    employee_id: 'emp-ops',
    employee_name: '值班架构师',
    employee_color: 'blue',
    dedup_key: `dedup-${over.proposal_id}`,
    skip_reason: '命中高风险门槛',
    impact_scope: '仅影响 staging 环境',
    evidence: 'diff: +12 -3 lines',
    ttl_hours: 72,
    created_at: NOW_SEC - 300,
    updated_at: NOW_SEC - 120,
    last_seen_at: NOW_SEC - 120,
    expires_at: NOW_SEC + 3600,
    occurrence_count: 1,
    last_reversible_from_state: null,
    resolution: null,
    ...over,
  };
}

function computeCounts(items: DecisionInboxItem[]): DecisionInboxCounts {
  return {
    pending: items.filter((i) => i.status === 'pending').length,
    schedule: items.filter((i) => i.status === 'pending' && i.source === 'schedule').length,
    session: items.filter((i) => i.status === 'pending' && i.source === 'session').length,
    snoozed: items.filter((i) => i.status === 'snoozed').length,
  };
}

function makeSession(
  over: Partial<WorkbenchSession> & Pick<WorkbenchSession, 'session_id'>
): WorkbenchSession {
  const now = Date.now();
  return {
    family: 'claude-code',
    title: `会话 ${over.session_id}`,
    directory: '/tmp/workspace',
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

function makeSessionsState(
  sessions: WorkbenchSession[],
  visible: WorkbenchSession[] = sessions
): WorkbenchSessionsState {
  return {
    sessions,
    visible,
    todaySessions: visible,
    loading: false,
    error: null,
    filter: 'all',
    setFilter: () => {},
    counts: { all: visible.length, 'for-you': 0 },
    reload: async () => {},
  };
}

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

beforeEach(() => {
  wsHandlers.clear();
  vi.clearAllMocks();
  usePageStore.setState({
    currentPage: 'session_workbench',
    workbenchSessionId: null,
    promotedTodayIds: [],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('pageStore #sessions/inbox 路由语义', () => {
  it('进入 #sessions/inbox 不得将 inbox 写入 promotedTodayIds', () => {
    usePageStore.getState().switchPage('session_workbench', 'inbox');
    expect(usePageStore.getState().currentPage).toBe('session_workbench');
    expect(usePageStore.getState().workbenchSessionId).toBe('inbox');
    expect(usePageStore.getState().promotedTodayIds).not.toContain('inbox');

    usePageStore.getState().promoteSessionToToday('inbox');
    expect(usePageStore.getState().promotedTodayIds).not.toContain('inbox');

    usePageStore.setState({
      currentPage: 'settings',
      workbenchSessionId: null,
      promotedTodayIds: [],
    });
    usePageStore.getState().applyRoute('session_workbench', 'inbox');
    expect(usePageStore.getState().currentPage).toBe('session_workbench');
    expect(usePageStore.getState().workbenchSessionId).toBe('inbox');
    expect(usePageStore.getState().promotedTodayIds).not.toContain('inbox');
  });
});

describe('SessionRail 32px 紧凑胶囊与同源计数', () => {
  it('展示计数、支持最多 240px 迷你抽屉展开，并在待决=0 时渲染 zero 态', async () => {
    const schItem = makeItem({
      proposal_id: 'prop-sch-1',
      source: 'schedule',
      title: '发布前回归检查审批',
      risk: 'high',
      risk_label: '高风险',
    });
    const sesItem = makeItem({
      proposal_id: 'prop-ses-1',
      source: 'session',
      session_id: 'ses-1',
      title: '确认数据库索引方案',
    });
    const snoozedItem = makeItem({
      proposal_id: 'prop-ses-2',
      source: 'session',
      session_id: 'ses-2',
      status: 'snoozed',
      title: '稍后处理的会话待决',
    });

    const items = [schItem, sesItem, snoozedItem];
    apiMocks.getDecisionInbox.mockResolvedValue({
      items,
      counts: computeCounts(items),
    } satisfies DecisionInboxListResponse);

    const { result } = renderHook(() => useDecisionInbox());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const onOpenInbox = vi.fn();
    const s1 = makeSession({ session_id: 'ses-1', title: '索引排查会话' });
    const s2 = makeSession({ session_id: 'ses-2', title: '稍后会话' });
    const sCron = makeSession({
      session_id: 'sch-sess-1',
      title: '定时巡检会话',
      origin: 'schedule' as WorkbenchSession['origin'],
    });

    const forYou = fakeForYou({
      'ses-1': { waitingSince: Date.now() - 60_000, words: '请选择 A 或 B', unseen: true },
      'ses-2': { waitingSince: Date.now() - 120_000, words: '稍后确认', unseen: true },
      'sch-sess-1': { waitingSince: Date.now() - 30_000, words: '定时等待中', unseen: true },
    });

    const { rerender } = render(
      <TestRail
        state={makeSessionsState([s1, s2, sCron], [s1, s2])}
        selectedId={null}
        onSelect={() => {}}
        forYou={forYou}
        inbox={result.current}
        isInboxOpen={false}
        onOpenInbox={onOpenInbox}
      />
    );

    const cntBadge = screen.getByTestId('rail-inbox-cnt');
    expect(cntBadge.textContent).toBe('2');
    expect(cntBadge.className).not.toContain('zero');
    expect(screen.queryByTestId('rail-inbox-mini-drawer')).toBeNull();

    // 同源计数对齐：ses-2 已被 snoozed，sCron 为 schedule 会话，因此左栏「待决」筛选计数必须仅计入 ses-1 (= 1)
    const decisionChip = screen.getByTestId('list-filter-decision');
    expect(decisionChip.textContent).toContain('1');

    fireEvent.click(decisionChip);
    expect(screen.getByText('索引排查会话')).toBeTruthy();
    expect(screen.queryByText('稍后会话')).toBeNull();

    // 点击 chevron 展开迷你抽屉并选中直达
    fireEvent.click(screen.getByTestId('rail-inbox-chevron'));
    await waitFor(() => expect(result.current.railExpanded).toBe(true));

    rerender(
      <TestRail
        state={makeSessionsState([s1, s2, sCron], [s1, s2])}
        selectedId={null}
        onSelect={() => {}}
        forYou={forYou}
        inbox={result.current}
        isInboxOpen={false}
        onOpenInbox={onOpenInbox}
      />
    );

    const drawer = screen.getByTestId('rail-inbox-mini-drawer');
    expect(drawer.className).toContain('inbox-mini-drawer');
    fireEvent.click(screen.getByTestId('rail-inbox-mini-item-prop-sch-1'));
    expect(onOpenInbox).toHaveBeenCalledWith('prop-sch-1');

    // 待决清零态：capsule 徽标显示 0 + .zero，迷你抽屉显示空态提示
    apiMocks.getDecisionInbox.mockResolvedValue({
      items: [snoozedItem],
      counts: { pending: 0, schedule: 0, session: 0, snoozed: 1 },
    } satisfies DecisionInboxListResponse);
    await act(async () => {
      await result.current.refresh();
    });

    rerender(
      <TestRail
        state={makeSessionsState([s1, s2], [s1, s2])}
        selectedId={null}
        onSelect={() => {}}
        forYou={forYou}
        inbox={result.current}
        isInboxOpen={true}
        onOpenInbox={onOpenInbox}
      />
    );

    expect(screen.getByTestId('rail-inbox-cnt').textContent).toBe('0');
    expect(screen.getByTestId('rail-inbox-cnt').className).toContain('zero');
    expect(screen.getByTestId('rail-inbox-mini-empty')).toBeTruthy();
  });
});

describe('DecisionInboxView 全流程交互、不可逆确认与仅可逆撤回', () => {
  it('覆盖 4 个页签、多类卡片动作、不可逆二次确认、仅 snooze/unsnooze 可撤销与空态跳转', async () => {
    const itemSingle = makeItem({
      proposal_id: 'p-single',
      source: 'schedule',
      title: '单选可逆决策',
      action_type: 'single-choice',
      options: [
        { key: 'A', label: '保守方案', effect: '仅回放日志', reversible: true },
        { key: 'B', label: '不可逆切换', effect: '直接切换生产流量', reversible: false },
      ],
      recommended: 'A',
      session_id: 'ses-single',
    });

    const itemMulti = makeItem({
      proposal_id: 'p-multi',
      source: 'session',
      title: '多选模块发布',
      action_type: 'multi-choice',
      multi: true,
      options: [
        { key: 'api', label: 'API 服务', effect: '重启 API', reversible: true },
        { key: 'web', label: 'Web 前端', effect: '刷新静态包', reversible: true },
      ],
      recommended: 'api',
      session_id: 'ses-multi',
    });

    const itemText = makeItem({
      proposal_id: 'p-text',
      source: 'session',
      title: '填写回复草稿',
      action_type: 'text-answer',
      options: [],
      recommended: null,
      draft: '请按灰度 10% 推进',
      suggestion: '先验证监控后再放量',
      suggestions: ['暂缓到明天上午'],
      session_id: 'ses-text',
    });

    const itemIrrev = makeItem({
      proposal_id: 'p-irrev',
      source: 'schedule',
      title: '清理过期快照（不可逆）',
      action_type: 'binary',
      irreversible: true,
      risk: 'high',
      risk_label: '高风险',
      options: [],
      recommended: null,
      session_id: 'ses-irrev',
    });

    let serverItems: DecisionInboxItem[] = [itemSingle, itemMulti, itemText, itemIrrev];

    apiMocks.getDecisionInbox.mockImplementation(async () => ({
      items: serverItems,
      counts: computeCounts(serverItems),
    }));

    apiMocks.snoozeDecisionItem.mockImplementation(async (id: string) => {
      const target = serverItems.find((i) => i.proposal_id === id)!;
      const updated: DecisionInboxItem = {
        ...target,
        status: 'snoozed',
        last_reversible_from_state: 'pending',
      };
      serverItems = serverItems.map((i) => (i.proposal_id === id ? updated : i));
      return { item: updated, counts: computeCounts(serverItems) } satisfies DecisionInboxMutationResponse;
    });

    apiMocks.undoDecisionItem.mockImplementation(async (id: string) => {
      const target = serverItems.find((i) => i.proposal_id === id)!;
      const updated: DecisionInboxItem = {
        ...target,
        status: 'pending',
        last_reversible_from_state: 'snoozed',
      };
      serverItems = serverItems.map((i) => (i.proposal_id === id ? updated : i));
      return { item: updated, counts: computeCounts(serverItems) } satisfies DecisionInboxMutationResponse;
    });

    apiMocks.resolveDecisionItem.mockImplementation(async (id: string) => {
      const target = serverItems.find((i) => i.proposal_id === id)!;
      const updated: DecisionInboxItem = {
        ...target,
        status: 'resolved',
      };
      serverItems = serverItems.filter((i) => i.proposal_id !== id);
      return { item: updated, counts: computeCounts(serverItems) } satisfies DecisionInboxMutationResponse;
    });

    apiMocks.rejectDecisionItem.mockImplementation(async (id: string) => {
      const target = serverItems.find((i) => i.proposal_id === id)!;
      const updated: DecisionInboxItem = {
        ...target,
        status: 'rejected',
      };
      serverItems = serverItems.filter((i) => i.proposal_id !== id);
      return { item: updated, counts: computeCounts(serverItems) } satisfies DecisionInboxMutationResponse;
    });

    const { result } = renderHook(() => useDecisionInbox());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const onBack = vi.fn();
    const onOpenSession = vi.fn();

    const { rerender } = render(
      <DecisionInboxView
        inbox={result.current}
        onBackToSessions={onBack}
        onOpenSession={onOpenSession}
      />
    );

    const reRenderView = () =>
      rerender(
        <DecisionInboxView
          inbox={result.current}
          onBackToSessions={onBack}
          onOpenSession={onOpenSession}
        />
      );

    // 4 个 tab 计数核对
    expect(screen.getByTestId('inbox-tab-pending').textContent).toContain('4');
    expect(screen.getByTestId('inbox-tab-schedule').textContent).toContain('2');
    expect(screen.getByTestId('inbox-tab-session').textContent).toContain('2');
    expect(screen.getByTestId('inbox-tab-snoozed').textContent).toContain('0');

    // 打开原会话 & 返回会话流
    fireEvent.click(screen.getByTestId('inbox-open-session'));
    expect(onOpenSession).toHaveBeenCalledWith('ses-single');
    fireEvent.click(screen.getByTestId('inbox-back-session'));
    expect(onBack).toHaveBeenCalledTimes(1);

    // 1) 选择不可逆选项 B，首次点击提交必须弹出橙色确认条，不直接发 resolve 请求
    fireEvent.click(screen.getByTestId('inbox-opt-B'));
    fireEvent.click(screen.getByTestId('inbox-approve-btn'));
    expect(apiMocks.resolveDecisionItem).not.toHaveBeenCalled();
    expect(screen.getByTestId('inbox-confirm-bar')).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByTestId('inbox-confirm-exec'));
    });
    await waitFor(() => expect(apiMocks.resolveDecisionItem).toHaveBeenCalledTimes(1));
    expect(apiMocks.resolveDecisionItem).toHaveBeenLastCalledWith('p-single', {
      choice: 'B',
      note: null,
    });
    reRenderView();

    // resolved 不可撤销：反馈条显示，但绝不出现 undo 按钮
    expect(screen.getByTestId('inbox-undo-bar').className).toContain('show');
    expect(screen.queryByTestId('inbox-undo-btn')).toBeNull();

    // 2) 多选动作
    fireEvent.click(screen.getByTestId('inbox-item-p-multi'));
    reRenderView();
    fireEvent.click(screen.getByTestId('inbox-opt-web'));
    fireEvent.change(screen.getByTestId('inbox-note-input'), { target: { value: '加急窗口' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('inbox-approve-btn'));
    });
    await waitFor(() => expect(apiMocks.resolveDecisionItem).toHaveBeenCalledTimes(2));
    expect(apiMocks.resolveDecisionItem).toHaveBeenLastCalledWith('p-multi', {
      choices: ['api', 'web'],
      choice: 'api',
      answer_text: null,
      note: '加急窗口',
    });
    reRenderView();
    expect(screen.queryByTestId('inbox-undo-btn')).toBeNull();

    // 3) text-answer：草稿预填 + 建议填充 + snooze 可撤回 -> undo
    fireEvent.click(screen.getByTestId('inbox-item-p-text'));
    reRenderView();
    const answerBox = screen.getByTestId('inbox-answer-input') as HTMLTextAreaElement;
    expect(answerBox.value).toBe('请按灰度 10% 推进');

    // snooze -> 必须出现可点击的「撤回」按钮
    await act(async () => {
      fireEvent.click(screen.getByTestId('inbox-ctx-snooze'));
    });
    await waitFor(() => expect(apiMocks.snoozeDecisionItem).toHaveBeenCalledWith('p-text'));
    reRenderView();
    expect(screen.getByTestId('inbox-undo-bar').className).toContain('show');
    expect(screen.getByTestId('inbox-undo-btn')).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByTestId('inbox-undo-btn'));
    });
    await waitFor(() => expect(apiMocks.undoDecisionItem).toHaveBeenCalledWith('p-text'));
    reRenderView();

    // 使用推荐短语并提交 text-answer
    fireEvent.click(screen.getByText(/先验证监控后再放量/));
    await act(async () => {
      fireEvent.click(screen.getByTestId('inbox-approve-btn'));
    });
    expect(apiMocks.resolveDecisionItem).toHaveBeenLastCalledWith('p-text', {
      answer_text: '先验证监控后再放量',
      note: null,
    });
    reRenderView();

    // 4) 不可逆二元条目：reject 不显示撤销按钮
    fireEvent.click(screen.getByTestId('inbox-item-p-irrev'));
    reRenderView();
    await act(async () => {
      fireEvent.click(screen.getByTestId('inbox-reject-btn'));
    });
    await waitFor(() => expect(apiMocks.rejectDecisionItem).toHaveBeenCalledWith('p-irrev', { note: null }));
    reRenderView();

    expect(screen.queryByTestId('inbox-undo-btn')).toBeNull();
    expect(screen.getByTestId('inbox-queue-empty')).toBeTruthy();
    expect(screen.getByTestId('inbox-ctx-empty')).toBeTruthy();

    // 5) WS DECISION_INBOX_UPDATE 实时刷新
    const initialCalls = apiMocks.getDecisionInbox.mock.calls.length;
    await act(async () => {
      wsHandlers.get('decision_inbox_update')?.forEach((fn) => fn({ type: 'decision_inbox_update' }));
    });
    await waitFor(() => expect(apiMocks.getDecisionInbox.mock.calls.length).toBeGreaterThan(initialCalls));
  });
});

describe('SessionRail 待决口径与 counts.session 严格同源对齐', () => {
  it('空列表时 decision 徽标为 0；存在 schedule / snoozed / snoozed-branch 时仅计入真实待决在线会话', async () => {
    const snoozedOnline = makeItem({
      proposal_id: 'session:ses-snz',
      source: 'session',
      status: 'snoozed',
      session_id: 'ses-snz',
    });
    const snoozedBranch = makeItem({
      proposal_id: 'session:ses-branch-snz',
      source: 'session',
      status: 'snoozed',
      session_id: 'ses-branch-snz',
    });
    apiMocks.getDecisionInbox.mockResolvedValue({
      items: [snoozedOnline, snoozedBranch],
      counts: { pending: 1, schedule: 0, session: 1, snoozed: 2 },
    } satisfies DecisionInboxListResponse);

    const { result } = renderHook(() => useDecisionInbox());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // 1. baseSessions 为空时，即使 counts['for-you'] > 0，待决角标也必须为 0
    const emptyState: WorkbenchSessionsState = {
      ...makeSessionsState([], []),
      counts: { all: 0, 'for-you': 3 },
    };
    const { rerender } = render(
      <TestRail
        state={emptyState}
        selectedId={null}
        onSelect={() => {}}
        forYou={fakeForYou({})}
        inbox={result.current}
        isInboxOpen={false}
        onOpenInbox={() => {}}
      />
    );
    expect(screen.getByTestId('list-filter-decision').textContent).toContain('0');

    // 2. 同时存在普通待决、已搁置在线会话、已搁置 branch 子会话的父会话、以及 schedule 会话（local_ops: false & origin: schedule）
    const activeOnline = makeSession({ session_id: 'ses-active', title: '唯一应计入的在线待决' });
    const snzSession = makeSession({ session_id: 'ses-snz', title: '已搁置主会话' });
    const parentOfSnzBranch = makeSession({
      session_id: 'ses-parent',
      title: '父会话本身未待决',
      need_decision: false,
    });
    const snzBranchSession = makeSession({
      session_id: 'ses-branch-snz',
      title: '已搁置分支子会话',
      parent_session_id: 'ses-parent',
      relation: { kind: 'branch', closed: false },
    });
    const cronOriginSession = makeSession({
      session_id: 'ses-cron-only-origin',
      title: '定时来源会话',
      local_ops: false,
      origin: 'schedule' as WorkbenchSession['origin'],
    });
    const cronLocalOpsSession = makeSession({
      session_id: 'ses-cron-local-ops',
      title: '本机运维定时会话',
      local_ops: true,
      origin: 'schedule' as WorkbenchSession['origin'],
    });

    const allSessions = [
      activeOnline,
      snzSession,
      parentOfSnzBranch,
      snzBranchSession,
      cronOriginSession,
      cronLocalOpsSession,
    ];
    const todayOnline = [activeOnline, snzSession, parentOfSnzBranch, snzBranchSession, cronOriginSession];

    const forYou = fakeForYou({
      'ses-active': { waitingSince: Date.now() - 20_000, words: '请拍板', unseen: true },
      'ses-snz': { waitingSince: Date.now() - 30_000, words: '已搁置', unseen: true },
      'ses-branch-snz': { waitingSince: Date.now() - 40_000, words: '子分支已搁置', unseen: true },
      'ses-cron-only-origin': { waitingSince: Date.now() - 10_000, words: '定时任务等待中', unseen: true },
      'ses-cron-local-ops': { waitingSince: Date.now() - 5_000, words: '定时运维等待中', unseen: true },
    });

    rerender(
      <TestRail
        state={makeSessionsState(allSessions, todayOnline)}
        selectedId={null}
        onSelect={() => {}}
        forYou={forYou}
        inbox={result.current}
        isInboxOpen={false}
        onOpenInbox={() => {}}
      />
    );

    // railCounts.decision 与后端 counts.session (= 1) 严格相等
    const decisionChip = screen.getByTestId('list-filter-decision');
    expect(decisionChip.textContent).toContain('1');

    // 点击筛选「待决」，仅展示 activeOnline，schedule 与 snoozed / snoozed-branch 均不出现
    fireEvent.click(decisionChip);
    const visibleTitles = screen.getAllByTestId('session-title').map((el) => el.textContent);
    expect(visibleTitles).toEqual(['唯一应计入的在线待决']);
    expect(screen.queryByText('定时来源会话')).toBeNull();
    expect(screen.queryByText('本机运维定时会话')).toBeNull();
    expect(screen.queryByText('已搁置主会话')).toBeNull();
    expect(screen.queryByText('父会话本身未待决')).toBeNull();
  });
});
