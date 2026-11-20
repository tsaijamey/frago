import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n';
import * as apiClient from '@/api/client';
import {
  CHILDREN_ACTIVE_POLL_MS,
  CHILDREN_IDLE_POLL_MS,
  useSessionChildren,
} from '@/hooks/useSessionChildren';
import * as useAutoRefreshMod from '@/hooks/useAutoRefresh';
import RecordStream from '../RecordStream';
import SessionLaunchPanel from '../SessionLaunchPanel';
import type { SessionChildrenResponse } from '@/types/api';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeRecord(over: Partial<WorkbenchRecord> = {}): WorkbenchRecord {
  return {
    id: over.id ?? 'r1',
    session_id: over.session_id ?? 'ses-1',
    group_id: null,
    seq: over.seq ?? 0,
    ts: over.ts ?? 1_700_000_000_000,
    kind: over.kind ?? 'user.say',
    payload: over.payload ?? { text: '你好' },
    agent_path: [],
    raw_available: false,
    ...over,
  };
}

function makeChildrenResp(
  over: Partial<SessionChildrenResponse> = {}
): SessionChildrenResponse {
  return {
    session_id: 'ses-1',
    launched_by: null,
    summary: {
      total_children: 0,
      running_children: 0,
      delivering_children: 0,
      total_processes: 0,
      running_processes: 0,
      has_running: false,
      host_alive: false,
      host_mode: 'none',
      external_host_alive: false,
    },
    child_sessions: [],
    child_processes: [],
    ...over,
  };
}

function baseProps(over: Record<string, unknown> = {}) {
  return {
    sessionId: 'ses-1',
    records: [
      makeRecord({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: '开始任务' } }),
      makeRecord({ id: 'a1', seq: 1, kind: 'agent.say', payload: { text: '好的' } }),
    ],
    loading: false,
    loadingOlder: false,
    hasOlder: false,
    error: null,
    onLoadOlder: vi.fn(),
    onSelectSession: vi.fn(),
    ...over,
  };
}

describe('Progress 面板内的派生来历与执行实况（修订版方案 A）', () => {
  it('AC-01 & AC-03: 无顶部横幅占位，纯空白或无关联普通会话在进展按钮与面板内保持零占位', () => {
    const { rerender } = render(
      <RecordStream
        {...baseProps({
          records: [],
          childrenData: makeChildrenResp(),
        })}
      />
    );
    expect(document.querySelector('[data-testid="session-children-bar"]')).toBeNull();
    expect(screen.queryByTestId('stream-lens')).toBeNull();
    expect(screen.queryByTestId('empty-stream-children-hint')).toBeNull();

    rerender(
      <RecordStream
        {...baseProps({
          childrenData: makeChildrenResp({
            summary: {
              total_children: 0,
              running_children: 0,
              delivering_children: 0,
              total_processes: 0,
              running_processes: 0,
              has_running: false,
              host_alive: true,
              host_mode: 'managed_tmux',
              external_host_alive: false,
            },
          }),
          observer: {
            state: {
              anchor: '主目标',
              phase_goal: null,
              happened: [],
              tail: { kind: 'output', text: '完成' },
              decision: null,
              tasks: [],
              runs: [
                {
                  run_id: 1,
                  task_id: 'T1',
                  actor: '主会话',
                  at: 1_700_000_001_000,
                  cursor_from: 0,
                  cursor_to: 2,
                  summary: '已完成',
                },
              ],
              model: 'observer',
              updated_at: 1_700_000_001_000,
            },
            loading: false,
            error: null,
          },
        })}
      />
    );

    // AC-10 & AC-12: 平台托管 tmux 绝不显示外部提示；进展按钮无旧 watcherCount、无角标、无圆点
    const watcherBtn = screen.getByTestId('lens-watcher');
    expect(watcherBtn.textContent).toBe('进展');
    expect(screen.queryByTestId('lens-watcher-badge')).toBeNull();
    expect(screen.queryByTestId('lens-watcher-external-dot')).toBeNull();

    fireEvent.click(watcherBtn);
    expect(screen.queryByTestId('progress-origin-strip')).toBeNull();
    expect(screen.queryByTestId('progress-delegation-section')).toBeNull();
    expect(screen.queryByText(/外部终端|外部进程/)).toBeNull();
    // 历史里程碑批次数迁入 L5 区块副标题
    expect(screen.getByTestId('watcher-milestones-table').textContent).toContain('已追加 1 轮');
  });

  it('AC-02 & AC-04: 无记录空流时存在上游来历或派发任务，保留镜头栏并展示空态查看进展入口', () => {
    const onSelectSession = vi.fn();
    render(
      <RecordStream
        {...baseProps({
          records: [],
          onSelectSession,
          childrenData: makeChildrenResp({
            launched_by: {
              session_id: 'root-0',
              title: '主控编排会话',
              family: 'claude-code',
              relation_kind: 'dispatch',
              origin: 'worker',
              source: 'async_dispatch',
              label: '由「主控编排会话」派发启动',
            },
            summary: {
              total_children: 1,
              running_children: 1,
              delivering_children: 0,
              total_processes: 0,
              running_processes: 0,
              has_running: true,
              host_alive: false,
              host_mode: 'none',
              external_host_alive: false,
            },
            child_sessions: [
              {
                session_id: 'sub-1',
                title: '派发子会话尚未落盘',
                family: 'claude-code',
                relation_kind: 'dispatch',
                origin: 'worker',
                status: 'running',
                depth: 1,
                is_running: true,
                alive: true,
                in_tmux: false,
                tmux_name: null,
                launched_by_session_id: 'ses-1',
                launched_by_title: '当前',
                launched_by_label: '由当前会话派发',
                source: 'async_dispatch',
                job_id: 'job-1',
                delivery_state: null,
                employee_id: null,
                prompt_head: '检查单测',
                started_at: 1_700_000_000_000,
                last_active_at: 1_700_000_001_000,
              },
            ],
          }),
        })}
      />
    );

    expect(screen.getByTestId('stream-lens')).toBeTruthy();
    expect(screen.getByTestId('lens-watcher-badge').textContent).toBe('1');
    expect(screen.getByTestId('empty-stream-children-hint')).toBeTruthy();

    fireEvent.click(screen.getByTestId('session-launched-by-open'));
    expect(onSelectSession).toHaveBeenCalledWith('root-0');

    fireEvent.click(screen.getByTestId('empty-stream-open-progress'));
    expect(screen.getByTestId('watcher-view')).toBeTruthy();
    expect(screen.getByTestId('progress-origin-strip').textContent).toContain('由「主控编排会话」派发启动');
    expect(screen.getByTestId('child-session-row').textContent).toContain('派发子会话尚未落盘');
  });

  it('AC-04/05/06/07/08/09/11/12: 活跃置顶、8层树缩进封顶、人话进程次级折叠、外部终端文案与执行体安全跳转', () => {
    const onSelectSession = vi.fn();
    const data = makeChildrenResp({
      launched_by: {
        session_id: null,
        title: null,
        family: null,
        relation_kind: null,
        origin: 'schedule',
        source: 'local_ops',
        label: '由本机定时任务 / 自动管理触发',
      },
      summary: {
        total_children: 7,
        running_children: 1,
        delivering_children: 1,
        total_processes: 3,
        running_processes: 3,
        has_running: true,
        host_alive: true,
        host_mode: 'external_cli',
        external_host_alive: true,
      },
      child_sessions: [
        {
          session_id: 'c1',
          title: '一级协调',
          family: 'claude-code',
          relation_kind: 'dispatch',
          origin: 'worker',
          status: 'delivering',
          depth: 1,
          is_running: false,
          alive: false,
          in_tmux: false,
          tmux_name: null,
          launched_by_session_id: 'ses-1',
          launched_by_title: '当前',
          launched_by_label: '由当前会话派发',
          source: 'both',
          job_id: 'job-del',
          delivery_state: 'queued',
          employee_id: 'analyst',
          prompt_head: '分析报告',
          started_at: 1_700_000_000_000,
          last_active_at: 1_700_000_005_000,
        },
        ...['c2', 'c3', 'c4', 'c5'].map((sid, idx) => ({
          session_id: sid,
          title: `第${idx + 2}层节点`,
          family: 'claude-code',
          relation_kind: 'dispatch',
          origin: 'worker',
          status: (idx === 3 ? 'running' : 'done') as 'running' | 'done',
          depth: idx + 2,
          is_running: idx === 3,
          alive: idx === 3,
          in_tmux: false,
          tmux_name: null,
          launched_by_session_id: idx === 0 ? 'c1' : `c${idx + 1}`,
          launched_by_title: '',
          launched_by_label: '',
          source: 'session_origin',
          job_id: null,
          delivery_state: null,
          employee_id: null,
          prompt_head: '',
          started_at: 1_700_000_000_000,
          last_active_at: 1_700_000_000_000,
        })),
      ],
      child_processes: [
        // 属于活跃子会话 c5 的 2 个进程（去重不计入角标）
        {
          pid: 4101,
          ppid: 4100,
          comm: 'pytest',
          command: 'python3 -m pytest tests/unit',
          elapsed: '01:12',
          state: 'R',
          is_running: true,
          kind: 'command',
          source: 'process_tree',
          tmux_name: 'frago-agent-c5',
          host_session_id: 'c5',
          launched_by_pid: 4100,
          launched_by_comm: 'claude',
          launched_by_session_id: 'c5',
          launched_by_label: '由子会话启动',
          linked_session_id: null,
        },
        {
          pid: 4102,
          ppid: 4101,
          comm: 'sh',
          command: 'sh -c echo running',
          elapsed: '00:20',
          state: 'S',
          is_running: true,
          kind: 'subshell',
          source: 'process_tree',
          tmux_name: null,
          host_session_id: 'c5',
          launched_by_pid: 4101,
          launched_by_comm: 'pytest',
          launched_by_session_id: 'c5',
          launched_by_label: '由子会话启动',
          linked_session_id: null,
        },
        // 主会话直接拉起且关联到已计数的活跃子会话 c1 的进程（应去重不计）
        {
          pid: 4200,
          ppid: 4199,
          comm: 'claude',
          command: 'claude --resume c1',
          elapsed: '00:15',
          state: 'S',
          is_running: true,
          kind: 'agent_cli',
          source: 'process_tree',
          tmux_name: null,
          host_session_id: 'ses-1',
          launched_by_pid: 4199,
          launched_by_comm: 'claude',
          launched_by_session_id: 'ses-1',
          launched_by_label: '由当前会话主进程启动',
          linked_session_id: 'c1',
        },
        // 主会话独立拉起、无 linked_session_id 的后台进程（计入角标，总共 2 个活跃子会话 + 1 个独立进程 = 3）
        {
          pid: 4201,
          ppid: 4200,
          comm: 'vite',
          command: 'npm run build',
          elapsed: '00:38',
          state: 'R',
          is_running: true,
          kind: 'command',
          source: 'process_tree',
          tmux_name: null,
          host_session_id: 'ses-1',
          launched_by_pid: 4200,
          launched_by_comm: 'claude',
          launched_by_session_id: 'ses-1',
          launched_by_label: '由当前会话主进程启动',
          linked_session_id: null,
        },
      ],
    });

    render(
      <RecordStream
        {...baseProps({
          onSelectSession,
          childrenData: data,
          observer: {
            state: {
              anchor: '目标',
              phase_goal: null,
              happened: [],
              tail: { kind: 'now', text: '推进中' },
              decision: null,
              tasks: [
                {
                  id: 'T1',
                  proposed_at: 1_700_000_000_000,
                  title: '核对数据',
                  status: 'doing',
                  actor: 'analyst',
                  conclusion: '进行中',
                },
              ],
              runs: [],
              model: 'observer',
              updated_at: 1_700_000_000_000,
            },
            loading: false,
            error: null,
          },
        })}
      />
    );

    // AC-12: 2 个活跃子会话 (c1 delivering + c5 running) + 1 个独立进程 (4201) = 3
    expect(screen.getByTestId('lens-watcher-badge').textContent).toBe('3');
    expect(screen.getByTestId('lens-watcher-badge').className).not.toContain('animate-pulse');

    fireEvent.click(screen.getByTestId('lens-watcher'));

    // AC-04: local_ops 无 session_id 时不出跳转按钮
    expect(screen.getByTestId('progress-origin-strip').textContent).toContain('定时任务');
    expect(screen.queryByTestId('session-launched-by-open')).toBeNull();

    // AC-05: 活跃置顶在 watcher-tasks-table 之上
    const view = screen.getByTestId('watcher-view');
    const delSec = screen.getByTestId('progress-delegation-section');
    const tasksSec = screen.getByTestId('watcher-tasks-table');
    expect(Boolean(delSec.compareDocumentPosition(tasksSec) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(view.contains(delSec)).toBe(true);

    // AC-11: 外部终端接入规范文案
    expect(screen.getByTestId('progress-external-host').textContent).toContain('外部终端接入运行中');

    // AC-06 & AC-07: 待回传主会话与第 5 层 L5 标签、视觉缩进封顶为 4
    const rows = screen.getAllByTestId('child-session-row');
    expect(rows.some((r) => r.textContent?.includes('待回传主会话'))).toBe(true);
    const l5Row = rows.find((r) => r.getAttribute('data-session-id') === 'c5')!;
    expect(l5Row.getAttribute('data-depth')).toBe('5');
    expect(l5Row.getAttribute('data-visual-depth')).toBe('4');
    expect(l5Row.textContent).toContain('L5');

    // AC-08: 进程默认只展示人话摘要，不默认裸露 PID 4101；点击展开后展示技术明细
    expect(screen.getByTestId('progress-child-processes').textContent).toContain('执行测试（pytest）');
    expect(screen.getByTestId('progress-child-processes').textContent).not.toContain('PID 4101');
    fireEvent.click(screen.getByTestId('process-details-toggle-4101'));
    const tech = screen.getByTestId('process-technical-details-4101');
    expect(tech.textContent).toContain('PID 4101');
    expect(tech.textContent).toContain('python3 -m pytest tests/unit');
    expect(tech.textContent).toContain('frago-agent-c5');

    // AC-09: Tasks Overview 唯一匹配执行体可点击跳转
    fireEvent.click(screen.getByTestId('task-actor-link-c1'));
    expect(onSelectSession).toHaveBeenCalledWith('c1');
  });

  it('AC-05: 纯历史委派默认降位折叠在事项总控表下方，点击可展开', () => {
    const historyData = makeChildrenResp({
      summary: {
        total_children: 1,
        running_children: 0,
        delivering_children: 0,
        total_processes: 0,
        running_processes: 0,
        has_running: false,
        host_alive: false,
        host_mode: 'none',
        external_host_alive: false,
      },
      child_sessions: [
        {
          session_id: 'hist-1',
          title: '已完成研究子会话',
          family: 'claude-code',
          relation_kind: 'dispatch',
          origin: 'worker',
          status: 'done',
          depth: 1,
          is_running: false,
          alive: false,
          in_tmux: false,
          tmux_name: null,
          launched_by_session_id: 'ses-1',
          launched_by_title: '当前',
          launched_by_label: '由当前会话派发',
          source: 'session_origin',
          job_id: null,
          delivery_state: null,
          employee_id: null,
          prompt_head: '',
          started_at: 1_700_000_000_000,
          last_active_at: 1_700_000_001_000,
        },
      ],
    });

    render(
      <RecordStream
        {...baseProps({
          childrenData: historyData,
          observer: {
            state: {
              anchor: '目标',
              phase_goal: null,
              happened: [],
              tail: { kind: 'output', text: '完毕' },
              decision: null,
              tasks: [],
              runs: [],
              model: 'observer',
              updated_at: 1_700_000_000_000,
            },
            loading: false,
            error: null,
          },
        })}
      />
    );

    fireEvent.click(screen.getByTestId('lens-watcher'));
    const delSec = screen.getByTestId('progress-delegation-section');
    const tasksSec = screen.getByTestId('watcher-tasks-table');
    // 位于事项总控表之后且默认折叠
    expect(Boolean(tasksSec.compareDocumentPosition(delSec) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(delSec.getAttribute('data-mode')).toBe('history-collapsed');
    expect(screen.queryByTestId('child-session-row')).toBeNull();

    fireEvent.click(screen.getByTestId('progress-delegation-toggle'));
    expect(screen.getByTestId('child-session-row').textContent).toContain('已完成研究子会话');
  });

  it('AC-06: 同级已完结超过 5 条时默认折留最近 3 条并支持展开全部', () => {
    const manyFinished = makeChildrenResp({
      summary: {
        total_children: 7,
        running_children: 0,
        delivering_children: 0,
        total_processes: 0,
        running_processes: 0,
        has_running: false,
        host_alive: false,
        host_mode: 'none',
        external_host_alive: false,
      },
      child_sessions: Array.from({ length: 7 }, (_, i) => ({
        session_id: `fin-${i}`,
        title: `已结束子任务 ${i}`,
        family: 'claude-code',
        relation_kind: 'dispatch',
        origin: 'worker',
        status: 'done',
        depth: 1,
        is_running: false,
        alive: false,
        in_tmux: false,
        tmux_name: null,
        launched_by_session_id: 'ses-1',
        launched_by_title: '当前',
        launched_by_label: '',
        source: 'session_origin',
        job_id: null,
        delivery_state: null,
        employee_id: null,
        prompt_head: '',
        started_at: 1_700_000_000_000 + i * 1000,
        last_active_at: 1_700_000_010_000 - i * 1000,
      })),
    });

    render(<RecordStream {...baseProps({ childrenData: manyFinished })} />);
    fireEvent.click(screen.getByTestId('lens-watcher'));
    fireEvent.click(screen.getByTestId('progress-delegation-toggle'));

    expect(screen.getAllByTestId('child-session-row')).toHaveLength(3);
    const expandMoreBtn = screen.getByTestId('tree-expand-finished-root');
    expect(expandMoreBtn.textContent).toContain('4');

    fireEvent.click(expandMoreBtn);
    expect(screen.getAllByTestId('child-session-row')).toHaveLength(7);
  });

  it('AC-13: useSessionChildren 不因平台托管 host_alive 进入 4 秒快轮询，仅对 live/has_running/external_host_alive 快轮询', async () => {
    const intervals: number[] = [];
    vi.spyOn(useAutoRefreshMod, 'useAutoRefresh').mockImplementation((_cb, opts) => {
      if (opts?.intervalMs) intervals.push(opts.intervalMs);
      return { refresh: vi.fn() };
    });
    vi.spyOn(apiClient, 'getSessionChildren').mockResolvedValue(
      makeChildrenResp({
        session_id: 'ses-tmux',
        summary: {
          total_children: 0,
          running_children: 0,
          delivering_children: 0,
          total_processes: 0,
          running_processes: 0,
          has_running: false,
          host_alive: true,
          host_mode: 'managed_tmux',
          external_host_alive: false,
        },
      })
    );

    const { result, rerender } = renderHook(
      ({ sid, live }) => useSessionChildren(sid, { live }),
      { initialProps: { sid: 'ses-tmux', live: false } }
    );

    await waitFor(() => {
      expect(result.current.data?.summary?.host_mode).toBe('managed_tmux');
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(intervals[intervals.length - 1]).toBe(CHILDREN_IDLE_POLL_MS);

    // 真实外部终端接入 -> 切入 4s 快轮询
    vi.spyOn(apiClient, 'getSessionChildren').mockResolvedValue(
      makeChildrenResp({
        session_id: 'ses-ext',
        summary: {
          total_children: 0,
          running_children: 0,
          delivering_children: 0,
          total_processes: 0,
          running_processes: 0,
          has_running: false,
          host_alive: true,
          host_mode: 'external_cli',
          external_host_alive: true,
        },
      })
    );
    await act(async () => {
      rerender({ sid: 'ses-ext', live: false });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(result.current.data?.summary?.external_host_alive).toBe(true);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(intervals[intervals.length - 1]).toBe(CHILDREN_ACTIVE_POLL_MS);
  });

  it('AC-15 & AC-18: 快速切换会话绝不串台上一场子数据；SessionLaunchPanel 不渲染过期 0/1 计数', () => {
    const sesAChildren = makeChildrenResp({
      session_id: 'ses-A',
      launched_by: {
        session_id: 'parent-A',
        title: '会话A上游',
        family: 'claude-code',
        relation_kind: 'branch',
        origin: 'human',
        source: 'session_origin',
        label: '从「会话A上游」分出分支',
      },
      summary: {
        total_children: 1,
        running_children: 1,
        delivering_children: 0,
        total_processes: 0,
        running_processes: 0,
        has_running: true,
        host_alive: false,
        host_mode: 'none',
        external_host_alive: false,
      },
      child_sessions: [
        {
          session_id: 'child-A',
          title: '会话A的专属子任务',
          family: 'claude-code',
          relation_kind: 'dispatch',
          origin: 'worker',
          status: 'running',
          depth: 1,
          is_running: true,
          alive: true,
          in_tmux: false,
          tmux_name: null,
          launched_by_session_id: 'ses-A',
          launched_by_title: 'A',
          launched_by_label: '',
          source: 'session_origin',
          job_id: null,
          delivery_state: null,
          employee_id: null,
          prompt_head: '',
          started_at: 1_700_000_000_000,
          last_active_at: 1_700_000_000_000,
        },
      ],
    });

    const { rerender } = render(
      <RecordStream {...baseProps({ sessionId: 'ses-A', childrenData: sesAChildren })} />
    );
    expect(screen.getByTestId('lens-watcher-badge').textContent).toBe('1');
    fireEvent.click(screen.getByTestId('lens-watcher'));
    expect(screen.getByTestId('watcher-view').textContent).toContain('会话A的专属子任务');

    // 切到 ses-B，但 childrenData 仍滞留 ses-A（模拟网络乱序）
    rerender(
      <RecordStream
        {...baseProps({
          sessionId: 'ses-B',
          records: [makeRecord({ id: 'b1', session_id: 'ses-B', seq: 0, payload: { text: 'B对话' } })],
          childrenData: sesAChildren,
        })}
      />
    );
    expect(screen.queryByTestId('lens-watcher-badge')).toBeNull();
    expect(screen.queryByText('会话A的专属子任务')).toBeNull();
    expect(screen.queryByText('从「会话A上游」分出分支')).toBeNull();

    // AC-18: SessionLaunchPanel 过渡态 lens-watcher 无静态 0/1 计数
    cleanup();
    render(
      <SessionLaunchPanel
        launch={{
          handle: 'h1',
          agentName: 'claude',
          cwd: '/tmp',
          text: '开始写代码',
          sessionId: null,
          phase: 'claiming',
          error: null,
          at: Date.now(),
        }}
        onDismiss={() => {}}
      />
    );
    expect(screen.getByTestId('lens-watcher').textContent).toBe('进展');
  });
});
