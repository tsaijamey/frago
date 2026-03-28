/**
 * TimelinePage — Live information feed
 *
 * Renders a vertical timeline of system events:
 * - Heartbeat (low visual weight)
 * - Running tasks (sub-agent blocks)
 * - Recent completed/failed tasks
 * - Real-time updates via WebSocket
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { useAppStore } from '@/stores/appStore';
import { formatRelativeTime, formatDuration } from './constants';
import { useTimeline } from './useTimeline';
import TimelineEventRow from './TimelineEventRow';
import SubAgentBlock from './SubAgentBlock';
import type { DashboardData } from '@/api/client';

// Re-fetch relative times every 30s
function useRelativeTimeRefresh() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000);
    return () => clearInterval(id);
  }, []);
  return tick;
}

const NEAR_BOTTOM_THRESHOLD = 80;

export default function TimelinePage() {
  const { dashboard, loadTasks, openTaskDetail } = useAppStore();
  const paEvents = useTimeline();
  const scrollRef = useRef<HTMLDivElement>(null);
  const isNearBottom = useRef(true);
  const isInitialLoad = useRef(true);
  const isProgrammaticScroll = useRef(false);
  // tick triggers re-render every 30s to update relative timestamps
  const _tick = useRelativeTimeRefresh();
  void _tick;

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  // Track user scroll position (skip programmatic scrolls)
  const handleScroll = useCallback(() => {
    if (isProgrammaticScroll.current) return;
    const el = scrollRef.current;
    if (!el) return;
    isNearBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_THRESHOLD;
  }, []);

  // Scroll to bottom helper — marks scroll as programmatic
  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    isProgrammaticScroll.current = true;
    el.scrollTop = el.scrollHeight;
    // Reset flag after browser processes the scroll event
    requestAnimationFrame(() => {
      isProgrammaticScroll.current = false;
    });
  }, []);

  // Content count for tracking changes (PA events + dashboard tasks)
  const contentCount =
    paEvents.length +
    (dashboard?.running_tasks?.length || 0) +
    (dashboard?.recent_tasks?.length || 0);

  // Scroll to bottom: unconditional on first load, conditional on new content
  useEffect(() => {
    if (isInitialLoad.current) {
      scrollToBottom();
      isInitialLoad.current = false;
    } else if (isNearBottom.current) {
      scrollToBottom();
    }
  }, [contentCount, scrollToBottom]);

  // Build timeline events from dashboard data
  const runningTasks = dashboard?.running_tasks || [];
  // Reverse recent tasks so oldest first (API returns newest first)
  const recentTasks = [...(dashboard?.recent_tasks || [])].reverse();

  const hasAnyContent = paEvents.length > 0 || runningTasks.length > 0 || recentTasks.length > 0;

  return (
    <div className="timeline-page" ref={scrollRef} onScroll={handleScroll}>
      <div className="timeline-feed">
        {/* Empty state */}
        {!hasAnyContent && (
          <div className="timeline-empty">
            <span className="timeline-empty-dot">◉</span>
            <span className="timeline-empty-text">等待事件...</span>
          </div>
        )}

        {/* PA event stream — ingestion, decisions, agent lifecycle */}
        {paEvents.map((event, i) => {
          // Insert spacer between different task groups
          const prevTaskId = i > 0 ? (paEvents[i - 1].data.task_id as string || paEvents[i - 1].data.id as string) : null;
          const curTaskId = (event.data.task_id as string || event.data.id as string) || null;
          const needsSpacer = i > 0 && curTaskId !== prevTaskId;
          return (
            <div key={event.id}>
              {needsSpacer && <div className="tl-spacer" />}
              <TimelineEventRow event={event} />
            </div>
          );
        })}

        {/* Recent completed/failed tasks — oldest first */}
        {recentTasks.map((task) => (
          <RecentTaskRow
            key={task.id}
            task={task}
            onClick={() => openTaskDetail(task.id)}
          />
        ))}

        {/* Running tasks — sub-agent blocks (always at bottom, most recent) */}
        {runningTasks.map((task) => (
          <SubAgentBlock
            key={task.id}
            task={task}
            onViewDetail={() => openTaskDetail(task.id)}
          />
        ))}

        {/* Heartbeat — system status (always last, like "now") */}
        <HeartbeatRow dashboard={dashboard} />
      </div>
    </div>
  );
}

/* ── Heartbeat Row ── */
function HeartbeatRow({ dashboard }: { dashboard: DashboardData | null }) {
  const runCount = dashboard?.running_tasks?.length || 0;
  const chrome = dashboard?.system_status?.chrome_connected;

  return (
    <div className="tl-row tl-row--heartbeat">
      <span className="tl-ts">{/* always present */}</span>
      <span className="tl-icon tl-icon--dim">♥</span>
      <span className="tl-text tl-text--dim">
        系统正常{runCount > 0 ? `    ${runCount} 个任务运行中` : '    无任务运行'}
        {chrome !== undefined && `    Chrome ${chrome ? 'ON' : 'OFF'}`}
      </span>
    </div>
  );
}

/* RunningTaskBlock replaced by SubAgentBlock component */

/* ── Recent Task Row ── */
interface RecentTask {
  id: string;
  name: string | null;
  status: string;
  duration_ms: number | null;
  ended_at: string | null;
  error_summary: string | null;
}

function RecentTaskRow({ task, onClick }: { task: RecentTask; onClick: () => void }) {
  const isError = task.status === 'error';
  const icon = isError ? '✗' : '✓';
  const iconClass = isError ? 'tl-icon--error' : 'tl-icon--accent';
  const titleClass = isError ? 'tl-title--error' : 'tl-title';

  const title = isError
    ? 'Agent 执行失败'
    : 'Agent 执行完毕';

  const subtitle = [
    task.duration_ms ? formatDuration(task.duration_ms) : null,
    task.name || null,
  ].filter(Boolean).join('    ');

  return (
    <div className="tl-row tl-row--event" onClick={onClick}>
      <span className="tl-ts">{task.ended_at ? formatRelativeTime(task.ended_at) : ''}</span>
      <span className={`tl-icon ${iconClass}`}>{icon}</span>
      <span className="tl-content">
        <span className={titleClass}>{title}</span>
        {subtitle && <span className="tl-subtitle">{subtitle}</span>}
        {task.error_summary && (
          <span className="tl-subtitle tl-subtitle--error">{task.error_summary}</span>
        )}
      </span>
    </div>
  );
}
