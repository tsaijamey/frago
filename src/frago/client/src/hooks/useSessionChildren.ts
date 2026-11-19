/**
 * useSessionChildren — 拉取当前会话的启动来源、派生子会话与运行中子进程。
 *
 * 与记录流互补：记录流只展示会话自身写进转录的内容；当主会话派出了异步 worker、
 * 启动了分支/交接，或 `claude --resume` 在后台跑着命令子进程时，本 hook 定期
 * 查询 `GET /api/workbench/sessions/{sid}/children`，确保详情页不会因为记录流暂时
 * 安静而让用户误以为后台没有事情在跑。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getSessionChildren } from '@/api/client';
import type { SessionChildrenResponse } from '@/types/api';
import { useAutoRefresh } from './useAutoRefresh';

export const CHILDREN_ACTIVE_POLL_MS = 4_000;
export const CHILDREN_IDLE_POLL_MS = 15_000;

export interface SessionChildrenState {
  data: SessionChildrenResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

export function useSessionChildren(
  sessionId: string | null,
  options: { live?: boolean } = {}
): SessionChildrenState {
  const { live = false } = options;
  const [data, setData] = useState<SessionChildrenResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentSidRef = useRef<string | null>(sessionId);
  const reqSeqRef = useRef(0);

  currentSidRef.current = sessionId;

  const load = useCallback(
    async (silent: boolean) => {
      const targetSid = currentSidRef.current;
      if (!targetSid) {
        setData(null);
        setLoading(false);
        setError(null);
        return;
      }
      const seq = ++reqSeqRef.current;
      if (!silent) setLoading(true);
      try {
        if (typeof getSessionChildren !== 'function') return;
        const res = await getSessionChildren(targetSid);
        if (currentSidRef.current !== targetSid || reqSeqRef.current !== seq) return;
        if (!res || typeof res !== 'object' || !res.summary) return;
        setData(res);
        setError(null);
      } catch (e) {
        if (currentSidRef.current !== targetSid || reqSeqRef.current !== seq) return;
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (currentSidRef.current === targetSid && reqSeqRef.current === seq && !silent) {
          setLoading(false);
        }
      }
    },
    []
  );

  useEffect(() => {
    setData(null);
    setError(null);
    if (!sessionId) {
      setLoading(false);
      return;
    }
    void load(false);
  }, [sessionId, load]);

  const reload = useCallback(() => load(true), [load]);

  const fastPoll = Boolean(live || data?.summary?.has_running || data?.summary?.host_alive);
  useAutoRefresh(
    async () => {
      if (!currentSidRef.current) return;
      await load(true);
    },
    {
      enabled: Boolean(sessionId),
      intervalMs: fastPoll ? CHILDREN_ACTIVE_POLL_MS : CHILDREN_IDLE_POLL_MS,
    }
  );

  const scopedData = data && data.session_id === sessionId ? data : null;
  return {
    data: scopedData,
    loading,
    error,
    reload,
  };
}
