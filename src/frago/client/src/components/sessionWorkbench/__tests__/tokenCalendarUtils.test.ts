import { describe, expect, it } from 'vitest';
import {
  computeVisibleDayCount,
  formatTokens,
  matchesSessionTitleTags,
  MAX_VISIBLE_DATE_CELLS,
  MIN_VISIBLE_DATE_CELLS,
  monthDaysList,
  monthMatrix,
  parseTagKeywords,
  shiftMonth,
  sliceVisibleDays,
  toDateKey,
} from '../tokenCalendarUtils';

describe('formatTokens', () => {
  it('shows — for zero, negative and non-finite', () => {
    expect(formatTokens(0)).toBe('—');
    expect(formatTokens(-5)).toBe('—');
    expect(formatTokens(NaN)).toBe('—');
  });

  it('keeps small counts as plain integers', () => {
    expect(formatTokens(1)).toBe('1');
    expect(formatTokens(999)).toBe('999');
  });

  it('abbreviates thousands / millions / billions with one decimal', () => {
    expect(formatTokens(1_230)).toBe('1.2K');
    expect(formatTokens(12_300)).toBe('12.3K');
    expect(formatTokens(1_200_000)).toBe('1.2M');
    expect(formatTokens(1_200_000_000)).toBe('1.2B');
  });

  it('drops a trailing .0', () => {
    expect(formatTokens(1_000)).toBe('1K');
    expect(formatTokens(2_000_000)).toBe('2M');
  });
});

describe('toDateKey', () => {
  it('formats local dates with zero padding', () => {
    expect(toDateKey(new Date(2026, 6, 3))).toBe('2026-07-03');
    expect(toDateKey(new Date(2026, 0, 1))).toBe('2026-01-01');
  });
});

describe('monthMatrix', () => {
  it('builds Monday-first weeks with cross-month padding (2026-07)', () => {
    // 2026-07-01 is a Wednesday → two leading June cells (Mon 29, Tue 30).
    const weeks = monthMatrix('2026-07');
    const flat = weeks.flat();
    expect(flat.length % 7).toBe(0);
    expect(weeks[0][0].date).toBe('2026-06-29');
    expect(weeks[0][0].inMonth).toBe(false);
    expect(weeks[0][2].date).toBe('2026-07-01');
    expect(weeks[0][2].inMonth).toBe(true);
    // 2026-07-31 is a Friday → trailing August cells fill Sat/Sun.
    const last = weeks[weeks.length - 1];
    expect(last[4].date).toBe('2026-07-31');
    expect(last[5].date).toBe('2026-08-01');
    expect(last[5].inMonth).toBe(false);
    expect(flat.filter((c) => c.inMonth)).toHaveLength(31);
  });

  it('covers February in a non-leap year (2026-02 starts on Sunday)', () => {
    const weeks = monthMatrix('2026-02');
    const flat = weeks.flat();
    // 2026-02-01 is a Sunday → six leading January cells.
    expect(weeks[0][6].date).toBe('2026-02-01');
    expect(flat.filter((c) => c.inMonth)).toHaveLength(28);
  });
});

describe('shiftMonth', () => {
  it('moves within a year', () => {
    expect(shiftMonth('2026-07', 1)).toBe('2026-08');
    expect(shiftMonth('2026-07', -1)).toBe('2026-06');
  });

  it('wraps across year boundaries', () => {
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
  });
});

describe('computeVisibleDayCount & sliceVisibleDays', () => {
  it('clamps visible day count strictly between n and n + 3 across screen heights', () => {
    expect(computeVisibleDayCount(200)).toBe(MIN_VISIBLE_DATE_CELLS);
    expect(computeVisibleDayCount(500)).toBeGreaterThanOrEqual(MIN_VISIBLE_DATE_CELLS);
    expect(computeVisibleDayCount(500)).toBeLessThanOrEqual(MAX_VISIBLE_DATE_CELLS);
    expect(computeVisibleDayCount(2000)).toBe(MAX_VISIBLE_DATE_CELLS);
    expect(MAX_VISIBLE_DATE_CELLS - MIN_VISIBLE_DATE_CELLS).toBe(3);
  });

  it('slices ordered dates around the selected date', () => {
    const days = monthDaysList('2026-10');
    expect(days).toHaveLength(31);
    const slice = sliceVisibleDays(days, '2026-10-15', 7);
    expect(slice.items).toHaveLength(7);
    expect(slice.items.map((d) => d.date)).toContain('2026-10-15');
    // Strictly ordered ascending
    for (let i = 1; i < slice.items.length; i++) {
      expect(slice.items[i].day).toBe(slice.items[i - 1].day + 1);
    }
  });
});

describe('parseTagKeywords & matchesSessionTitleTags', () => {
  it('parses and deduplicates tag keywords', () => {
    expect(parseTagKeywords(['calendar'], 'timeline, calendar  token')).toEqual([
      'calendar',
      'timeline',
      'token',
    ]);
  });

  it('cross-filters session title and custom title with AND semantics', () => {
    const s = {
      title: '我的自定义标题：重构日历浮窗',
      custom_title: '我的自定义标题：重构日历浮窗',
      raw_title: 'Merge token calendar with session timeline modal',
    };
    expect(matchesSessionTitleTags(s, ['日历', 'timeline'])).toBe(true);
    expect(matchesSessionTitleTags(s, ['token', '浮窗'])).toBe(true);
    expect(matchesSessionTitleTags(s, ['日历', '不存在的词'])).toBe(false);
  });
});

