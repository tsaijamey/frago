/**
 * useSessionObserver — 会话页右栏的数据。
 *
 * 取法有推有拉，缺一不可：
 *
 * - **推**：停在这场会话上时听 `session_observer_update`，旁路 AI 每写完一次服务端就推一次，
 *   最快。
 * - **拉**：选中一场会话、切回来、推送连接重新连上、页面从后台回到前台时各拉一次
 *   `GET /api/workbench/sessions/{sid}/observer`；此外停在这场会话上时每 15 秒拉一次。
 *
 * 只推不拉的那一版出过事（2026-09-11）：服务端 17:21:09 确实推了，一个开了很久的页面却没
 * 换——中栏有自己的轮询兜底照样在走，右栏只在选中那一刻读过一次，于是人看到的是「会话
 * 在更新，旁路停在旧的上」。推送为什么会漏，原因可以有很多（连接悄悄断过、页面被浏览器
 * 挂起过），右栏不该押在其中任何一种不发生上。
 *
 * 拉回来的比手上的旧（旁路 AI 刚推来一版更新的，而这次拉的请求出门更早），就不用它：
 * 新内容不能被旧内容盖掉。
 *
 * 旁路 AI 在服务端跑，跟这一页停在哪场会话无关：切走打断不了它，这里也 NEVER 因为切走
 * 去通知服务端停下什么。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getWebSocketClient, MessageType, type WebSocketMessage } from '../api/websocket';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 停在一场会话上时多久自己拉一次。推送正常时这一拉什么也不改。 */
export const OBSERVER_POLL_MS = 15_000;

/** ok 填过 / failed 上一次没问到 / empty 还没填过 / unbound 旁路 AI 没绑模型。 */
export type ObserverStatus = 'ok' | 'failed' | 'empty' | 'unbound';

/**
 * 「已经发生的事」的最后一条，也就是眼下的状态。agent 在做是「此刻」，东西落地了是
 * 「产出」；产出被下一个状态顶掉时，服务端把它挪进 happened。
 */
export interface ObserverTail {
  kind: 'now' | 'output';
  text: string;
}

export interface ObserverState {
  bound: boolean;
  /** 这场在做什么：人说过的原话，不经模型改写。 */
  anchor: string | null;
  tail: ObserverTail | null;
  decision: string;
  /** 已经发生的事（不含末条），新的在前。 */
  happened: string[];
  /**
   * 每一格自己上次变样的时刻（毫秒），跟正文一一对应。右栏按时间线读要用它。
   *
   * 老的槽位文件里没有这几格，读回来是 null / 一串 null：那几格照常显示，只是不带时间。
   * 所以画的时候一律当「可能没有」处理，NEVER 假定一定有。
   */
  happened_at?: (number | null)[];
  anchor_at?: number | null;
  tail_at?: number | null;
  decision_at?: number | null;
  /** 毫秒时间戳。槽位真的变过才会动。 */
  updated_at: number | null;
  model: string | null;
  status: ObserverStatus;
  status_detail: string | null;
}

export async function fetchObserverState(sessionId: string): Promise<ObserverState> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/observer`
  );
  if (!res.ok) throw new Error(String(res.status));
  return (await res.json()) as ObserverState;
}

/**
 * 拉回来的这一版该不该替换手上的。只有它确实更旧才不用：槽位改过的时刻更早。
 * 状态本身变了（没绑 → 绑了、失败 → 恢复）也要换，那不体现在槽位改动的时刻上。
 */
function newer(current: ObserverState | null, fetched: ObserverState): ObserverState {
  if (!current) return fetched;
  const had = current.updated_at ?? 0;
  const got = fetched.updated_at ?? 0;
  if (got < had) return current;
  if (
    got === had &&
    fetched.status === current.status &&
    fetched.status_detail === current.status_detail &&
    fetched.bound === current.bound
  ) {
    return current;
  }
  return fetched;
}

export interface SessionObserverView {
  state: ObserverState | null;
  loading: boolean;
  error: string | null;
}

export function useSessionObserver(sessionId: string | null): SessionObserverView {
  const [state, setState] = useState<ObserverState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<string | null>(sessionId);
  current.current = sessionId;

  /** 拉一次。回来时人已经切到别的会话了，就丢掉。 */
  const pull = useCallback(async (sid: string) => {
    try {
      const fetched = await fetchObserverState(sid);
      if (current.current !== sid) return;
      setState((prev) => newer(prev, fetched));
      setError(null);
    } catch (e: unknown) {
      if (current.current === sid) setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    // 换会话先清空：上一场的内容留在这里，人会以为说的是眼下这一场。
    setState(null);
    setError(null);
    if (!sessionId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void pull(sessionId).finally(() => {
      if (current.current === sessionId) setLoading(false);
    });

    const client = getWebSocketClient();
    const onUpdate = (msg: WebSocketMessage) => {
      const data = msg.data as { session_id?: string; state?: ObserverState } | undefined;
      if (!data || data.session_id !== sessionId || !data.state) return;
      setState(data.state);
      setError(null);
    };
    const unsubscribe = client.on(MessageType.SESSION_OBSERVER_UPDATE, onUpdate);
    // 推送连接断过又连上：断开的那段时间里推过什么，这边一概没收到，所以连上就补拉一次。
    const unsubscribeConnect = client.onConnect?.(() => void pull(sessionId));

    // 页面在后台时浏览器会压着定时器，回到前台立刻补一次，不等下一个 15 秒。
    const onVisible = () => {
      if (document.visibilityState === 'visible') void pull(sessionId);
    };
    document.addEventListener('visibilitychange', onVisible);
    const timer = setInterval(() => {
      if (document.visibilityState !== 'hidden') void pull(sessionId);
    }, OBSERVER_POLL_MS);

    return () => {
      unsubscribe();
      unsubscribeConnect?.();
      document.removeEventListener('visibilitychange', onVisible);
      clearInterval(timer);
    };
  }, [sessionId, pull]);

  return { state, loading, error };
}
