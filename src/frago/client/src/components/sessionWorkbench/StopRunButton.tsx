/**
 * StopRunButton — 标题栏最右那个「结束运行」。
 *
 * 它结束的是这场会话此刻在 tmux 里的运行，不是把会话删掉：记录还在，还能翻，只是
 * 不能再往里发话。人认为这一场已经谈完了，按它把那具还占着几百兆内存的壳收掉。
 *
 * **按钮恒可按，不预先探测会话在不在跑。** 打开一场会话是高频动作，为了让按钮亮或灭
 * 而每次都去问一趟 tmux，代价摊在每一次点击上；这个按钮一天按不了几次。代价是按下去
 * 才知道有没有关到，那句话由服务端如实说出来（「这一场没在跑」照说，NEVER 装作关掉了）。
 *
 * 两段确认问的不是同一件事：第一下问「你真要结束吗」，本地问，不出门；出门后若服务端
 * 说屏上还在干活——那一下什么都没动——换成问「它还在干活，仍要打断吗」。
 *
 * **只剩图标，那一行放不下字。** 标题、工作目录和删除按钮都在同一行上，按钮带文字会
 * 把标题挤没。少了字就得让图标自己说话：等人再按一次的两档换成感叹号并染上警示色，
 * 在飞的那一档转圈，其余是电源符号。每一档的完整说法挂在悬停提示与无障碍名称上，
 * 屏幕阅读器听到的和从前写在按钮上的是同一句话。
 */

import { useTranslation } from 'react-i18next';
import { Loader2, Power, TriangleAlert } from 'lucide-react';
import { useStopSessionRun, type StopPhase } from '@/hooks/useStopSessionRun';

interface StopRunButtonProps {
  sessionId: string;
  /** 真关掉之后调它——左栏那一行的状态该跟着变。 */
  onStopped?: () => void;
}

/** 每一档该说什么。结局那三档说的是刚发生的事，几秒后自己退回起始档。 */
const LABEL_KEY: Record<StopPhase, string> = {
  idle: 'workbench.stopRun.action',
  confirming: 'workbench.stopRun.confirm',
  busyConfirming: 'workbench.stopRun.forceConfirm',
  stopping: 'workbench.stopRun.stopping',
  stopped: 'workbench.stopRun.stopped',
  absent: 'workbench.stopRun.absent',
  failed: 'workbench.stopRun.failed',
};

/** 要人再按一次的两档才染色——那两档按下去会有后果，其余只是在陈述。 */
const ASKING: StopPhase[] = ['confirming', 'busyConfirming'];

export default function StopRunButton({ sessionId, onStopped }: StopRunButtonProps) {
  const { t } = useTranslation();
  const { phase, error, press, cancel } = useStopSessionRun(sessionId, { onStopped });

  const asking = ASKING.includes(phase);
  const tone = asking
    ? 'border-accent-warning/40 bg-accent-warning-10 text-accent-warning'
    : 'border-border-color text-text-muted hover:text-text-primary';
  const label = t(LABEL_KEY[phase]);

  return (
    <button
      type="button"
      onClick={press}
      onBlur={cancel}
      disabled={phase === 'stopping'}
      // 失败那一档把服务端的说法挂在悬停上：这一行放不下一句完整的报错，但那句话不能
      // 丢——人得知道是没找到会话还是 tmux 拒了。其余档位悬停到的是当前这一档的说法。
      title={error || label}
      aria-label={label}
      className={`flex shrink-0 items-center justify-center rounded border p-1.5 transition-colors disabled:opacity-60 ${tone}`}
    >
      {phase === 'stopping' ? (
        <Loader2 size={13} strokeWidth={1.5} className="animate-spin" />
      ) : asking ? (
        <TriangleAlert size={13} strokeWidth={1.5} />
      ) : (
        <Power size={13} strokeWidth={1.5} />
      )}
    </button>
  );
}
