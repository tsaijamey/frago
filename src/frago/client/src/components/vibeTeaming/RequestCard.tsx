/**
 * 右栏「Your request」卡：我从右下框发给对方 agent 的一句话，此刻走到哪一步。
 *
 * **只画已经发生的和眼下这一步。** 还没发生的步骤名一个都不预告；推不出来就停在上一
 * 步（判据见 `teamRequest.ts` 的 `stepsFor`）。时刻只标最后一步，前几步悬停可见——一排
 * 三个时刻挤在一行里，人读到的是一串数字而不是进度。
 *
 * 右栏记录里真实转来的请求（对方会话里那条带核实行的用户发言）也画成这张卡：那是对方
 * 会话里的原样，前缀与核实行对我没有意义，我要看的是我说了什么、它走到哪了。
 */

import { useTranslation } from 'react-i18next';
import { Check, Clock } from 'lucide-react';
import { formatClock } from '@/components/sessionWorkbench/RecordCard';
import TeamAvatar from './TeamAvatar';
import type { RequestStep } from './teamRequest';

const STEP_LABEL: Record<RequestStep, string> = {
  sent: 'team.request.sent',
  delivered: 'team.request.delivered',
  on_it: 'team.request.onIt',
  waiting_owner: 'team.request.waitingOwner',
  replied: 'team.request.replied',
};

/** 这几步是「做完了」的终点，画成打勾而不是转圈。 */
const SETTLED: RequestStep[] = ['replied'];

export interface RequestCardProps {
  text: string;
  steps: { step: RequestStep; at: number | null }[];
  /** 卡底一行小字；没有就不画。 */
  foot?: string | null;
}

export default function RequestCard({ text, steps, foot }: RequestCardProps) {
  const { t } = useTranslation();
  const last = steps[steps.length - 1];
  const headAt = steps[0]?.at ?? last?.at ?? null;
  return (
    <div
      data-testid="team-request-card"
      data-step={last?.step}
      className="overflow-hidden rounded-[10px] border border-border-strong bg-bg-primary"
    >
      <div className="flex items-center gap-[7px] px-2.5 pt-[7px] text-[11px] text-text-muted">
        <TeamAvatar who="me" size="sm" />
        <b className="text-[12px] font-semibold text-text-primary">{t('team.request.title')}</b>
        <span>{t('team.request.via')}</span>
        {headAt ? (
          <span className="ml-auto font-mono text-[11px] text-text-dim">{formatClock(headAt)}</span>
        ) : null}
      </div>
      <div className="px-2.5 pb-2 pt-1">
        <p className="line-clamp-3 whitespace-pre-wrap text-[13px] leading-[1.55] [overflow-wrap:anywhere]">
          {text}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 border-t border-border-color bg-bg-hover px-2.5 py-[7px] text-[11px]">
        {steps.map(({ step, at }, i) => {
          const isLast = i === steps.length - 1;
          const now = isLast && !SETTLED.includes(step);
          const clock = at ? formatClock(at) : '';
          return (
            <span
              key={step}
              data-testid={`request-step-${step}`}
              title={!isLast && clock ? clock : undefined}
              className={`inline-flex items-center gap-[5px] whitespace-nowrap ${
                now
                  ? step === 'waiting_owner'
                    ? 'font-medium text-accent-warning'
                    : 'font-medium text-text-primary'
                  : 'text-text-secondary'
              }`}
            >
              {i > 0 ? <span className="mr-px text-text-dim">›</span> : null}
              {now ? <Clock size={12} /> : <Check size={12} />}
              {t(STEP_LABEL[step])}
              {isLast && clock ? (
                <span className="font-mono text-[11px] font-normal text-text-dim">{clock}</span>
              ) : null}
            </span>
          );
        })}
      </div>
      {foot ? <p className="bg-bg-hover px-2.5 pb-2 text-[11px] text-text-muted">{foot}</p> : null}
    </div>
  );
}
