/**
 * useStopSessionRun — 关闭当前这场会话在 tmux 里的那个会话。
 *
 * 走 `POST /api/workbench/sessions/{sid}/stop`。**按钮要不要出现不归这里管**：会话清单
 * 每 15 秒一轮本来就带着「这一场此刻开在 tmux 里吗」（`in_tmux`），页面照它决定挂不挂
 * 按钮，这一侧不再额外问 tmux。清单那份可能旧上一轮，所以关的结果仍由服务端如实说——
 * 没在跑就是没在跑，NEVER 假装关掉了。
 *
 * 确认由弹窗来问，这里只管出门与判读结局。服务端说屏上还在干活时那一下**没有动任何
 * 东西**，停在 `busy` 这一档等人决定；人再按才带 `force` 出门。
 *
 * 状态是一次性的，换会话时整个清空：上一场的结局跟这一场没有任何关系。
 */

import { useCallback, useEffect, useRef, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 服务端对这一按的答复。三种结局的判读见 `useStopSessionRun`。 */
export interface StopRunResult {
  sid: string;
  /** 找到了一具活着的 tmux 吗。为 false 时什么都没动。 */
  alive: boolean;
  /** 屏上还在干活。为 true 且 `stopped` 为 false 时，服务端刻意没动它。 */
  busy: boolean;
  stopped: boolean;
  /** 那场 tmux 的名字。没找到时为 null。 */
  name: string | null;
  /** 走的是池的驱逐（`pool`）还是 tmux（`tmux`）。 */
  via: string | null;
  error: string | null;
}

export async function stopSessionRun(sessionId: string, force: boolean): Promise<StopRunResult> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/stop`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    }
  );
  if (!res.ok) {
    let detail = String(res.status);
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string' && body.detail) detail = body.detail;
    } catch {
      /* 响应不是 JSON，退回状态码 */
    }
    throw new Error(detail);
  }
  return (await res.json()) as StopRunResult;
}

/**
 * 这一轮走到哪了。
 *
 * - `idle` 还没出门；
 * - `stopping` 请求在飞；
 * - `busy` 服务端说它还在干活、什么都没动，等人决定打不打断；
 * - `stopped` 关掉了；
 * - `absent` tmux 里已经没有这一场（清单那份旧了一轮）；
 * - `failed` 没关成，说法在 `error`。
 */
export type StopPhase = 'idle' | 'stopping' | 'busy' | 'stopped' | 'absent' | 'failed';

export interface StopSessionRunState {
  phase: StopPhase;
  /** 失败时服务端的说法，原样转述。 */
  error: string | null;
  /** 出门。`force` 只在 `busy` 那一档之后才该带。 */
  run: (force: boolean) => Promise<StopPhase>;
  /** 回到起始档（弹窗关上时）。 */
  reset: () => void;
}

export function useStopSessionRun(sessionId: string | null): StopSessionRunState {
  const [phase, setPhase] = useState<StopPhase>('idle');
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reset = useCallback(() => {
    setPhase('idle');
    setError(null);
  }, []);

  // 换会话就整个归零。
  useEffect(reset, [sessionId, reset]);

  const run = useCallback(
    async (force: boolean): Promise<StopPhase> => {
      if (!sessionId) return 'idle';
      setPhase('stopping');
      setError(null);
      let next: StopPhase;
      let message: string | null = null;
      try {
        const result = await stopSessionRun(sessionId, force);
        if (!result.alive) next = 'absent';
        else if (!result.stopped && result.busy) next = 'busy';
        else if (!result.stopped) {
          next = 'failed';
          message = result.error;
        } else next = 'stopped';
      } catch (e) {
        next = 'failed';
        message = e instanceof Error ? e.message : String(e);
      }
      if (mounted.current) {
        setPhase(next);
        setError(message);
      }
      return next;
    },
    [sessionId]
  );

  return { phase, error, run, reset };
}
