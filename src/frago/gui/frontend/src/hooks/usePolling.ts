import { useEffect, useRef, useCallback } from 'react';

/**
 * 轮询 Hook
 *
 * @param callback 轮询回调函数
 * @param interval 轮询间隔（毫秒）
 * @param enabled 是否启用轮询
 */
export function usePolling(
  callback: () => void | Promise<void>,
  interval: number,
  enabled: boolean = true
) {
  const savedCallback = useRef(callback);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 保存最新的回调
  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  // 手动触发
  const trigger = useCallback(() => {
    savedCallback.current();
  }, []);

  // 设置轮询
  useEffect(() => {
    if (!enabled) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    // 立即执行一次
    savedCallback.current();

    // 设置定时器
    intervalRef.current = setInterval(() => {
      savedCallback.current();
    }, interval);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [interval, enabled]);

  return { trigger };
}
