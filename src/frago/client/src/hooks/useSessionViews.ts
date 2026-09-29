/**
 * useSessionViews — 每场会话你上次点开它的时刻，以及「开在 tmux 里」那道流光。
 *
 * 记录存在服务端（`GET /api/workbench/views`、`PUT /api/workbench/views/{id}`），不存浏览器
 * 本地：换一个浏览器、换一台设备，本地存储天生不通，在一处看过的那几场换个地方打开又全
 * 成了「没看过」。
 *
 * **「看过没」只是次要标记。** 从前它决定一个绿圈亮不亮（停下一小时内、之后没点开过）。
 * 那个口径在 09-24 13:52 那一刻会点亮 7 场，其中 6 场是早已不在 tmux 里的 worker，没人
 * 在等；而一场点开看过、仍开着终端等回话的会话，绿圈却灭了。现在「要不要你来」由
 * `useForYou` 从终端直接读，这里只交出上次点开的时刻，供 For you 那一条判「停下之后看过
 * 没」、没看过的标题加粗。
 *
 * 「开在 tmux 里」（流光）答的是「哪几场还占着一个在跑的 agent」，与时间、看没看过都无关，
 * tmux 关掉它才灭。判据由服务端给（`in_tmux`），只按名字对。
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import i18n from '@/i18n';
import { pageCache } from './pageCache';
import type { WorkbenchSession } from './useWorkbenchSessions';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 这一场此刻开在 tmux 里。 */
export function isInTmux(session: WorkbenchSession): boolean {
  return session.in_tmux === true;
}

export interface SessionViewsState {
  /** 你上次点开这场会话的时刻（毫秒）；从没点开过为 undefined。 */
  viewedAt: (sessionId: string) => number | undefined;
  /** 这场会话此刻开在 tmux 里没有。 */
  isInTmux: (session: WorkbenchSession) => boolean;
  /** 记下此刻点开了这场会话。失败不抛——少记一次只是标题多粗一会儿。 */
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

/** 最近一次拿到手的已读记录（见 `pageCache`）。切菜单回来标题不再先全粗一下。 */
const lastViewed = pageCache<Record<string, number>>();

export function useSessionViews(): SessionViewsState {
  const [viewed, setViewed] = useState<Record<string, number>>(() => lastViewed.get() ?? {});

  useEffect(() => {
    lastViewed.set(viewed);
  }, [viewed]);

  useEffect(() => {
    let alive = true;
    fetchViews()
      .then((map) => {
        if (alive) setViewed(map);
      })
      .catch(() => {
        // 取不到就当一场都没点开过：左栏照常摆得出清单，只是多几行标题加粗。
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

  const viewedAt = useCallback((sessionId: string) => viewed[sessionId], [viewed]);

  return useMemo(() => ({ viewedAt, isInTmux, markViewed }), [viewedAt, markViewed]);
}
