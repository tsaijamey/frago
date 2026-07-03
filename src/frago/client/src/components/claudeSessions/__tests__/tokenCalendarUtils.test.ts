import { describe, expect, it } from 'vitest';
import { formatTokens, monthMatrix, shiftMonth, toDateKey } from '../tokenCalendarUtils';

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
