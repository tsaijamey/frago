/**
 * 「这场改过哪些文件」那份清单的取法。
 *
 * 盯四件事：**按需取**（没打开过那一档就不去读整场记录）、取过就留着（同一场里来回切档
 * 不重取）、重取走 `reload`、换会话把旧请求的结果扔掉。第三件最要紧：那些文件是上一场的，
 * 摆到这一场上是错的。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getSessionFiles = vi.fn();
vi.mock('@/api', () => ({
  getSessionFiles: (sid: string) => getSessionFiles(sid),
}));

import { useSessionFiles } from '../useSessionFiles';
import type { SessionFileRow } from '@/types/api';

const A = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const B = 'ses_058288655ffeYMxYC1AZKCcv56';

function row(path: string): SessionFileRow {
  return { path, action: 'modified', count: 1, first_seq: 0 };
}

beforeEach(() => {
  getSessionFiles.mockReset();
  getSessionFiles.mockResolvedValue([row('/w/a.py')]);
});

describe('按需取', () => {
  it('挂上不取：没打开过那一档就不去读整场记录', async () => {
    const { result } = renderHook(() => useSessionFiles(A));

    // 等一拍，确认确实没有请求发出去。
    await act(async () => {});
    expect(getSessionFiles).not.toHaveBeenCalled();
    // 「还不知道」与「没有」摆成两个样子：这份是 null，不是空数组。
    expect(result.current.files).toBeNull();
  });

  it('打开那一档才取，取回来摆出来', async () => {
    const { result } = renderHook(() => useSessionFiles(A));

    act(() => result.current.ensure());

    await waitFor(() => expect(result.current.files).toEqual([row('/w/a.py')]));
    expect(getSessionFiles).toHaveBeenCalledTimes(1);
    expect(getSessionFiles).toHaveBeenCalledWith(A);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('取过就留着：同一场里来回切档不再重取', async () => {
    const { result } = renderHook(() => useSessionFiles(A));

    act(() => result.current.ensure());
    await waitFor(() => expect(result.current.files).not.toBeNull());

    act(() => result.current.ensure());
    act(() => result.current.ensure());
    await act(async () => {});

    expect(getSessionFiles).toHaveBeenCalledTimes(1);
  });

  it('没有会话时 ensure 什么都不做', async () => {
    const { result } = renderHook(() => useSessionFiles(null));

    act(() => result.current.ensure());
    await act(async () => {});

    expect(getSessionFiles).not.toHaveBeenCalled();
  });
});

describe('重取与换会话', () => {
  it('reload 再取一次，拿到新那一份', async () => {
    const { result } = renderHook(() => useSessionFiles(A));
    act(() => result.current.ensure());
    await waitFor(() => expect(result.current.files).not.toBeNull());

    getSessionFiles.mockResolvedValue([row('/w/a.py'), row('/w/b.py')]);
    act(() => result.current.reload());

    await waitFor(() => expect(result.current.files).toHaveLength(2));
    expect(getSessionFiles).toHaveBeenCalledTimes(2);
  });

  it('取不到：原因摆出来，下一拍 ensure 会再试', async () => {
    getSessionFiles.mockRejectedValue(new Error('Failed to fetch'));
    const { result } = renderHook(() => useSessionFiles(A));

    act(() => result.current.ensure());
    await waitFor(() => expect(result.current.error).toBe('Failed to fetch'));
    expect(result.current.files).toBeNull();

    getSessionFiles.mockResolvedValue([row('/w/a.py')]);
    act(() => result.current.ensure());
    await waitFor(() => expect(result.current.files).toEqual([row('/w/a.py')]));
  });

  it('换会话先清干净：上一场那份不许留在屏幕上', async () => {
    const { result, rerender } = renderHook(({ sid }) => useSessionFiles(sid), {
      initialProps: { sid: A },
    });
    act(() => result.current.ensure());
    await waitFor(() => expect(result.current.files).not.toBeNull());

    rerender({ sid: B });

    expect(result.current.files).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it('上一场的请求回来晚了一步：扔掉，不摆到这一场', async () => {
    let release: (rows: SessionFileRow[]) => void = () => {};
    getSessionFiles.mockImplementation(
      () => new Promise<SessionFileRow[]>((resolve) => (release = resolve))
    );
    const { result, rerender } = renderHook(({ sid }) => useSessionFiles(sid), {
      initialProps: { sid: A },
    });

    act(() => result.current.ensure());
    rerender({ sid: B });
    // 上一场那一份这时才回来。
    await act(async () => {
      release([row('/w/stale.py')]);
    });

    expect(result.current.files).toBeNull();
  });
});
