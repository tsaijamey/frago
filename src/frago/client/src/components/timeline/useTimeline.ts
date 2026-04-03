/**
 * useTimeline — Aggregates timeline events from REST + WebSocket.
 *
 * Data sources:
 * 1. GET /api/timeline — historical events (humanized by backend, trace-driven)
 * 2. WebSocket timeline_event — real-time humanized events
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { MessageType, type WebSocketMessage } from '@/api/websocket';

export interface TimelineEvent {
  id: string;
  timestamp: string;
  event_type: string;
  title: string;
  subtitle: string | null;
  task_id: string | null;
  msg_id: string | null;
  run_id: string | null;
  raw_data: Record<string, unknown> | null;
}

export function useTimeline(): TimelineEvent[] {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const seenIds = useRef(new Set<string>());

  // Load historical events from backend
  useEffect(() => {
    async function loadHistory() {
      try {
        const res = await fetch('/api/timeline?limit=50');
        if (!res.ok) return;
        const json = await res.json();
        const loaded = (json.events || []) as TimelineEvent[];
        // Track IDs for dedup against WS events
        for (const e of loaded) seenIds.current.add(e.id);
        setEvents(loaded);
      } catch {
        // Timeline still works with real-time events only
      }
    }
    loadHistory();
  }, []);

  // Handle real-time timeline events from WebSocket
  const handleMessage = useCallback((message: WebSocketMessage) => {
    if (message.type !== MessageType.TIMELINE_EVENT) return;
    const event = (message as unknown as { event: TimelineEvent }).event;
    if (!event) return;

    // Dedup: skip if already loaded from REST
    if (seenIds.current.has(event.id)) return;
    seenIds.current.add(event.id);

    setEvents((prev) => {
      const next = [...prev, event];
      // Keep last 200 events to prevent memory growth
      if (next.length > 200) {
        const trimmed = next.slice(-200);
        // Rebuild seenIds from trimmed list
        seenIds.current = new Set(trimmed.map((e) => e.id));
        return trimmed;
      }
      return next;
    });
  }, []);

  useWebSocket({
    messageTypes: [MessageType.TIMELINE_EVENT],
    onMessage: handleMessage,
  });

  return events;
}
