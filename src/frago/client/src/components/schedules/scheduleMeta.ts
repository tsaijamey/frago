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

const pad2 = (v: string | number) => String(v).padStart(2, '0');

/**
 * cron 翻成人话，只翻一小撮确定翻得对的写法，认不出就返回 null。
 *
 * 翻错了比看不懂更糟：所以白名单以外一律不翻，翻出来的也永远和原式同屏（见 cronRawText）。
 * 认得的写法（分 时 日 月 星期）：
 *   M H * * *    每天，H 可以是逗号列表
 *   M H * * D    每周某天，D 取 0–7，0 和 7 都是周日（与服务端 croniter 一致）
 *   M H * * 1-5  工作日
 *   M H N * *    每月某日
 */
export function cronText(expr: string, t: TFunction): string | null {
  const f = expr.trim().split(/\s+/);
  if (f.length !== 5) return null;
  const [mi, hr, dom, mon, dow] = f;
  if (!/^\d{1,2}$/.test(mi) || !/^\d{1,2}(,\d{1,2})*$/.test(hr) || mon !== '*') return null;
  if (Number(mi) > 59 || hr.split(',').some((h) => Number(h) > 23)) return null;

  const times = hr.split(',').map((h) => `${pad2(h)}:${pad2(mi)}`);
  const at =
    times.length > 1
      ? times.slice(0, -1).join(t('schedules.freq.listSep')) + t('schedules.freq.and') + times[times.length - 1]
      : times[0];

  if (dom === '*' && dow === '*') return t('schedules.freq.daily', { at });
  if (dom === '*' && /^[0-7]$/.test(dow)) {
    return t('schedules.freq.weekly', { at, day: t(`schedules.freq.dow.${Number(dow) % 7}`) });
  }
  if (dom === '*' && dow === '1-5') return t('schedules.freq.weekdays', { at });
  if (/^\d{1,2}$/.test(dom) && Number(dom) >= 1 && Number(dom) <= 31 && dow === '*') {
    return t('schedules.freq.monthly', { at, dom: Number(dom) });
  }
  return null;
}

/** 多久跑一次，给人读的那一句。cron 认不出就只印原式，不给半对的译文。 */
export function frequencyText(s: ScheduleItem, t: TFunction): string {
  if (s.cron) return cronText(s.cron, t) ?? t('schedules.freq.cron', { expr: s.cron });
  const sec = s.interval_seconds;
  if (!sec) return '—';
  if (sec % 3600 === 0) return t('schedules.freq.hours', { count: sec / 3600 });
  if (sec % 60 === 0) return t('schedules.freq.minutes', { count: sec / 60 });
  return t('schedules.freq.seconds', { count: sec });
}

/** 人话下面那行灰色原式。没 cron、或没翻出人话（第一行已经是原式）时给空，免得印两遍。 */
export function cronRawText(s: ScheduleItem, t: TFunction): string {
  if (!s.cron || cronText(s.cron, t) === null) return '';
  return t('schedules.freq.cron', { expr: s.cron });
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * 上次运行落在哪天：今天、昨天，更早写月日。
 * 服务端给的是不带时区的本机时间，按字面拆开，不经 Date 解析，免得被当成 UTC 挪了时区。
 */
export function lastRunText(iso: string | null | undefined, now: Date, t: TFunction): string {
  const m = iso?.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return '—';
  const [, y, mo, d, hh, mm] = m;
  const time = `${hh}:${mm}`;
  const sameDay = (day: Date) =>
    day.getFullYear() === Number(y) && day.getMonth() + 1 === Number(mo) && day.getDate() === Number(d);
  if (sameDay(now)) return t('schedules.lastRun.today', { time });
  if (sameDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))) {
    return t('schedules.lastRun.yesterday', { time });
  }
  return t('schedules.lastRun.date', {
    time,
    month: Number(mo),
    mon: MONTHS[Number(mo) - 1],
    day: Number(d),
  });
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
