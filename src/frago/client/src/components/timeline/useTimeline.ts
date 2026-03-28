/**
 * useTimeline — Aggregates PA events from WebSocket + REST into a unified timeline.
 *
 * Data sources:
 * 1. GET /api/pa/tasks — historical ingested tasks (on mount)
 * 2. WebSocket PA_* events — real-time PA decision stream
 * 3. Dashboard data — running/recent tasks (existing)
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { MessageType, type WebSocketMessage } from '@/api/websocket';

export interface TimelineEvent {
  id: string;
  type:
    | 'heartbeat'
    | 'ingestion'
    | 'pa_decision'
    | 'agent_launched'
    | 'agent_exited'
    | 'pa_reply';
  timestamp: string;
  data: Record<string, unknown>;
}

const PA_MESSAGE_TYPES = [
  MessageType.PA_INGESTION,
  MessageType.PA_DECISION,
  MessageType.PA_AGENT_LAUNCHED,
  MessageType.PA_AGENT_EXITED,
  MessageType.PA_REPLY,
] as const;

function wsTypeToEventType(wsType: string): TimelineEvent['type'] | null {
  switch (wsType) {
    case MessageType.PA_INGESTION:
      return 'ingestion';
    case MessageType.PA_DECISION:
      return 'pa_decision';
    case MessageType.PA_AGENT_LAUNCHED:
      return 'agent_launched';
    case MessageType.PA_AGENT_EXITED:
      return 'agent_exited';
    case MessageType.PA_REPLY:
      return 'pa_reply';
    default:
      return null;
  }
}

let eventCounter = 0;

export function useTimeline(): TimelineEvent[] {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const eventsRef = useRef(events);
  eventsRef.current = events;

  // Load historical tasks on mount and reconstruct event chains
  // Each IngestedTask with status fields can imply multiple events:
  //   created_at + channel + prompt → ingestion
  //   status=executing + session_id → pa_decision (run) + agent_launched
  //   status=completed + completed_at + result_summary → agent_exited + pa_reply
  //   status=failed + error → agent_exited (failed)
  useEffect(() => {
    async function loadHistory() {
      try {
        const res = await fetch('/api/pa/tasks?limit=20');
        if (!res.ok) return;
        const json = await res.json();
        const tasks = (json.tasks || []) as Record<string, unknown>[];
        const allEvents: TimelineEvent[] = [];

        for (const t of tasks) {
          const taskId = t.id as string;
          const createdAt = (t.created_at as string) || new Date().toISOString();

          // 1. Ingestion event (always present)
          allEvents.push({
            id: `hist-ing-${taskId}`,
            type: 'ingestion',
            timestamp: createdAt,
            data: t,
          });

          // 2. If task was executed (has session_id), infer PA decision + agent launch
          const sessionId = t.session_id as string | null;
          const status = t.status as string;
          if (sessionId && (status === 'executing' || status === 'completed' || status === 'failed')) {
            // PA decision — estimated ~2s after ingestion
            const decisionTime = new Date(new Date(createdAt).getTime() + 2000).toISOString();
            allEvents.push({
              id: `hist-dec-${taskId}`,
              type: 'pa_decision',
              timestamp: decisionTime,
              data: { action: 'run', task_id: taskId, details: { description: sessionId } },
            });

            // Agent launched — estimated ~3s after ingestion
            const launchTime = new Date(new Date(createdAt).getTime() + 3000).toISOString();
            allEvents.push({
              id: `hist-launch-${taskId}`,
              type: 'agent_launched',
              timestamp: launchTime,
              data: { run_id: sessionId, task_id: taskId, description: sessionId },
            });
          }

          // 3. If task completed/failed, infer agent_exited
          const completedAt = t.completed_at as string | null;
          if (completedAt && (status === 'completed' || status === 'failed')) {
            const durationMs = completedAt && createdAt
              ? new Date(completedAt).getTime() - new Date(createdAt).getTime()
              : 0;

            allEvents.push({
              id: `hist-exit-${taskId}`,
              type: 'agent_exited',
              timestamp: completedAt,
              data: {
                run_id: sessionId,
                task_id: taskId,
                has_completion: status === 'completed',
                duration_seconds: Math.floor(durationMs / 1000),
              },
            });

            // 4. If completed with result_summary, infer pa_reply
            const resultSummary = t.result_summary as string | null;
            const channel = t.channel as string;
            if (resultSummary && status === 'completed') {
              // Reply happens ~2s after completion
              const replyTime = new Date(new Date(completedAt).getTime() + 2000).toISOString();
              allEvents.push({
                id: `hist-reply-${taskId}`,
                type: 'pa_reply',
                timestamp: replyTime,
                data: {
                  task_id: taskId,
                  channel,
                  reply_text: resultSummary,
                },
              });
            }
          }
        }

        // Sort all events by timestamp, oldest first
        allEvents.sort(
          (a, b) =>
            new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
        );
        setEvents(allEvents);
      } catch {
        // Silently fail — Timeline still works with real-time events only
      }
    }
    loadHistory();
  }, []);

  // Handle real-time PA events from WebSocket
  const handleMessage = useCallback((message: WebSocketMessage) => {
    const eventType = wsTypeToEventType(message.type);
    if (!eventType) return;

    // Extract all fields from message into a plain record
    const data: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(message)) {
      data[k] = v;
    }

    const newEvent: TimelineEvent = {
      id: `ws-${eventType}-${++eventCounter}`,
      type: eventType,
      timestamp: (data.timestamp as string) || new Date().toISOString(),
      data,
    };

    setEvents((prev) => {
      const next = [...prev, newEvent];
      // Keep last 200 events to prevent memory growth
      if (next.length > 200) return next.slice(-200);
      return next;
    });
  }, []);

  useWebSocket({
    messageTypes: [...PA_MESSAGE_TYPES],
    onMessage: handleMessage,
  });

  return events;
}
