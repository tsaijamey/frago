/**
 * useSessionViews — 每场会话你上次点开它的时刻，以及据此判出来的两个标记。
 *
 * 记录存在服务端（`GET /api/workbench/views`、`PUT /api/workbench/views/{id}`），不存浏览器
 * 本地：同一台机器上这个页面至少有两个壳，两边的本地存储天生不通，在桌面客户端看过的
 * 那几场换到浏览器又全成了「没看过」。
 *
 * **两个标记都以一小时为界，各答一个问题。**
 *
 * - 「没看过」（绿圈）：agent 说完话停下了，而你还没回去看这一场。判据是停下来那一刻——
 *   也就是最后一句回复的时刻——在一小时之内，且你没在那之后点开过它。没有点开记录的
 *   同样算，一小时这道窗口已经挡住了那些旧会话：它们停在几天前，不会亮。
 * - 「最近动过」（活的绿边）：最后一次活动在一小时之内，与看没看过无关。它答的是
 *   「我刚才在哪儿谈的」，所以看过之后照样亮着，过了一小时自己灭。
 *
 * 判据写成下面两个纯函数，用例直接盯它们——这种口径一旦只活在界面代码里，过几天就没人
 * 说得清绿圈到底什么时候亮。
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import i18n from '@/i18n';
import { activityTs, type WorkbenchSession } from './useWorkbenchSessions';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 两个标记共用的时间窗：一小时。 */
export const RECENT_MS = 60 * 60 * 1000;

/**
 * 这一场 agent 说完话停下了、你还没回去看。
 *
 * `viewedAt` 是你上次点开它的时刻，从没点开过就是 undefined。还在跑的不算——它还没停下，
 * 没有"说完了"这回事。
 */
export function isUnreadAt(
  session: WorkbenchSession,
  viewedAt: number | undefined,
  now: number
): boolean {
  if (session.status === 'running') return false;
  const stopped = activityTs(session);
  if (!stopped || now - stopped >= RECENT_MS) return false;
  return viewedAt === undefined || stopped > viewedAt;
}

/** 这一场最近动过：最后一次活动在一小时之内。 */
export function isRecentAt(session: WorkbenchSession, now: number): boolean {
  const last = activityTs(session);
  return Boolean(last) && now - last < RECENT_MS;
}

export interface SessionViewsState {
  /** 这场会话有没有你还没看过的新回复。 */
  isUnread: (session: WorkbenchSession) => boolean;
  /** 这场会话最近动过没有。 */
  isRecent: (session: WorkbenchSession) => boolean;
  /** 记下此刻点开了这场会话。失败不抛——少记一次只是标记多亮一会儿。 */
  markViewed: (sessionId: string) => void;
}

export async function fetchViews(): Promise<Record<string, number>> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/views`);
  if (!res.ok) throw new Error(i18n.t('workbench.errors.viewsFetchFailed', { status: res.status }));
  const body = (await res.json()) as { viewed?: Record<string, number> };
  return body.viewed ?? {};
}

export async function putView(sessionId: string): Promise<number> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/views/${encodeURIComponent(sessionId)}`,
    { method: 'PUT' }
  );
  if (!res.ok) throw new Error(i18n.t('workbench.errors.viewSaveFailed', { status: res.status }));
  const body = (await res.json()) as { viewed_at?: number };
  return body.viewed_at ?? Date.now();
}

export function useSessionViews(): SessionViewsState {
  const [viewed, setViewed] = useState<Record<string, number>>({});

  useEffect(() => {
    let alive = true;
    fetchViews()
      .then((map) => {
        if (alive) setViewed(map);
      })
      .catch(() => {
        // 取不到就当一场都没点开过：左栏照常摆得出清单，绿圈只会多亮几个。
      });
    return () => {
      alive = false;
    };
  }, []);

  const markViewed = useCallback((sessionId: string) => {
    // 点下去那一刻标记就该灭，不等服务端。没存下的话下次开页面它又亮起来——
    // 比让人对着一个点不灭的标记按第二次强。
    setViewed((prev) => ({ ...prev, [sessionId]: Date.now() }));
    void putView(sessionId)
      .then((at) => setViewed((prev) => ({ ...prev, [sessionId]: at })))
      .catch(() => {});
  }, []);

  return useMemo(
    () => ({
      isUnread: (session: WorkbenchSession) =>
        isUnreadAt(session, viewed[session.session_id], Date.now()),
      isRecent: (session: WorkbenchSession) => isRecentAt(session, Date.now()),
      markViewed,
    }),
    [viewed, markViewed]
  );
}
