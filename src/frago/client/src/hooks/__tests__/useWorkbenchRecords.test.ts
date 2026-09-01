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
      expect(urls.some((u) => u.includes('after=300'))).toBe(true);
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
        const fresh = { ...record(3), ts: Date.now(), kind: 'tool.call' as const };
        const body = /[?&]tail=true/.test(String(input))
          ? [record(0), record(1), record(2)]
          : grown
            ? [fresh]
            : [];
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
        const mine = { ...record(3), ts: Date.now(), kind: 'user.say' as const };
        const body = /[?&]tail=true/.test(String(input))
          ? [record(0), record(1), record(2)]
          : grown
            ? [mine]
            : [];
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
  function stubGrowing(fresh: () => WorkbenchRecord | null) {
    return vi.fn(async (input: RequestInfo | URL) => {
      const body = /[?&]tail=true/.test(String(input))
        ? [record(0), record(1), record(2)]
        : (() => {
            const f = fresh();
            return f ? [f] : [];
          })();
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
