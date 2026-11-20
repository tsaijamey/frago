/**
 * ProgressChildrenSection — 「进展 (Progress)」面板内的 L0 上游来历微条与 L2 委派和后台执行区。
 *
 * 严格遵循方案 A 的五项前置修订条件：
 * - L0 上游来历微条：仅当存在 `launched_by` 时单行展示，无 `session_id` 时不出无效按钮，无上游零占位；
 * - L2 动态升降位：有活跃项或外部终端接入时置顶在 L1 锚点卡紧下方，纯历史委派时默认折叠为单行汇总条；
 * - 8 层派生树形重组：带环路保护、默认展开第 1 层与活跃/异常祖先路径、同级 >5 条已完结折留最近 3 条、视觉缩进第 4 层封顶；
 * - OS 运行中子进程：默认人话摘要 + 运行时长 + 来源归属，PID/完整命令行/tmux 名收进次级折叠；
 * - 全程严守双主题语义令牌，禁止脉冲闪烁、禁止红点、禁止单边粗竖线。
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  Clock,
  CornerDownRight,
  Cpu,
  GitBranch,
  GitFork,
  Terminal,
} from 'lucide-react';
import type {
  SessionChildProcess,
  SessionChildSession,
  SessionChildrenResponse,
  SessionLaunchedBy,
} from '@/types/api';
import {
  buildChildSessionTree,
  cleanCommandPreview,
  clipTitle,
  dedupChildSessions,
  describeProcessSource,
  formatElapsedHuman,
  partitionTreeSiblings,
  summarizeChildProcess,
  type ChildSessionTreeNode,
} from '@/utils/sessionChildrenTree';

export interface ProgressOriginStripProps {
  launchedBy: SessionLaunchedBy | null | undefined;
  onSelectSession?: (sessionId: string) => void;
}

export function ProgressOriginStrip({
  launchedBy,
  onSelectSession,
}: ProgressOriginStripProps) {
  const { t } = useTranslation();
  if (!launchedBy) return null;

  const isSchedule = launchedBy.origin === 'schedule' || launchedBy.source === 'local_ops';
  const Icon = isSchedule ? Clock : launchedBy.relation_kind === 'branch' ? GitBranch : GitFork;
  const fullTitle = launchedBy.title ? clipTitle(launchedBy.title, 60) : launchedBy.label;

  return (
    <div
      data-testid="progress-origin-strip"
      className="w-origin-strip"
    >
      <span data-testid="session-launched-by" className="w-origin-main">
        <Icon size={13} strokeWidth={1.5} className="w-origin-icon" />
        <span className="w-origin-label" title={fullTitle}>
          {launchedBy.label}
        </span>
      </span>
      {launchedBy.session_id && onSelectSession ? (
        <button
          type="button"
          data-testid="session-launched-by-open"
          onClick={() => onSelectSession(launchedBy.session_id!)}
          title={launchedBy.title ?? launchedBy.session_id}
          className="w-origin-btn"
        >
          <span>{t('workbench.children.originOpen')}</span>
          <ArrowUpRight size={11} strokeWidth={1.5} />
        </button>
      ) : null}
    </div>
  );
}

function childStatusMeta(
  status: SessionChildSession['status'],
  t: (k: string, opts?: Record<string, unknown>) => string
): { label: string; cls: string; dotCls: string } {
  switch (status) {
    case 'running':
      return {
        label: t('workbench.children.status.running'),
        cls: 'is-running',
        dotCls: 'd-run',
      };
    case 'delivering':
      return {
        label: t('workbench.children.status.delivering'),
        cls: 'is-delivering',
        dotCls: 'd-warn',
      };
    case 'awaiting_input':
      return {
        label: t('workbench.children.status.awaiting_input'),
        cls: 'is-waiting',
        dotCls: 'd-warn',
      };
    case 'error':
      return {
        label: t('workbench.children.status.error'),
        cls: 'is-error',
        dotCls: 'd-err',
      };
    case 'done':
      return {
        label: t('workbench.children.status.done'),
        cls: 'is-done',
        dotCls: 'd-muted',
      };
    default:
      return {
        label: t('workbench.children.status.idle'),
        cls: 'is-idle',
        dotCls: 'd-muted',
      };
  }
}

function formatShortAge(ms: number | null | undefined, isZh: boolean): string {
  if (!ms) return '';
  const diffMin = Math.max(0, Math.floor((Date.now() - ms) / 60_000));
  if (diffMin < 1) return isZh ? '刚刚' : 'just now';
  if (diffMin < 60) return isZh ? `${diffMin} 分钟前` : `${diffMin}m ago`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return isZh ? `${diffHour} 小时前` : `${diffHour}h ago`;
  const diffDay = Math.floor(diffHour / 24);
  return isZh ? `${diffDay} 天前` : `${diffDay}d ago`;
}

export interface ProgressDelegationSectionProps {
  data: SessionChildrenResponse | null | undefined;
  onSelectSession?: (sessionId: string) => void;
}

export function ProgressDelegationSection({
  data,
  onSelectSession,
}: ProgressDelegationSectionProps) {
  const { t, i18n } = useTranslation();
  const isZh = Boolean(i18n.language?.startsWith('zh'));

  const sessionId = data?.session_id ?? '';
  const summary = data?.summary;
  const dedupedSessions = useMemo(
    () => dedupChildSessions(data?.child_sessions ?? []),
    [data?.child_sessions]
  );
  const childProcesses = data?.child_processes ?? [];
  const hasExternal = Boolean(summary?.external_host_alive);
  const hasRunning = Boolean(summary?.has_running);
  const isActive = hasRunning || hasExternal;
  const totalItems = dedupedSessions.length + childProcesses.length;

  const [historyExpandedBySid, setHistoryExpandedBySid] = useState<Record<string, boolean>>({});
  const [nodeExpandedOverrides, setNodeExpandedOverrides] = useState<Record<string, boolean>>({});
  const [showAllFinishedMap, setShowAllFinishedMap] = useState<Record<string, boolean>>({});
  const [procDetailsOpen, setProcDetailsOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setNodeExpandedOverrides({});
    setShowAllFinishedMap({});
    setProcDetailsOpen({});
  }, [sessionId]);

  const treeNodes = useMemo(
    () => (sessionId ? buildChildSessionTree(sessionId, dedupedSessions) : []),
    [sessionId, dedupedSessions]
  );

  const childSessionById = useMemo(() => {
    const map = new Map<string, SessionChildSession>();
    for (const c of dedupedSessions) {
      map.set(c.session_id, c);
    }
    return map;
  }, [dedupedSessions]);

  const toggleHistoryExpanded = useCallback(() => {
    if (!sessionId) return;
    setHistoryExpandedBySid((prev) => ({
      ...prev,
      [sessionId]: !prev[sessionId],
    }));
  }, [sessionId]);

  const toggleNodeExpanded = useCallback(
    (node: ChildSessionTreeNode) => {
      const key = `${sessionId}:${node.session.session_id}`;
      setNodeExpandedOverrides((prev) => {
        const cur = key in prev ? prev[key] : node.defaultExpanded;
        return { ...prev, [key]: !cur };
      });
    },
    [sessionId]
  );

  const toggleFinishedSiblings = useCallback(
    (parentKey: string) => {
      const fullKey = `${sessionId}:${parentKey}`;
      setShowAllFinishedMap((prev) => ({
        ...prev,
        [fullKey]: !prev[fullKey],
      }));
    },
    [sessionId]
  );

  if (!data || !summary || (!hasExternal && totalItems === 0)) {
    return null;
  }

  const historyExpanded = Boolean(historyExpandedBySid[sessionId]);

  // 纯历史态（全部已结束且无外部终端接入）：默认折叠为单行汇总条
  if (!isActive && !historyExpanded) {
    return (
      <section
        data-testid="progress-delegation-section"
        data-mode="history-collapsed"
        className="w-delegation-collapsed"
      >
        <div className="w-delegation-collapsed-info" data-testid="progress-history-summary">
          <GitFork size={13} strokeWidth={1.5} className="w-delegation-icon" />
          <span>{t('workbench.children.historySummary', { count: totalItems })}</span>
        </div>
        <button
          type="button"
          data-testid="progress-delegation-toggle"
          aria-expanded={false}
          onClick={toggleHistoryExpanded}
          className="w-delegation-toggle-btn"
        >
          <span>{t('workbench.children.expand')}</span>
          <ChevronRight size={12} strokeWidth={1.5} />
        </button>
      </section>
    );
  }

  const renderSiblingList = (nodes: ChildSessionTreeNode[], parentKey: string) => {
    const partition = partitionTreeSiblings(nodes);
    const showAll = Boolean(showAllFinishedMap[`${sessionId}:${parentKey}`]);
    const listToRender = showAll ? nodes : partition.visibleNodes;

    return (
      <>
        {listToRender.map((node) => {
          const child = node.session;
          const meta = childStatusMeta(child.status, t);
          const nodeKey = `${sessionId}:${child.session_id}`;
          const isNodeExpanded =
            nodeKey in nodeExpandedOverrides
              ? nodeExpandedOverrides[nodeKey]
              : node.defaultExpanded;
          const indentPx = Math.max(0, node.visualDepth - 1) * 16;
          const displayTitle =
            child.title && child.title !== child.session_id
              ? child.title
              : child.prompt_head || child.session_id;
          const actorLabel = child.employee_id || child.family;
          const ageStr = formatShortAge(child.last_active_at ?? child.started_at, isZh);

          return (
            <div key={child.session_id} className="w-tree-branch">
              <div
                data-testid="child-session-row"
                data-session-id={child.session_id}
                data-depth={node.treeDepth}
                data-visual-depth={node.visualDepth}
                data-running={child.is_running ? 'true' : 'false'}
                data-status={child.status}
                style={{ paddingLeft: `${indentPx}px` }}
                className="w-tree-row"
              >
                <div className="w-tree-row-card">
                  <div className="w-tree-main">
                    {node.treeDepth > 1 ? (
                      <CornerDownRight
                        size={12}
                        strokeWidth={1.5}
                        aria-hidden="true"
                        className="w-tree-connector"
                      />
                    ) : null}
                    <span
                      data-testid="child-session-status"
                      className={`w-child-pill ${meta.cls}`}
                    >
                      <span aria-hidden="true" className={`w-dot ${meta.dotCls}`} />
                      <span>{meta.label}</span>
                    </span>
                    {node.treeDepth > 4 ? (
                      <span
                        data-testid="child-session-depth-tag"
                        className="w-depth-tag"
                      >
                        L{node.treeDepth}
                      </span>
                    ) : null}
                    <span className="w-tree-title" title={displayTitle}>
                      {displayTitle}
                    </span>
                  </div>

                  <div className="w-tree-actions">
                    {node.children.length > 0 ? (
                      <button
                        type="button"
                        data-testid={`tree-node-toggle-${child.session_id}`}
                        aria-expanded={isNodeExpanded}
                        onClick={() => toggleNodeExpanded(node)}
                        className="w-tree-fold-btn"
                      >
                        <span>
                          {t('workbench.children.nestedCount', { count: node.totalDescendants })}
                        </span>
                        {isNodeExpanded ? (
                          <ChevronDown size={11} strokeWidth={1.5} />
                        ) : (
                          <ChevronRight size={11} strokeWidth={1.5} />
                        )}
                      </button>
                    ) : null}
                    {onSelectSession ? (
                      <button
                        type="button"
                        data-testid={`open-child-session-${child.session_id}`}
                        onClick={() => onSelectSession(child.session_id)}
                        className="w-tree-open-btn"
                      >
                        <span>{t('workbench.children.openSession')}</span>
                        <ArrowUpRight size={11} strokeWidth={1.5} />
                      </button>
                    ) : null}
                  </div>

                  <div className="w-tree-sub" data-testid="child-session-launcher">
                    <span>
                      {t(`workbench.children.kind.${child.relation_kind}`, {
                        defaultValue: child.relation_kind,
                      })}
                    </span>
                    {actorLabel ? (
                      <>
                        <span aria-hidden="true">·</span>
                        <span>{actorLabel}</span>
                      </>
                    ) : null}
                    {ageStr ? (
                      <>
                        <span aria-hidden="true">·</span>
                        <span className="tabular-nums">{ageStr}</span>
                      </>
                    ) : null}
                  </div>
                </div>
              </div>

              {node.children.length > 0 && isNodeExpanded
                ? renderSiblingList(node.children, child.session_id)
                : null}
            </div>
          );
        })}

        {partition.hiddenCount > 0 ? (
          <div
            className="w-tree-more-wrap"
            style={{
              paddingLeft: `${Math.max(0, (nodes[0]?.visualDepth ?? 1) - 1) * 16}px`,
            }}
          >
            <button
              type="button"
              data-testid={`tree-expand-finished-${parentKey}`}
              onClick={() => toggleFinishedSiblings(parentKey)}
              className="w-tree-more-btn"
            >
              {showAll
                ? t('workbench.children.collapseFinished')
                : t('workbench.children.expandAllFinished', {
                    count: partition.hiddenCount,
                  })}
            </button>
          </div>
        ) : null}
      </>
    );
  };

  return (
    <section
      data-testid="progress-delegation-section"
      data-mode={isActive ? 'active' : 'history-expanded'}
      className="w-sec w-delegation-sec"
    >
      <div className="w-sec-hd">
        <span className="w-sec-title">{t('workbench.children.sectionTitle')}</span>
        <div className="w-delegation-hd-right">
          <span className="w-sec-sub">
            {isActive
              ? t('workbench.children.activeSubtitle')
              : t('workbench.children.historySummary', { count: totalItems })}
          </span>
          {!isActive ? (
            <button
              type="button"
              data-testid="progress-delegation-toggle"
              aria-expanded={true}
              onClick={toggleHistoryExpanded}
              className="w-delegation-toggle-btn"
            >
              <span>{t('workbench.children.collapse')}</span>
              <ChevronDown size={12} strokeWidth={1.5} />
            </button>
          ) : null}
        </div>
      </div>

      <div className="w-delegation-box">
        {hasExternal ? (
          <div
            data-testid="progress-external-host"
            className="w-ext-banner"
          >
            <Terminal size={14} strokeWidth={1.5} className="w-ext-icon" />
            <div className="w-ext-body">
              <div className="w-ext-title">{t('workbench.children.externalHostTitle')}</div>
              <div className="w-ext-desc">{t('workbench.children.externalHostDesc')}</div>
            </div>
          </div>
        ) : null}

        {treeNodes.length > 0 ? (
          <div data-testid="progress-child-sessions" className="w-delegation-group">
            <div className="w-delegation-group-hd">
              <GitFork size={12} strokeWidth={1.5} />
              <span>{t('workbench.children.sessionsSection')}</span>
              <span className="w-delegation-count">{dedupedSessions.length}</span>
            </div>
            <div className="w-tree-list">{renderSiblingList(treeNodes, 'root')}</div>
          </div>
        ) : null}

        {childProcesses.length > 0 ? (
          <div data-testid="progress-child-processes" className="w-delegation-group">
            <div className="w-delegation-group-hd">
              <Cpu size={12} strokeWidth={1.5} />
              <span>{t('workbench.children.processesSection')}</span>
              <span className="w-delegation-count">{childProcesses.length}</span>
            </div>
            <div className="w-proc-list">
              {childProcesses.map((proc: SessionChildProcess) => {
                const procKey = `${proc.pid}-${proc.ppid}`;
                const detailsOpen = Boolean(procDetailsOpen[procKey]);
                const summaryText = summarizeChildProcess(proc, isZh);
                const elapsedText = formatElapsedHuman(proc.elapsed, isZh);
                const sourceText = describeProcessSource(
                  proc,
                  sessionId,
                  childSessionById,
                  isZh
                );

                return (
                  <div
                    key={procKey}
                    data-testid="child-process-row"
                    data-running={proc.is_running ? 'true' : 'false'}
                    className="w-proc-row"
                  >
                    <div className="w-proc-head">
                      <div className="w-proc-main">
                        <span className="w-child-pill is-running">
                          <span aria-hidden="true" className="w-dot d-run" />
                          <span>{t('workbench.children.status.running')}</span>
                        </span>
                        <span className="w-proc-summary">{summaryText}</span>
                      </div>
                      <div className="w-proc-actions">
                        <button
                          type="button"
                          data-testid={`process-details-toggle-${proc.pid}`}
                          aria-expanded={detailsOpen}
                          onClick={() =>
                            setProcDetailsOpen((prev) => ({
                              ...prev,
                              [procKey]: !prev[procKey],
                            }))
                          }
                          className="w-tree-fold-btn"
                        >
                          <span>
                            {detailsOpen
                              ? t('workbench.children.processDetailsHide')
                              : t('workbench.children.processDetailsToggle')}
                          </span>
                          {detailsOpen ? (
                            <ChevronDown size={11} strokeWidth={1.5} />
                          ) : (
                            <ChevronRight size={11} strokeWidth={1.5} />
                          )}
                        </button>
                        {proc.linked_session_id && onSelectSession ? (
                          <button
                            type="button"
                            data-testid={`open-linked-session-${proc.linked_session_id}`}
                            onClick={() => onSelectSession(proc.linked_session_id!)}
                            className="w-tree-open-btn"
                          >
                            <span>{t('workbench.children.openLinkedSession')}</span>
                            <ArrowUpRight size={11} strokeWidth={1.5} />
                          </button>
                        ) : null}
                      </div>
                    </div>

                    <div className="w-proc-sub">
                      {elapsedText ? (
                        <span className="tabular-nums">{elapsedText}</span>
                      ) : null}
                      {elapsedText ? <span aria-hidden="true">·</span> : null}
                      <span>{sourceText}</span>
                    </div>

                    {detailsOpen ? (
                      <div
                        data-testid={`process-technical-details-${proc.pid}`}
                        className="w-proc-tech"
                      >
                        <div className="w-proc-tech-meta">
                          <span>PID {proc.pid}</span>
                          <span>PPID {proc.ppid}</span>
                          {proc.tmux_name ? <span>{proc.tmux_name}</span> : null}
                        </div>
                        <div className="w-proc-tech-cmd">
                          {cleanCommandPreview(proc.command)}
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
