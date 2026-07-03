/**
 * tokenCalendarUtils — pure helpers for the token calendar modal.
 * Kept free of React/DOM so vitest can exercise them directly.
 */

/** Abbreviate a token count: 1.2B / 1.2M / 12.3K; 0 or negative → "—". */
export function formatTokens(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '—';
  if (n >= 1e9) return trim1(n / 1e9) + 'B';
  if (n >= 1e6) return trim1(n / 1e6) + 'M';
  if (n >= 1e3) return trim1(n / 1e3) + 'K';
  return String(Math.round(n));
}

function trim1(v: number): string {
  const s = (Math.round(v * 10) / 10).toFixed(1);
  return s.endsWith('.0') ? s.slice(0, -2) : s;
}

export interface CalendarCell {
  /** Local date key, YYYY-MM-DD */
  date: string;
  day: number;
  inMonth: boolean;
}

/** Format a local Date as YYYY-MM-DD (no UTC shift). */
export function toDateKey(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

/**
 * Build the day matrix for a month ("YYYY-MM"): full weeks from Monday to
 * Sunday, leading/trailing cells filled from the adjacent months.
 */
export function monthMatrix(month: string): CalendarCell[][] {
  const [y, m] = month.split('-').map(Number);
  const first = new Date(y, m - 1, 1);
  // getDay(): Sunday=0 … Saturday=6; we want Monday-first offset 0…6.
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(y, m - 1, 1 - lead);
  const weeks: CalendarCell[][] = [];
  const cursor = new Date(start);
  do {
    const week: CalendarCell[] = [];
    for (let i = 0; i < 7; i++) {
      week.push({
        date: toDateKey(cursor),
        day: cursor.getDate(),
        inMonth: cursor.getMonth() === m - 1 && cursor.getFullYear() === y,
      });
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(week);
  } while (cursor.getMonth() === m - 1 && cursor.getFullYear() === y);
  return weeks;
}

/** Shift a "YYYY-MM" month by delta months. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
