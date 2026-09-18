/**
 * 右栏收推送这一步。喂的是服务端真实发出的那条消息的形状（2026-09-11 17:21:09 在 8093
 * 推送通道上抓到的），看右栏的数据换不换。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Handler = (msg: unknown) => void;
const handlers = new Map<string, Set<Handler>>();
const connectHandlers = new Set<() => void>();

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
      onConnect: (handler: () => void) => {
        connectHandlers.add(handler);
        return () => connectHandlers.delete(handler);
      },
    }),
  };
});

import { OBSERVER_POLL_MS, useSessionObserver } from '../useSessionObserver';

const SID = 'd68d2f2a-6429-4f59-a645-c6d9ffbeb381';
const base = {
  bound: true,
  anchor: '原锚',
  tail: { kind: 'now', text: '旧的此刻' },
  decision: '',
  happened: [],
  updated_at: 1,
  model: 'deepseek-v4-flash',
  status: 'ok',
  status_detail: null,
};

function push(state: Record<string, unknown>, sessionId = SID) {
  // 与服务端 create_message 产出的形状一致：type / timestamp / data
  const msg = {
    type: 'session_observer_update',
    timestamp: '2026-09-11T17:21:09',
    data: { session_id: sessionId, state },
  };
  handlers.get('session_observer_update')?.forEach((h) => h(JSON.parse(JSON.stringify(msg))));
}

describe('useSessionObserver 收推送', () => {
  beforeEach(() => {
    handlers.clear();
    connectHandlers.clear();
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => base })) as unknown as typeof fetch;
  });
  afterEach(() => vi.restoreAllMocks());

  it('这场会话的推送一到，右栏的数据就换成新的', async () => {
    const { result } = renderHook(() => useSessionObserver(SID));
    await waitFor(() => expect(result.current.state?.tail?.text).toBe('旧的此刻'));
    act(() => push({ ...base, tail: { kind: 'now', text: '新的此刻' }, updated_at: 2 }));
    expect(result.current.state?.tail?.text).toBe('新的此刻');
  });

  it('别的会话的推送不动这一场', async () => {
    const { result } = renderHook(() => useSessionObserver(SID));
    await waitFor(() => expect(result.current.state?.tail?.text).toBe('旧的此刻'));
    act(() => push({ ...base, tail: { kind: 'now', text: '别人的' } }, 'another-session'));
    expect(result.current.state?.tail?.text).toBe('旧的此刻');
  });
});

describe('useSessionObserver 推送漏了也能自己跟上', () => {
  let served: Record<string, unknown>;

  beforeEach(() => {
    handlers.clear();
    connectHandlers.clear();
    served = { ...base };
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => served })) as unknown as typeof fetch;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('一条推送都没来，停在这场会话上 15 秒后自己换上新内容', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = renderHook(() => useSessionObserver(SID));
    await waitFor(() => expect(result.current.state?.tail?.text).toBe('旧的此刻'));
    served = { ...base, tail: { kind: 'now', text: '服务端早就写好的新内容' }, updated_at: 5 };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OBSERVER_POLL_MS + 10);
    });
    await waitFor(() => expect(result.current.state?.tail?.text).toBe('服务端早就写好的新内容'));
  });

  it('推送连接重新连上的那一刻补拉一次', async () => {
    const { result } = renderHook(() => useSessionObserver(SID));
    await waitFor(() => expect(result.current.state?.tail?.text).toBe('旧的此刻'));
    served = { ...base, tail: { kind: 'now', text: '断线期间写的' }, updated_at: 7 };
    await act(async () => {
      connectHandlers.forEach((h) => h());
    });
    await waitFor(() => expect(result.current.state?.tail?.text).toBe('断线期间写的'));
  });

  it('拉回来的比推送来的旧，不用它', async () => {
    const { result } = renderHook(() => useSessionObserver(SID));
    await waitFor(() => expect(result.current.state?.tail?.text).toBe('旧的此刻'));
    act(() => push({ ...base, tail: { kind: 'now', text: '推送来的新内容' }, updated_at: 9 }));
    served = { ...base, tail: { kind: 'now', text: '更早的' }, updated_at: 3 };
    await act(async () => {
      connectHandlers.forEach((h) => h());
    });
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.state?.tail?.text).toBe('推送来的新内容');
  });
});
