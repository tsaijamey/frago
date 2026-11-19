/**
 * SessionChildrenBar — 会话详情页顶部的「启动来源、派生子会话与运行中子进程」状态条。
 *
 * 解决「详情页看着安静/空着、实际后台仍有子进程或子会话在跑」造成的误判：
 * - 展示当前会话自己由谁启动（若它是 worker / 分支 / 交接 / 定时任务）；
 * - 展示由本会话（或其子会话）派生的全部子会话与活跃 OS 子进程（含 `claude --resume` 子进程）；
 * - 明确标明「是谁起的（launched_by_label）」「是什么」「现在是否还在跑」。
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  Cpu,
  GitBranch,
  GitFork,
  Terminal,
} from 'lucide-react';
import type {
  SessionChildProcess,
  SessionChildSession,
  SessionChildrenResponse,
} from '@/types/api';

export interface SessionChildrenBarProps {
  data: SessionChildrenResponse | null;
  onSelectSession?: (sessionId: string) => void;
}

function cleanCommandPreview(raw: string): string {
  return (raw || '').replace(/\\012/g, ' ').replace(/\s+/g, ' ').trim();
}

function statusMeta(
  status: SessionChildSession['status'],
  t: (k: string, opts?: Record<string, unknown>) => string
): { label: string; textCls: string; dotCls: string; pillCls: string } {
  switch (status) {
    case 'running':
      return {
        label: t('workbench.children.status.running'),
        textCls: 'text-accent-primary',
        dotCls: 'bg-accent-primary animate-pulse',
        pillCls: 'border-border-color bg-bg-card text-accent-primary',
      };
    case 'delivering':
      return {
        label: t('workbench.children.status.delivering'),
        textCls: 'text-accent-warning',
        dotCls: 'bg-accent-warning',
        pillCls:
          'border-transparent bg-accent-warning-10 text-accent-warning [box-shadow:inset_0_0_0_1px_var(--accent-warning-border)]',
      };
    case 'error':
      return {
        label: t('workbench.children.status.error'),
        textCls: 'text-accent-error',
        dotCls: 'bg-accent-error',
        pillCls: 'border-border-color bg-bg-card text-accent-error',
      };
    case 'done':
      return {
        label: t('workbench.children.status.done'),
        textCls: 'text-text-muted',
        dotCls: 'bg-text-dim',
        pillCls: 'border-border-color bg-bg-card text-text-muted',
      };
    default:
      return {
        label: t('workbench.children.status.idle'),
        textCls: 'text-text-muted',
        dotCls: 'bg-text-dim',
        pillCls: 'border-border-color bg-bg-card text-text-muted',
      };
  }
}

export default function SessionChildrenBar({
  data,
  onSelectSession,
}: SessionChildrenBarProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [userToggledSid, setUserToggledSid] = useState<string | null>(null);

  const sessionId = data?.session_id ?? null;
  const hasRunning = Boolean(data?.summary?.has_running);

  // 有运行中任务时默认展开，确保用户无需额外点击就能立刻看到正在跑的子进程/子会话；
  // 切换会话或用户手动收起后尊重用户操作。
  useEffect(() => {
    if (!sessionId) {
      setExpanded(false);
      setUserToggledSid(null);
      return;
    }
    if (userToggledSid !== sessionId) {
      setExpanded(hasRunning);
    }
  }, [sessionId, hasRunning, userToggledSid]);

  if (!data || !data.summary) return null;

  const {
    launched_by: launchedBy,
    summary,
    child_sessions: childSessions = [],
    child_processes: childProcesses = [],
  } = data;
  const totalItems = childSessions.length + childProcesses.length;
  const hasContent = Boolean(launchedBy || totalItems > 0 || summary.host_alive);
  if (!hasContent) return null;

  const activeCount =
    summary.running_children + summary.delivering_children + summary.running_processes;

  const handleToggle = () => {
    if (sessionId) setUserToggledSid(sessionId);
    setExpanded((v) => !v);
  };

  return (
    <section
      data-testid="session-children-bar"
      data-has-running={summary.has_running ? 'true' : 'false'}
      className="shrink-0 border-b border-border-color bg-bg-secondary px-4 py-2 text-[12px]"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          {summary.has_running ? (
            <span
              data-testid="session-children-running-banner"
              className="inline-flex items-center gap-1.5 font-medium text-accent-primary"
            >
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent-primary"
              />
              <span>{t('workbench.children.runningBanner', { count: activeCount })}</span>
            </span>
          ) : summary.host_alive && totalItems === 0 ? (
            <span
              data-testid="session-children-host-alive"
              className="inline-flex items-center gap-1.5 font-medium text-accent-primary"
            >
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent-primary"
              />
              <span>{t('workbench.children.hostAlive')}</span>
            </span>
          ) : totalItems > 0 ? (
            <span
              data-testid="session-children-history-summary"
              className="inline-flex items-center gap-1.5 text-text-secondary"
            >
              <GitFork size={13} strokeWidth={1.5} className="shrink-0 text-text-muted" />
              <span>{t('workbench.children.historySummary', { count: totalItems })}</span>
            </span>
          ) : null}

          {launchedBy ? (
            <span
              data-testid="session-launched-by"
              className="inline-flex min-w-0 items-center gap-1 rounded-[6px] border border-border-color bg-bg-card px-2 py-0.5 text-[11px] text-text-secondary"
            >
              <GitBranch size={12} strokeWidth={1.5} className="shrink-0 text-text-muted" />
              <span className="truncate">{launchedBy.label}</span>
              {launchedBy.session_id && onSelectSession ? (
                <button
                  type="button"
                  data-testid="session-launched-by-open"
                  onClick={() => onSelectSession(launchedBy.session_id!)}
                  title={launchedBy.title ?? launchedBy.session_id}
                  className="inline-flex shrink-0 items-center gap-0.5 font-medium text-text-primary hover:underline"
                >
                  <span>{t('workbench.children.openSession')}</span>
                  <ArrowUpRight size={11} strokeWidth={1.5} />
                </button>
              ) : null}
            </span>
          ) : null}
        </div>

        {totalItems > 0 ? (
          <button
            type="button"
            data-testid="session-children-toggle"
            aria-expanded={expanded}
            onClick={handleToggle}
            className="inline-flex shrink-0 items-center gap-1 rounded-[6px] border border-border-color bg-bg-card px-2 py-0.5 text-[11px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
          >
            {expanded ? (
              <ChevronDown size={12} strokeWidth={1.5} />
            ) : (
              <ChevronRight size={12} strokeWidth={1.5} />
            )}
            <span>
              {expanded ? t('workbench.children.collapse') : t('workbench.children.expand')}
            </span>
            <span className="font-mono tabular-nums text-text-muted">{totalItems}</span>
          </button>
        ) : null}
      </div>

      {expanded && totalItems > 0 ? (
        <div
          data-testid="session-children-list"
          className="mt-2 max-h-[220px] space-y-2 overflow-y-auto pr-0.5"
        >
          {childProcesses.length > 0 ? (
            <div className="space-y-1">
              <div className="flex items-center gap-1 text-[11px] font-medium text-text-muted">
                <Cpu size={12} strokeWidth={1.5} />
                <span>{t('workbench.children.processesSection')}</span>
                <span className="font-mono tabular-nums">{childProcesses.length}</span>
              </div>
              <div className="space-y-1">
                {childProcesses.map((proc: SessionChildProcess) => (
                  <div
                    key={`${proc.pid}-${proc.ppid}`}
                    data-testid="child-process-row"
                    data-running={proc.is_running ? 'true' : 'false'}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-[6px] border border-border-color bg-bg-card px-2.5 py-1.5 text-[11px]"
                  >
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <span className="inline-flex shrink-0 items-center gap-1 font-medium text-accent-primary">
                          <span
                            aria-hidden="true"
                            className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent-primary"
                          />
                          <span>{t('workbench.children.status.running')}</span>
                        </span>
                        <span className="shrink-0 font-mono tabular-nums text-text-muted">
                          PID {proc.pid}
                        </span>
                        {proc.elapsed ? (
                          <span className="shrink-0 font-mono tabular-nums text-text-dim">
                            · {proc.elapsed}
                          </span>
                        ) : null}
                        <span
                          title={proc.command}
                          className="min-w-0 flex-1 truncate font-mono text-text-primary"
                        >
                          {cleanCommandPreview(proc.command)}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5 text-text-muted">
                        <Terminal size={11} strokeWidth={1.5} className="shrink-0" />
                        <span>{proc.launched_by_label}</span>
                        <span>·</span>
                        <span>
                          {t(`workbench.children.kind.${proc.kind}`, { defaultValue: proc.kind })}
                        </span>
                      </div>
                    </div>
                    {proc.linked_session_id && onSelectSession ? (
                      <button
                        type="button"
                        data-testid={`open-linked-session-${proc.linked_session_id}`}
                        onClick={() => onSelectSession(proc.linked_session_id!)}
                        className="inline-flex shrink-0 items-center gap-0.5 rounded-[5px] border border-border-color px-1.5 py-0.5 text-[11px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                      >
                        <span>{t('workbench.children.openSession')}</span>
                        <ArrowUpRight size={11} strokeWidth={1.5} />
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {childSessions.length > 0 ? (
            <div className="space-y-1">
              <div className="flex items-center gap-1 text-[11px] font-medium text-text-muted">
                <GitFork size={12} strokeWidth={1.5} />
                <span>{t('workbench.children.sessionsSection')}</span>
                <span className="font-mono tabular-nums">{childSessions.length}</span>
              </div>
              <div className="space-y-1">
                {childSessions.map((child: SessionChildSession) => {
                  const meta = statusMeta(child.status, t);
                  return (
                    <div
                      key={child.session_id}
                      data-testid="child-session-row"
                      data-session-id={child.session_id}
                      data-running={child.is_running ? 'true' : 'false'}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-[6px] border border-border-color bg-bg-card px-2.5 py-1.5 text-[11px]"
                    >
                      <div className="min-w-0 flex-1 space-y-0.5">
                        <div className="flex min-w-0 items-center gap-1.5">
                          <span
                            data-testid="child-session-status"
                            className={`inline-flex shrink-0 items-center gap-1 rounded-[4px] border px-1.5 py-0 font-medium ${meta.pillCls}`}
                          >
                            <span
                              aria-hidden="true"
                              className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dotCls}`}
                            />
                            <span>{meta.label}</span>
                          </span>
                          <span
                            title={child.title}
                            className="min-w-0 flex-1 truncate font-medium text-text-primary"
                          >
                            {child.title}
                          </span>
                          <span className="shrink-0 font-mono text-text-muted">
                            {child.family}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5 text-text-muted">
                          <span data-testid="child-session-launcher">
                            {child.launched_by_label}
                          </span>
                          <span>·</span>
                          <span>
                            {t(`workbench.children.kind.${child.relation_kind}`, {
                              defaultValue: child.relation_kind,
                            })}
                          </span>
                          {child.tmux_name ? (
                            <>
                              <span>·</span>
                              <span className="font-mono">{child.tmux_name}</span>
                            </>
                          ) : null}
                        </div>
                      </div>
                      {onSelectSession ? (
                        <button
                          type="button"
                          data-testid={`open-child-session-${child.session_id}`}
                          onClick={() => onSelectSession(child.session_id)}
                          className="inline-flex shrink-0 items-center gap-0.5 rounded-[5px] border border-border-color px-1.5 py-0.5 text-[11px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                        >
                          <span>{t('workbench.children.openSession')}</span>
                          <ArrowUpRight size={11} strokeWidth={1.5} />
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
