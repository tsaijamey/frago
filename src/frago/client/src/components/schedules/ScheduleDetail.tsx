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
import {
  STATE_CHIP,
  formatTime,
  frequencyText,
  notifyText,
  stateOf,
  targetText,
} from './scheduleMeta';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="td-section">
      <div className="td-section-title">{title}</div>
      {children}
    </div>
  );
}

function HistoryRow({ entry }: { entry: ScheduleHistoryEntry }) {
  const { t } = useTranslation();
  const failed = entry.status === 'failed';
  return (
    <li className={`sc-run ${failed ? 'sc-run--failed' : ''}`}>
      <div className="sc-run-head">
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
    <div className="td-panel">
      <div className="td-head">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`td-chip ${STATE_CHIP[state]}`}>{t(`schedules.state.${state}`)}</span>
            <span className="td-chip td-chip--normal">{t(`schedules.kind.${schedule.kind}`)}</span>
          </div>
          <h2 className="td-title">{schedule.name}</h2>
          <div className="td-id">{schedule.id}</div>
        </div>
        <button type="button" className="td-close" onClick={onClose} aria-label={t('common.close')}>
          <X size={16} />
        </button>
      </div>

      <div className="sc-actions">
        <button
          type="button"
          className="sc-action"
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
          <>
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
          </>
        ) : (
          <button
            type="button"
            className="sc-action sc-action--quiet"
            onClick={() => setConfirmRemove(true)}
            disabled={busy !== null}
          >
            <Trash2 size={14} />
            {t('schedules.actions.remove')}
          </button>
        )}
      </div>

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

        <Section title={t('schedules.detail.timing')}>
          <dl className="sc-facts">
            <dt>{t('schedules.detail.frequency')}</dt>
            <dd>{frequencyText(schedule, t)}</dd>
            <dt>{t('schedules.detail.nextRun')}</dt>
            <dd>{schedule.enabled ? formatTime(schedule.next_run_at) : t('schedules.state.disabled')}</dd>
            <dt>{t('schedules.detail.lastRun')}</dt>
            <dd>{formatTime(schedule.last_run_at)}</dd>
            <dt>{t('schedules.detail.lastSuccess')}</dt>
            <dd>{formatTime(schedule.last_success_at)}</dd>
            <dt>{t('schedules.detail.runCount')}</dt>
            <dd>{schedule.run_count}</dd>
            {schedule.consecutive_failures > 0 && (
              <>
                <dt>{t('schedules.detail.failures')}</dt>
                <dd className="sc-warn">{schedule.consecutive_failures}</dd>
              </>
            )}
            {schedule.start_at && (
              <>
                <dt>{t('schedules.detail.startAt')}</dt>
                <dd>{formatTime(schedule.start_at)}</dd>
              </>
            )}
            {schedule.end_at && (
              <>
                <dt>{t('schedules.detail.endAt')}</dt>
                <dd>{formatTime(schedule.end_at)}</dd>
              </>
            )}
            <dt>{t('schedules.detail.createdAt')}</dt>
            <dd>{formatTime(schedule.created_at)}</dd>
          </dl>
        </Section>

        <Section title={t('schedules.detail.notify')}>
          <p className="td-text">{notifyText(schedule, t)}</p>
        </Section>

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
