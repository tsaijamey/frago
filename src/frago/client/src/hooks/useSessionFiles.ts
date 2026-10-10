/**
 * useSessionFiles — 这一场会话动过哪些文件。
 *
 * 数据在服务端（`GET /api/workbench/sessions/{sid}/files`）：它要现读这一场的全部记录、逐条
 * 挑出写与改的工具调用，**不是一次轻查询**（本机量过 0.1–0.5 秒）。取法：
 *
 * - **切到哪一场就取哪一场**（页面那一侧一挂上就 `ensure`）。这个数摆在镜头排上，是这一场
 *   的读数之一，空着一眼看去就是「没动过文件」——按需取（点开才读）的代价是那颗按钮一直
 *   空着，那是假的。
 * - 取回来就留着，同一场会话里来回切档不再重取（人在清单与记录流之间来回看是常事）。要最
 *   新的那一份就 `reload()`。
 * - 换会话之后旧请求回来一律扔掉：那些文件是上一场的，摆到这一场上是错的。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getSessionFiles } from '@/api';
import type { SessionFileRow } from '@/types/api';

export interface SessionFilesState {
  /**
   * 这份清单。`null` 是**还没取回来**，空数组是取了、这一场确实没动过文件。
   * 「还不知道」与「没有」是两件事，合并了界面就只能摆空。
   */
  files: SessionFileRow[] | null;
  loading: boolean;
  error: string | null;
  /** 切到这一场、或打开这一档时喊一声。没取过才真去取，取过或正在取就什么都不做。 */
  ensure: () => void;
  /** 重取一份。取失败之后手动再试走它。 */
  reload: () => void;
}

export function useSessionFiles(sessionId: string | null): SessionFilesState {
  const [files, setFiles] = useState<SessionFileRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** 当前是哪一场。异步回来的结果对不上就扔掉。 */
  const sidRef = useRef<string | null>(sessionId);
  /** 第几次请求。换会话也加一，在路上的那一次因此作废。 */
  const seq = useRef(0);
  /**
   * `ensure` 要一眼看出「取过没有、在不在路上」，但要**不看 state**——它一变，页面上那条
   * 「打开就取」的效应会跟着重跑，取失败时就成了连着重试的死循环。所以这两样各留一份 ref，
   * state 只管摆出来。
   */
  const filesRef = useRef<SessionFileRow[] | null>(null);
  const loadingRef = useRef(false);

  useEffect(() => {
    sidRef.current = sessionId;
    seq.current += 1;
    filesRef.current = null;
    loadingRef.current = false;
    setFiles(null);
    setLoading(false);
    setError(null);
  }, [sessionId]);

  const reload = useCallback(async () => {
    const sid = sidRef.current;
    if (!sid || loadingRef.current) return;
    const mine = (seq.current += 1);
    loadingRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const rows = await getSessionFiles(sid);
      if (sidRef.current !== sid || seq.current !== mine) return;
      filesRef.current = rows;
      setFiles(rows);
    } catch (e) {
      if (sidRef.current !== sid || seq.current !== mine) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (sidRef.current === sid && seq.current === mine) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, []);

  const ensure = useCallback(() => {
    if (filesRef.current !== null || loadingRef.current) return;
    void reload();
  }, [reload]);

  return { files, loading, error, ensure, reload: () => void reload() };
}
