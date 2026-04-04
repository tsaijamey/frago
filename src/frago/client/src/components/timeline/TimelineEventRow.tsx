/**
 * TimelineEventRow — Renders a single timeline event.
 *
 * Title/subtitle from backend. Icons from Lucide based on event_type.
 * Color-coded border-left by msg_id, visual weight by level (L1/L2/L3).
 */

import { useTranslation } from 'react-i18next';
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

/** Humanize event on the frontend using i18n keys + raw_data */
function useHumanizedEvent(event: TimelineEvent): { title: string; subtitle: string | null } {
  const { t } = useTranslation();
  const data = event.raw_data || {};

  switch (event.event_type) {
    case 'ingestion': {
      const channel = (data.channel as string) || '';
      const prompt = (data.prompt as string) || '';
      const match = prompt.match(/<instruction>\s*([\s\S]*?)\s*<\/instruction>/);
      const instruction = match ? match[1].trim() : prompt;
      return { title: t('timeline.event.receivedMessage', { channel }), subtitle: instruction || null };
    }
    case 'pa_decision': {
      const action = (data.action as string) || '';
      const details = (data.details as Record<string, string>) || {};
      const desc = details.description || details.recipe_name || details.prompt || '';
      const keyMap: Record<string, string> = {
        run: 'timeline.event.decisionRun',
        reply: 'timeline.event.decisionReply',
        resume: 'timeline.event.decisionResume',
        recipe: 'timeline.event.decisionRecipe',
        update: 'timeline.event.decisionUpdate',
      };
      const title = keyMap[action] ? t(keyMap[action]) : action;
      return { title, subtitle: desc || null };
    }
    case 'agent_launched': {
      const desc = (data.description as string) || '';
      return { title: t('timeline.event.agentLaunched'), subtitle: desc || null };
    }
    case 'agent_exited': {
      const ok = data.has_completion as boolean | undefined;
      const duration = data.duration_seconds as number | undefined;
      const title = ok ? t('timeline.event.agentCompleted') : t('timeline.event.agentFailed');
      const subtitle = duration ? t('timeline.event.agentDuration', { duration }) : null;
      return { title, subtitle };
    }
    case 'pa_reply': {
      const channel = (data.channel as string) || '';
      const text = (data.reply_text as string) || '';
      return { title: t('timeline.event.replied', { channel }), subtitle: text || null };
    }
    default:
      return { title: event.title, subtitle: event.subtitle };
  }
}

export default function TimelineEventRow({ event, color }: Props) {
  const { icon: Icon, className: iconClass } = getIconConfig(event);
  const { title, subtitle: rawSubtitle } = useHumanizedEvent(event);
  const subtitle = rawSubtitle ? truncate(rawSubtitle, 80) : null;
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
        <span className={titleClass}>{title}</span>
        {subtitle && <span className="tl-subtitle">{subtitle}</span>}
      </span>
    </div>
  );
}
