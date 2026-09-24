/**
 * cron 人话与上次运行说法的用例。
 *
 * 人话翻错比看不懂更糟：白名单里每一种写法都钉一条，白名单外的每一类都钉「不翻」。
 * 文案走真的 en / zh 两份词条，词条键改名或漏了复数形态，这里会先红。
 */

import { beforeAll, describe, expect, it } from 'vitest';
import i18next, { type TFunction } from 'i18next';
import type { ScheduleItem } from '@/api';
import en from '@/i18n/locales/en.json';
import zh from '@/i18n/locales/zh.json';
import { cronRawText, cronText, frequencyText, lastRunText } from '../scheduleMeta';

let tEn: TFunction;
let tZh: TFunction;

beforeAll(async () => {
  const make = async (lng: string) => {
    const inst = i18next.createInstance();
    await inst.init({
      lng,
      fallbackLng: 'en',
      resources: { en: { translation: en }, zh: { translation: zh } },
      interpolation: { escapeValue: false },
    });
    return inst.t;
  };
  tEn = await make('en');
  tZh = await make('zh');
});

const item = (over: Partial<ScheduleItem>) => ({ cron: null, interval_seconds: null, ...over }) as ScheduleItem;

describe('cronText', () => {
  it('本机 2026-09-24 的六条写法全部翻得出', () => {
    expect(cronText('0 11 * * *', tEn)).toBe('Every day at 11:00');
    expect(cronText('20 10 * * *', tEn)).toBe('Every day at 10:20');
    expect(cronText('30 12 * * *', tEn)).toBe('Every day at 12:30');
    expect(cronText('0 9,18 * * *', tEn)).toBe('Every day at 09:00 and 18:00');
    expect(cronText('0 10 * * *', tEn)).toBe('Every day at 10:00');
    expect(cronText('0 14 * * *', tEn)).toBe('Every day at 14:00');
  });

  it('三个以上时刻用逗号加 and 连接', () => {
    expect(cronText('0 8,12,18 * * *', tEn)).toBe('Every day at 08:00, 12:00 and 18:00');
    expect(cronText('0 8,12,18 * * *', tZh)).toBe('每天 08:00、12:00 和 18:00');
  });

  it('每周、工作日、每月', () => {
    expect(cronText('0 9 * * 1', tEn)).toBe('Every Monday at 09:00');
    expect(cronText('0 9 * * 1-5', tEn)).toBe('Weekdays at 09:00');
    expect(cronText('0 9 1 * *', tEn)).toBe('Monthly on day 1 at 09:00');
  });

  it('星期 0 和 7 都是周日', () => {
    expect(cronText('0 9 * * 0', tEn)).toBe('Every Sunday at 09:00');
    expect(cronText('0 9 * * 7', tEn)).toBe('Every Sunday at 09:00');
  });

  it('时刻补零到两位', () => {
    expect(cronText('5 9 * * *', tEn)).toBe('Every day at 09:05');
  });

  it('中文', () => {
    expect(cronText('0 9,18 * * *', tZh)).toBe('每天 09:00 和 18:00');
    expect(cronText('0 9 * * 1', tZh)).toBe('每周一 09:00');
    expect(cronText('0 9 * * 1-5', tZh)).toBe('工作日 09:00');
    expect(cronText('0 9 1 * *', tZh)).toBe('每月 1 日 09:00');
  });

  it.each([
    '*/5 * * * *',
    '0,30 9 * * *',
    '0 9 * 1 *',
    '0 9 * * MON',
    '0 9 * * 1,3',
    '0 9 1 * 1',
    '@daily',
    '0 0 9 * * *',
    '0 */2 * * *',
    '60 9 * * *',
    '0 24 * * *',
    '0 9 0 * *',
  ])('白名单外不翻：%s', (expr) => {
    expect(cronText(expr, tEn)).toBeNull();
  });
});

describe('frequencyText / cronRawText', () => {
  it('翻出人话时第二行给原式', () => {
    const s = item({ cron: '0 11 * * *' });
    expect(frequencyText(s, tEn)).toBe('Every day at 11:00');
    expect(cronRawText(s, tEn)).toBe('cron 0 11 * * *');
  });

  it('翻不出时第一行就是原式，第二行空着', () => {
    const s = item({ cron: '*/5 * * * *' });
    expect(frequencyText(s, tEn)).toBe('cron */5 * * * *');
    expect(cronRawText(s, tEn)).toBe('');
  });

  it('按间隔跑的任务', () => {
    expect(frequencyText(item({ interval_seconds: 3600 }), tEn)).toBe('Every hour');
    expect(frequencyText(item({ interval_seconds: 7200 }), tEn)).toBe('Every 2 hours');
    expect(frequencyText(item({ interval_seconds: 1800 }), tEn)).toBe('Every 30 minutes');
    expect(frequencyText(item({ interval_seconds: 45 }), tEn)).toBe('Every 45 s');
    expect(frequencyText(item({ interval_seconds: 7200 }), tZh)).toBe('每 2 小时');
    expect(cronRawText(item({ interval_seconds: 7200 }), tEn)).toBe('');
  });

  it('既没 cron 也没间隔', () => {
    expect(frequencyText(item({}), tEn)).toBe('—');
  });
});

describe('次数单复数', () => {
  it('1 run / 2 runs / 已跑 1 次', () => {
    expect(tEn('schedules.row.runs', { count: 1 })).toBe('1 run');
    expect(tEn('schedules.row.runs', { count: 2 })).toBe('2 runs');
    expect(tEn('schedules.row.runs', { count: 0 })).toBe('0 runs');
    expect(tZh('schedules.row.runs', { count: 1 })).toBe('已跑 1 次');
  });

  it('全部停用提示', () => {
    expect(tEn('schedules.allDisabled.title', { count: 6 })).toBe('All 6 schedules are disabled.');
    expect(tZh('schedules.allDisabled.title', { count: 6 })).toBe('6 个定时任务全部停用。');
  });
});

describe('lastRunText', () => {
  const now = new Date(2026, 8, 24, 15, 0);

  it('今天、昨天、更早', () => {
    expect(lastRunText('2026-09-24T10:20:00.123456', now, tEn)).toBe('Today, 10:20');
    expect(lastRunText('2026-09-23T11:00:00', now, tEn)).toBe('Yesterday, 11:00');
    expect(lastRunText('2026-09-21T14:00:00', now, tEn)).toBe('Sep 21, 14:00');
  });

  it('中文', () => {
    expect(lastRunText('2026-09-24T10:20:00', now, tZh)).toBe('今天 10:20');
    expect(lastRunText('2026-09-23T11:00:00', now, tZh)).toBe('昨天 11:00');
    expect(lastRunText('2026-09-21T14:00:00', now, tZh)).toBe('9月21日 14:00');
  });

  it('跨年：元旦那天看前一年最后一天是昨天', () => {
    expect(lastRunText('2025-12-31T23:30:00', new Date(2026, 0, 1, 8, 0), tEn)).toBe('Yesterday, 23:30');
  });

  it('从没跑过', () => {
    expect(lastRunText(null, now, tEn)).toBe('—');
  });
});
