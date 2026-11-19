import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import i18n from '@/i18n';
import SessionChildrenBar from '../SessionChildrenBar';
import type { SessionChildrenResponse } from '@/types/api';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function makeResponse(over: Partial<SessionChildrenResponse> = {}): SessionChildrenResponse {
  return {
    session_id: 'parent-1',
    launched_by: null,
    summary: {
      total_children: 0,
      running_children: 0,
      delivering_children: 0,
      total_processes: 0,
      running_processes: 0,
      host_alive: false,
      has_running: false,
    },
    child_sessions: [],
    child_processes: [],
    ...over,
  };
}

describe('SessionChildrenBar', () => {
  it('无来源、无子会话、无活跃宿主或子进程时不渲染占位噪音', () => {
    const { container, rerender } = render(<SessionChildrenBar data={null} />);
    expect(container.firstChild).toBeNull();

    rerender(<SessionChildrenBar data={makeResponse()} />);
    expect(container.firstChild).toBeNull();
  });

  it('存在运行中的 claude --resume 子进程与派生 Worker 时默认展开，明确回答是谁起的、是什么、是否还在跑', () => {
    const onSelect = vi.fn();
    const data = makeResponse({
      summary: {
        total_children: 1,
        running_children: 1,
        delivering_children: 0,
        total_processes: 1,
        running_processes: 1,
        host_alive: true,
        has_running: true,
      },
      child_processes: [
        {
          pid: 4201,
          ppid: 4200,
          comm: 'pytest',
          command: 'python3 -m pytest tests/unit',
          elapsed: '01:12',
          state: 'R',
          is_running: true,
          kind: 'command',
          source: 'process_tree',
          tmux_name: null,
          host_session_id: 'parent-1',
          launched_by_pid: 4200,
          launched_by_comm: 'claude',
          launched_by_session_id: 'parent-1',
          launched_by_label: '由当前会话主进程 (claude · PID 4200) 启动',
          linked_session_id: null,
        },
      ],
      child_sessions: [
        {
          session_id: 'worker-1',
          title: '独立代码评审 Worker',
          family: 'claude-code',
          relation_kind: 'dispatch',
          origin: 'worker',
          status: 'running',
          is_running: true,
          alive: true,
          in_tmux: true,
          tmux_name: 'frago-agent-worker-1',
          launched_by_session_id: 'parent-1',
          launched_by_title: '主控会话',
          launched_by_label: '由当前会话派发',
          source: 'session_origin',
          job_id: null,
          delivery_state: null,
          employee_id: null,
          prompt_head: '评审改动',
          started_at: 1_700_000_000_000,
          last_active_at: 1_700_000_010_000,
        },
      ],
    });

    render(<SessionChildrenBar data={data} onSelectSession={onSelect} />);

    expect(screen.getByTestId('session-children-bar').getAttribute('data-has-running')).toBe('true');
    expect(screen.getByTestId('session-children-running-banner').textContent).toContain('2');
    // 默认展开，无需额外点击即可看到
    expect(screen.getByTestId('session-children-list')).toBeTruthy();

    const procRow = screen.getByTestId('child-process-row');
    expect(procRow.getAttribute('data-running')).toBe('true');
    expect(procRow.textContent).toContain('PID 4201');
    expect(procRow.textContent).toContain('由当前会话主进程 (claude · PID 4200) 启动');
    expect(procRow.textContent).toContain('python3 -m pytest tests/unit');

    const childRow = screen.getByTestId('child-session-row');
    expect(childRow.getAttribute('data-running')).toBe('true');
    expect(childRow.textContent).toContain('运行中');
    expect(childRow.textContent).toContain('独立代码评审 Worker');
    expect(screen.getByTestId('child-session-launcher').textContent).toBe('由当前会话派发');

    fireEvent.click(screen.getByTestId('open-child-session-worker-1'));
    expect(onSelect).toHaveBeenCalledWith('worker-1');
  });

  it('仅有已完结历史子会话时默认折叠，可展开查看已完成状态，并展示当前会话自身的启动来源', () => {
    const onSelect = vi.fn();
    const data = makeResponse({
      session_id: 'child-9',
      launched_by: {
        session_id: 'root-0',
        title: '根主控会话',
        family: 'claude-code',
        relation_kind: 'dispatch',
        origin: 'worker',
        source: 'session_origin',
        label: '由「根主控会话」派发启动',
      },
      summary: {
        total_children: 1,
        running_children: 0,
        delivering_children: 0,
        total_processes: 0,
        running_processes: 0,
        host_alive: false,
        has_running: false,
      },
      child_sessions: [
        {
          session_id: 'grand-1',
          title: '二级自测子会话',
          family: 'claude-code',
          relation_kind: 'dispatch',
          origin: 'worker',
          status: 'done',
          is_running: false,
          alive: false,
          in_tmux: false,
          tmux_name: null,
          launched_by_session_id: 'child-9',
          launched_by_title: '当前子会话',
          launched_by_label: '由当前会话派发',
          source: 'session_origin',
          job_id: null,
          delivery_state: null,
          employee_id: null,
          prompt_head: '',
          started_at: 1_700_000_000_000,
          last_active_at: 1_700_000_005_000,
        },
      ],
    });

    render(<SessionChildrenBar data={data} onSelectSession={onSelect} />);

    expect(screen.getByTestId('session-launched-by').textContent).toContain('由「根主控会话」派发启动');
    fireEvent.click(screen.getByTestId('session-launched-by-open'));
    expect(onSelect).toHaveBeenCalledWith('root-0');

    expect(screen.getByTestId('session-children-history-summary')).toBeTruthy();
    expect(screen.queryByTestId('session-children-list')).toBeNull();

    fireEvent.click(screen.getByTestId('session-children-toggle'));
    const childRow = screen.getByTestId('child-session-row');
    expect(childRow.getAttribute('data-running')).toBe('false');
    expect(screen.getByTestId('child-session-status').textContent).toContain('已完成');
  });
});
