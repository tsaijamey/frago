import { describe, expect, it } from 'vitest';
import type {
  SessionChildProcess,
  SessionChildSession,
  SessionChildrenResponse,
} from '@/types/api';
import {
  buildChildSessionTree,
  computeProgressBadge,
  formatElapsedHuman,
  matchActorToChildSession,
  partitionTreeSiblings,
  summarizeChildProcess,
} from '../sessionChildrenTree';

function makeChild(over: Partial<SessionChildSession> & { session_id: string }): SessionChildSession {
  return {
    title: `会话 ${over.session_id}`,
    family: 'claude-code',
    relation_kind: 'dispatch',
    origin: 'worker',
    status: 'done',
    is_running: false,
    alive: false,
    in_tmux: false,
    tmux_name: null,
    launched_by_session_id: 'root',
    launched_by_title: '根会话',
    launched_by_label: '由当前会话派发',
    source: 'session_origin',
    job_id: null,
    delivery_state: null,
    employee_id: null,
    prompt_head: '',
    started_at: 1_700_000_000_000,
    last_active_at: 1_700_000_000_000,
    ...over,
  };
}

function makeProc(over: Partial<SessionChildProcess> & { pid: number }): SessionChildProcess {
  return {
    ppid: 1000,
    comm: 'python3',
    command: 'python3 -m pytest tests/unit',
    elapsed: '01:12',
    state: 'R',
    is_running: true,
    kind: 'command',
    source: 'process_tree',
    tmux_name: null,
    host_session_id: 'root',
    launched_by_pid: 1000,
    launched_by_comm: 'claude',
    launched_by_session_id: 'root',
    launched_by_label: '由当前会话主进程启动',
    linked_session_id: null,
    ...over,
  };
}

function makeResp(over: Partial<SessionChildrenResponse> = {}): SessionChildrenResponse {
  return {
    session_id: 'root',
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

describe('sessionChildrenTree utils', () => {
  it('computeProgressBadge 按目标会话与独立进程严格去重并处理 9+ 与纯外部圆点', () => {
    // 0 活跃且无外部接入 -> 无角标无圆点
    expect(computeProgressBadge(makeResp())).toEqual({
      activeCount: 0,
      runningCount: 0,
      deliveringCount: 0,
      badgeText: null,
      tone: 'none',
      externalOnlyDot: false,
    });

    // 1 个运行中子会话下挂 2 个子进程 -> 去重为 1
    const oneChildTwoProcs = makeResp({
      summary: {
        total_children: 1,
        running_children: 1,
        delivering_children: 0,
        total_processes: 2,
        running_processes: 2,
        has_running: true,
        host_alive: true,
        host_mode: 'managed_tmux',
        external_host_alive: false,
      },
      child_sessions: [makeChild({ session_id: 'w1', status: 'running', is_running: true })],
      child_processes: [
        makeProc({ pid: 201, host_session_id: 'w1', launched_by_session_id: 'w1' }),
        makeProc({ pid: 202, host_session_id: 'w1', launched_by_session_id: 'w1' }),
      ],
    });
    expect(computeProgressBadge(oneChildTwoProcs)).toMatchObject({
      activeCount: 1,
      badgeText: '1',
      tone: 'running',
      externalOnlyDot: false,
    });

    // 再加 1 个主会话直接拉起的无归属独立后台进程 -> 计为 2
    const plusMainProc = {
      ...oneChildTwoProcs,
      child_processes: [
        ...oneChildTwoProcs.child_processes,
        makeProc({ pid: 203, host_session_id: 'root', launched_by_session_id: 'root', linked_session_id: null }),
      ],
    };
    expect(computeProgressBadge(plusMainProc)).toMatchObject({
      activeCount: 2,
      badgeText: '2',
      tone: 'running',
    });

    // 仅待回传态 -> 告警橙 tone = delivering
    const deliveringOnly = makeResp({
      summary: {
        total_children: 1,
        running_children: 0,
        delivering_children: 1,
        total_processes: 0,
        running_processes: 0,
        has_running: true,
        host_alive: false,
        host_mode: 'none',
        external_host_alive: false,
      },
      child_sessions: [makeChild({ session_id: 'w-del', status: 'delivering' })],
    });
    expect(computeProgressBadge(deliveringOnly)).toMatchObject({
      activeCount: 1,
      badgeText: '1',
      tone: 'delivering',
    });

    // 12 个活跃子会话 -> 显示 9+
    const twelve = makeResp({
      child_sessions: Array.from({ length: 12 }, (_, idx) =>
        makeChild({ session_id: `w-${idx}`, status: 'running', is_running: true })
      ),
    });
    expect(computeProgressBadge(twelve).badgeText).toBe('9+');

    // 0 活跃子任务但 external_host_alive = true -> 静止引导微点
    const extOnly = makeResp({
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
    });
    expect(computeProgressBadge(extOnly)).toEqual({
      activeCount: 0,
      runningCount: 0,
      deliveringCount: 0,
      badgeText: null,
      tone: 'none',
      externalOnlyDot: true,
    });
  });

  it('buildChildSessionTree 支持 8 层重组、环路保护、活跃祖先自动展开与第 4 层缩进封顶', () => {
    const chain: SessionChildSession[] = [
      makeChild({ session_id: 'l1-active', launched_by_session_id: 'root', status: 'done' }),
      makeChild({ session_id: 'l2-active', launched_by_session_id: 'l1-active', status: 'done' }),
      makeChild({ session_id: 'l3-active', launched_by_session_id: 'l2-active', status: 'done' }),
      makeChild({ session_id: 'l4-active', launched_by_session_id: 'l3-active', status: 'done' }),
      makeChild({ session_id: 'l5-active', launched_by_session_id: 'l4-active', status: 'done' }),
      makeChild({ session_id: 'l6-active', launched_by_session_id: 'l5-active', status: 'running', is_running: true }),
      // 第二条全完结分支：第 2 层节点默认收起
      makeChild({ session_id: 'l1-done', launched_by_session_id: 'root', status: 'done' }),
      makeChild({ session_id: 'l2-done', launched_by_session_id: 'l1-done', status: 'done' }),
      // 环路测试：cyc-a <-> cyc-b 不得死循环
      makeChild({ session_id: 'cyc-a', launched_by_session_id: 'cyc-b', status: 'done' }),
      makeChild({ session_id: 'cyc-b', launched_by_session_id: 'cyc-a', status: 'done' }),
    ];

    const tree = buildChildSessionTree('root', chain);
    const l1Active = tree.find((n) => n.session.session_id === 'l1-active')!;
    const l1Done = tree.find((n) => n.session.session_id === 'l1-done')!;

    expect(l1Active.subtreeHasActiveOrError).toBe(true);
    expect(l1Active.defaultExpanded).toBe(true);
    expect(l1Done.subtreeHasActiveOrError).toBe(false);
    expect(l1Done.defaultExpanded).toBe(false);

    // 走到第 6 层，visualDepth 在 4 封顶
    let cur = l1Active;
    for (let depth = 2; depth <= 6; depth += 1) {
      expect(cur.children).toHaveLength(1);
      cur = cur.children[0];
      expect(cur.treeDepth).toBe(depth);
      expect(cur.visualDepth).toBe(Math.min(depth, 4));
      if (depth < 6) {
        expect(cur.defaultExpanded).toBe(true);
      }
    }
    expect(cur.session.session_id).toBe('l6-active');
    expect(tree.some((n) => n.session.session_id === 'cyc-a' || n.session.session_id === 'cyc-b')).toBe(true);
  });

  it('partitionTreeSiblings 在同级已完结超过 5 条时折留最近 3 条并保留全部活跃/异常项', () => {
    const items: SessionChildSession[] = [
      makeChild({ session_id: 'run-1', status: 'running', is_running: true }),
      makeChild({ session_id: 'err-1', status: 'error' }),
      ...Array.from({ length: 7 }, (_, i) =>
        makeChild({
          session_id: `done-${i}`,
          status: 'done',
          last_active_at: 1_700_000_000_000 + (7 - i) * 1000,
        })
      ),
    ];
    const tree = buildChildSessionTree('root', items);
    const part = partitionTreeSiblings(tree);
    expect(part.visibleNodes.map((n) => n.session.session_id)).toEqual([
      'run-1',
      'err-1',
      'done-0',
      'done-1',
      'done-2',
    ]);
    expect(part.hiddenCount).toBe(4);
  });

  it('summarizeChildProcess 与 formatElapsedHuman 输出普通人可读摘要与时长', () => {
    expect(summarizeChildProcess(makeProc({ pid: 1, command: 'python3 -m pytest tests/unit' }), true)).toBe(
      '执行测试（pytest）'
    );
    expect(summarizeChildProcess(makeProc({ pid: 2, command: '/bin/bash -c "npm run build"' }), true)).toBe(
      '前端构建与类型检查'
    );
    expect(summarizeChildProcess(makeProc({ pid: 3, command: 'claude --resume abc', kind: 'agent_cli' }), false)).toBe(
      'Running agent CLI (Claude)'
    );
    expect(formatElapsedHuman('01:12', true)).toBe('已运行 1 分 12 秒');
    expect(formatElapsedHuman('00:45', false)).toBe('Running 45s');
  });

  it('matchActorToChildSession 仅在唯一确定匹配时返回子会话', () => {
    const children = [
      makeChild({ session_id: 'child-stock-1', employee_id: 'stock-analyst', title: '股市分析员' }),
      makeChild({ session_id: 'child-dup-1', employee_id: 'reviewer', title: '评审 A' }),
      makeChild({ session_id: 'child-dup-2', employee_id: 'reviewer', title: '评审 B' }),
    ];
    expect(matchActorToChildSession('主会话', children)).toBeNull();
    expect(matchActorToChildSession('stock-analyst', children)?.session_id).toBe('child-stock-1');
    expect(matchActorToChildSession('reviewer', children)).toBeNull();
  });
});
