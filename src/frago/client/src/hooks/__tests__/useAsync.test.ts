import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useAsync, useAsyncCallback } from '../useAsync';

describe('useAsync', () => {
  it('starts idle (not loading) when immediate is not set', () => {
    const { result } = renderHook(() => useAsync(async () => 1));
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('transitions loading -> data on a successful run', async () => {
    const fn = vi.fn(async (n: number) => n * 2);
    const { result } = renderHook(() => useAsync(fn));

    let returned: number | undefined;
    await act(async () => {
      returned = await result.current.run(21);
    });

    expect(returned).toBe(42);
    expect(result.current.data).toBe(42);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(fn).toHaveBeenCalledWith(21);
  });

  it('captures the error and clears loading on a rejected run', async () => {
    const { result } = renderHook(() =>
      useAsync(async () => {
        throw new Error('boom');
      })
    );

    let returned: unknown;
    await act(async () => {
      returned = await result.current.run();
    });

    expect(returned).toBeUndefined();
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe('boom');
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
  });

  it('wraps a non-Error throw into an Error', async () => {
    const { result } = renderHook(() =>
      useAsync(async () => {
        throw 'string-failure';
      })
    );
    await act(async () => {
      await result.current.run();
    });
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe('string-failure');
  });

  it('clears a prior error when a later run succeeds', async () => {
    let shouldFail = true;
    const { result } = renderHook(() =>
      useAsync(async () => {
        if (shouldFail) throw new Error('first');
        return 'ok';
      })
    );

    await act(async () => {
      await result.current.run();
    });
    expect(result.current.error?.message).toBe('first');

    shouldFail = false;
    await act(async () => {
      await result.current.run();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBe('ok');
  });

  it('runs once on mount when immediate is true', async () => {
    const fn = vi.fn(async () => 'auto');
    const { result } = renderHook(() => useAsync(fn, { immediate: true }));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.data).toBe('auto'));
    expect(fn).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(false);
  });

  it('setData overrides data without touching loading/error', async () => {
    const { result } = renderHook(() => useAsync(async () => 1));
    act(() => {
      result.current.setData(99);
    });
    expect(result.current.data).toBe(99);
    expect(result.current.loading).toBe(false);
  });
});

describe('useAsyncCallback', () => {
  it('returns a [run, state] pair tracking loading/error', async () => {
    const fn = vi.fn(async (s: string) => s.toUpperCase());
    const { result } = renderHook(() => useAsyncCallback(fn));

    const [run] = result.current;
    let out: string | undefined;
    await act(async () => {
      out = await run('hi');
    });

    expect(out).toBe('HI');
    expect(result.current[1].loading).toBe(false);
    expect(result.current[1].error).toBeNull();
  });

  it('surfaces the error through the state tuple', async () => {
    const { result } = renderHook(() =>
      useAsyncCallback(async () => {
        throw new Error('cb-fail');
      })
    );
    await act(async () => {
      await result.current[0]();
    });
    expect(result.current[1].error?.message).toBe('cb-fail');
  });
});
