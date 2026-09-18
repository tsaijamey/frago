/**
 * 一条定时任务摊开看，外加三个动作：立即跑、启用/停用、删除。
 *
 * 清单那一行只放得下名字和状态；真要判断「这条任务到底有没有在干活」，靠的是执行
 * 记录——最近几次什么时候触发、成没成、为什么没通知。这些此前只有
 * `frago schedule history` 看得到，而且那里连失败原因都不印。
 *
 * 删除要点两下：第一下只把按钮换成「确认删除」，第二下才真删。定时任务删了没有
 * 回收站，点错一下，一条跑了几个月的任务就没了。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Pause, Play, Trash2, X, Zap } from 'lucide-react';
import type { ScheduleHistoryEntry, ScheduleItem } from '@/api';
import ScheduleStateIcon from './ScheduleStateIcon';
import {
  STATE_CHIP,
  formatTime,
  frequencyText,
  notifyText,
  stateOf,
  targetText,
  timeoutText,
} from './scheduleMeta';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="td-section">
      <div className="td-section-title">{title}</div>
      {children}
    </div>
  );
}

/** 属性表的一行：左边名字，右边值。 */
function Prop({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <dt className="tdp-prop-label">{label}</dt>
      <dd className={`tdp-prop-value ${className ?? ''}`}>{children}</dd>
    </>
  );
}

function HistoryRow({ entry }: { entry: ScheduleHistoryEntry }) {
  const { t } = useTranslation();
  const failed = entry.status === 'failed';
  return (
    <li className={`sc-run ${failed ? 'sc-run--failed' : ''}`}>
      <div className="sc-run-head">
        <ScheduleStateIcon
          state={failed ? 'failing' : entry.status === 'success' ? 'ok' : 'never'}
          decorative
        />
        <span className="sc-run-time">{formatTime(entry.triggered_at)}</span>
        <span className={`td-chip ${failed ? 'td-chip--high' : 'td-chip--done'}`}>
          {t(`schedules.runStatus.${entry.status ?? 'unknown'}`, {
            defaultValue: entry.status ?? '—',
          })}
        </span>
        {entry.manual && <span className="td-tag">{t('schedules.history.manual')}</span>}
        {entry.duration_ms != null && (
          <span className="sc-run-meta">{t('schedules.history.duration', { ms: entry.duration_ms })}</span>
        )}
        {entry.exit_code != null && entry.exit_code !== 0 && (
          <span className="sc-run-meta">{t('schedules.history.exitCode', { code: entry.exit_code })}</span>
        )}
      </div>
      {entry.error && <pre className="sc-run-error">{entry.error}</pre>}
      {entry.notify_reason && (
        <div className="sc-run-meta">
          {entry.notified
            ? t('schedules.history.notified', { status: entry.notify_status ?? '—' })
            : t('schedules.history.notNotified', { reason: entry.notify_reason })}
        </div>
      )}
    </li>
  );
}

interface ScheduleDetailProps {
  schedule: ScheduleItem;
  /** 哪个动作正在等服务端回话；等的时候三个按钮都锁住，免得连点。 */
  busy: 'run' | 'toggle' | 'remove' | null;
  onRun: () => void;
  onToggle: () => void;
  onRemove: () => void;
  onClose: () => void;
}

export default function ScheduleDetail({
  schedule,
  busy,
  onRun,
  onToggle,
  onRemove,
  onClose,
}: ScheduleDetailProps) {
  const { t } = useTranslation();
  const [confirmRemove, setConfirmRemove] = useState(false);
  const state = stateOf(schedule);
  const history = [...schedule.history].reverse();
  const hasParams = Object.keys(schedule.params ?? {}).length > 0;

  return (
    <div className="td-panel tdp-panel">
      <div className="td-head">
        <div className="min-w-0 flex-1">
          <h2 className="td-title">{schedule.name}</h2>
          <div className="td-id">{schedule.id}</div>
        </div>
        <button type="button" className="td-close" onClick={onClose} aria-label={t('common.close')}>
          <X size={16} />
        </button>
      </div>

      {/* 动作排序：立即跑是最常用的，实心放最前；启停跟在后面；删除推到最右端，
          跟常用动作隔开一段，手不容易顺势点到。 */}
      <div className="sc-actions">
        <button
          type="button"
          className="sc-action sc-action--primary"
          onClick={onRun}
          disabled={busy !== null || schedule.running}
          title={schedule.running ? t('schedules.actions.runBusy') : undefined}
        >
          {busy === 'run' ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
          {t('schedules.actions.run')}
        </button>
        <button type="button" className="sc-action" onClick={onToggle} disabled={busy !== null}>
          {busy === 'toggle' ? (
            <Loader2 size={14} className="animate-spin" />
          ) : schedule.enabled ? (
            <Pause size={14} />
          ) : (
            <Play size={14} />
          )}
          {schedule.enabled ? t('schedules.actions.disable') : t('schedules.actions.enable')}
        </button>
        {confirmRemove ? (
          <span className="sc-actions-danger">
            <button
              type="button"
              className="sc-action sc-action--danger"
              onClick={onRemove}
              disabled={busy !== null}
            >
              {busy === 'remove' ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              {t('schedules.actions.confirmRemove')}
            </button>
            <button
              type="button"
              className="sc-action"
              onClick={() => setConfirmRemove(false)}
              disabled={busy !== null}
            >
              {t('common.cancel')}
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="sc-action sc-action--quiet sc-actions-danger"
            onClick={() => setConfirmRemove(true)}
            disabled={busy !== null}
          >
            <Trash2 size={14} />
            {t('schedules.actions.remove')}
          </button>
        )}
      </div>

      {/* 「这条任务现在什么情况、什么时候跑、跑了几次、通知谁」排成一张两列表；
          执行内容和执行记录这类要细读的放在表下面。 */}
      <dl className="tdp-props">
        <Prop label={t('schedules.detail.status')}>
          <span className={`td-chip tdp-status-chip ${STATE_CHIP[state]}`}>
            <ScheduleStateIcon state={state} decorative />
            {t(`schedules.state.${state}`)}
          </span>
        </Prop>
        <Prop label={t('schedules.detail.kind')}>{t(`schedules.kind.${schedule.kind}`)}</Prop>
        <Prop label={t('schedules.detail.frequency')}>{frequencyText(schedule, t)}</Prop>
        <Prop label={t('schedules.detail.timeout')}>{timeoutText(schedule, t)}</Prop>
        <Prop label={t('schedules.detail.nextRun')}>
          {schedule.enabled ? (
            formatTime(schedule.next_run_at)
          ) : (
            <span className="tdp-prop-muted">{t('schedules.state.disabled')}</span>
          )}
        </Prop>
        <Prop label={t('schedules.detail.lastRun')}>{formatTime(schedule.last_run_at)}</Prop>
        <Prop label={t('schedules.detail.lastSuccess')}>{formatTime(schedule.last_success_at)}</Prop>
        <Prop label={t('schedules.detail.runCount')}>{schedule.run_count}</Prop>
        {schedule.consecutive_failures > 0 && (
          <Prop label={t('schedules.detail.failures')} className="sc-warn">
            {schedule.consecutive_failures}
          </Prop>
        )}
        {schedule.start_at && (
          <Prop label={t('schedules.detail.startAt')}>{formatTime(schedule.start_at)}</Prop>
        )}
        {schedule.end_at && <Prop label={t('schedules.detail.endAt')}>{formatTime(schedule.end_at)}</Prop>}
        <Prop label={t('schedules.detail.createdAt')}>{formatTime(schedule.created_at)}</Prop>
        <Prop label={t('schedules.detail.notify')}>{notifyText(schedule, t)}</Prop>
      </dl>

      <div className="td-body">
        <Section title={t(`schedules.detail.target.${schedule.kind}`, { defaultValue: schedule.kind })}>
          <pre className="sc-target">{targetText(schedule) || '—'}</pre>
          {schedule.kind !== 'recipe' && schedule.cwd && (
            <div className="sc-run-meta">{t('schedules.detail.cwd', { cwd: schedule.cwd })}</div>
          )}
          {schedule.kind === 'prompt' && (
            <>
              <div className="sc-run-meta">
                {schedule.instructions
                  ? t('schedules.detail.instructions', { name: schedule.instructions })
                  : t('schedules.detail.noInstructions')}
              </div>
              {/* 规则原文照印：它就是 CoreAgent 那边认的写法，翻译一遍反而对不上。 */}
              <div className="sc-run-meta">
                {schedule.allowed_tools.length > 0
                  ? t('schedules.detail.allowedTools', { list: schedule.allowed_tools.join(', ') })
                  : t('schedules.detail.allowedToolsAll')}
              </div>
              {schedule.disallowed_tools.length > 0 && (
                <div className="sc-run-meta">
                  {t('schedules.detail.disallowedTools', {
                    list: schedule.disallowed_tools.join(', '),
                  })}
                </div>
              )}
            </>
          )}
        </Section>

        {hasParams && (
          <Section title={t('schedules.detail.params')}>
            <pre className="sc-target">{JSON.stringify(schedule.params, null, 2)}</pre>
          </Section>
        )}

        <Section title={t('schedules.history.title', { n: schedule.history.length })}>
          {history.length === 0 ? (
            <p className="td-text">{t('schedules.history.empty')}</p>
          ) : (
            <ul className="sc-runs">
              {history.map((entry, i) => (
                <HistoryRow key={`${entry.triggered_at ?? ''}-${i}`} entry={entry} />
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}
