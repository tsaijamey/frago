import { useCallback, useEffect, useRef, useState } from 'react';
import { getClaudeSessionDetail } from '@/api';

/**
 * useSessionActivity — the shared multi-session background-keepalive engine.
 *
 * The detail drawer only foreground-polls the ONE session it currently shows,
 * and drops that poll when you switch away. This hook is the layer that keeps
 * *every session you've sent into* alive in the background: after a send it
 * tracks that sid, keeps probing its transcript on a single shared interval,
 * and when the turn finishes while you're looking elsewhere it flags the row as
 * unread. Opening a session clears its unread.
 *
 * This engine is presentation-agnostic on purpose — a "focused + unread badge"
 * list and a future "split-screen" view both consume the same per-sid state;
 * only how the badge/panel is drawn differs. Nothing here commits to a layout.
 */

export type ActivityStatus = 'running' | 'done';

export interface SessionActivity {
  status: ActivityStatus;
  /** A finished turn landed while this session was NOT the open one. */
  unread: boolean;
}

// How often the shared background loop probes tracked sessions, and how long a
// tracked turn may run before we stop probing it (mirrors the drawer's own 6-min
// foreground deadline so background and foreground give up together).
const POLL_INTERVAL_MS = 2500;
const DEFAULT_DEADLINE_MS = 6 * 60 * 1000;

interface Tracked {
  // Terminal-record marker captured at send time; the turn is "new-done" only
  // once the transcript's marker advances past it (same rule the drawer uses).
  baselineMarker: string | null;
  deadlineMs: number;
}

export function useSessionActivity() {
  // Per-sid render state (what the list rows read for badges).
  const [activity, setActivity] = useState<Record<string, SessionActivity>>({});

  // Sessions still being probed in the background, keyed by sid. A ref (not
  // state) so the interval callback always sees the live set without re-arming.
  const trackedRef = useRef<Map<string, Tracked>>(new Map());
  // The sid whose drawer is currently open — a finished turn on THIS sid must
  // not raise an unread badge (the user is already watching it).
  const openSidRef = useRef<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const setOpenSid = useCallback((sid: string | null) => {
    openSidRef.current = sid;
  }, []);

  // Register a session for background tracking right after a send. Marks it
  // running with a fresh (unread-cleared) state; wall-clock deadline bounds it.
  const track = useCallback((sid: string, baselineMarker: string | null) => {
    trackedRef.current.set(sid, {
      baselineMarker,
      deadlineMs: Date.now() + DEFAULT_DEADLINE_MS,
    });
    setActivity((cur) => ({ ...cur, [sid]: { status: 'running', unread: false } }));
  }, []);

  // Opening a session clears its unread flag (keeps its status).
  const markRead = useCallback((sid: string) => {
    setActivity((cur) => {
      const entry = cur[sid];
      if (!entry || !entry.unread) return cur;
      return { ...cur, [sid]: { ...entry, unread: false } };
    });
  }, []);

  // The single shared probe loop. Iterates tracked sids each tick; a session
  // leaves the tracked set when its turn lands (marker advanced past baseline)
  // or its deadline lapses. Probes with limit=1 to keep each read cheap.
  useEffect(() => {
    const tick = async () => {
      const entries = Array.from(trackedRef.current.entries());
      await Promise.all(
        entries.map(async ([sid, tr]) => {
          try {
            const d = await getClaudeSessionDetail(sid, 1);
            const landed =
              d.done === true && (d.last_uuid ?? null) !== tr.baselineMarker;
            if (landed) {
              trackedRef.current.delete(sid);
              setActivity((cur) => ({
                ...cur,
                [sid]: { status: 'done', unread: openSidRef.current !== sid },
              }));
              return;
            }
          } catch {
            // transient read error — keep tracking, retry next tick
          }
          if (Date.now() >= tr.deadlineMs) {
            // Gave up waiting; mark done but don't nag with an unread badge.
            trackedRef.current.delete(sid);
            setActivity((cur) => ({
              ...cur,
              [sid]: { status: 'done', unread: false },
            }));
          }
        })
      );
    };
    timerRef.current = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current != null) window.clearInterval(timerRef.current);
    };
  }, []);

  return { activity, track, markRead, setOpenSid };
}
