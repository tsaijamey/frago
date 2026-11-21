/**
 * EmployeeSessionsPanel 单测与 24h 历史会话左栏可见性回归验证。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import EmployeeSessionsPanel from '../EmployeeSessionsPanel';
import i18n from '@/i18n';
import type { EmployeePost } from '@/hooks/useEmployees';
import { withinToday, type WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import { usePageStore } from '@/stores/pageStore';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const SAMPLE_EMP: EmployeePost = {
  member_post_id: 'dev-bot',
  title: '研发专员',
  agent_kernel: 'claude',
  description: '负责后端与前端研发工作。',
  work_scope: '',
  cwd: '/Users/frago/Repos/frago',
  knowledge_domains: [],
  recipes: [],
  data_slots: [],
  schedule_ids: [],
  active_session_ids: [],
  allowed_commands: [],
  created_at: '',
  updated_at: '',
  data_summary: { slot_count: 0, entry_count: 0, slots: [] },
};

function makeSession(over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  const now = Date.now();
  return {
    session_id: 's-1',
    family: 'claude-code',
    title: '默认会话标题',
    raw_title: '默认会话标题',
    custom_title: null,
    directory: '/Users/frago/Repos/frago',
    created_at: now - 3600_000,
    last_active_at: now - 60_000,
    last_reply_at: now - 60_000,
    agent_paths: [],
    status: 'done',
    lifecycle_state: 'completed',
    digest_done: '已完成代码改造并跑通验证',
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    in_tmux: false,
    tmux_name: null,
    alive: false,
    has_running_worker: false,
    need_decision: false,
    employee_id: 'dev-bot',
    employee_title: '研发专员',
    employee_color: 'violet',
    ...over,
  };
}

describe('EmployeeSessionsPanel', () => {
  it('0 会话时整行隐藏分段筛选，呈现克制空态且无第二颗绿色主按钮', () => {
    const onLaunch = vi.fn();
    render(
      <EmployeeSessionsPanel
        employee={SAMPLE_EMP}
        sessions={[]}
        total={0}
        activeCount={0}
        completedCount={0}
        hasMore={false}
        filter="all"
        onFilterChange={vi.fn()}
        loading={false}
        loadingMore={false}
        error={null}
        onRetry={vi.fn()}
        onLoadMore={vi.fn()}
        onEditEmployee={vi.fn()}
        onLaunchSession={onLaunch}
        onOpenSession={vi.fn()}
      />
    );

    expect(screen.queryByTestId('employee-sessions-filter')).toBeNull();
    expect(screen.getByTestId('empty-sessions-state')).toBeTruthy();
    expect(screen.getByText('暂无会话记录')).toBeTruthy();
    // 头栏移除重复徽章与职责简介，次要按钮固定为「岗位详情」
    expect(document.querySelector('.roster-emp-badge')).toBeNull();
    expect(document.querySelector('.roster-desc')).toBeNull();
    expect(screen.getByTestId('employee-edit-btn').textContent?.trim()).toBe('岗位详情');
    // 全屏唯一绿色主按钮只在上下文头栏
    const primaryBtns = document.querySelectorAll('.emp-btn-primary');
    expect(primaryBtns).toHaveLength(1);
    fireEvent.click(screen.getByTestId('employee-launch-btn'));
    expect(onLaunch).toHaveBeenCalledWith(SAMPLE_EMP);
  });

  it('展示运行中、待拍板、异常与已结束状态胶囊，支持筛选、分页加载与一键进入会话', () => {
    const onFilterChange = vi.fn();
    const onLoadMore = vi.fn();
    const onOpenSession = vi.fn();

    const list: WorkbenchSession[] = [
      makeSession({
        session_id: 's-run',
        title: '正在跑的任务',
        status: 'running',
        lifecycle_state: 'running',
        need_decision: true,
      }),
      makeSession({
        session_id: 's-err',
        title: '出错的会话',
        status: 'error',
        lifecycle_state: 'error',
        digest_stuck: '构建报错 exit code 1',
      }),
      makeSession({
        session_id: 's-done',
        title: '已归档任务',
        status: 'done',
        lifecycle_state: 'completed',
      }),
    ];

    render(
      <EmployeeSessionsPanel
        employee={SAMPLE_EMP}
        sessions={list}
        total={12}
        activeCount={1}
        completedCount={11}
        hasMore
        filter="all"
        onFilterChange={onFilterChange}
        loading={false}
        loadingMore={false}
        error={null}
        onRetry={vi.fn()}
        onLoadMore={onLoadMore}
        onEditEmployee={vi.fn()}
        onLaunchSession={vi.fn()}
        onOpenSession={onOpenSession}
      />
    );

    expect(screen.getByTestId('session-filter-all').textContent).toBe('全部 12');
    expect(screen.getByTestId('session-filter-active').textContent).toBe('进行中 1');
    expect(screen.getByTestId('session-filter-completed').textContent).toBe('已结束 11');

    expect(screen.getByText('进行中')).toBeTruthy();
    expect(screen.getByText('待拍板')).toBeTruthy();
    expect(screen.getByText('异常')).toBeTruthy();
    expect(screen.getByText('已结束')).toBeTruthy();
    expect(screen.getByText('构建报错 exit code 1')).toBeTruthy();

    fireEvent.click(screen.getByTestId('session-filter-active'));
    expect(onFilterChange).toHaveBeenCalledWith('active');

    const moreBtn = screen.getByTestId('employee-sessions-load-more');
    expect(moreBtn.textContent).toContain('剩余 9 场');
    fireEvent.click(moreBtn);
    expect(onLoadMore).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('enter-session-s-done'));
    expect(onOpenSession).toHaveBeenCalledWith('s-done');
  });

  it('超过 24 小时的历史会话切入会话工作台后豁免 withinToday 窗口过滤保持左栏可见', () => {
    const now = Date.now();
    const oldTs = now - 72 * 60 * 60 * 1000;
    const oldSession = makeSession({
      session_id: 'old-72h-sid',
      title: '三天前的关键会话',
      created_at: oldTs,
      last_active_at: oldTs,
      last_reply_at: oldTs,
      status: 'done',
      lifecycle_state: 'completed',
    });

    // 未豁免前，24 小时滚动窗口会把它过滤掉
    expect(withinToday([oldSession], new Set(), now)).toEqual([]);

    // 模拟从员工页跳转过去
    usePageStore.setState({ promotedTodayIds: [] });
    usePageStore.getState().switchPage('session_workbench', 'old-72h-sid');

    const promoted = new Set(usePageStore.getState().promotedTodayIds);
    expect(promoted.has('old-72h-sid')).toBe(true);
    expect(withinToday([oldSession], promoted, now).map((s) => s.session_id)).toEqual([
      'old-72h-sid',
    ]);
  });
});
