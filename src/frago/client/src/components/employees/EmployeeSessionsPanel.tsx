/**
 * EmployeeSessionsPanel — 选中员工的名下全部会话面板（下半区工作区）。
 *
 * - 上下文头栏：岗位名 + 分段筛选（全部/进行中/已结束；总数为 0 时隐藏）
 *   + 次级「岗位详情」按钮 + 全屏唯一实心品牌绿「+ 新建会话」主动作按钮。
 * - 会话列表：状态胶囊（运行中 / 待拍板 / 报错 / 已完成）、标题、摘要、最近活跃时间、
 *   工作目录简名、内核名、一键「进入会话 →」；支持 has_more 增量加载与 0 会话克制空态。
 */

import type { RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Loader2, Pencil, Plus, RotateCw } from 'lucide-react';
import type { EmployeePost } from '@/hooks/useEmployees';
import type { EmployeeSessionFilter } from '@/hooks/useEmployeeSessions';
import { activityTs, type SessionFamily, type WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import { FAMILY_ICON, shortAge } from '@/components/sessionWorkbench/SessionItem';
import { withTilde } from '@/components/sessionWorkbench/filePaths';
import { stripTextQuoteBlocks } from '@/utils/textQuoteBlocks';
import { stripWebBridgeContext } from '@/utils/webBridgeContext';
import { kernelLabel } from './employeeMeta';

function formatExactTime(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function sessionFamilyLabel(family: SessionFamily | string): string {
  if (family in FAMILY_ICON) {
    return FAMILY_ICON[family as SessionFamily].label;
  }
  return kernelLabel(family);
}

function isSessionRunning(s: WorkbenchSession): boolean {
  return (
    s.status === 'running' ||
    s.lifecycle_state === 'running' ||
    s.lifecycle_state === 'queued' ||
    s.lifecycle_state === 'awaiting_input'
  );
}

function isSessionError(s: WorkbenchSession): boolean {
  return s.status === 'error' || s.lifecycle_state === 'error';
}

function shortDirLabel(dir: string): string {
  const clean = withTilde(dir || '');
  if (!clean) return '~';
  return clean;
}

export interface EmployeeSessionsPanelProps {
  employee: EmployeePost | null;
  sessions: WorkbenchSession[];
  total: number;
  activeCount: number;
  completedCount: number;
  hasMore: boolean;
  filter: EmployeeSessionFilter;
  onFilterChange: (next: EmployeeSessionFilter) => void;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  onRetry: () => void;
  onLoadMore: () => void;
  onEditEmployee: (post: EmployeePost) => void;
  onLaunchSession: (post: EmployeePost) => void;
  onOpenSession: (sessionId: string) => void;
  firstEnterButtonRef?: RefObject<HTMLButtonElement>;
}

export default function EmployeeSessionsPanel({
  employee,
  sessions,
  total,
  activeCount,
  completedCount,
  hasMore,
  filter,
  onFilterChange,
  loading,
  loadingMore,
  error,
  onRetry,
  onLoadMore,
  onEditEmployee,
  onLaunchSession,
  onOpenSession,
  firstEnterButtonRef,
}: EmployeeSessionsPanelProps) {
  const { t } = useTranslation();

  if (!employee) return null;

  const totalAll = activeCount + completedCount;
  const remaining = Math.max(0, total - sessions.length);

  return (
    <section
      className="roster-panel"
      aria-label={t('employees.sessions.panelAria')}
      data-testid="employee-sessions-panel"
    >
      <div className="roster-inner">
        <div className="roster-head">
          <div className="roster-head-left">
            <h2 className="roster-title" data-testid="employee-sessions-title">
              {t('employees.sessions.titleOf', { name: employee.title })}
            </h2>

            {totalAll > 0 ? (
              <div
                className="emp-seg"
                role="group"
                aria-label={t('employees.sessions.filterAria')}
                data-testid="employee-sessions-filter"
              >
                <button
                  type="button"
                  className={`emp-seg-btn ${filter === 'all' ? 'on' : ''}`}
                  data-testid="session-filter-all"
                  onClick={() => onFilterChange('all')}
                >
                  {t('employees.sessions.filterAll', { n: totalAll })}
                </button>
                <button
                  type="button"
                  className={`emp-seg-btn ${filter === 'active' ? 'on' : ''}`}
                  data-testid="session-filter-active"
                  onClick={() => onFilterChange('active')}
                >
                  {t('employees.sessions.filterActive', { n: activeCount })}
                </button>
                <button
                  type="button"
                  className={`emp-seg-btn ${filter === 'completed' ? 'on' : ''}`}
                  data-testid="session-filter-completed"
                  onClick={() => onFilterChange('completed')}
                >
                  {t('employees.sessions.filterCompleted', { n: completedCount })}
                </button>
              </div>
            ) : null}
          </div>

          <div className="roster-actions">
            <button
              type="button"
              className="emp-btn"
              onClick={() => onEditEmployee(employee)}
              data-testid="employee-edit-btn"
            >
              <Pencil size={13} strokeWidth={1.5} />
              {t('employees.sessions.editPost')}
            </button>

            <button
              type="button"
              className="emp-btn emp-btn-primary"
              onClick={() => onLaunchSession(employee)}
              data-testid="employee-launch-btn"
            >
              <Plus size={14} strokeWidth={1.8} />
              {t('employees.sessions.newSession')}
            </button>
          </div>
        </div>

        <div className="session-list" data-testid="employee-sessions-list">
          {error ? (
            <div
              className="mt-2 flex items-center justify-between gap-3 rounded-[10px] border border-accent-error-border bg-accent-error-10 px-3 py-2.5 text-[12px] text-accent-error"
              data-testid="employee-sessions-error"
            >
              <span className="min-w-0 break-words">{error}</span>
              <button
                type="button"
                className="emp-btn shrink-0"
                onClick={onRetry}
              >
                <RotateCw size={12} strokeWidth={1.6} />
                {t('common.retry', { defaultValue: 'Retry' })}
              </button>
            </div>
          ) : loading && sessions.length === 0 ? (
            <p
              className="flex items-center gap-2 py-6 text-[12px] text-text-muted"
              data-testid="employee-sessions-loading"
            >
              <Loader2 size={14} className="cs-spin" />
              {t('common.loading')}
            </p>
          ) : sessions.length === 0 ? (
            <div className="emp-empty-state" data-testid="empty-sessions-state">
              <div className="emp-empty-title">
                {totalAll > 0
                  ? t('employees.sessions.filteredEmptyTitle')
                  : t('employees.sessions.emptyTitle')}
              </div>
              <div className="emp-empty-desc">
                {totalAll > 0
                  ? t('employees.sessions.filteredEmptyDesc')
                  : t('employees.sessions.emptyDesc')}
              </div>
            </div>
          ) : (
            <>
              {sessions.map((s, idx) => {
                const running = isSessionRunning(s);
                const errored = !running && isSessionError(s);
                const ts = activityTs(s);
                const relTime = shortAge(ts);
                const absTime = formatExactTime(ts);
                const cleanedTitle =
                  stripTextQuoteBlocks(stripWebBridgeContext(s.title)) || s.title;
                const summary =
                  (errored ? s.digest_stuck : null) ||
                  s.digest_done ||
                  t('employees.sessions.noSummary');
                const dirLabel = shortDirLabel(s.directory);
                const famLabel = sessionFamilyLabel(s.family);

                return (
                  <div
                    key={s.session_id}
                    className={`session-card ${running ? 'is-running' : ''} ${
                      errored ? 'is-error' : ''
                    }`}
                    data-testid={`employee-session-row-${s.session_id}`}
                  >
                    <div className="sc-main">
                      <div className="sc-top">
                        {running ? (
                          <span className="st-badge running">
                            <span className="live-pulse" />
                            {t('employees.sessions.running')}
                          </span>
                        ) : errored ? (
                          <span className="st-badge error">
                            {t('employees.sessions.error')}
                          </span>
                        ) : (
                          <span className="st-badge completed">
                            {t('employees.sessions.completed')}
                          </span>
                        )}

                        {s.need_decision ? (
                          <span className="st-badge decision">
                            {t('employees.sessions.needDecision')}
                          </span>
                        ) : null}

                        <span className="sc-title" title={cleanedTitle}>
                          {cleanedTitle}
                        </span>
                      </div>

                      <div className="sc-summary" title={summary}>
                        {summary}
                      </div>

                      <div className="sc-meta">
                        <span
                          title={
                            absTime
                              ? t('employees.sessions.exactTimeTitle', { time: absTime })
                              : undefined
                          }
                        >
                          {relTime || absTime}
                        </span>
                        <span>·</span>
                        <span title={t('employees.sessions.cwdTitle', { dir: s.directory })}>
                          {dirLabel}
                        </span>
                        <span>·</span>
                        <span>{famLabel}</span>
                      </div>
                    </div>

                    <button
                      ref={idx === 0 ? firstEnterButtonRef : undefined}
                      type="button"
                      className="enter-btn"
                      data-testid={`enter-session-${s.session_id}`}
                      onClick={() => onOpenSession(s.session_id)}
                    >
                      {t('employees.sessions.enter')}
                      <ArrowRight size={13} strokeWidth={1.6} />
                    </button>
                  </div>
                );
              })}

              {hasMore ? (
                <button
                  type="button"
                  className="load-more-btn"
                  disabled={loadingMore}
                  data-testid="employee-sessions-load-more"
                  onClick={onLoadMore}
                >
                  {loadingMore
                    ? t('employees.sessions.loadingMore')
                    : t('employees.sessions.loadMore', { n: remaining })}
                </button>
              ) : null}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
