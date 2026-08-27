/**
 * 让一页自己去把数据取新，不必人按 F5。
 *
 * 在这之前，配方、技能、会话清单这些页都是"挂载时取一次，此后再不动"。人开着
 * 界面在旁边干活，页面上的内容停在半小时前——最要命的是它看起来完全正常，没有
 * 任何迹象表明这是一份旧的，人会照着旧数据做判断。
 *
 * 三个时机重取：定时（只在页面看得见的时候）、切回这个标签页时、窗口重新拿到
 * 焦点时。页面被藏起来时定时器空转不发请求——没人在看的页面不值得占着服务端。
 *
 * 与 `usePolling` 的分工：那个是纯定时器，谁在看、看得见看不见一概不问，适合
 * 「装完等结果」这类必须一直跑到底的轮询；这个是给**内容页**用的，前提是没人
 * 看的时候不该烧请求。
 */

import { useCallback, useEffect, useRef } from 'react';

export interface AutoRefreshOptions {
  /** 隔多久重取一次，毫秒。给 0 就不定时，只在人回到页面时重取。 */
  intervalMs?: number;
  /** 关掉之后一次都不取（比如这一页当前没显示）。 */
  enabled?: boolean;
  /**
   * 距上一次取回不足这么久就跳过。
   *
   * 挡的是"切出去又马上切回来"：切窗口、切标签页、点一下浏览器地址栏都可能连着
   * 触发好几个事件，没有这道闸，一次误触就是三四趟请求。
   */
  minGapMs?: number;
}

export interface AutoRefreshResult {
  /** 立刻取一次，不看时间闸——给"刷新"按钮用。 */
  refresh: () => void;
}

const DEFAULT_INTERVAL_MS = 15_000;
const DEFAULT_MIN_GAP_MS = 2_000;

export function useAutoRefresh(
  fn: () => void | Promise<void>,
  options: AutoRefreshOptions = {}
): AutoRefreshResult {
  const {
    intervalMs = DEFAULT_INTERVAL_MS,
    enabled = true,
    minGapMs = DEFAULT_MIN_GAP_MS,
  } = options;

  const fnRef = useRef(fn);
  fnRef.current = fn;

  const inFlight = useRef(false);
  const lastRunAt = useRef(0);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const minGapRef = useRef(minGapMs);
  minGapRef.current = minGapMs;

  const run = useCallback(async (force: boolean) => {
    if (!enabledRef.current) return;
    // 上一趟还没回来就不再发。慢的那趟后到会把新的结果盖回旧的。
    if (inFlight.current) return;
    if (!force && Date.now() - lastRunAt.current < minGapRef.current) return;

    inFlight.current = true;
    try {
      await fnRef.current();
    } finally {
      inFlight.current = false;
      lastRunAt.current = Date.now();
    }
  }, []);

  const refresh = useCallback(() => {
    void run(true);
  }, [run]);

  // 开局取一次。这一趟不看时间闸——页面刚打开就是该有内容的时候。
  useEffect(() => {
    if (!enabled) return;
    void run(true);
  }, [enabled, run]);

  useEffect(() => {
    if (!enabled || intervalMs <= 0) return;
    const timer = setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      void run(false);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [enabled, intervalMs, run]);

  useEffect(() => {
    if (!enabled) return;
    const onVisible = () => {
      if (document.visibilityState === 'visible') void run(false);
    };
    const onFocus = () => {
      void run(false);
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onFocus);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onFocus);
    };
  }, [enabled, run]);

  return { refresh };
}
