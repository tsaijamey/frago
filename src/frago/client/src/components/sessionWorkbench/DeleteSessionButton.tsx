/**
 * DeleteSessionButton — 标题栏最右那个「删除会话」。
 *
 * **三家都出现，删的是各家的那一份。** Claude Code 的记录是一个 JSONL 加一个同名目录，
 * 删掉的是那两样；opencode 与 codex 的会话躺在自己的库里，删法是借引擎自己的删除命令。
 * 弹窗里那句「删的是什么」把家族名填进去说，人按下去之前知道自己动的是哪一份。
 * frago 在 ``~/.frago/sessions`` 下另存的副本不跟着动，删除接口也只承诺"清单里不再有它"。
 *
 * **二次确认走弹窗，不是按钮两段式。** 这一步动的是盘上的真东西，弹窗放得下"删哪一场、
 * 删完会怎样、还有没有退路"这三句话；按钮上变一行字放不下。确认之前在弹窗里先把这一场
 * 的标题、编号、工作目录摆出来——左栏一行行挨着看，点错一行是常有的事。
 *
 * **弹窗里的每一句话都要能自己站着。** 删之前说清删掉的是什么、删完会怎样、能不能反悔；
 * 删不动的时候说清卡在哪儿、人下一步按什么。这份文案的写法与取舍见
 * ``workbench.delete.*`` ——里面的措辞是给用户看的，不是给读过这套代码的人看的。
 *
 * **在跑的会话删不掉，由服务端拦下。** 拒绝的两句话由这一侧按状态码换成本地文案
 * （见 ``errorText``）；引擎自己吐的那句原样摆出来。这一侧不预先探测会话在不在跑：
 * 探测要么按 tmux 每点一次问一趟，要么看记录文件推一个不准的答案。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Trash2 } from 'lucide-react';
import Modal from '@/components/ui/Modal';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 删掉之后服务端交代的账。``warnings`` 是删了但没收拾干净的地方。 */
export interface DeleteSessionResult {
  sid: string;
  family: 'claude-code' | 'opencode' | 'codex';
  /** 删掉了哪几样，服务端写好的人话，原样摆出来。 */
  removed: string[];
  warnings: string[];
}

/** 删不掉时服务端回的那一下。状态码要留着，见 ``errorText``。 */
interface DeleteFailure {
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

interface DeleteSessionButtonProps {
  session: WorkbenchSession;
  /** 真删掉之后调它——清单要重取，中栏要退回清单态。 */
  onDeleted?: (result: DeleteSessionResult) => void;
}

export default function DeleteSessionButton({ session, onDeleted }: DeleteSessionButtonProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<DeleteFailure | null>(null);

  const close = () => {
    if (busy) return;
    setOpen(false);
    setFailure(null);
  };

  /** 删不动时摆哪句话。 */
  const errorText = (failure: DeleteFailure): string => {
    // 这两档由状态码定死，换成我们自己的说法。服务端那两句是中文写死的，英文界面上摆着
    // 一段中文等于没说；而且"本机已经没有了""还在跑"这两件事人不需要再读一遍解释。
    if (failure.status === 404) return t('workbench.delete.gone');
    if (failure.status === 409) return t('workbench.delete.running');
    // 其余（引擎不认这场、没装那个引擎、盘写不进去）照搬服务端那句话：
    // 拒绝的理由只有它知道，我们转述一次就多一层失真。
    return failure.detail;
  };

  const confirm = () => {
    setBusy(true);
    setFailure(null);
    void deleteWorkbenchSession(session.session_id)
      .then((result) => {
        setOpen(false);
        onDeleted?.(result);
      })
      .catch((e: unknown) => {
        // 失败就留在弹窗里：拒绝的理由多半是"这一场还在跑"，人正好接着去按「关闭 tmux 会话」。
        if (e instanceof DeleteSessionError) setFailure({ status: e.status, detail: e.message });
        else setFailure({ status: 0, detail: e instanceof Error ? e.message : String(e) });
      })
      .finally(() => setBusy(false));
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={t('workbench.delete.action')}
        aria-label={t('workbench.delete.action')}
        data-testid="session-delete"
        className="flex shrink-0 items-center justify-center rounded border border-border-color p-1.5 text-text-muted transition-colors hover:border-accent-error/40 hover:text-accent-error"
      >
        <Trash2 size={13} strokeWidth={1.5} />
      </button>

      <Modal
        isOpen={open}
        onClose={close}
        title={t('workbench.delete.title')}
        footer={
          <>
            <button
              type="button"
              onClick={close}
              disabled={busy}
              className="flex-1 rounded-[8px] px-3 py-1.5 text-[13px] text-text-secondary transition-colors duration-200 hover:bg-bg-hover disabled:opacity-60"
            >
              {t('workbench.delete.cancel')}
            </button>
            <button
              type="button"
              onClick={confirm}
              disabled={busy}
              data-testid="session-delete-confirm"
              className="flex flex-1 items-center justify-center gap-1.5 rounded-[8px] bg-accent-error px-3 py-1.5 text-[13px] font-medium text-[var(--text-on-accent)] transition-opacity duration-200 hover:opacity-90 disabled:opacity-60"
            >
              {busy ? <Loader2 size={13} strokeWidth={1.5} className="animate-spin" /> : null}
              {busy ? t('workbench.delete.busy') : t('workbench.delete.ok')}
            </button>
          </>
        }
      >
        <div className="space-y-2">
          {/* 先摆出删的是哪一场。左栏一行行挨着看，点错一行是常有的事。 */}
          <div className="rounded-[8px] bg-bg-subtle px-3 py-2">
            <p className="truncate text-[13px] font-medium text-text-primary">{session.title}</p>
            <p className="truncate font-mono text-[11px] text-text-muted">
              {session.session_id}
            </p>
            <p className="truncate font-mono text-[11px] text-text-dim">{session.directory}</p>
          </div>

          {/* 删之前三句话，一句一个职责：动的是哪一份、删完会怎样、能不能反悔。 */}
          <p className="text-[13px] leading-[1.6] text-text-secondary">
            {t('workbench.delete.what', {
              engine: t(`workbench.family.${session.family}`, { defaultValue: session.family }),
            })}
          </p>
          <p className="text-[13px] leading-[1.6] text-text-secondary">
            {t('workbench.delete.effect')}
          </p>
          <p className="text-[13px] leading-[1.6] text-accent-warning">
            {t('workbench.delete.irreversible')}
          </p>

          {failure ? (
            <div
              data-testid="session-delete-error"
              className="rounded-[8px] bg-bg-subtle px-3 py-2 text-[12px] leading-[1.6] text-accent-error"
            >
              <span className="break-words">{errorText(failure)}</span>
            </div>
          ) : null}
        </div>
      </Modal>
    </>
  );
}
