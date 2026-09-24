/**
 * SendProgress — 一句话的步骤链：`✓ On its way › ✓ In the session › ✓ Picked up 13:04:52`。
 *
 * 三处共用这一个组件：输入框上方的待发气泡、记录流里那句话下面、以及「要人拍板」卡片
 * 点选后发出的答复。共用一个，步骤名与画法才不会各走各的。
 *
 * 两条纪律：
 *
 * 1. **只画已经发生的几步。** 还没发生的步骤不预告，也不出百分比与进度条——工作台的
 *    全域禁令。
 * 2. **时刻只标在最后一步上**，保证一行放得下；前几步的时刻悬停可见。答完之后整串收成
 *    一句「✓ Answered in 52 s」（插话是「✓ Folded in › ✓ Answered」）。
 */

import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { formatClock, formatDuration } from './RecordCard';
import type { SendStep, SendTrail } from '@/hooks/useWorkbenchRecords';

/** 两条路径各自的步骤顺序。失败只接在 On its way 后面。 */
const IDLE_CHAIN: SendStep[] = ['on_its_way', 'in_the_session', 'picked_up', 'answered'];
const MID_TURN_CHAIN: SendStep[] = ['on_its_way', 'queued', 'folded_in', 'answered'];

export const STEP_LABEL_KEY: Record<SendStep, string> = {
  on_its_way: 'workbench.progress.onItsWay',
  in_the_session: 'workbench.progress.inTheSession',
  queued: 'workbench.progress.queued',
  picked_up: 'workbench.progress.pickedUp',
  folded_in: 'workbench.progress.foldedIn',
  answered: 'workbench.progress.answered',
  failed: 'workbench.progress.failed',
};

/** 这份进度按顺序走过的步骤。只列 `steps` 里有键的。 */
export function stepsTaken(trail: SendTrail): SendStep[] {
  if (trail.steps.failed !== undefined) {
    return (['on_its_way', 'failed'] as SendStep[]).filter((s) => trail.steps[s] !== undefined);
  }
  const chain = trail.midTurn ? MID_TURN_CHAIN : IDLE_CHAIN;
  return chain.filter((s) => trail.steps[s] !== undefined);
}

export default function SendProgress({
  trail,
  className = '',
}: {
  trail: SendTrail;
  className?: string;
}) {
  const { t } = useTranslation();
  const taken = stepsTaken(trail);
  if (!taken.length) return null;
  const title = taken
    .map((s) => `${t(STEP_LABEL_KEY[s])} ${formatClock(trail.steps[s] ?? 0)}`)
    .join(' · ');

  let shown: SendStep[] = taken;
  let answeredIn = '';
  const answeredAt = trail.steps.answered;
  if (answeredAt !== undefined) {
    // 答完了：闲着那一路收成一句带耗时的话，插话留下「并进去了」那一步
    if (trail.midTurn) {
      shown = taken.filter((s) => s === 'folded_in' || s === 'answered');
    } else {
      shown = ['answered'];
      answeredIn = formatDuration(answeredAt - (trail.steps.on_its_way ?? answeredAt));
    }
  }
  const last = shown[shown.length - 1];

  return (
    <p
      data-testid="send-progress"
      data-step={last}
      title={title}
      className={`flex min-w-0 flex-wrap items-center gap-x-1 text-[11px] text-text-muted ${className}`}
    >
      {shown.map((step, i) => {
        const failed = step === 'failed';
        return (
          <Fragment key={step}>
            {i > 0 ? <span aria-hidden className="text-text-dim">›</span> : null}
            <span className={`inline-flex items-center gap-1 ${failed ? 'text-accent-error' : ''}`}>
              <span aria-hidden>{failed ? '✕' : '✓'}</span>
              <span className={step === last ? 'text-text-secondary' : ''}>
                {answeredIn && step === 'answered'
                  ? t('workbench.progress.answeredIn', { duration: answeredIn })
                  : t(STEP_LABEL_KEY[step])}
              </span>
              {step === last && !answeredIn ? (
                <span className="font-mono text-text-dim">{formatClock(trail.steps[step] ?? 0)}</span>
              ) : null}
            </span>
          </Fragment>
        );
      })}
    </p>
  );
}
