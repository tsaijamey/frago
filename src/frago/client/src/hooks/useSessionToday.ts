/**
 * useSessionToday — 「今天从 timeline 捡回来用」的名单。
 *
 * 左栏的口径是**今天有过真正回复的会话**。昨天晚上 23:59:59 说过话的一场，今天早上打开
 * 页面就不该再占着位置；但有些旧会话今天还要接着用，人从 timeline 里把它捡回来，它当天
 * 留在左栏。名单存在服务端（`GET/PUT/DELETE /api/workbench/today`），与置顶同一个理由：
 * 页面在多个浏览器、多台设备上打开，localStorage 天生不通。
 *
 * **只记「哪天捡的」。** 服务端按本地日期筛，第二天没有新回复就自然不在名单里——不需要
 * 谁去清。界面这边同样在本地零点之后重取一次，免得「今天是哪天」还停在昨天。
 *
 * **点下去那一刻界面就改，不等服务端。** 与置顶一样：等一次往返才动的开关点起来像卡住；
 * 服务端拒绝时把界面改回去，NEVER 让人停在一个盘上并不存在的状态。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import i18n from '@/i18n';
import { pageCache } from './pageCache';
import {
  expandSessionGroupIds,
  getSessionGroupIds,
  type WorkbenchSession,
} from './useWorkbenchSessions';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export interface SessionTodaySnapshot {
  /** 服务端认为的今天（本地日期 `YYYY-MM-DD`）。 */
  today: string;
  /** 今天捡回来用的会话编号。 */
  picked: string[];
}

export interface SessionTodayState {
  /** 今天捡回来用的会话编号。 */
  picked: string[];
  /** 查一场在不在今天的名单里。列表逐行都要问一次，用 Set 而不是 includes。 */
  isPicked: (sessionId: string) => boolean;
  /** 捡回来 / 放下。失败时界面已经改回去了，错照样抛出来让调用方去报。 */
  toggle: (sessionId: string) => Promise<void>;
  /** 服务端认为的今天；还没取到时为 null。 */
  today: string | null;
  /** 重取名单（跨过本地零点、或者页面重新可见时用）。 */
  refresh: () => Promise<void>;
}

function parse(body: unknown): SessionTodaySnapshot {
  const data = (body ?? {}) as { today?: unknown; picked?: unknown };
  return {
    today: typeof data.today === 'string' ? data.today : '',
    picked: Array.isArray(data.picked)
      ? data.picked.filter((id): id is string => typeof id === 'string' && id.length > 0)
      : [],
  };
}

export async function fetchToday(): Promise<SessionTodaySnapshot> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/today`);
  if (!res.ok) throw new Error(i18n.t('workbench.errors.todayFetchFailed', { status: res.status }));
  return parse(await res.json());
}

export async function putToday(sessionId: string): Promise<SessionTodaySnapshot> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/today/${encodeURIComponent(sessionId)}`,
    { method: 'PUT' }
  );
  if (!res.ok) throw new Error(i18n.t('workbench.errors.todaySaveFailed', { status: res.status }));
  return parse(await res.json());
}

export async function deleteToday(sessionId: string): Promise<SessionTodaySnapshot> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/today/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' }
  );
  if (!res.ok) throw new Error(i18n.t('workbench.errors.todaySaveFailed', { status: res.status }));
  return parse(await res.json());
}

/** 最近一次拿到手的名单。切菜单回来时左栏不再先闪一下旧口径。 */
const lastToday = pageCache<SessionTodaySnapshot>();

/** 距下一个本地零点还有多少毫秒（多加一秒，确保跨过去之后才取）。 */
function msUntilTomorrow(now: number = Date.now()): number {
  const next = new Date(now);
  next.setHours(24, 0, 0, 0);
  return Math.max(1_000, next.getTime() - now + 1_000);
}

export function useSessionToday(sessions: WorkbenchSession[] = []): SessionTodayState {
  const [snapshot, setSnapshot] = useState<SessionTodaySnapshot>(
    () => lastToday.get() ?? { today: '', picked: [] }
  );
  const sessionsRef = useRef<WorkbenchSession[]>(sessions);
  sessionsRef.current = sessions;

  useEffect(() => {
    lastToday.set(snapshot);
  }, [snapshot]);

  const refresh = useCallback(async () => {
    const next = await fetchToday();
    setSnapshot(next);
  }, []);

  /**
   * 开局取一次；之后只在**跨过本地零点**与**页面重新可见**时再取。
   *
   * 名单只有这一个页面会改，服务端不会背着它变——不像会话清单那样需要定时重取。零点那
   * 一次是必须的：昨天捡回来的几条，今天必须从名单里消失；页面一直开着的话，没人重取
   * 它们就会一直留在屏幕上。
   */
  useEffect(() => {
    let alive = true;
    fetchToday()
      .then((next) => {
        if (alive) setSnapshot(next);
      })
      .catch(() => {
        // 取不到就按空名单走：左栏照常摆得出「今天有回复」的那些会话，只是少了捡回来的
        // 这几场。开局弹一句人还没做任何事的报错，除了吓人没有用处。
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let timer: number;
    const schedule = () => {
      timer = window.setTimeout(() => {
        refresh().catch(() => {
          // 零点这一趟失败不打断任何事：下一次页面可见、或者人再捡一场时会再对一次。
        });
        schedule();
      }, msUntilTomorrow());
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    const onVisible = () => {
      if (document.hidden) return;
      refresh().catch(() => {
        // 同上：取不到就先用手上那份。
      });
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [refresh]);

  const rawPickedSet = useMemo(() => new Set(snapshot.picked), [snapshot.picked]);
  const pickedSet = useMemo(
    () =>
      sessions.length
        ? expandSessionGroupIds(sessions, snapshot.picked)
        : rawPickedSet,
    [sessions, snapshot.picked, rawPickedSet]
  );
  const expandedPicked = useMemo(
    () => (sessions.length ? Array.from(pickedSet) : snapshot.picked),
    [sessions.length, pickedSet, snapshot.picked]
  );
  const isPicked = useCallback(
    (sessionId: string) => pickedSet.has(sessionId),
    [pickedSet]
  );

  /**
   * 连点时以**最后一下**为准。两次请求的先后到达顺序不保证，先发的后到就会把后发的
   * 结果盖回去——那么刚从 timeline 捡回来的一场会自己弹走。与 `useSessionPins` 同一套。
   */
  const latestIntent = useRef(new Map<string, number>());
  const seq = useRef(0);

  const toggle = useCallback(
    async (sessionId: string) => {
      const currentSessions = sessionsRef.current;
      const groupIds = currentSessions.length
        ? getSessionGroupIds(currentSessions, sessionId)
        : [sessionId];
      const groupSet = new Set(groupIds);
      const wasPicked = groupIds.some((id) => rawPickedSet.has(id)) || pickedSet.has(sessionId);
      const toRemove = wasPicked
        ? groupIds.filter((id) => rawPickedSet.has(id))
        : [];
      const removeTargets = wasPicked
        ? toRemove.length > 0
          ? toRemove
          : [sessionId]
        : [];
      const ticket = ++seq.current;
      for (const id of groupIds) {
        latestIntent.current.set(id, ticket);
      }

      // 先改界面：主会话、branched 会话与 worker 会话作为一个整体一起捡回或放下。
      setSnapshot((prev) => ({
        ...prev,
        picked: wasPicked
          ? prev.picked.filter((id) => !groupSet.has(id))
          : [sessionId, ...prev.picked.filter((id) => id !== sessionId)],
      }));

      try {
        let authoritative: SessionTodaySnapshot | null = null;
        if (wasPicked) {
          for (const id of removeTargets) {
            authoritative = await deleteToday(id);
          }
        } else {
          authoritative = await putToday(sessionId);
        }
        if (latestIntent.current.get(sessionId) !== ticket) return;
        if (authoritative) setSnapshot(authoritative);
      } catch (e) {
        if (latestIntent.current.get(sessionId) === ticket) {
          // 没存下就把界面改回去。停在一个盘上并不存在的状态，人下次打开会以为名单丢了。
          setSnapshot((prev) => ({
            ...prev,
            picked: wasPicked
              ? [
                  ...removeTargets,
                  ...prev.picked.filter((id) => !removeTargets.includes(id)),
                ]
              : prev.picked.filter((id) => !groupSet.has(id)),
          }));
        }
        throw e;
      }
    },
    [rawPickedSet, pickedSet]
  );

  return {
    picked: expandedPicked,
    isPicked,
    toggle,
    today: snapshot.today || null,
    refresh,
  };
}
