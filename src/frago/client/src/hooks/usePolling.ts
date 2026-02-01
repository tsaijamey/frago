import { useEffect, useRef, useCallback } from 'react';

/**
 * Polling Hook
 *
 * @param callback Polling callback function
 * @param interval Polling interval (milliseconds)
 * @param enabled Whether polling is enabled
 */
export function usePolling(
  callback: () => void | Promise<void>,
  interval: number,
  enabled: boolean = true
) {
  const savedCallback = useRef(callback);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Save the latest callback
  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  // Manual trigger
  const trigger = useCallback(() => {
    savedCallback.current();
  }, []);

  // Setup polling
  useEffect(() => {
    if (!enabled) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    // Execute immediately once
    savedCallback.current();

    // Setup timer
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
