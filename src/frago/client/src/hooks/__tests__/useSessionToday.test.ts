/**
 * 「今天捡回来用」名单这一路的用例。
 *
 * 盯四件事：名单从服务端来（不是浏览器本地）、点下去界面立刻动、服务端拒绝时界面改回去、
 * 连点时以最后一下为准。跨天过期是服务端的判据（日期比较），这里只认服务端回来的那份。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSessionToday } from '../useSessionToday';

const A = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const B = 'ses_058288655ffeYMxYC1AZKCcv56';
const DAY = '2026-10-19';

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

function failed(status = 500): Response {
  return { ok: false, status, json: async () => ({}) } as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => jsonResponse({ today: DAY, picked: [] }));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useSessionToday', () => {
  it('名单从服务端取，带上服务端认为的今天', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ today: DAY, picked: [A, B] }));
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(result.current.picked).toEqual([A, B]));
    expect(result.current.today).toBe(DAY);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/workbench/today');
  });

  it('取不到就当一场都没捡，左栏照常摆得出今天有回复的清单', async () => {
    fetchMock.mockResolvedValueOnce(failed(503));
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current.picked).toEqual([]);
  });

  it('捡回来时发的是 PUT', async () => {
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockResolvedValueOnce(jsonResponse({ today: DAY, picked: [A] }));
    await act(async () => {
      await result.current.toggle(A);
    });
    expect(fetchMock).toHaveBeenLastCalledWith(`/api/workbench/today/${A}`, { method: 'PUT' });
    expect(result.current.picked).toEqual([A]);
    expect(result.current.isPicked(A)).toBe(true);
  });

  it('再点一次是放下，发的是 DELETE', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ today: DAY, picked: [A] }));
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(result.current.picked).toEqual([A]));
    fetchMock.mockResolvedValueOnce(jsonResponse({ today: DAY, picked: [] }));
    await act(async () => {
      await result.current.toggle(A);
    });
    expect(fetchMock).toHaveBeenLastCalledWith(`/api/workbench/today/${A}`, { method: 'DELETE' });
    expect(result.current.picked).toEqual([]);
  });

  it('点下去界面立刻动，不等服务端回来', async () => {
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    let release: (r: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        release = resolve;
      })
    );
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.toggle(A);
    });
    // 服务端还没开口，这场已经进今天的名单了。
    expect(result.current.picked).toEqual([A]);
    await act(async () => {
      release(jsonResponse({ today: DAY, picked: [A] }));
      await pending;
    });
  });

  it('服务端拒绝时界面改回去，并把错抛出来', async () => {
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockResolvedValueOnce(failed(500));

    await act(async () => {
      await expect(result.current.toggle(A)).rejects.toThrow();
    });
    expect(result.current.picked).toEqual([]);
  });

  it('次序以服务端回的那份为准', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ today: DAY, picked: [A] }));
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(result.current.picked).toEqual([A]));
    fetchMock.mockResolvedValueOnce(jsonResponse({ today: DAY, picked: [B, A] }));
    await act(async () => {
      await result.current.toggle(B);
    });
    expect(result.current.picked).toEqual([B, A]);
  });

  it('连点两下时以最后一下为准，先发的后到也盖不回来', async () => {
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    let releaseFirst: (r: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        releaseFirst = resolve;
      })
    );
    let first: Promise<void> = Promise.resolve();
    act(() => {
      first = result.current.toggle(A);
    });
    expect(result.current.picked).toEqual([A]);

    fetchMock.mockResolvedValueOnce(jsonResponse({ today: DAY, picked: [] }));
    await act(async () => {
      await result.current.toggle(A);
    });
    expect(result.current.picked).toEqual([]);

    await act(async () => {
      releaseFirst(jsonResponse({ today: DAY, picked: [A] }));
      await first;
    });
    expect(result.current.picked).toEqual([]);
  });

  it('refresh 重取一趟，跨天后的名单以下一次服务端答复为准', async () => {
    const { result } = renderHook(() => useSessionToday());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockResolvedValueOnce(jsonResponse({ today: '2026-10-20', picked: [] }));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.today).toBe('2026-10-20');
    expect(result.current.picked).toEqual([]);
  });
});
