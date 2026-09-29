/**
 * DeleteSessionButton — 「删除会话」的动作与报错说法。入口在「…」菜单（`SessionMenu`）第三段。
 *
 * 09-29 第五轮四改：页头的垃圾桶按钮与弹窗退场，删会话收进卡片与页头共用的「…」菜单，
 * 确认画在菜单里。这里留下的是菜单要调的那几样：接口、按状态码换话、一次删除的状态。
 *
 * **三家都能删，删的是各家的那一份。** Claude Code 的记录是一个 JSONL 加一个同名目录，
 * 删掉的是那两样；opencode 与 codex 的会话躺在自己的库里，删法是借引擎自己的删除命令。
 * frago 在 ``~/.frago/sessions`` 下另存的副本不跟着动，删除接口也只承诺"清单里不再有它"。
 *
 * **在跑的会话删不掉，由服务端拦下。** 拒绝的两句话由这一侧按状态码换成本地文案
 * （见 ``deleteErrorKey``）；引擎自己吐的那句原样摆出来。这一侧不预先探测会话在不在跑：
 * 探测要么按 tmux 每点一次问一趟，要么看记录文件推一个不准的答案。
 */

import { useCallback, useState } from 'react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 删掉之后服务端交代的账。``warnings`` 是删了但没收拾干净的地方。 */
export interface DeleteSessionResult {
  sid: string;
  family: 'claude-code' | 'opencode' | 'codex' | 'coreagent';
  /** 删掉了哪几样，服务端写好的人话，原样摆出来。 */
  removed: string[];
  warnings: string[];
}

/** 删不掉时服务端回的那一下。状态码要留着，见 ``errorText``。 */
export interface DeleteFailure {
  status: number;
  detail: string;
}

/** 服务端说没删成。状态码单独带出来，别只留一句话。 */
export class DeleteSessionError extends Error {
  readonly status: number;

  constructor(detail: string, status: number) {
    super(detail);
    this.name = 'DeleteSessionError';
    this.status = status;
  }
}

export async function deleteWorkbenchSession(sessionId: string): Promise<DeleteSessionResult> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' }
  );
  if (!res.ok) {
    let detail = String(res.status);
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string' && body.detail) detail = body.detail;
    } catch {
      /* 响应不是 JSON，退回状态码 */
    }
    throw new DeleteSessionError(detail, res.status);
  }
  return (await res.json()) as DeleteSessionResult;
}

/**
 * 删不动时换成本地说法的那两档。这两档由状态码定死：服务端那两句是中文写死的，英文界面上
 * 摆着一段中文等于没说；而且"本机已经没有了""还在跑"这两件事人不需要再读一遍解释。
 * 其余（引擎不认这场、没装那个引擎、盘写不进去）返回 null，照搬服务端那句话——拒绝的理由
 * 只有它知道，转述一次就多一层失真。
 */
export function deleteErrorKey(status: number): string | null {
  if (status === 404) return 'workbench.delete.gone';
  if (status === 409) return 'workbench.delete.running';
  return null;
}

export interface DeleteSessionState {
  busy: boolean;
  /** 删不动的那一下；没出过错为 null。 */
  failure: DeleteFailure | null;
  /** 出门。删掉了返回 true（已调过 `onDeleted`），删不动返回 false、`failure` 有值。 */
  confirm: () => Promise<boolean>;
  reset: () => void;
}

export function useDeleteSession(
  session: WorkbenchSession,
  onDeleted?: (result: DeleteSessionResult) => void
): DeleteSessionState {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<DeleteFailure | null>(null);
  const reset = useCallback(() => setFailure(null), []);
  const confirm = useCallback(async () => {
    setBusy(true);
    setFailure(null);
    try {
      const result = await deleteWorkbenchSession(session.session_id);
      onDeleted?.(result);
      return true;
    } catch (e) {
      // 删不动就留在确认那一段：多半是还在跑，人正好在同一个菜单里先关 tmux。
      if (e instanceof DeleteSessionError) setFailure({ status: e.status, detail: e.message });
      else setFailure({ status: 0, detail: e instanceof Error ? e.message : String(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }, [session.session_id, onDeleted]);
  return { busy, failure, confirm, reset };
}
