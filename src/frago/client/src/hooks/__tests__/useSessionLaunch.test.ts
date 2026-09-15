/**
 * 新会话从「点了创建」到「界面上真的有它」这段路。
 *
 * 三家分两条：claude 的编号点完创建当场就有，codex / opencode 要等它自己报。两条最后
 * 汇到同一处——会话进了清单，这块启动状态就该让位。
 *
 * 认编号那条路会去问服务端，这里用替身顶掉；轮询的第一拍在 700ms，所以这几条用真时钟等。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { useSessionLaunch } from '../useSessionLaunch';
import type { PendingLaunch } from '../useAgentClients';
import type { WorkbenchSession } from '../useWorkbenchSessions';
import i18n from '@/i18n';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const HANDLE = 'launch-1';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function pending(over: Partial<PendingLaunch> = {}): PendingLaunch {
  return {
    handle: HANDLE,
    agent: 'codex',
    display_name: 'codex',
    cwd: '/Users/frago/Repos/frago',
    session_id: null,
    error: null,
    finished: false,
    ...over,
  };
}

function session(sid: string): WorkbenchSession {
  return {
    session_id: sid,
    family: 'claude-code',
    title: '新会话',
    directory: '/Users/frago/Repos/frago',
    status: 'running',
  } as WorkbenchSession;
}

/** 顶替「问这次新建报编号没有」那条接口。 */
function stubPending(answer: () => PendingLaunch) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => answer() }) as Response)
  );
}

describe('新会话正在启动', () => {
  it('claude 的编号当场就有，直接进「正在启动」并把中栏切过去', () => {
    const onReady = vi.fn();
    const { result } = renderHook(() =>
      useSessionLaunch({ sessions: [], reload: () => {}, onReady })
    );

    act(() => {
      result.current.begin(pending({ session_id: SID, display_name: 'Claude Code' }), '把日志翻出来');
    });

    expect(result.current.launch?.phase).toBe('warming');
    expect(result.current.launch?.sessionId).toBe(SID);
    // 那句话要留着：等待期间界面上只有它是人自己的东西。
    expect(result.current.launch?.text).toBe('把日志翻出来');
    expect(onReady).toHaveBeenCalledWith(SID);
  });

  it('编号要等的那两家先停在「正在认领编号」，报出来才转档', async () => {
    let reported = false;
    stubPending(() => pending({ session_id: reported ? SID : null }));
    const onReady = vi.fn();
    const { result } = renderHook(() =>
      useSessionLaunch({ sessions: [], reload: () => {}, onReady })
    );

    act(() => {
      result.current.begin(pending(), '起一场新的');
    });
    expect(result.current.launch?.phase).toBe('claiming');
    expect(onReady).not.toHaveBeenCalled();

    reported = true;
    await waitFor(() => expect(result.current.launch?.phase).toBe('warming'), { timeout: 4000 });
    expect(result.current.launch?.sessionId).toBe(SID);
    expect(onReady).toHaveBeenCalledWith(SID);
  });

  it('会话进了清单，这块就让位——它替的正是那一行', async () => {
    const onReady = vi.fn();
    const { result, rerender } = renderHook(
      ({ sessions }) => useSessionLaunch({ sessions, reload: () => {}, onReady }),
      { initialProps: { sessions: [] as WorkbenchSession[] } }
    );

    act(() => {
      result.current.begin(pending({ session_id: SID }), '起一场新的');
    });
    expect(result.current.launch).not.toBeNull();

    rerender({ sessions: [session(SID)] });
    await waitFor(() => expect(result.current.launch).toBeNull());
  });

  it('中栏正开着这一场时，进了清单照样让位——不许等 agent 开口', async () => {
    /**
     * 这一条钉的是一次真事故。判据一度被改成"中栏正开着这一场时，等 agent 动了才让
     * 位"，理由是想让人看清那两步。代价是这块卡会挂死：新起的那一场在清单里还不算
     * "在跑"，记录流因此既不轮询也没人推，agent 说没说话这一侧根本问不到，卡就一直
     * 站在中栏挡着不走。退场判据只能挂在这一侧看得见的事实上。
     */
    const { result, rerender } = renderHook(
      ({ sessions }) =>
        useSessionLaunch({
          sessions,
          reload: () => {},
          onReady: () => {},
          recordsSessionId: null,
          // 记录一条都还没有，也不该拦着它让位。
          recordCount: 0,
        }),
      { initialProps: { sessions: [] as WorkbenchSession[] } }
    );

    act(() => {
      result.current.begin(pending({ session_id: SID }), '起一场新的');
    });
    expect(result.current.launch).not.toBeNull();

    rerender({ sessions: [session(SID)] });
    await waitFor(() => expect(result.current.launch).toBeNull());
  });

  it('清单还没扫到它，但它已经写下第一笔了，同样让位', async () => {
    const { result, rerender } = renderHook(
      ({ n }) =>
        useSessionLaunch({
          sessions: [],
          reload: () => {},
          onReady: () => {},
          recordsSessionId: n > 0 ? SID : null,
          recordCount: n,
        }),
      { initialProps: { n: 0 } }
    );

    act(() => {
      result.current.begin(pending({ session_id: SID }), '起一场新的');
    });
    expect(result.current.launch).not.toBeNull();

    rerender({ n: 3 });
    await waitFor(() => expect(result.current.launch).toBeNull());
  });

  it('中栏手上还是上一场的记录时，不许当成新这一场写下了第一笔', async () => {
    /**
     * 钉的是一次真事故：人从一场有内容的会话里点新建，中栏切到新编号的那一次渲染里
     * 手上还是上一场的记录，启动卡一挂上就被当成"已经写下第一笔"撤掉，人根本看不见它。
     */
    const OLD = '11111111-2222-4333-8444-555555555555';
    const { result, rerender } = renderHook(
      ({ owner, n }) =>
        useSessionLaunch({
          sessions: [],
          reload: () => {},
          onReady: () => {},
          recordsSessionId: owner,
          recordCount: n,
        }),
      { initialProps: { owner: OLD as string | null, n: 40 } }
    );

    act(() => {
      result.current.begin(pending({ session_id: SID }), '起一场新的');
    });
    rerender({ owner: OLD, n: 40 });
    await new Promise((r) => setTimeout(r, 50));
    expect(result.current.launch).not.toBeNull();

    // 下一拍清空了，卡照样挂着。
    rerender({ owner: null, n: 0 });
    await new Promise((r) => setTimeout(r, 50));
    expect(result.current.launch).not.toBeNull();
  });

  it('没起来就停在那儿说原因，不自己消失——一关了之，人连刚打的字都找不回来', async () => {
    stubPending(() => pending({ error: 'codex 起不来：命令没找到' }));
    const { result } = renderHook(() =>
      useSessionLaunch({ sessions: [], reload: () => {}, onReady: () => {} })
    );

    act(() => {
      result.current.begin(pending(), '起一场新的');
    });

    await waitFor(() => expect(result.current.launch?.phase).toBe('failed'), { timeout: 4000 });
    expect(result.current.launch?.error).toContain('命令没找到');
    expect(result.current.launch?.text).toBe('起一场新的');

    act(() => result.current.dismiss());
    expect(result.current.launch).toBeNull();
  });
});
