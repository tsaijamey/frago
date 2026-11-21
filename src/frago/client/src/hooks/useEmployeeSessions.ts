/**
 * useEmployeeSessions — 拉取指定员工名下的全部历史与运行中会话列表。
 *
 * 后端 `GET /api/employees/{member_post_id}/sessions` 已复用与 `/api/workbench/sessions`
 * 同源的四级血缘判定（直接标签 + 本体 + active_session_ids + 8 跳 branch/handoff 继承，
 * 排除普通 worker），并按「运行中/待拍板优先 + 最近活动时间倒序」排序与服务端分页。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import i18n from '@/i18n';
import type { WorkbenchSession } from './useWorkbenchSessions';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export type EmployeeSessionFilter = 'all' | 'active' | 'completed';

export interface EmployeeSessionsResponse {
  employee_id: string;
  sessions: WorkbenchSession[];
  total: number;
  active_count: number;
  completed_count: number;
  has_more: boolean;
}

export interface FetchEmployeeSessionsOptions {
  status?: EmployeeSessionFilter;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}

export const DEFAULT_EMPLOYEE_SESSIONS_PAGE_SIZE = 20;

export async function fetchEmployeeSessions(
  memberPostId: string,
  options: FetchEmployeeSessionsOptions = {}
): Promise<EmployeeSessionsResponse> {
  const status = options.status ?? 'all';
  const limit = options.limit ?? DEFAULT_EMPLOYEE_SESSIONS_PAGE_SIZE;
  const offset = options.offset ?? 0;
  const qs = new URLSearchParams({
    status,
    limit: String(limit),
    offset: String(offset),
  });
  const res = await fetch(
    `${API_BASE_URL}/api/employees/${encodeURIComponent(memberPostId)}/sessions?${qs.toString()}`,
    { signal: options.signal }
  );
  if (!res.ok) {
    let detail = '';
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? '';
    } catch {
      detail = '';
    }
    throw new Error(
      detail || i18n.t('employees.errors.sessionsFailed', { status: res.status })
    );
  }
  const body = (await res.json()) as Partial<EmployeeSessionsResponse>;
  return {
    employee_id: body.employee_id ?? memberPostId,
    sessions: Array.isArray(body.sessions) ? body.sessions : [],
    total: typeof body.total === 'number' ? body.total : 0,
    active_count: typeof body.active_count === 'number' ? body.active_count : 0,
    completed_count: typeof body.completed_count === 'number' ? body.completed_count : 0,
    has_more: Boolean(body.has_more),
  };
}

export interface EmployeeSessionsState {
  sessions: WorkbenchSession[];
  total: number;
  activeCount: number;
  completedCount: number;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  loadMore: () => Promise<void>;
  reload: () => void;
}

export function useEmployeeSessions(
  employeeId: string | null,
  status: EmployeeSessionFilter = 'all',
  pageSize: number = DEFAULT_EMPLOYEE_SESSIONS_PAGE_SIZE
): EmployeeSessionsState {
  const [sessions, setSessions] = useState<WorkbenchSession[]>([]);
  const [total, setTotal] = useState(0);
  const [activeCount, setActiveCount] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reqSeq = useRef(0);
  const activeKeyRef = useRef('');
  const loadedCountRef = useRef(0);
  const loadMoreAbortRef = useRef<AbortController | null>(null);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    loadMoreAbortRef.current?.abort();
    loadMoreAbortRef.current = null;

    if (!employeeId) {
      activeKeyRef.current = '';
      loadedCountRef.current = 0;
      setSessions([]);
      setTotal(0);
      setActiveCount(0);
      setCompletedCount(0);
      setHasMore(false);
      setLoading(false);
      setLoadingMore(false);
      setError(null);
      return;
    }

    const key = `${employeeId}::${status}`;
    const keyChanged = activeKeyRef.current !== key;
    activeKeyRef.current = key;
    const seq = ++reqSeq.current;
    const controller = new AbortController();

    if (keyChanged) {
      loadedCountRef.current = 0;
      setSessions([]);
      setHasMore(false);
    }
    const requestLimit = keyChanged
      ? pageSize
      : Math.min(200, Math.max(pageSize, loadedCountRef.current));

    setLoading(true);
    setLoadingMore(false);
    setError(null);

    fetchEmployeeSessions(employeeId, {
      status,
      limit: requestLimit,
      offset: 0,
      signal: controller.signal,
    })
      .then((res) => {
        if (reqSeq.current !== seq || controller.signal.aborted) return;
        loadedCountRef.current = res.sessions.length;
        setSessions(res.sessions);
        setTotal(res.total);
        setActiveCount(res.active_count);
        setCompletedCount(res.completed_count);
        setHasMore(res.has_more);
        setError(null);
      })
      .catch((e: unknown) => {
        if (reqSeq.current !== seq || controller.signal.aborted) return;
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(
          e instanceof Error ? e.message : i18n.t('employees.errors.sessionsFailedPlain')
        );
      })
      .finally(() => {
        if (reqSeq.current === seq) setLoading(false);
      });

    return () => {
      controller.abort();
      loadMoreAbortRef.current?.abort();
      loadMoreAbortRef.current = null;
    };
  }, [employeeId, status, pageSize, nonce]);

  const loadMore = useCallback(async () => {
    if (!employeeId || loading || loadingMore || !hasMore) return;
    const seq = reqSeq.current;
    const offset = sessions.length;
    loadMoreAbortRef.current?.abort();
    const controller = new AbortController();
    loadMoreAbortRef.current = controller;
    setLoadingMore(true);
    try {
      const res = await fetchEmployeeSessions(employeeId, {
        status,
        limit: pageSize,
        offset,
        signal: controller.signal,
      });
      if (reqSeq.current !== seq || controller.signal.aborted) return;
      setSessions((prev) => {
        const seen = new Set(prev.map((s) => s.session_id));
        const next = [...prev];
        for (const item of res.sessions) {
          if (!seen.has(item.session_id)) {
            seen.add(item.session_id);
            next.push(item);
          }
        }
        loadedCountRef.current = next.length;
        return next;
      });
      setTotal(res.total);
      setActiveCount(res.active_count);
      setCompletedCount(res.completed_count);
      setHasMore(res.has_more);
    } catch (e: unknown) {
      if (reqSeq.current !== seq || controller.signal.aborted) return;
      if (e instanceof DOMException && e.name === 'AbortError') return;
      setError(
        e instanceof Error ? e.message : i18n.t('employees.errors.sessionsFailedPlain')
      );
    } finally {
      if (loadMoreAbortRef.current === controller) {
        loadMoreAbortRef.current = null;
      }
      if (reqSeq.current === seq) setLoadingMore(false);
    }
  }, [employeeId, status, pageSize, loading, loadingMore, hasMore, sessions.length]);

  return {
    sessions,
    total,
    activeCount,
    completedCount,
    hasMore,
    loading,
    loadingMore,
    error,
    loadMore,
    reload,
  };
}
