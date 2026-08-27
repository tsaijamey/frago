/**
 * 页面自己把数据取新这件事。
 *
 * 守两头：该取的时候真的去取（开局、到点、切回页面），不该取的时候一趟都不发
 * （页面被藏起来、上一趟还没回来、刚取完又被触发）。后一半同样要紧——一个每秒
 * 发三趟的"自动刷新"会把服务端拖垮，届时人只会把它关掉。
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAutoRefresh } from '../useAutoRefresh';

/**
 * 把挂载那一趟跑完。
 *
 * 挂载那一趟里有个 await，同一个时间片内它还没走完 finally——真实使用中没人会在
 * 挂载的同一瞬间去切窗口，但用例会，所以先让它落定再往下测。
 */
async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  });
}

describe('useAutoRefresh', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility('visible');
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('开局就取一次，不必等第一个周期', async () => {
    const fn = vi.fn();
    renderHook(() => useAutoRefresh(fn, { intervalMs: 1000 }));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('到点自己再取', async () => {
    const fn = vi.fn();
    renderHook(() => useAutoRefresh(fn, { intervalMs: 1000, minGapMs: 0 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(fn).toHaveBeenCalledTimes(4); // 开局那一趟 + 三个周期
  });

  it('页面被藏起来时定时器空转，一趟都不发', async () => {
    // 没人在看的页面不值得占着服务端。
    const fn = vi.fn();
    renderHook(() => useAutoRefresh(fn, { intervalMs: 1000, minGapMs: 0 }));
    await settle();
    fn.mockClear();
    setVisibility('hidden');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fn).not.toHaveBeenCalled();
  });

  it('切回这个页面时立刻取一次，不用干等一个周期', async () => {
    const fn = vi.fn();
    renderHook(() => useAutoRefresh(fn, { intervalMs: 60_000, minGapMs: 0 }));
    await settle();
    fn.mockClear();
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('窗口重新拿到焦点时也取', async () => {
    const fn = vi.fn();
    renderHook(() => useAutoRefresh(fn, { intervalMs: 60_000, minGapMs: 0 }));
    await settle();
    fn.mockClear();
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('刚取完又被触发就跳过', async () => {
    // 切窗口、切标签页、点一下地址栏会连着触发好几个事件，没有这道闸就是三四趟。
    const fn = vi.fn();
    renderHook(() => useAutoRefresh(fn, { intervalMs: 60_000, minGapMs: 5000 }));
    await settle();
    fn.mockClear();
    // 先让时间闸过去，否则这三下本来就都该被挡——那验不出"三下只发一趟"。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new Event('focus'));
    });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('时间闸没过就一趟都不发', async () => {
    const fn = vi.fn();
    renderHook(() => useAutoRefresh(fn, { intervalMs: 60_000, minGapMs: 5000 }));
    await settle();
    fn.mockClear();
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });
    expect(fn).not.toHaveBeenCalled();
  });

  it('人按刷新时不看时间闸', async () => {
    const fn = vi.fn();
    const { result } = renderHook(() =>
      useAutoRefresh(fn, { intervalMs: 60_000, minGapMs: 60_000 })
    );
    await settle();
    fn.mockClear();
    await act(async () => {
      result.current.refresh();
    });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('上一趟没回来就不再发', async () => {
    // 慢的那趟后到会把新的结果盖回旧的。
    let release: (() => void) | null = null;
    const fn = vi.fn(() => new Promise<void>((resolve) => {
      release = resolve;
    }));
    const { result } = renderHook(() =>
      useAutoRefresh(fn, { intervalMs: 60_000, minGapMs: 0 })
    );
    expect(fn).toHaveBeenCalledTimes(1);

    await act(async () => {
      result.current.refresh();
      result.current.refresh();
    });
    expect(fn).toHaveBeenCalledTimes(1);

    await act(async () => {
      release?.();
    });
    await act(async () => {
      result.current.refresh();
    });
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('关掉之后一趟都不取', async () => {
    const fn = vi.fn();
    renderHook(() => useAutoRefresh(fn, { intervalMs: 1000, enabled: false }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      window.dispatchEvent(new Event('focus'));
    });
    expect(fn).not.toHaveBeenCalled();
  });

  it('卸载之后定时器不再响', async () => {
    const fn = vi.fn();
    const { unmount } = renderHook(() => useAutoRefresh(fn, { intervalMs: 1000, minGapMs: 0 }));
    unmount();
    await settle();
    fn.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      window.dispatchEvent(new Event('focus'));
    });
    expect(fn).not.toHaveBeenCalled();
  });
});
