/**
 * 排队投进去的那一单，信封怎么走。
 *
 * CoreAgent 那一场正忙时，服务端当场回「已排队」而不是等整轮（等的话请求要挂几十分钟）。
 * 于是「接口回来就等于这一轮说完」那条老规矩对它不成立：信封得留着，一路显示排队中，
 * 直到那句话真的落进流里——也就是助手读到它的那一刻。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

type Handler = (msg: unknown) => void;
const handlers = new Map<string, Set<Handler>>();

vi.mock('@/api/websocket', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/api/websocket')>();
  return {
    ...real,
    getWebSocketClient: () => ({
      on: (type: string, handler: Handler) => {
        if (!handlers.has(type)) handlers.set(type, new Set());
        handlers.get(type)!.add(handler);
        return () => handlers.get(type)?.delete(handler);
      },
    }),
  };
});

import { PAGE_SIZE, useWorkbenchRecords, type WorkbenchRecord } from '../useWorkbenchRecords';

const SID = 'core_18dbe0cfd02cb8a00000865f0000';

function record(seq: number, kind: WorkbenchRecord['kind'], payload: Record<string, unknown>): WorkbenchRecord {
  return {
    id: `rec-${seq}`,
    session_id: SID,
    group_id: null,
    seq,
    ts: Date.now(),
    kind,
    agent_path: [],
    payload,
    raw_available: true,
  };
}

function stubSession(total: number) {
  return vi.fn(async () => {
    const start = Math.max(0, total - PAGE_SIZE);
    const seqs = Array.from({ length: total - start }, (_, i) => start + i);
    return {
      ok: true,
      json: async () => seqs.map((s) => record(s, 'agent.say', { text: `第 ${s} 条` })),
    } as Response;
  });
}

function push(records: WorkbenchRecord[], sessionId = SID) {
  const msg = {
    type: 'session_records_append',
    timestamp: '2026-10-06T16:40:00',
    data: { session_id: sessionId, records },
  };
  handlers.get('session_records_append')?.forEach((h) => h(JSON.parse(JSON.stringify(msg))));
}

async function opened() {
  vi.stubGlobal('fetch', stubSession(0));
  const { result } = renderHook(() => useWorkbenchRecords(SID));
  await waitFor(() => expect(result.current.loading).toBe(false));
  return result;
}

describe('排队投进去的那一单', () => {
  beforeEach(() => {
    handlers.clear();
    vi.unstubAllGlobals();
  });

  it('标成排队中，接口回来那一刻不许把它收掉', async () => {
    const result = await opened();
    let id = '';
    act(() => {
      id = result.current.markSent('接着干', 0);
    });
    act(() => result.current.markQueued(id));

    expect(result.current.outbound.map((m) => m.state)).toEqual(['queued']);

    // 排队那条路当场就返回：页面接的 onSent 会调 settleSent，它不许收掉这一单。
    act(() => result.current.settleSent(id));

    expect(result.current.outbound.map((m) => m.id)).toEqual([id]);
    expect(result.current.outbound[0].state).toBe('queued');
  });

  it('助手读到它、它落进流里，信封才退场', async () => {
    const result = await opened();
    let id = '';
    act(() => {
      id = result.current.markSent('接着干', 0);
    });
    act(() => result.current.markQueued(id));
    act(() => result.current.settleSent(id));
    expect(result.current.outbound).toHaveLength(1);

    act(() => push([record(0, 'user.say', { text: '接着干' })]));

    expect(result.current.outbound).toHaveLength(0);
  });

  it('照常等整轮的那一单不受影响：接口回来照样收掉它', async () => {
    const result = await opened();
    let id = '';
    act(() => {
      id = result.current.markSent('接着干', 0);
    });

    act(() => result.current.settleSent(id));

    expect(result.current.outbound).toHaveLength(0);
  });
});
