/**
 * 一条定时任务摊开看，外加四个动作：立即跑、启用/停用、编辑、删除。
 *
 * 支持两种呈现外壳：
 * - `workspace`（默认在工作台右侧主区渲染，与主原型 `#schedules/detail/:id` 1:1 对齐）
 * - `drawer`（兼容独立抽屉渲染与现有单测）
 *
 * 删除要点两下：第一下只把按钮换成「确认删除」，第二下才真删。定时任务删了没有
 * 回收站，点错一下，一条跑了几个月的任务就没了。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ExternalLink,
  Loader2,
  Pause,
  Pencil,
  Play,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  X,
  Zap,
} from 'lucide-react';
import type { ScheduleHistoryEntry, ScheduleItem } from '@/api';
import type { EmployeeItem } from '@/types/api';
import { usePageStore } from '@/stores/appStore';
import MarkdownContent from '@/components/ui/MarkdownContent';
import ScheduleStateIcon from './ScheduleStateIcon';
import {
  STATE_CHIP,
  cronRawText,
  empColorToken,
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

function HistoryRow({
  entry,
  workspace,
}: {
  entry: ScheduleHistoryEntry;
  workspace?: boolean;
}) {
  const { t } = useTranslation();
  const switchPage = usePageStore((s) => s.switchPage);
  const setWorkbenchSessionId = usePageStore((s) => s.setWorkbenchSessionId);
  const failed = entry.status === 'failed';

  const openSession = () => {
    if (!entry.session_id) return;
    setWorkbenchSessionId(entry.session_id);
    switchPage('session_workbench');
  };

  return (
    <li className={`${workspace ? 'sc-run-item' : 'sc-run'} ${failed ? 'sc-run--failed' : ''}`}>
      <div className={workspace ? 'sc-run-top' : 'sc-run-head'}>
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
      {entry.session_title && <div className="sc-run-title">{entry.session_title}</div>}
      {entry.error && <pre className="sc-run-error">{entry.error}</pre>}
      {entry.answer && (
        <div className="sc-run-answer">
          <div className="sc-run-answer-label">{t('schedules.history.answer')}</div>
          <MarkdownContent className="sc-run-answer-body" content={entry.answer} />
        </div>
      )}
      {entry.session_id && (
        <button type="button" className="sc-run-link w-fit" onClick={openSession}>
          <ExternalLink size={12} />
          <span>{t('schedules.history.openSession')}</span>
          <span className="opacity-75 text-xs font-mono">
            (
            {entry.session_id.length > 14
              ? `${entry.session_id.slice(0, 6)}...${entry.session_id.slice(-4)}`
              : entry.session_id}
            )
          </span>
        </button>
      )}
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
  /** 哪个动作正在等服务端回话；等的时候按钮锁住，免得连点。 */
  busy: 'run' | 'toggle' | 'remove' | null;
  onRun: () => void;
  onToggle: () => void;
  onRemove: () => void;
  onClose: () => void;
  onEdit?: () => void;
  employee?: EmployeeItem | null;
  variant?: 'drawer' | 'workspace';
}

export default function ScheduleDetail({
  schedule,
  busy,
  onRun,
  onToggle,
  onRemove,
  onClose,
  onEdit,
  employee,
  variant = 'drawer',
}: ScheduleDetailProps) {
  const { t } = useTranslation();
  const [confirmRemove, setConfirmRemove] = useState(false);
  const state = stateOf(schedule);
  const history = [...schedule.history].reverse();
  const hasParams = Object.keys(schedule.params ?? {}).length > 0;
  const switchPage = usePageStore((s) => s.switchPage);
  const setWorkbenchSessionId = usePageStore((s) => s.setWorkbenchSessionId);

  const effectiveSessionId =
    schedule.last_session_id ||
    schedule.last_run?.session_id ||
    (schedule.history.length > 0 ? schedule.history[schedule.history.length - 1].session_id : null);

  const openSession = (sid: string) => {
    setWorkbenchSessionId(sid);
    switchPage('session_workbench');
  };

  const isEmployee = schedule.kind === 'employee';
  const empId = schedule.employee_id ?? '';
  const empTitle = employee?.title || schedule.employee_title || empId;
  const empKernel = employee?.agent_kernel || schedule.employee_kernel;
  const empCwd = employee?.cwd || schedule.employee_cwd || schedule.cwd;
  const empColor = empColorToken(empId, employee?.color);
  const empMissing =
    isEmployee &&
    (Boolean(schedule.employee_missing) ||
      (Boolean(empId) && employee === null));

  const ownershipBadge = isEmployee ? (
    <span
      className="sc-chip emp"
      data-emp-color={empColor}
      data-testid="sc-ownership-badge"
    >
      <ShieldCheck size={11} />
      {t('schedules.detail.ownershipNative', { id: empId || '—' })}
    </span>
  ) : (
    <span className="sc-chip" data-testid="sc-ownership-badge">
      {t('schedules.detail.ownershipLegacy', {
        kind: t(`schedules.kind.${schedule.kind}`),
      })}
    </span>
  );

  const actionButtons = (
    <>
      <button
        type="button"
        className={variant === 'workspace' ? 'sc-btn primary' : 'sc-action sc-action--primary'}
        onClick={onRun}
        disabled={busy !== null || schedule.running}
        title={schedule.running ? t('schedules.actions.runBusy') : undefined}
        data-testid="sc-detail-run-btn"
      >
        {busy === 'run' ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
        {t('schedules.actions.run')}
      </button>
      <button
        type="button"
        className={variant === 'workspace' ? 'sc-btn' : 'sc-action'}
        onClick={onToggle}
        disabled={busy !== null}
        data-testid="sc-detail-toggle-btn"
      >
        {busy === 'toggle' ? (
          <Loader2 size={13} className="animate-spin" />
        ) : schedule.enabled ? (
          <Pause size={13} />
        ) : (
          <Play size={13} />
        )}
        {schedule.enabled ? t('schedules.actions.disable') : t('schedules.actions.enable')}
      </button>
      {onEdit && (
        <button
          type="button"
          className={variant === 'workspace' ? 'sc-btn' : 'sc-action'}
          onClick={onEdit}
          disabled={busy !== null}
          data-testid="sc-detail-edit-btn"
        >
          <Pencil size={13} />
          {t('schedules.detail.editBinding')}
        </button>
      )}
      {confirmRemove ? (
        <span className="sc-actions-danger flex items-center gap-1.5">
          <button
            type="button"
            className="ui-danger-pill"
            onClick={onRemove}
            disabled={busy !== null}
            data-testid="sc-detail-confirm-remove-btn"
          >
            {busy === 'remove' ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
            {t('schedules.actions.confirmRemove')}
          </button>
          <button
            type="button"
            className={variant === 'workspace' ? 'sc-btn' : 'sc-action'}
            onClick={() => setConfirmRemove(false)}
            disabled={busy !== null}
          >
            {t('common.cancel')}
          </button>
        </span>
      ) : (
        <button
          type="button"
          className={variant === 'workspace' ? 'sc-btn danger' : 'ui-danger-pill sc-actions-danger'}
          onClick={() => setConfirmRemove(true)}
          disabled={busy !== null}
          data-testid="sc-detail-remove-btn"
        >
          <Trash2 size={13} />
          {t('schedules.actions.remove')}
        </button>
      )}
    </>
  );

  const noticesBlock = (
    <>
      {empMissing && (
        <div className="sc-notice warn" data-testid="sc-detail-emp-missing">
          <TriangleAlert size={15} />
          <div className="flex-1 flex items-center justify-between gap-2 flex-wrap">
            <span>{t('schedules.detail.employeeMissing', { id: empId })}</span>
            {onEdit && (
              <button type="button" className="sc-btn warn sm" onClick={onEdit}>
                {t('schedules.detail.editBinding')}
              </button>
            )}
          </div>
        </div>
      )}
      {schedule.kind === 'command' && onEdit && (
        <div className="sc-notice warn" data-testid="sc-detail-command-notice">
          <TriangleAlert size={15} />
          <div className="flex-1 flex items-center justify-between gap-2 flex-wrap">
            <span>{t('schedules.detail.commandNotice')}</span>
            <button
              type="button"
              className="sc-btn warn sm"
              onClick={onEdit}
              data-testid="sc-switch-native-btn"
            >
              {t('schedules.detail.switchToNative')}
            </button>
          </div>
        </div>
      )}
    </>
  );

  const propsRows = (
    <>
      <Prop label={t('schedules.detail.status')}>
        <span className={`td-chip tdp-status-chip ${STATE_CHIP[state]}`}>
          <ScheduleStateIcon state={state} decorative />
          {t(`schedules.state.${state}`)}
        </span>
      </Prop>
      <Prop label={t('schedules.detail.kind')}>{t(`schedules.kind.${schedule.kind}`)}</Prop>
      {isEmployee && (
        <Prop label={t('schedules.detail.employeeLabel')}>
          <span className="sc-chip emp" data-emp-color={empColor}>
            @{empId || '—'}
          </span>
          {empTitle && empTitle !== empId && <span>{empTitle}</span>}
          {empKernel && <span className="sc-chip">{empKernel}</span>}
          {empMissing && (
            <span className="sc-chip warn">{t('schedules.state.failing')}</span>
          )}
        </Prop>
      )}
      {schedule.session_title_template && (
        <Prop label={t('schedules.detail.titleTemplate')}>
          <code className="text-[12px] font-mono break-all">
            {schedule.session_title_template}
          </code>
        </Prop>
      )}
      <Prop label={t('schedules.detail.frequency')}>
        <span>{frequencyText(schedule, t)}</span>
        {cronRawText(schedule, t) && <span className="sc-raw">{cronRawText(schedule, t)}</span>}
      </Prop>
      <Prop label={t('schedules.detail.timeout')}>{timeoutText(schedule, t)}</Prop>
      <Prop label={t('schedules.detail.nextRun')}>
        {schedule.enabled ? (
          formatTime(schedule.next_run_at)
        ) : (
          <span className="tdp-prop-muted">{t('schedules.state.disabled')}</span>
        )}
      </Prop>
      <Prop label={t('schedules.detail.lastRun')}>
        <div className="sc-last-run-wrap flex items-center gap-2 flex-wrap">
          <span>{formatTime(schedule.last_run_at)}</span>
          {effectiveSessionId && (
            <button
              type="button"
              className="sc-run-link inline-flex items-center gap-1 text-xs"
              onClick={() => openSession(effectiveSessionId)}
              title={t('schedules.history.openSession')}
            >
              <ExternalLink size={12} />
              <span>{t('schedules.history.openSession')}</span>
              <span className="opacity-75 text-xs font-mono">
                (
                {effectiveSessionId.length > 14
                  ? `${effectiveSessionId.slice(0, 6)}...${effectiveSessionId.slice(-4)}`
                  : effectiveSessionId}
                )
              </span>
            </button>
          )}
        </div>
      </Prop>
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
      {schedule.end_at && (
        <Prop label={t('schedules.detail.endAt')}>{formatTime(schedule.end_at)}</Prop>
      )}
      <Prop label={t('schedules.detail.createdAt')}>{formatTime(schedule.created_at)}</Prop>
      <Prop label={t('schedules.detail.notify')}>{notifyText(schedule, t)}</Prop>
    </>
  );

  const targetDetails = (
    <>
      <pre className="sc-target">{targetText(schedule) || '—'}</pre>
      {isEmployee && empCwd && (
        <div className="sc-run-meta">{t('schedules.detail.employeeInheritedCwd', { cwd: empCwd })}</div>
      )}
      {!isEmployee && schedule.kind !== 'recipe' && schedule.cwd && (
        <div className="sc-run-meta">{t('schedules.detail.cwd', { cwd: schedule.cwd })}</div>
      )}
      {schedule.kind === 'prompt' && (
        <>
          <div className="sc-run-meta">
            {schedule.instructions
              ? t('schedules.detail.instructions', { name: schedule.instructions })
              : t('schedules.detail.noInstructions')}
          </div>
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
    </>
  );

  if (variant === 'workspace') {
    return (
      <div className="sc-work-pane" data-testid="sc-detail-workspace">
        <div className="sc-work-in">
          <div className="sc-det-head">
            <div className="min-w-0 flex-1">
              <div className="sc-det-title">
                <ScheduleStateIcon state={state} decorative />
                <span>{schedule.name}</span>
                {ownershipBadge}
              </div>
              <div className="sc-det-id">{schedule.id}</div>
            </div>
            <div className="sc-det-acts">
              {actionButtons}
              <button
                type="button"
                className="sc-btn"
                onClick={onClose}
                aria-label={t('common.close')}
              >
                <X size={13} />
              </button>
            </div>
          </div>

          {noticesBlock}

          <section className="sc-sec-card">
            <div className="sc-sec-hd">
              <h3>{t('schedules.detail.status')}</h3>
              <span className="sub">{schedule.last_session_title || schedule.id}</span>
            </div>
            <div className="sc-sec-bd">
              <dl className="sc-props">{propsRows}</dl>
            </div>
          </section>

          <section className="sc-sec-card">
            <div className="sc-sec-hd">
              <h3>{t(`schedules.detail.target.${schedule.kind}`, { defaultValue: schedule.kind })}</h3>
            </div>
            <div className="sc-sec-bd">{targetDetails}</div>
          </section>

          {hasParams && (
            <section className="sc-sec-card">
              <div className="sc-sec-hd">
                <h3>{t('schedules.detail.params')}</h3>
              </div>
              <div className="sc-sec-bd">
                <pre className="sc-target">{JSON.stringify(schedule.params, null, 2)}</pre>
              </div>
            </section>
          )}

          <section className="sc-sec-card">
            <div className="sc-sec-hd">
              <h3>{t('schedules.history.title', { n: schedule.history.length })}</h3>
            </div>
            <div className="sc-sec-bd">
              {history.length === 0 ? (
                <p className="td-text">{t('schedules.history.empty')}</p>
              ) : (
                <ul className="sc-run-list">
                  {history.map((entry, i) => (
                    <HistoryRow
                      key={`${entry.triggered_at ?? ''}-${i}`}
                      entry={entry}
                      workspace
                    />
                  ))}
                </ul>
              )}
            </div>
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className="td-panel tdp-panel ui-drawer">
      <div className="td-head ui-drawer-head">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="td-title ui-drawer-title">{schedule.name}</h2>
            {ownershipBadge}
          </div>
          <div className="td-id">{schedule.id}</div>
        </div>
        <div className="ui-drawer-actions">
          <button
            type="button"
            className="td-close ui-icon-btn"
            onClick={onClose}
            aria-label={t('common.close')}
          >
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="ui-drawer-body tdp-drawer-body">
        {noticesBlock}

        <div className="sc-actions">{actionButtons}</div>

        <dl className="tdp-props">{propsRows}</dl>

        <div className="td-body">
          <Section title={t(`schedules.detail.target.${schedule.kind}`, { defaultValue: schedule.kind })}>
            {targetDetails}
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
    </div>
  );
}
