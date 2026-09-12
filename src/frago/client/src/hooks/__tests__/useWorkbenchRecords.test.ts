/**
 * 中栏数据源：尾部优先装载、往上翻前插旧页、活会话轮询取增量。
 *
 * fetch 这一层用一场「虚拟会话」顶替：总条数可变，模拟会话还在长。三种取法各自断言
 * 查询参数与落进流里的序号。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  PAGE_SIZE,
  POLL_INTERVAL_MS,
  useWorkbenchRecords,
  type WorkbenchRecord,
} from '../useWorkbenchRecords';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

function record(seq: number): WorkbenchRecord {
  return {
    id: `rec-${seq}`,
    session_id: SID,
    group_id: null,
    seq,
    ts: 1_753_800_000_000 + seq,
    kind: 'agent.say',
    agent_path: [],
    payload: { text: `第 ${seq} 条` },
    raw_available: true,
  };
}

/** 顶替 fetch：一场 `total()` 条的虚拟会话，认识 tail / after / limit 三个参数。 */
function stubSession(total: () => number) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const limit = Number(url.match(/limit=(\d+)/)?.[1] ?? PAGE_SIZE);
    const n = total();
    let seqs: number[];
    if (/[?&]tail=true/.test(url)) {
      const start = Math.max(0, n - limit);
      seqs = Array.from({ length: n - start }, (_, i) => start + i);
    } else {
      const after = Number(url.match(/after=(\d+)/)?.[1] ?? 0);
      const end = Math.min(after + limit, n);
      seqs = Array.from({ length: Math.max(end - after, 0) }, (_, i) => after + i);
    }
    return { ok: true, json: async () => seqs.map(record) } as Response;
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useWorkbenchRecords', () => {
  it('打开会话取尾部一页，之上还有就报还有', async () => {
    vi.stubGlobal('fetch', stubSession(() => 450));
    const { result } = renderHook(() => useWorkbenchRecords(SID));

    await waitFor(() => expect(result.current.records).toHaveLength(PAGE_SIZE));
    expect(result.current.records[0].seq).toBe(250);
    expect(result.current.records[PAGE_SIZE - 1].seq).toBe(449);
    expect(result.current.hasOlder).toBe(true);

    const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
    expect(urls[0]).toContain('tail=true');
  });

  it('小会话一次取完，之上没有了', async () => {
    vi.stubGlobal('fetch', stubSession(() => 50));
    const { result } = renderHook(() => useWorkbenchRecords(SID));

    await waitFor(() => expect(result.current.records).toHaveLength(50));
    expect(result.current.records[0].seq).toBe(0);
    expect(result.current.hasOlder).toBe(false);
  });

  it('往上翻把更早的一页前插进来，直到会话开头', async () => {
    vi.stubGlobal('fetch', stubSession(() => 450));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(PAGE_SIZE));

    await act(() => result.current.loadOlder());
    expect(result.current.records).toHaveLength(400);
    expect(result.current.records[0].seq).toBe(50);
    expect(result.current.hasOlder).toBe(true);

    await act(() => result.current.loadOlder());
    expect(result.current.records).toHaveLength(450);
    expect(result.current.records[0].seq).toBe(0);
    expect(result.current.hasOlder).toBe(false);
  });

  it('活会话轮询取增量，新条目往尾部追加', async () => {
    // 假时钟要在挂载之前就装上——挂载后才换钟，早已排上的真定时器不归假钟管。
    vi.useFakeTimers();
    try {
      let total = 300;
      vi.stubGlobal('fetch', stubSession(() => total));
      const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
      await act(async () => {});
      expect(result.current.records).toHaveLength(PAGE_SIZE);
      expect(result.current.records[PAGE_SIZE - 1].seq).toBe(299);

      total = 305;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 100);
      });
      expect(result.current.records).toHaveLength(PAGE_SIZE + 5);
      expect(result.current.records[PAGE_SIZE + 4].seq).toBe(304);

      const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
      expect(urls.some((u) => u.includes('after=299'))).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('死会话不轮询，发话后的重拉把它叫醒', async () => {
    vi.useFakeTimers();
    try {
      let total = 300;
      const fetchMock = stubSession(() => total);
      vi.stubGlobal('fetch', fetchMock);
      const { result } = renderHook(() => useWorkbenchRecords(SID));
      await act(async () => {});
      expect(result.current.records).toHaveLength(PAGE_SIZE);

      // 不活的会话：时间流过，一个请求都不多。
      const callsBefore = fetchMock.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
      });
      expect(fetchMock.mock.calls.length).toBe(callsBefore);

      // 发话后重拉：会话活了，增量自己流进来。
      await act(async () => {
        await result.current.reload();
      });
      total = 302;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 100);
      });
      expect(result.current.records).toHaveLength(PAGE_SIZE + 2);
      expect(result.current.records[PAGE_SIZE + 1].seq).toBe(301);
    } finally {
      vi.useRealTimers();
    }
  });

  it('换会话时旧流清掉，从头按尾部重取', async () => {
    const fetchMock = stubSession(() => 450);
    vi.stubGlobal('fetch', fetchMock);
    const { result, rerender } = renderHook(
      ({ sid }) => useWorkbenchRecords(sid),
      { initialProps: { sid: SID } }
    );
    await waitFor(() => expect(result.current.records).toHaveLength(PAGE_SIZE));

    rerender({ sid: 'another-one' });
    // 新会话按尾部重取了一回，请求打到新编号上。
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(
        urls.some((u) => u.includes('another-one') && u.includes('tail=true'))
      ).toBe(true);
    });
    await waitFor(() => expect(result.current.records).toHaveLength(PAGE_SIZE));
  });
});

describe('打开的时候档案还是空的', () => {
  // 新建那一场必定经过这个状态：中栏在点完创建那一刻就切了过去，那时它一条记录都还没
  // 写下。取增量要拿手头末条当起点，空手就无从下手——这几条钉住"空手也要能自己接上"，
  // 别再让人切走再切回来才看得见内容。

  it('空手开局的活会话，档案写下第一笔后自己取回来', async () => {
    vi.useFakeTimers();
    try {
      let total = 0;
      vi.stubGlobal('fetch', stubSession(() => total));
      const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
      await act(async () => {});
      expect(result.current.records).toHaveLength(0);

      total = 3;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 100);
      });
      expect(result.current.records).toHaveLength(3);
      expect(result.current.records[0].seq).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('会话转成「在跑」那一刻当场补取，不必等下一趟轮询', async () => {
    let total = 0;
    vi.stubGlobal('fetch', stubSession(() => total));
    const { result, rerender } = renderHook(
      ({ live }) => useWorkbenchRecords(SID, { live }),
      { initialProps: { live: false } }
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.records).toHaveLength(0);

    // 它进了左栏、显示「在跑」——档案这时已经落地了。
    total = 3;
    rerender({ live: true });
    await waitFor(() => expect(result.current.records).toHaveLength(3));
  });
});

describe('刚发完话那一阵', () => {
  it('举起「在等 agent 开口」，流里已有的旧记录不算它开了口', async () => {
    vi.stubGlobal('fetch', stubSession(() => 3));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    expect(result.current.awaitingAgent).toBe(false);
    act(() => result.current.markSent('一句话'));
    // 手上这三条都是上一轮的，一条都不该被当成"它刚开口"。
    expect(result.current.awaitingAgent).toBe(true);
  });

  it('agent 真吐出新记录，「在等」立刻撤掉', async () => {
    let grown = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        const fresh = { ...record(3), ts: Date.now(), kind: 'tool.call' as const };
        const all = [record(0), record(1), record(2), ...(grown ? [fresh] : [])];
        const after = Number(url.match(/after=(\d+)/)?.[1] ?? 0);
        const body = /[?&]tail=true/.test(url) ? all : all.filter((r) => r.seq >= after);
        return { ok: true, json: async () => body } as Response;
      })
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => result.current.markSent('一句话'));
    expect(result.current.awaitingAgent).toBe(true);

    // markSent 进了快节拍，一秒一趟——不必等满平时的五秒。
    grown = true;
    await waitFor(() => expect(result.current.records).toHaveLength(4), { timeout: 4000 });
    await waitFor(() => expect(result.current.awaitingAgent).toBe(false));
  });

  it('用户自己刚说的那句不算 agent 开了口', async () => {
    let grown = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        const mine = { ...record(3), ts: Date.now(), kind: 'user.say' as const };
        const all = [record(0), record(1), record(2), ...(grown ? [mine] : [])];
        const after = Number(url.match(/after=(\d+)/)?.[1] ?? 0);
        const body = /[?&]tail=true/.test(url) ? all : all.filter((r) => r.seq >= after);
        return { ok: true, json: async () => body } as Response;
      })
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => result.current.markSent('一句话'));
    grown = true;
    await waitFor(() => expect(result.current.records).toHaveLength(4), { timeout: 4000 });
    expect(result.current.awaitingAgent).toBe(true);
  });

  it('那句话根本没发出去时把「在等」撤掉——挂着一句假的比不提示还糟', async () => {
    vi.stubGlobal('fetch', stubSession(() => 3));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => result.current.markSent('一句话'));
    expect(result.current.awaitingAgent).toBe(true);
    act(() => result.current.clearSent());
    expect(result.current.awaitingAgent).toBe(false);
  });

  it('换一场会话，上一场的「在等」不许跟过去', async () => {
    vi.stubGlobal('fetch', stubSession(() => 3));
    const other = '11111111-2222-3333-4444-555555555555';
    const { result, rerender } = renderHook(({ sid }) => useWorkbenchRecords(sid), {
      initialProps: { sid: SID },
    });
    await waitFor(() => expect(result.current.records).toHaveLength(3));
    act(() => result.current.markSent('一句话'));
    expect(result.current.awaitingAgent).toBe(true);

    rerender({ sid: other });
    expect(result.current.awaitingAgent).toBe(false);
  });
});

describe('送达信号：输入区靠它放行', () => {
  /** 三条打底，第四条随 `fresh` 出现。取增量按服务端的规矩给：从 `after` 那一格起的整段。 */
  function stubGrowing(fresh: () => WorkbenchRecord | null) {
    return vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const f = fresh();
      const all = [record(0), record(1), record(2), ...(f ? [f] : [])];
      const after = Number(url.match(/after=(\d+)/)?.[1] ?? 0);
      const body = /[?&]tail=true/.test(url) ? all : all.filter((r) => r.seq >= after);
      return { ok: true, json: async () => body } as Response;
    });
  }

  it('自己那句话作为用户发言落进流里，就算送达', async () => {
    let landed = false;
    vi.stubGlobal(
      'fetch',
      stubGrowing(() =>
        landed
          ? { ...record(3), ts: Date.now(), kind: 'user.say', payload: { text: '去备份目录找' } }
          : null
      )
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => result.current.markSent('去备份目录找'));
    expect(result.current.deliveredAt).toBeNull();

    landed = true;
    await waitFor(() => expect(result.current.deliveredAt).not.toBeNull(), { timeout: 4000 });
  });

  it('插话没有用户发言那种形态，靠插话卡也要能算送达', async () => {
    // agent 正忙时投进去的话被引擎并进当轮，会话记录里**根本不会有用户发言**。
    // 只认用户发言的话，这种情况下输入框永远等不到放行——正是"发出去了却清不掉"。
    let landed = false;
    vi.stubGlobal(
      'fetch',
      stubGrowing(() =>
        landed
          ? {
              ...record(3),
              ts: Date.now(),
              kind: 'context.inject',
              payload: { channel: 'queued_command', body: '插一句', queue_state: 'absorbed' },
            }
          : null
      )
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => result.current.markSent('插一句'));
    landed = true;
    await waitFor(() => expect(result.current.deliveredAt).not.toBeNull(), { timeout: 4000 });
  });

  it('流里的老记录不算送达——同一句话重发一遍不许被上一轮那条顶掉', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => [
          // 时刻在很久以前：这是上一轮说过的同一句话。
          { ...record(0), ts: 1_753_800_000_000, kind: 'user.say', payload: { text: '再来一次' } },
        ],
      })) as unknown as typeof fetch
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(1));

    act(() => result.current.markSent('再来一次'));
    expect(result.current.deliveredAt).toBeNull();
  });

  it('换一场会话，上一场的送达信号不许跟过去', async () => {
    vi.stubGlobal('fetch', stubSession(() => 3));
    const other = '11111111-2222-3333-4444-555555555555';
    const { result, rerender } = renderHook(({ sid }) => useWorkbenchRecords(sid), {
      initialProps: { sid: SID },
    });
    await waitFor(() => expect(result.current.records).toHaveLength(3));
    act(() => result.current.markSent('一句话'));
    rerender({ sid: other });
    expect(result.current.deliveredAt).toBeNull();
  });
});

describe('信封：已发送 → 已入队列 → 成为一轮', () => {
  /** 三条打底，第四条随 `fresh` 出现。取增量按服务端的规矩给：从 `after` 那一格起的整段。 */
  function stubGrowing(fresh: () => WorkbenchRecord | null) {
    return vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const f = fresh();
      const all = [record(0), record(1), record(2), ...(f ? [f] : [])];
      const after = Number(url.match(/after=(\d+)/)?.[1] ?? 0);
      const body = /[?&]tail=true/.test(url) ? all : all.filter((r) => r.seq >= after);
      return { ok: true, json: async () => body } as Response;
    });
  }

  it('刚发出去是「已发送」：请求出了门，会话里还找不到它', async () => {
    vi.stubGlobal('fetch', stubSession(() => 3));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    expect(result.current.outbound).toHaveLength(0);
    act(() => {
      result.current.markSent('去备份目录找', 1);
    });
    expect(result.current.outbound).toHaveLength(1);
    expect(result.current.outbound[0].state).toBe('sent');
    expect(result.current.outbound[0].text).toBe('去备份目录找');
    expect(result.current.outbound[0].attachments).toBe(1);
  });

  it('agent 正忙，它成了一张还在队列上的插话卡：转「已入队列」，信封不撤', async () => {
    let landed = false;
    vi.stubGlobal(
      'fetch',
      stubGrowing(() =>
        landed
          ? {
              ...record(3),
              ts: Date.now(),
              kind: 'context.inject',
              payload: { channel: 'queued_command', body: '插一句', queue_state: 'pending' },
            }
          : null
      )
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => {
      result.current.markSent('插一句');
    });
    landed = true;
    await waitFor(() => expect(result.current.outbound[0]?.state).toBe('queued'), {
      timeout: 4000,
    });
    // 进了会话就算送达：输入区的发送按钮该放回去了，哪怕它还排在队列上。
    expect(result.current.deliveredAt).not.toBeNull();
  });

  it('那一轮把它并进去了，信封退场——记录流里已经有它的位置', async () => {
    let landed = false;
    vi.stubGlobal(
      'fetch',
      stubGrowing(() =>
        landed
          ? {
              ...record(3),
              ts: Date.now(),
              kind: 'context.inject',
              payload: { channel: 'queued_command', body: '插一句', queue_state: 'absorbed' },
            }
          : null
      )
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => {
      result.current.markSent('插一句');
    });
    landed = true;
    await waitFor(() => expect(result.current.outbound).toHaveLength(0), { timeout: 4000 });
  });

  it('agent 当时闲着，它直接成了用户发言：信封同样退场', async () => {
    let landed = false;
    vi.stubGlobal(
      'fetch',
      stubGrowing(() =>
        landed
          ? { ...record(3), ts: Date.now(), kind: 'user.say', payload: { text: '去备份目录找' } }
          : null
      )
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => {
      result.current.markSent('去备份目录找');
    });
    expect(result.current.outbound).toHaveLength(1);
    landed = true;
    await waitFor(() => expect(result.current.outbound).toHaveLength(0), { timeout: 4000 });
  });

  it('斜杠命令落进档案时穿了一层壳，照样要认出来是自己那一句', async () => {
    // 人打的是 `/goal 把日历挪到底部`，档案里写的是 <command-name>/goal</command-name>
    // 加 <command-args>把日历挪到底部</command-args>。两份字面上毫无关系，认不出这层壳
    // 信封就会一直挂着说"已发送"，而 agent 早就在干活了。形状取自真会话记录。
    let landed = false;
    vi.stubGlobal(
      'fetch',
      stubGrowing(() =>
        landed
          ? {
              ...record(3),
              ts: Date.now(),
              kind: 'user.say',
              payload: {
                text:
                  '<command-name>/goal</command-name>\n            ' +
                  '<command-message>goal</command-message>\n            ' +
                  '<command-args>把日历挪到底部，settings 挪到 data 下面</command-args>',
              },
            }
          : null
      )
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => {
      result.current.markSent('/goal 把日历挪到底部，settings 挪到 data 下面');
    });
    expect(result.current.outbound).toHaveLength(1);

    landed = true;
    await waitFor(() => expect(result.current.outbound).toHaveLength(0), { timeout: 4000 });
  });

  it('壳改由数据层拆开之后，信封照样认得出是自己那一句', async () => {
    // 翻译层现在把三段标签拆好：命令落 `command`、人打的参数落 `text`。信封要把两半
    // 拼回去比对——只认档案里那层原样包装的话，新记录一条都对不上，信封会一直挂着。
    let landed = false;
    vi.stubGlobal(
      'fetch',
      stubGrowing(() =>
        landed
          ? {
              ...record(3),
              ts: Date.now(),
              kind: 'user.say',
              payload: {
                command: '/goal',
                text: '把日历挪到底部，settings 挪到 data 下面',
                input_mode: 'slash-command',
              },
            }
          : null
      )
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => {
      result.current.markSent('/goal 把日历挪到底部，settings 挪到 data 下面');
    });
    expect(result.current.outbound).toHaveLength(1);

    landed = true;
    await waitFor(() => expect(result.current.outbound).toHaveLength(0), { timeout: 4000 });
  });

  it('跑完就完的命令不会惊动模型，它自己打印的那段就是回执', async () => {
    // `/rename` 只改个名字，agent 从头到尾不会开口。等 agent 开口就是等一件永远不会
    // 发生的事——那句"在等"要一直挂到上限才自己撤掉，而命令早就跑完了。
    let landed = false;
    vi.stubGlobal(
      'fetch',
      stubGrowing(() =>
        landed
          ? {
              ...record(3),
              ts: Date.now(),
              kind: 'context.inject',
              payload: {
                channel: 'local-command-output',
                source: 'local-command',
                stdout: 'Session renamed to: 修标签显示',
              },
            }
          : null
      )
    );
    const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    act(() => {
      result.current.markSent('/rename');
    });
    expect(result.current.awaitingAgent).toBe(true);

    landed = true;
    await waitFor(() => expect(result.current.awaitingAgent).toBe(false), { timeout: 4000 });
  });

  it('发送接口回来了就收信封：那一轮都说完了，它必定已经在会话里', async () => {
    vi.stubGlobal('fetch', stubSession(() => 3));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    let id = '';
    act(() => {
      id = result.current.markSent('一句认不出来的话');
    });
    expect(result.current.outbound).toHaveLength(1);

    act(() => result.current.settleSent(id));
    expect(result.current.outbound).toHaveLength(0);
  });

  it('没发出去就按编号收走那一个信封，别的不动', async () => {
    vi.stubGlobal('fetch', stubSession(() => 3));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(3));

    let first = '';
    act(() => {
      first = result.current.markSent('第一句');
    });
    act(() => {
      result.current.markSent('第二句');
    });
    expect(result.current.outbound).toHaveLength(2);

    act(() => result.current.clearSent(first));
    expect(result.current.outbound.map((m) => m.text)).toEqual(['第二句']);
  });

  it('换一场会话，上一场的信封不许跟过去', async () => {
    vi.stubGlobal('fetch', stubSession(() => 3));
    const other = '11111111-2222-3333-4444-555555555555';
    const { result, rerender } = renderHook(({ sid }) => useWorkbenchRecords(sid), {
      initialProps: { sid: SID },
    });
    await waitFor(() => expect(result.current.records).toHaveLength(3));
    act(() => {
      result.current.markSent('一句话');
    });
    expect(result.current.outbound).toHaveLength(1);

    rerender({ sid: other });
    expect(result.current.outbound).toHaveLength(0);
  });
});

describe('这场会话的编号被重排过', () => {
  /**
   * 顶替 fetch：一场会话，内容由一串**身份稳定**的记录给出，序号按它当下的位置现排。
   *
   * 抽掉中间一条就等于引擎重写了一次账本——账本只留最后一份，前面那份一被丢掉，它后面
   * 所有内容的编号就整体往前挪一格。真服务端就是这么发的：序号是每次重翻档案时现排的。
   */
  function stubArchive(ids: () => string[]) {
    return vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const limit = Number(url.match(/limit=(\d+)/)?.[1] ?? PAGE_SIZE);
      const all = ids().map((id, seq) => ({ ...record(seq), id }));
      const body = /[?&]tail=true/.test(url)
        ? all.slice(Math.max(0, all.length - limit))
        : all
            .filter((r) => r.seq >= Number(url.match(/after=(\d+)/)?.[1] ?? 0))
            .slice(0, limit);
      return { ok: true, json: async () => body } as Response;
    });
  }

  it('号往前挪了一格，新写下来的那句话照样取得回来', async () => {
    // 这是"话发进去了、中栏却看不见它"的那一刻：挪格之后人刚说的那句正好落回轮询已经
    // 问过的号段。只问"比手上末条更新的"，这一趟必定空手——回执就是这么丢的。
    vi.useFakeTimers();
    try {
      let ids = ['a0', 'a1', 'a2', 'ledger', 'a4', 'a5'];
      vi.stubGlobal('fetch', stubArchive(() => ids));
      const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
      await act(async () => {});
      expect(result.current.records.map((r) => r.id)).toEqual(ids);

      // 一轮说完：旧账本被新的顶掉（少一条），人紧接着说了一句（多一条）。
      ids = ['a0', 'a1', 'a2', 'a4', 'a5', '人刚说的那句'];
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 100);
      });

      expect(result.current.records.map((r) => r.id)).toContain('人刚说的那句');
    } finally {
      vi.useRealTimers();
    }
  });

  it('号没动就只追加真的新内容，作对照多要的那一条不留下重影', async () => {
    vi.useFakeTimers();
    try {
      let ids = ['a0', 'a1', 'a2'];
      vi.stubGlobal('fetch', stubArchive(() => ids));
      const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
      await act(async () => {});

      ids = ['a0', 'a1', 'a2', 'a3'];
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 100);
      });

      expect(result.current.records.map((r) => r.id)).toEqual(['a0', 'a1', 'a2', 'a3']);
    } finally {
      vi.useRealTimers();
    }
  });

  it('挪格之后，自己那句话照样认得出送达——输入区靠它放行', async () => {
    vi.useFakeTimers();
    try {
      let ids = ['a0', 'a1', 'ledger', 'a3'];
      vi.stubGlobal('fetch', stubArchive(() => ids));
      const { result } = renderHook(() => useWorkbenchRecords(SID, { live: true }));
      await act(async () => {});

      act(() => {
        result.current.markSent('去备份目录找');
      });
      expect(result.current.deliveredAt).toBeNull();
      expect(result.current.outbound).toHaveLength(1);

      // 账本被顶掉，人那句话落进档案：整场少一条又多一条，尾巴上的号原地没变。
      ids = ['a0', 'a1', 'a3', 'said'];
      const mine = vi.fn(async (input: RequestInfo | URL) => {
        const res = await stubArchive(() => ids)(input);
        const body = (await res.json()) as WorkbenchRecord[];
        return {
          ok: true,
          json: async () =>
            body.map((r) =>
              r.id === 'said'
                ? { ...r, ts: Date.now(), kind: 'user.say' as const, payload: { text: '去备份目录找' } }
                : r
            ),
        } as Response;
      });
      vi.stubGlobal('fetch', mine);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 100);
      });

      expect(result.current.deliveredAt).not.toBeNull();
      expect(result.current.outbound).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
