/**
 * useTmuxSessionCount / useTmuxSessions —— 本机 tmux 会话的清点。
 *
 * **拆成两个钩子，是因为两件事的代价差着数量级。** 左下角那个数字每分钟要一次，它
 * 只问「几场、多少内存」，服务端不碰任何记录文件；浮窗里每行那句「上次说了什么」
 * 得把十几份 jsonl 读一遍，那是人点开的那一刻才做的事，之后除非他自己刷新，不再重来。
 *
 * 拿不到就当零场：这台机器可能压根没起 tmux，那不是错误状态，不该弹红框。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  closeTmuxSessions,
  getTmuxSessionCount,
  getTmuxSessions,
  setTmuxCleanupThreshold,
} from '@/api';
import { fetchWorkbenchSessions } from './useWorkbenchSessions';
import type { CloseTmuxSessionsResponse, TmuxSessionsResponse } from '@/types/api';

/** 左下角那个数字的刷新节拍。会话是人自己开的，一分钟一次足够跟上。 */
const COUNT_INTERVAL_MS = 60_000;

export function useTmuxSessionCount(): { total: number; totalMemoryMb: number } {
  const [state, setState] = useState({ total: 0, totalMemoryMb: 0 });

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const data = await getTmuxSessionCount();
        if (alive) setState({ total: data.total, totalMemoryMb: data.total_memory_mb });
      } catch {
        // 问不到就保持上一次的数字，不闪不弹——这条不值得打断任何人。
      }
    };
    tick();
    const timer = setInterval(tick, COUNT_INTERVAL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  return state;
}

export interface TmuxSessionsState {
  data: TmuxSessionsResponse | null;
  loading: boolean;
  error: string | null;
  /** 会话编号 → 人在左栏认得的那句标题。tmux 会话名只是把手，uuid 不是给人看的。 */
  titles: Record<string, string>;
  reload: () => void;
  close: (names: string[]) => Promise<CloseTmuxSessionsResponse>;
  saveThreshold: (hours: number) => Promise<void>;
}

/**
 * 浮窗打开期间的清单。`excerptChars` 决定每行正文截多长——传多少由浮窗按自己的
 * 行宽定，不在服务端写死。
 */
export function useTmuxSessions(excerptChars: number): TmuxSessionsState {
  const [data, setData] = useState<TmuxSessionsResponse | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // 标题来自会话清单那条既有接口。`tmux_sessions` 只认得出把手（uuid / 业务名），
  // 清单里的主角该是人在左栏看见的那句话。拿不到标题时退回把手名，不弹错——
  // 这是排版信息，不该拦住清点本身。
  useEffect(() => {
    let local = true;
    fetchWorkbenchSessions()
      .then((rows) => {
        if (!local) return;
        const map: Record<string, string> = {};
        for (const row of rows) {
          if (row.session_id && row.title) map[row.session_id] = row.title;
        }
        setTitles(map);
      })
      .catch(() => {
        // 标题只是副信息，取不到就不取。
      });
    return () => {
      local = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTmuxSessions(excerptChars);
      if (alive.current) setData(result);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [excerptChars]);

  useEffect(() => {
    reload();
  }, [reload]);

  const close = useCallback(
    async (names: string[]) => {
      const result = await closeTmuxSessions(names);
      // 关完必须重新清点，不能自己从清单里划掉：有的会话可能没关成（服务端逐条回报），
      // 界面凭猜测把它抹掉，人会以为内存已经腾出来了。
      await reload();
      return result;
    },
    [reload]
  );

  const saveThreshold = useCallback(async (hours: number) => {
    const result = await setTmuxCleanupThreshold(hours);
    if (alive.current) setData(result);
  }, []);

  return { data, loading, error, titles, reload, close, saveThreshold };
}
