/**
 * 定时任务所处那一档的圆圈记号，清单行首和详情属性表共用。
 *
 * 与事务页的状态圆圈同一套画法：形状分得开五档（空虚线圈、转圈、打勾、感叹号、暂停），
 * 不靠颜色也认得出；旁边没有字的地方，档位名留给读屏和悬停提示。
 */

import { useTranslation } from 'react-i18next';
import { CircleAlert, CircleCheck, CircleDashed, CirclePause, LoaderCircle } from 'lucide-react';
import type { ScheduleState } from './scheduleMeta';

const ICONS = {
  disabled: CirclePause,
  running: LoaderCircle,
  failing: CircleAlert,
  ok: CircleCheck,
  never: CircleDashed,
} satisfies Record<ScheduleState, typeof CircleCheck>;

interface ScheduleStateIconProps {
  state: ScheduleState;
  /** 旁边已经写了档位名时传 true，免得读屏念两遍。 */
  decorative?: boolean;
}

export default function ScheduleStateIcon({ state, decorative = false }: ScheduleStateIconProps) {
  const { t } = useTranslation();
  const Icon = ICONS[state];
  const label = t(`schedules.state.${state}`);

  return (
    <span className={`tdp-status sc-state--${state}`} title={decorative ? undefined : label}>
      <Icon
        size={16}
        strokeWidth={2}
        aria-hidden="true"
        className={state === 'running' ? 'animate-spin' : undefined}
      />
      {!decorative && <span className="sr-only">{label}</span>}
    </span>
  );
}
