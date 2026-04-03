/**
 * TimelinePage — Live information feed
 *
 * Renders a vertical timeline of system events:
 * - PA event stream (trace-driven, humanized by backend)
 * - Running tasks (sub-agent blocks)
 * - Heartbeat (system status)
 */

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useTimeline } from './useTimeline';
import TimelineEventRow from './TimelineEventRow';
import SubAgentBlock from './SubAgentBlock';
import { Heart } from 'lucide-react';
import type { DashboardData } from '@/api/client';

/** Deterministic color palette for msg_id groups */
const MSG_COLORS = [
  '#4ecdc4', // teal (matches accent-primary)
  '#7c6ef0', // purple
  '#f0a050', // orange
  '#e06080', // rose
  '#50b0f0', // sky blue
  '#a0d050', // lime
  '#f07070', // coral
  '#60c0a0', // mint
];

/** Build a stable msg_id → color map from events (order of first appearance) */
function buildColorMap(events: { msg_id: string | null }[]): Map<string, string> {
  const map = new Map<string, string>();
  let idx = 0;
  for (const e of events) {
    if (e.msg_id && !map.has(e.msg_id)) {
      map.set(e.msg_id, MSG_COLORS[idx % MSG_COLORS.length]);
      idx++;
    }
  }
  return map;
}

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

  // Filter out "回复消息" (pa_decision + reply) — redundant, pa_reply always follows
  const filteredEvents = useMemo(
    () => paEvents.filter((e) => !(e.event_type === 'pa_decision' && e.raw_data?.action === 'reply')),
    [paEvents],
  );
  const colorMap = useMemo(() => buildColorMap(filteredEvents), [filteredEvents]);

  // Content count for tracking changes
  const runningTasks = dashboard?.running_tasks || [];
  const contentCount = filteredEvents.length + runningTasks.length;

  // Scroll to bottom: unconditional on first load, conditional on new content
  useEffect(() => {
    if (isInitialLoad.current) {
      scrollToBottom();
      isInitialLoad.current = false;
    } else if (isNearBottom.current) {
      scrollToBottom();
    }
  }, [contentCount, scrollToBottom]);

  const hasAnyContent = filteredEvents.length > 0 || runningTasks.length > 0;

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

        {/* PA event stream — trace-driven, humanized by backend */}
        {filteredEvents.map((event, i) => {
          // Insert spacer between different message groups
          const prevMsgId = i > 0 ? filteredEvents[i - 1].msg_id : null;
          const curMsgId = event.msg_id || null;
          const needsSpacer = i > 0 && curMsgId !== prevMsgId;
          const color = curMsgId ? colorMap.get(curMsgId) : undefined;
          return (
            <div key={event.id}>
              {needsSpacer && <div className="tl-spacer" />}
              <TimelineEventRow event={event} color={color} />
            </div>
          );
        })}

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
      <span className="tl-icon tl-icon--dim">
        <Heart size={14} />
      </span>
      <span className="tl-text tl-text--dim">
        系统正常{runCount > 0 ? `    ${runCount} 个任务运行中` : '    无任务运行'}
        {chrome !== undefined && `    Chrome ${chrome ? 'ON' : 'OFF'}`}
      </span>
    </div>
  );
}
