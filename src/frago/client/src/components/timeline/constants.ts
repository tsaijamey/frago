/**
 * Timeline event type constants and visual config
 */

import i18n from '@/i18n';

export function formatRelativeTime(isoTimestamp: string): string {
  const now = Date.now();
  const then = new Date(isoTimestamp).getTime();
  const diffSec = Math.floor((now - then) / 1000);

  if (diffSec < 10) return i18n.t('timeline.time.justNow');
  if (diffSec < 60) return i18n.t('timeline.time.secondsAgo', { count: diffSec });
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return i18n.t('timeline.time.minutesAgo', { count: diffMin });
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return i18n.t('timeline.time.hoursAgo', { count: diffHour });
  const d = new Date(isoTimestamp);
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  if (min < 60) return `${min}m ${remSec}s`;
  const hr = Math.floor(min / 60);
  return `${hr}h ${min % 60}m`;
}

export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const min = Math.floor(seconds / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  return `${hr}h ${min % 60}m`;
}
