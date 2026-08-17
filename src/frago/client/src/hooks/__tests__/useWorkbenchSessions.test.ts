/**
 * 左栏两个筛选维度的取数逻辑：搜索、时间范围、状态各管各的，计数在状态之前算完。
 *
 * 时间范围比的是**排序用的那个时刻**（最后一句回复，取不到才退回文件动过的时刻），
 * 不是创建时刻——一场半年前开、昨天还在跑的会话，问「最近七天」时必须留下。所以样本
 * 的时刻按取数那一刻现算，不写死。
 *
 * 搜索有两条腿：本地筛标题目录编号，服务端搜会话内容，结果取并集。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  activityTs,
  useWorkbenchSessions,
  type WorkbenchSession,
} from '../useWorkbenchSessions';

const DAY = 24 * 60 * 60 * 1000;

function session(over: Partial<WorkbenchSession> & Pick<WorkbenchSession, 'session_id'>): WorkbenchSession {
  const now = Date.now();
  return {
    family: 'claude-code',
    title: '会话工作台 webUI',
    directory: '/Users/frago/Repos/frago',
    created_at: now - 200 * DAY,
    last_active_at: now,
    last_reply_at: null,
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

describe('排序与筛选用的时刻', () => {
  it('有回复时刻就用它，NEVER 用文件动过的时刻', () => {
    const now = Date.now();
    const s = session({
      session_id: 'x',
      last_active_at: now,
      last_reply_at: now - 10 * DAY,
    });
    expect(activityTs(s)).toBe(now - 10 * DAY);
  });

  it('取不到回复时刻才退回文件动过的时刻', () => {
    const now = Date.now();
    expect(activityTs(session({ session_id: 'x', last_active_at: now }))).toBe(now);
  });

  it('时间范围按同一个时刻收窄：只被 hook 蹭过的老会话不该留在最近七天里', async () => {
    const now = Date.now();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => [
          // 文件是刚刚动过的（hook 写了一条），但最后一句回复是二十天前。
          session({
            session_id: 'touched-only',
            last_active_at: now - 60_000,
            last_reply_at: now - 20 * DAY,
          }),
          session({ session_id: 'really-talked', last_reply_at: now - 60_000 }),
        ],
      })) as unknown as typeof fetch
    );
    const hook = renderHook(() => useWorkbenchSessions());
    await waitFor(() => expect(hook.result.current.sessions).toHaveLength(2));

    act(() => hook.result.current.setDays(7));

    expect(hook.result.current.visible.map((s) => s.session_id)).toEqual(['really-talked']);
  });
});

describe('内容检索这条腿', () => {
  it('太短的词不发请求，只走本地那一条', async () => {
    const result = await loaded();

    act(() => result.current.setSearch('动'));

    expect(result.current.content.searching).toBe(false);
    expect(result.current.content.matches.size).toBe(0);
  });

  it('内容命中的会话即使标题对不上也要留在清单里', async () => {
    vi.useFakeTimers();
    try {
      const calls: string[] = [];
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          calls.push(url);
          if (url.includes('/api/workbench/search')) {
            return {
              ok: true,
              json: async () => ({
                sessions: [
                  {
                    session_id: 'old',
                    family: 'opencode',
                    hit_count: 3,
                    capped: false,
                    hits: [
                      {
                        record_id: 'r1',
                        kind: 'user.say',
                        ts: 1,
                        snippet: '…把飞书那条推送修一下…',
                      },
                    ],
                  },
                ],
                warnings: ['ripgrep 不在 PATH 上'],
              }),
            };
          }
          return { ok: true, json: async () => fixture() };
        }) as unknown as typeof fetch
      );

      const hook = renderHook(() => useWorkbenchSessions());
      await vi.waitFor(() => expect(hook.result.current.sessions).toHaveLength(3));

      act(() => hook.result.current.setSearch('飞书推送'));
      // 敲完字要等一拍才发，这一拍之内不该有请求。
      expect(calls.some((u) => u.includes('/api/workbench/search'))).toBe(false);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(600);
      });

      // 标题里没有「飞书推送」，纯靠内容命中留下来。
      expect(hook.result.current.visible.map((s) => s.session_id)).toEqual(['old']);
      expect(hook.result.current.content.matches.get('old')?.hit_count).toBe(3);
      expect(hook.result.current.content.warnings).toEqual(['ripgrep 不在 PATH 上']);
    } finally {
      vi.useRealTimers();
    }
  });
});
