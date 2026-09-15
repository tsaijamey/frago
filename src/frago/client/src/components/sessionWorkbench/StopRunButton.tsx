/**
 * StopRunButton — 标题栏右上角那个「关闭 tmux 会话」。
 *
 * 它关的是这场会话此刻在 tmux 里的那个会话，不是把会话删掉：记录还在，还能翻；之后再
 * 发消息，服务端会按续接命令重新拉起一个，上下文接得上。人认为这一场暂时谈完了，按它
 * 把那具还占着几百兆内存的壳收掉。
 *
 * **只在这一场开在 tmux 里时出现，由页面决定挂不挂。** 判据是会话清单每轮带来的
 * `in_tmux`，不额外问 tmux。清单只按名字对，飞书群、语音、命令行起的会话对不上，
 * 页面上就没有这个按钮——那些到左下角的 tmux 清点浮窗里关。
 *
 * **确认走弹窗，照删除按钮的做法。** 按钮上放不下字，从前「点一下变感叹号，再点一下」
 * 让人完全不知道会发生什么。弹窗说清三件事：关的是哪个 tmux 会话、记录与之后发消息会
 * 怎样、它还在干活时会被打断。服务端说屏上还在干活时那一下什么都没动，弹窗换成
 * 「仍要关闭」再问一次。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, SquareTerminal } from 'lucide-react';
import Modal from '@/components/ui/Modal';
import { useStopSessionRun } from '@/hooks/useStopSessionRun';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

interface StopRunButtonProps {
  session: WorkbenchSession;
  /** tmux 里这一场没了（关掉了，或本来就没了）之后调它——清单重取，按钮随之消失。 */
  onStopped?: () => void;
}

export default function StopRunButton({ session, onStopped }: StopRunButtonProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { phase, error, run, reset } = useStopSessionRun(session.session_id);
  const stopping = phase === 'stopping';

  const close = () => {
    if (stopping) return;
    setOpen(false);
    reset();
  };

  const confirm = () => {
    void run(phase === 'busy').then((next) => {
      if (next === 'stopped') {
        setOpen(false);
        reset();
        onStopped?.();
      } else if (next === 'absent') {
        // 清单那份旧了一轮：弹窗留着把话说完，清单照样重取，按钮下一眼就没了。
        onStopped?.();
      }
    });
  };

  const label = t('workbench.stopRun.action');

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={label}
        aria-label={label}
        data-testid="session-stop-run"
        className="flex shrink-0 items-center justify-center rounded border border-border-color p-1.5 text-text-muted transition-colors hover:border-accent-warning/40 hover:text-accent-warning"
      >
        <SquareTerminal size={13} strokeWidth={1.5} />
      </button>

      <Modal
        isOpen={open}
        onClose={close}
        title={t('workbench.stopRun.title')}
        footer={
          <>
            <button
              type="button"
              onClick={close}
              disabled={stopping}
              className="flex-1 rounded-[8px] px-3 py-1.5 text-[13px] text-text-secondary transition-colors duration-200 hover:bg-bg-hover disabled:opacity-60"
            >
              {phase === 'absent' ? t('workbench.stopRun.dismiss') : t('workbench.stopRun.cancel')}
            </button>
            {phase === 'absent' ? null : (
              <button
                type="button"
                onClick={confirm}
                disabled={stopping}
                data-testid="session-stop-run-confirm"
                className="flex flex-1 items-center justify-center gap-1.5 rounded-[8px] bg-accent-warning px-3 py-1.5 text-[13px] font-medium text-[var(--text-on-accent)] transition-opacity duration-200 hover:opacity-90 disabled:opacity-60"
              >
                {stopping ? <Loader2 size={13} strokeWidth={1.5} className="animate-spin" /> : null}
                {stopping
                  ? t('workbench.stopRun.stopping')
                  : phase === 'busy'
                    ? t('workbench.stopRun.forceOk')
                    : t('workbench.stopRun.ok')}
              </button>
            )}
          </>
        }
      >
        <div className="space-y-2">
          {/* 先摆出关的是哪一场、tmux 里叫什么。 */}
          <div className="rounded-[8px] bg-bg-subtle px-3 py-2">
            <p className="truncate text-[13px] font-medium text-text-primary">{session.title}</p>
            {session.tmux_name ? (
              <p className="truncate font-mono text-[11px] text-text-muted">
                tmux: {session.tmux_name}
              </p>
            ) : null}
            <p className="truncate font-mono text-[11px] text-text-dim">{session.directory}</p>
          </div>

          <p className="text-[13px] leading-[1.6] text-text-secondary">
            {t('workbench.stopRun.what')}
          </p>
          <p className="text-[13px] leading-[1.6] text-text-secondary">
            {t('workbench.stopRun.effect')}
          </p>
          <p
            data-testid="session-stop-run-interrupt"
            className={`text-[13px] leading-[1.6] ${phase === 'busy' ? 'font-medium text-accent-warning' : 'text-text-secondary'}`}
          >
            {phase === 'busy' ? t('workbench.stopRun.busyNow') : t('workbench.stopRun.interrupt')}
          </p>

          {phase === 'absent' || phase === 'failed' ? (
            <div
              data-testid="session-stop-run-result"
              className={`rounded-[8px] bg-bg-subtle px-3 py-2 text-[12px] leading-[1.6] ${phase === 'failed' ? 'text-accent-error' : 'text-text-secondary'}`}
            >
              <span className="break-words">
                {phase === 'absent'
                  ? t('workbench.stopRun.absent')
                  : t('workbench.stopRun.failed', { error: error ?? '' })}
              </span>
            </div>
          ) : null}
        </div>
      </Modal>
    </>
  );
}
