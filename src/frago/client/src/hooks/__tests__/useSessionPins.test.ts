/**
 * 置顶名单这一路的用例。
 *
 * 盯四件事：名单从服务端来（不是浏览器本地）、点下去界面立刻动、服务端拒绝时界面改回去、
 * 连点时以最后一下为准。折叠状态是另一回事——它是"我这块屏幕现在想不想看见"，存本地。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSessionPins } from '../useSessionPins';

const A = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const B = 'ses_058288655ffeYMxYC1AZKCcv56';

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function failed(status = 500): Response {
  return { ok: false, status, json: async () => ({}) } as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  fetchMock = vi.fn(async () => jsonResponse({ pinned: [] }));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useSessionPins', () => {
  it('名单从服务端取，不从浏览器本地取', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ pinned: [A, B] }));
    const { result } = renderHook(() => useSessionPins());
    await waitFor(() => expect(result.current.pinned).toEqual([A, B]));
    expect(fetchMock.mock.calls[0][0]).toBe('/api/workbench/pins');
  });

  it('取不到就当一场都没置顶，左栏照常摆得出清单', async () => {
    fetchMock.mockResolvedValueOnce(failed(503));
    const { result } = renderHook(() => useSessionPins());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current.pinned).toEqual([]);
  });

  it('置顶时发的是 PUT', async () => {
    const { result } = renderHook(() => useSessionPins());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockResolvedValueOnce(jsonResponse({ pinned: [A] }));
    await act(async () => {
      await result.current.toggle(A);
    });
    expect(fetchMock).toHaveBeenLastCalledWith(`/api/workbench/pins/${A}`, { method: 'PUT' });
    expect(result.current.pinned).toEqual([A]);
  });

  it('再点一次是取消置顶，发的是 DELETE', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ pinned: [A] }));
    const { result } = renderHook(() => useSessionPins());
    await waitFor(() => expect(result.current.pinned).toEqual([A]));
    fetchMock.mockResolvedValueOnce(jsonResponse({ pinned: [] }));
    await act(async () => {
      await result.current.toggle(A);
    });
    expect(fetchMock).toHaveBeenLastCalledWith(`/api/workbench/pins/${A}`, { method: 'DELETE' });
    expect(result.current.pinned).toEqual([]);
  });

  it('点下去界面立刻动，不等服务端回来', async () => {
    const { result } = renderHook(() => useSessionPins());
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
    // 服务端还没开口，图钉已经亮了。
    expect(result.current.pinned).toEqual([A]);
    await act(async () => {
      release(jsonResponse({ pinned: [A] }));
      await pending;
    });
  });

  it('服务端拒绝时界面改回去，并把错抛出来', async () => {
    const { result } = renderHook(() => useSessionPins());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockResolvedValueOnce(failed(500));

    await act(async () => {
      await expect(result.current.toggle(A)).rejects.toThrow();
    });
    // 停在一个盘上并不存在的状态，人下次打开会以为置顶丢了。
    expect(result.current.pinned).toEqual([]);
  });

  it('次序以服务端回的那份为准', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ pinned: [A] }));
    const { result } = renderHook(() => useSessionPins());
    await waitFor(() => expect(result.current.pinned).toEqual([A]));
    fetchMock.mockResolvedValueOnce(jsonResponse({ pinned: [B, A] }));
    await act(async () => {
      await result.current.toggle(B);
    });
    expect(result.current.pinned).toEqual([B, A]);
  });

  it('连点两下时以最后一下为准，先发的后到也盖不回来', async () => {
    const { result } = renderHook(() => useSessionPins());
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
    expect(result.current.pinned).toEqual([A]);

    // 第二下（取消置顶）先回来。
    fetchMock.mockResolvedValueOnce(jsonResponse({ pinned: [] }));
    await act(async () => {
      await result.current.toggle(A);
    });
    expect(result.current.pinned).toEqual([]);

    // 第一下姗姗来迟，它的结果不算数——否则那颗图钉会自己弹回去。
    await act(async () => {
      releaseFirst(jsonResponse({ pinned: [A] }));
      await first;
    });
    expect(result.current.pinned).toEqual([]);
  });

  it('折叠状态存本地，下次打开还折着', async () => {
    const { result, unmount } = renderHook(() => useSessionPins());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current.collapsed).toBe(false);
    act(() => {
      result.current.setCollapsed(true);
    });
    expect(result.current.collapsed).toBe(true);
    unmount();

    const again = renderHook(() => useSessionPins());
    expect(again.result.current.collapsed).toBe(true);
  });

  it('折叠状态不发去服务端', async () => {
    const { result } = renderHook(() => useSessionPins());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const before = fetchMock.mock.calls.length;
    act(() => {
      result.current.setCollapsed(true);
    });
    expect(fetchMock.mock.calls.length).toBe(before);
  });
});
