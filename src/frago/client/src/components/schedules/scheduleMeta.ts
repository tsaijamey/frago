/**
 * 定时任务页上几处共用的判定：一条任务现在处在哪一档、多久跑一次怎么说、时间怎么印。
 * 清单行和详情面板必须用同一套，否则同一条任务在两边读出两种状态。
 */

import type { TFunction } from 'i18next';
import type { ScheduleItem } from '@/api';

/** 一条任务此刻最该让人知道的那一档。顺序即优先级：停用压过一切，在跑压过上次结果。 */
export type ScheduleState = 'disabled' | 'running' | 'failing' | 'ok' | 'never';

export function stateOf(s: ScheduleItem): ScheduleState {
  if (!s.enabled) return 'disabled';
  if (s.running) return 'running';
  if (s.last_status === 'failed' || s.consecutive_failures > 0) return 'failing';
  if (s.last_status) return 'ok';
  return 'never';
}

export const STATE_CHIP: Record<ScheduleState, string> = {
  disabled: 'sc-chip--disabled',
  running: 'td-chip--doing',
  failing: 'td-chip--high',
  ok: 'td-chip--done',
  never: 'td-chip--todo',
};

export type ScheduleFilter = 'all' | 'enabled' | 'failing' | 'disabled';

export const FILTERS: ScheduleFilter[] = ['all', 'enabled', 'failing', 'disabled'];

export function matchesFilter(s: ScheduleItem, filter: ScheduleFilter): boolean {
  switch (filter) {
    case 'all':
      return true;
    case 'enabled':
      return s.enabled;
    case 'disabled':
      return !s.enabled;
    case 'failing':
      return stateOf(s) === 'failing';
  }
}

/** 多久跑一次。cron 原样印出——翻译成自然语言容易翻错，翻错了比看不懂更糟。 */
export function frequencyText(s: ScheduleItem, t: TFunction): string {
  if (s.cron) return t('schedules.freq.cron', { expr: s.cron });
  const sec = s.interval_seconds;
  if (!sec) return '—';
  if (sec % 3600 === 0) return t('schedules.freq.hours', { n: sec / 3600 });
  if (sec % 60 === 0) return t('schedules.freq.minutes', { n: sec / 60 });
  return t('schedules.freq.seconds', { n: sec });
}

/** 一次最多跑多久，到点就被掐掉。没显式给过的任务是默认的 2 小时。 */
export function timeoutText(s: ScheduleItem, t: TFunction): string {
  const sec = s.timeout;
  if (!sec) return '—';
  if (sec % 3600 === 0) return t('schedules.limit.hours', { n: sec / 3600 });
  if (sec % 60 === 0) return t('schedules.limit.minutes', { n: sec / 60 });
  return t('schedules.limit.seconds', { n: sec });
}

/** 这条任务执行的是什么：命令原文、配方名、或那句自然语言。 */
export function targetText(s: ScheduleItem): string {
  if (s.kind === 'command') return s.command ?? '';
  if (s.kind === 'recipe') return s.recipe ?? '';
  return s.prompt ?? '';
}

/** 服务端给的是本机时间的 ISO 串（带微秒）。印到秒，T 换成空格。 */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  return iso.replace('T', ' ').slice(0, 19);
}

export function notifyText(s: ScheduleItem, t: TFunction): string {
  const on = s.notify?.on;
  if (!on || on === 'never') return t('schedules.notify.never');
  return t('schedules.notify.to', {
    on: t(`schedules.notify.on.${on}`, { defaultValue: on }),
    to: s.notify.to ?? '—',
  });
}
