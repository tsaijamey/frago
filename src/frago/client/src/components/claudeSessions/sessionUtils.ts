import { User, Bot, CircleHelp } from 'lucide-react';
import type { ClaudeSessionHuman } from '@/api/client';

export const DAY_OPTIONS = [1, 7, 14, 30];

export const HUMAN_META: Record<
  ClaudeSessionHuman,
  { Icon: typeof User; color: string; labelKey: string }
> = {
  human: { Icon: User, color: 'var(--accent-success)', labelKey: 'claudeSessions.filter.human' },
  maybe: { Icon: CircleHelp, color: 'var(--accent-warning)', labelKey: 'claudeSessions.filter.maybe' },
  agent: { Icon: Bot, color: 'var(--text-muted)', labelKey: 'claudeSessions.filter.agent' },
};

export function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diffMs = Date.now() - then;
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}
