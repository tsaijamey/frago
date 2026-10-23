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

/**
 * 左侧竖排日期列表展示的单元格数量下限 n 与上限 n + 3。
 * 随各类屏幕高度自适应：至少展示 n 个，最多展示 n + 3 个。
 */
export const MIN_VISIBLE_DATE_CELLS = 6;
export const MAX_VISIBLE_DATE_CELLS = MIN_VISIBLE_DATE_CELLS + 3;

const IDEAL_DATE_CELL_HEIGHT_PX = 68;

/**
 * 根据屏幕/容器可用高度计算左侧竖排展示的日期单元格个数，严格落在 [baseN, baseN + 3] 闭区间内。
 */
export function computeVisibleDayCount(
  availableHeightPx: number,
  baseN: number = MIN_VISIBLE_DATE_CELLS
): number {
  const minCount = Math.max(1, baseN);
  const maxCount = minCount + 3;
  if (!Number.isFinite(availableHeightPx) || availableHeightPx <= 0) {
    return minCount + 1;
  }
  const raw = Math.floor(availableHeightPx / IDEAL_DATE_CELL_HEIGHT_PX);
  return Math.max(minCount, Math.min(maxCount, raw));
}

/**
 * 生成指定月份 ("YYYY-MM") 从 1 号到月末按顺序排列的日期列表。
 */
export function monthDaysList(month: string): CalendarCell[] {
  const [y, m] = month.split('-').map(Number);
  const cursor = new Date(y, m - 1, 1);
  const out: CalendarCell[] = [];
  while (cursor.getFullYear() === y && cursor.getMonth() === m - 1) {
    out.push({
      date: toDateKey(cursor),
      day: cursor.getDate(),
      inMonth: true,
    });
    cursor.setDate(cursor.getDate() + 1);
  }
  return out;
}

export interface VisibleDaySlice {
  items: CalendarCell[];
  startIndex: number;
  canPrev: boolean;
  canNext: boolean;
}

/**
 * 从按顺序排列的日期列表中切出连续 visibleCount 个单元格（至少 n 个，最多 n + 3 个）。
 * 未指定手动起点时按固定页段定位（绝不把选中日期强制挪到垂直居中位置）。
 */
export function sliceVisibleDays(
  days: CalendarCell[],
  selectedDate: string | null,
  visibleCount: number,
  manualStart?: number | null
): VisibleDaySlice {
  if (!days.length) {
    return { items: [], startIndex: 0, canPrev: false, canNext: false };
  }
  const count = Math.max(1, Math.min(days.length, visibleCount));
  const maxStart = Math.max(0, days.length - count);
  let start = 0;
  if (manualStart !== undefined && manualStart !== null) {
    start = Math.max(0, Math.min(maxStart, manualStart));
  } else if (selectedDate) {
    const idx = days.findIndex((c) => c.date === selectedDate);
    if (idx >= 0) {
      start = Math.max(0, Math.min(maxStart, Math.floor(idx / count) * count));
    }
  }
  return {
    items: days.slice(start, start + count),
    startIndex: start,
    canPrev: start > 0,
    canNext: start + count < days.length,
  };
}

/** 本地日期 YYYY-MM-DD 的零点与次日零点（毫秒时间戳）。 */
export function dayBounds(dateKey: string): { start: number; end: number } {
  const [y, m, d] = dateKey.split('-').map(Number);
  const start = new Date(y, m - 1, d, 0, 0, 0, 0).getTime();
  const end = new Date(y, m - 1, d + 1, 0, 0, 0, 0).getTime();
  return { start, end };
}

/**
 * 将已确认的 Tag 数组与当前输入框草稿合并解析为去重后的关键词数组。
 * 支持空格、中英文逗号、分号切分多组关键词。
 */
export function parseTagKeywords(tags: string[], draft: string = ''): string[] {
  const raw = [...tags, ...draft.split(/[\s,，;；]+/)];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of raw) {
    const trimmed = item.trim();
    if (!trimmed) continue;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(trimmed);
  }
  return out;
}

/**
 * 按多组 Tag 关键词对会话标题或用户自定义标题做交叉筛选（AND 交集，大小写不敏感）。
 */
export function matchesSessionTitleTags(
  session: {
    title: string;
    raw_title?: string | null;
    custom_title?: string | null;
  },
  tags: string[]
): boolean {
  if (!tags.length) return true;
  const haystack = [session.title, session.custom_title, session.raw_title]
    .filter(Boolean)
    .join('\n')
    .toLowerCase();
  return tags.every((tag) => haystack.includes(tag.trim().toLowerCase()));
}

