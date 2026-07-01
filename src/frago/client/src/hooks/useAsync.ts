/**
 * useAsync — unified loading / error / data handling for async work.
 *
 * Replaces the repeated `setLoading(true) / try / catch / finally
 * setLoading(false)` boilerplate scattered across components.
 *
 * Two shapes are provided:
 *   - useAsync(fn, { immediate })  → fetch-style: tracks { data, loading,
 *     error } and exposes run(); optionally runs once on mount.
 *   - useAsyncCallback(fn)         → handler-style: wraps an async callback
 *     and returns [run, { loading, error }] for event handlers.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
}

export interface UseAsyncResult<T, Args extends unknown[]> extends AsyncState<T> {
  run: (...args: Args) => Promise<T | undefined>;
  setData: (data: T | null) => void;
}

export function useAsync<T, Args extends unknown[] = []>(
  fn: (...args: Args) => Promise<T>,
  options: { immediate?: boolean } = {}
): UseAsyncResult<T, Args> {
  const { immediate = false } = options;
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: immediate,
    error: null,
  });

  // Keep the latest fn without forcing run() to change identity.
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const run = useCallback(async (...args: Args): Promise<T | undefined> => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fnRef.current(...args);
      if (mountedRef.current) {
        setState({ data, loading: false, error: null });
      }
      return data;
    } catch (err) {
      if (mountedRef.current) {
        setState((s) => ({
          ...s,
          loading: false,
          error: err instanceof Error ? err : new Error(String(err)),
        }));
      }
      return undefined;
    }
  }, []);

  const setData = useCallback((data: T | null) => {
    setState((s) => ({ ...s, data }));
  }, []);

  const immediateRef = useRef(immediate);
  useEffect(() => {
    if (immediateRef.current) {
      void run(...([] as unknown as Args));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { ...state, run, setData };
}

export interface UseAsyncCallbackState {
  loading: boolean;
  error: Error | null;
}

export function useAsyncCallback<T, Args extends unknown[]>(
  fn: (...args: Args) => Promise<T>
): [(...args: Args) => Promise<T | undefined>, UseAsyncCallbackState] {
  const { run, loading, error } = useAsync<T, Args>(fn);
  return [run, { loading, error }];
}
