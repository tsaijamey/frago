/**
 * 左栏两个筛选维度的取数逻辑：搜索、时间范围、状态各管各的，计数在状态之前算完。
 *
 * 时间范围比的是**最后活动时刻**，不是创建时刻——一场半年前开、昨天还在跑的会话，问
 * 「最近七天」时必须留下。所以样本的时刻按取数那一刻现算，不写死。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkbenchSessions, type WorkbenchSession } from '../useWorkbenchSessions';

const DAY = 24 * 60 * 60 * 1000;

function session(over: Partial<WorkbenchSession> & Pick<WorkbenchSession, 'session_id'>): WorkbenchSession {
  const now = Date.now();
  return {
    family: 'claude-code',
    title: '会话工作台 webUI',
    directory: '/Users/frago/Repos/frago',
    created_at: now - 200 * DAY,
    last_active_at: now,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    ...over,
  };
}

function fixture(): WorkbenchSession[] {
  const now = Date.now();
  return [
    session({ session_id: 'today', title: '今天动过', last_active_at: now - 2 * 60_000 }),
    session({
      session_id: 'three-days',
      title: '三天前动过',
      last_active_at: now - 3 * DAY,
      status: 'error',
    }),
    session({
      session_id: 'old',
      title: '半年前就没动了',
      last_active_at: now - 200 * DAY,
      status: 'idle',
      family: 'opencode',
    }),
  ];
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => fixture() })) as unknown as typeof fetch
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function loaded() {
  const hook = renderHook(() => useWorkbenchSessions());
  await waitFor(() => expect(hook.result.current.sessions).toHaveLength(3));
  return hook.result;
}

describe('useWorkbenchSessions', () => {
  it('默认不限时间——一千多场不该被一个默认值挡在外面', async () => {
    const result = await loaded();
    expect(result.current.days).toBe(0);
    expect(result.current.visible).toHaveLength(3);
  });

  it('时间范围按最后活动时刻收窄，计数跟着一起收', async () => {
    const result = await loaded();

    act(() => result.current.setDays(1));
    expect(result.current.visible.map((s) => s.session_id)).toEqual(['today']);
    expect(result.current.counts.all).toBe(1);

    act(() => result.current.setDays(7));
    expect(result.current.visible.map((s) => s.session_id)).toEqual(['today', 'three-days']);
    expect(result.current.counts.error).toBe(1);
  });

  it('时间范围与状态是两个维度，可以同时生效', async () => {
    const result = await loaded();

    act(() => result.current.setDays(7));
    act(() => result.current.setStatus('error'));
    expect(result.current.visible.map((s) => s.session_id)).toEqual(['three-days']);
    // 计数在状态之前算完，所以点进「出错」之后别档的数还是原来那些。
    expect(result.current.counts.all).toBe(2);
    expect(result.current.counts.done).toBe(1);
  });

  it('搜索先收一道，时间范围再收一道', async () => {
    const result = await loaded();

    act(() => result.current.setSearch('动过'));
    expect(result.current.counts.all).toBe(2);
    act(() => result.current.setDays(1));
    expect(result.current.visible.map((s) => s.session_id)).toEqual(['today']);
  });
});
