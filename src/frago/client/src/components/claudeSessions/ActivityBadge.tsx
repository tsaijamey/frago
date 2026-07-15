import { Loader2 } from 'lucide-react';
import type { SessionActivity } from './useSessionActivity';

/**
 * ActivityBadge — the per-row multi-session status marker.
 *
 * Presentation-agnostic on purpose: a spinning ring while a background turn is
 * still running, a solid unread dot once a reply landed while the user was
 * looking elsewhere. Consumed by both session lists (and reusable by any future
 * multi-session layout). Renders nothing when the session has no live activity.
 */
export default function ActivityBadge({ state }: { state?: SessionActivity }) {
  if (!state) return null;
  if (state.status === 'running') {
    return (
      <span className="cs-activity cs-activity--running" title="running">
        <Loader2 size={12} className="cs-spin" />
      </span>
    );
  }
  if (state.unread) {
    return <span className="cs-activity cs-activity--unread" title="new reply" />;
  }
  return null;
}
