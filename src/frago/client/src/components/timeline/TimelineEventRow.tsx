/**
 * TimelineEventRow — Renders a single timeline event.
 *
 * Title/subtitle from backend. Icons from Lucide based on event_type.
 * Color-coded border-left by msg_id, visual weight by level (L1/L2/L3).
 */

import { formatRelativeTime } from './constants';
import type { TimelineEvent } from './useTimeline';
import {
  Mail,
  Zap,
  Play,
  CheckCircle2,
  XCircle,
  Reply,
  Circle,
  type LucideIcon,
} from 'lucide-react';

/** Truncate text to maxLen, adding ellipsis */
function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '…';
}

interface IconConfig {
  icon: LucideIcon;
  className: string;
}

function getIconConfig(event: TimelineEvent): IconConfig {
  switch (event.event_type) {
    case 'ingestion':
      return { icon: Mail, className: 'tl-icon--accent' };

    case 'pa_decision':
      return { icon: Zap, className: 'tl-icon--accent' };

    case 'agent_launched':
      return { icon: Play, className: 'tl-icon--accent' };

    case 'agent_exited': {
      const ok = event.raw_data?.has_completion as boolean | undefined;
      return ok
        ? { icon: CheckCircle2, className: 'tl-icon--accent' }
        : { icon: XCircle, className: 'tl-icon--error' };
    }

    case 'pa_reply':
      return { icon: Reply, className: 'tl-icon--accent' };

    default:
      return { icon: Circle, className: 'tl-icon--dim' };
  }
}

/** Map event_type to visual level: L1 (ingestion), L2 (decision/reply), L3 (agent) */
function getLevel(eventType: string): string {
  switch (eventType) {
    case 'ingestion':
      return 'L1';
    case 'pa_decision':
    case 'pa_reply':
      return 'L2';
    case 'agent_launched':
    case 'agent_exited':
      return 'L3';
    default:
      return 'L2';
  }
}

interface Props {
  event: TimelineEvent;
  color?: string;
}

export default function TimelineEventRow({ event, color }: Props) {
  const { icon: Icon, className: iconClass } = getIconConfig(event);
  const subtitle = event.subtitle ? truncate(event.subtitle, 80) : null;
  const level = getLevel(event.event_type);
  const isError = event.event_type === 'agent_exited' && !(event.raw_data?.has_completion);
  const titleClass = isError ? 'tl-title tl-title--error' : 'tl-title';

  return (
    <div
      className={`tl-row tl-row--event tl-row--${level}`}
      style={color ? { '--tl-row-color': color } as React.CSSProperties : undefined}
    >
      <span className="tl-ts">{formatRelativeTime(event.timestamp)}</span>
      <span className={`tl-icon ${iconClass}`}>
        <Icon size={18} />
      </span>
      <span className="tl-content">
        <span className={titleClass}>{event.title}</span>
        {subtitle && <span className="tl-subtitle">{subtitle}</span>}
      </span>
    </div>
  );
}
