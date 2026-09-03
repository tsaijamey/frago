/**
 * useSessionPins — 左栏置顶名单的数据源。
 *
 * 名单存在服务端（`GET/PUT/DELETE /api/workbench/pins`），不存浏览器本地。同一台机器上
 * 这个页面至少有两个壳——桌面客户端与浏览器，两边的 localStorage 天生不通；置顶是人一条
 * 条挑出来的，在桌面客户端挑好的十几场换到浏览器一场都不在，那不是"没同步"，是丢了。
 *
 * **点下去那一刻界面就改，不等服务端。** 置顶是个开关，等一次往返才动的开关点起来像卡住。
 * 服务端拒绝时把界面**改回去**并把错抛出来，NEVER 让界面停在一个盘上并不存在的状态。
 *
 * 次序一律以服务端回的那份为准：置顶会把已经在名单里的挪到最前，这个次序由服务端定，
 * 界面照抄。两处各排一遍迟早各排各的。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import i18n from '@/i18n';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 置顶区折不折起来记在本地。这是"我这个屏幕上现在想不想看见"，不是跨设备的数据。 */
const COLLAPSED_KEY = 'frago-workbench-pins-collapsed';

export interface SessionPinsState {
  /** 置顶的会话编号，最近置顶的在最前。 */
  pinned: string[];
  /** 查一场在不在名单里。列表逐行都要问一次，用 Set 而不是 includes。 */
  isPinned: (sessionId: string) => boolean;
  /** 置顶 / 取消置顶。失败时界面已经改回去了，错照样抛出来让调用方去报。 */
  toggle: (sessionId: string) => Promise<void>;
  /** 置顶区折起来了没有。 */
  collapsed: boolean;
  setCollapsed: (value: boolean) => void;
}

export async function fetchPins(): Promise<string[]> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/pins`);
  if (!res.ok) throw new Error(i18n.t('workbench.errors.pinsFetchFailed', { status: res.status }));
  const body = (await res.json()) as { pinned?: string[] };
  return body.pinned ?? [];
}

export async function putPin(sessionId: string): Promise<string[]> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/pins/${encodeURIComponent(sessionId)}`,
    { method: 'PUT' }
  );
  if (!res.ok) throw new Error(i18n.t('workbench.errors.pinSaveFailed', { status: res.status }));
  const body = (await res.json()) as { pinned?: string[] };
  return body.pinned ?? [];
}

export async function deletePin(sessionId: string): Promise<string[]> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/pins/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' }
  );
  if (!res.ok) throw new Error(i18n.t('workbench.errors.unpinSaveFailed', { status: res.status }));
  const body = (await res.json()) as { pinned?: string[] };
  return body.pinned ?? [];
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === 'true';
  } catch {
    return false;
  }
}

export function useSessionPins(): SessionPinsState {
  const [pinned, setPinned] = useState<string[]>([]);
  const [collapsed, setCollapsedState] = useState<boolean>(readCollapsed);

  /**
   * 开局取一次就够。这份名单只有这一个页面会改，服务端不会背着它变——不像会话清单那样
   * 需要定时重取。
   */
  useEffect(() => {
    let alive = true;
    fetchPins()
      .then((list) => {
        if (alive) setPinned(list);
      })
      .catch(() => {
        // 取不到就当一场都没置顶：左栏照常摆得出会话清单，只是少了置顶那一区。
        // 这里不弹提示——开局弹一句人还没做任何事的报错，除了吓人没有用处。
      });
    return () => {
      alive = false;
    };
  }, []);

  const pinnedSet = useMemo(() => new Set(pinned), [pinned]);
  const isPinned = useCallback((sessionId: string) => pinnedSet.has(sessionId), [pinnedSet]);

  /**
   * 连点时以**最后一下**为准。
   *
   * 两次请求的先后到达顺序不保证，先发的后到就会把后发的结果盖回去——界面上那颗图钉
   * 会自己弹回去。记下这一场最后一次点的是哪个方向，只有最后那一趟的结果算数。
   */
  const latestIntent = useRef(new Map<string, number>());
  const seq = useRef(0);

  const toggle = useCallback(
    async (sessionId: string) => {
      const wasPinned = pinnedSet.has(sessionId);
      const ticket = ++seq.current;
      latestIntent.current.set(sessionId, ticket);

      // 先改界面。开关点下去要立刻动，NEVER 等一次往返。
      setPinned((prev) =>
        wasPinned ? prev.filter((id) => id !== sessionId) : [sessionId, ...prev.filter((id) => id !== sessionId)]
      );

      try {
        const authoritative = wasPinned ? await deletePin(sessionId) : await putPin(sessionId);
        if (latestIntent.current.get(sessionId) !== ticket) return;
        setPinned(authoritative);
      } catch (e) {
        if (latestIntent.current.get(sessionId) === ticket) {
          // 没存下就把界面改回去。停在一个盘上并不存在的状态，人下次打开会以为置顶丢了。
          setPinned((prev) =>
            wasPinned
              ? [sessionId, ...prev.filter((id) => id !== sessionId)]
              : prev.filter((id) => id !== sessionId)
          );
        }
        throw e;
      }
    },
    [pinnedSet]
  );

  const setCollapsed = useCallback((value: boolean) => {
    setCollapsedState(value);
    try {
      localStorage.setItem(COLLAPSED_KEY, String(value));
    } catch {
      // 存不下也照常折叠，只是下次打开回到展开。折叠状态丢了不值得打断任何事。
    }
  }, []);

  return { pinned, isPinned, toggle, collapsed, setCollapsed };
}
