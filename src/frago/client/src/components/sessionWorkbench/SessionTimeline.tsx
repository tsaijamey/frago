/**
 * SessionTimeline — 用量日历与会话时间轴合一浮窗。
 *
 * 1. 首先展示月历网格（每天的词元用量 + 会话数，支持切换月份与刷新）；
 * 2. 点击任意日期单元格后，切换为左右分栏：
 *    - 左侧：按日期先后顺序竖排的日期单元格列表，随各类屏幕高度自适应展示 [n, n+3] 个（6~9 个）；
 *    - 右侧：聚焦展示该日期（或所选时间窗口）下的会话时间轴；
 * 3. 右上角提供多组 Tag 型关键词筛选框：按会话标题或用户自定义标题交叉筛选会话（AND 交集），允许跨日期。
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Virtuoso } from 'react-virtuoso';
import {
  CalendarCheck,
  CalendarDays,
  CalendarPlus,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock,
  Minus,
  Plus,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';

import { getTokenCalendar } from '@/api';
import type { TokenCalendarResponse } from '@/api/client';
import i18n from '@/i18n';
import type { ForYouState } from '@/hooks/useForYou';
import type { SessionTodayState } from '@/hooks/useSessionToday';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import { useAppStore } from '@/stores/appStore';
import {
  computeVisibleDayCount,
  dayBounds,
  formatTokens,
  matchesSessionTitleTags,
  MIN_VISIBLE_DATE_CELLS,
  monthDaysList,
  monthMatrix,
  parseTagKeywords,
  shiftMonth,
  sliceVisibleDays,
  toDateKey,
} from './tokenCalendarUtils';

/** 日期与刻度跟界面语言走；不跟浏览器/系统语言走。 */
function locale(): string | undefined {
  return i18n.language || undefined;
}

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/**
 * 显式档位。
 * 「全部」不在这一组里——它是一个独立的状态（`fitAll`），跨度等于这台机器的全部历史。
 */
const SPAN_HOURS = [24, 72, 168, 720] as const;
const SPAN_KEYS = [
  'workbench.timeline.spans.24h',
  'workbench.timeline.spans.3d',
  'workbench.timeline.spans.7d',
  'workbench.timeline.spans.30d',
] as const;
/** 档位按钮上的短写法：24h / 3d / 7d / 30d，五个按钮在窄窗里也摆得下。 */
const SPAN_SHORT_KEYS = [
  'workbench.timeline.shortSpans.24h',
  'workbench.timeline.shortSpans.3d',
  'workbench.timeline.shortSpans.7d',
  'workbench.timeline.shortSpans.30d',
] as const;
const DEFAULT_SPAN_INDEX = 2;

/** 条最少 24px 宽：比条高（20px）宽，缩到再远也是横着的一笔。 */
const MIN_BAR_PX = 24;
/** 标题最宽 360px：有的会话标题就是开口那一整段话，不限宽会铺半屏。 */
const MAX_LABEL_PX = 360;
const PAD = 8;
const ROW_HEIGHT = 26;

/**
 * 右端留出的未来空白：占窗口宽度的比例，最多两天。
 */
const FUTURE_FRACTION = 0.08;
const FUTURE_MAX = 2 * DAY;

const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;

interface Lane {
  s: WorkbenchSession;
  start: number;
  last: number;
  noReply: boolean;
}

interface Block {
  heads: Lane[];
  kids: Lane[] | null;
  hidden: number;
  sortAt: number;
}

interface Tick {
  at: number;
  label: string;
  day: boolean;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function formatDuration(ms: number): string {
  const m = Math.max(1, Math.round(ms / 60_000));
  if (m < 60) return `${m}m`;
  if (m < 1440) return m % 60 ? `${Math.floor(m / 60)}h ${pad2(m % 60)}` : `${Math.floor(m / 60)}h`;
  return `${(Math.round(m / 144) / 10).toFixed(1)}d`;
}

function stamp(ms: number): string {
  return new Date(ms).toLocaleString(locale(), {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function weekdayKeyOfDate(dateKey: string): (typeof WEEKDAY_KEYS)[number] {
  const [y, m, d] = dateKey.split('-').map(Number);
  const idx = (new Date(y, m - 1, d).getDay() + 6) % 7;
  return WEEKDAY_KEYS[idx];
}

/**
 * 会话铺成条：左端创建时刻，右端最后一句回复。没有回复时两端同点（画成空心条）。
 */
function toLanes(sessions: WorkbenchSession[]): Lane[] {
  const seen = new Set<string>();
  const out: Lane[] = [];
  for (const s of sessions) {
    if (seen.has(s.session_id)) continue;
    seen.add(s.session_id);
    const last = s.last_reply_at ?? s.created_at;
    const start = Math.min(s.created_at, last);
    out.push({ s, start, last, noReply: s.last_reply_at === null });
  }
  return out;
}

/**
 * 父子聚成一块。规则照左栏（`SessionRail` 的 trunkRows / childrenOf / orphanRows）：
 * ① 认得出派它的那场、那场也在窗口里 → 折到那场下面；
 * ② 是 worker 但认不出父、或父不在窗口里 → 收进末尾「认不出父会话的 worker」那一组；
 * ③ 其余 → 主干。
 */
function groupLanes(all: Lane[], inWin: Lane[]): { blocks: Block[]; lanes: Lane[] } {
  const byId = new Map(all.map((x) => [x.s.session_id, x]));
  const inIds = new Set(inWin.map((x) => x.s.session_id));
  const kids = new Map<string, Lane[]>();
  for (const x of all) {
    const s = x.s;
    const p = s.parent_session_id;
    if (
      !p ||
      p === s.session_id ||
      !byId.has(p) ||
      s.origin !== 'worker' ||
      s.relation?.kind === 'branch'
    ) {
      continue;
    }
    const bucket = kids.get(p);
    if (bucket) bucket.push(x);
    else kids.set(p, [x]);
  }

  const done = new Set<string>();
  const claimed = new Set<string>();
  const blocks: Block[] = [];
  for (const x of inWin) {
    const id = x.s.session_id;
    if (done.has(id) || claimed.has(id)) continue;
    const s = x.s;
    const isKid =
      s.origin === 'worker' &&
      Boolean(s.parent_session_id) &&
      s.parent_session_id !== s.session_id &&
      byId.has(s.parent_session_id as string) &&
      s.relation?.kind !== 'branch';
    if (isKid) continue;
    done.add(id);
    const allKids = kids.get(id) ?? [];
    const mine = allKids.filter((k) => inIds.has(k.s.session_id));
    for (const k of mine) claimed.add(k.s.session_id);
    blocks.push({
      heads: [x],
      kids: mine,
      hidden: allKids.length - mine.length,
      sortAt: Math.max(x.start, ...mine.map((k) => k.last)),
    });
  }
  const lone = inWin.filter((x) => !done.has(x.s.session_id) && !claimed.has(x.s.session_id));
  if (lone.length) blocks.push({ heads: lone, kids: null, hidden: 0, sortAt: 0 });
  blocks.sort((p, q) => q.sortAt - p.sortAt);
  return { blocks, lanes: blocks.flatMap((b) => b.heads.concat(b.kids ?? [])) };
}

function ticksFor(start: number, end: number, span: number): Tick[] {
  const step =
    span <= 8 * HOUR
      ? HOUR
      : span <= 30 * HOUR
        ? 3 * HOUR
        : span <= 4 * DAY
          ? 12 * HOUR
          : span <= 12 * DAY
            ? DAY
            : span <= 40 * DAY
              ? 7 * DAY
              : span <= 130 * DAY
                ? 30 * DAY
                : 90 * DAY;
  const tz = new Date().getTimezoneOffset() * 60_000;
  const first =
    step >= DAY ? Math.ceil((start - tz) / step) * step + tz : Math.ceil(start / step) * step;
  const nowYear = new Date().getFullYear();
  const out: Tick[] = [];
  for (let t = first; t <= end; t += step) {
    const d = new Date(t);
    const at = (t - start) / span;
    const midnight = d.getHours() === 0 && d.getMinutes() === 0;
    const day = step >= DAY || midnight;
    const month = d.toLocaleDateString(locale(), { month: 'short' });
    const label =
      step >= 30 * DAY
        ? d.getFullYear() !== nowYear
          ? `${month} ${d.getFullYear()}`
          : month
        : day
          ? `${d.toLocaleDateString(locale(), { weekday: 'short' })} ${d.getDate()} ${month}`
          : `${pad2(d.getHours())}:00`;
    out.push({ at, label, day });
  }
  return out;
}

function spanIndexAt(span: number): number {
  let index = 0;
  SPAN_HOURS.forEach((h, i) => {
    if (h * HOUR <= span) index = i;
  });
  return index;
}

export interface SessionTimelineProps {
  sessions: WorkbenchSession[];
  selectedId: string | null;
  /** 哪几场挂着 For you（条上画一个小圆点）。 */
  forYou?: ForYouState;
  /** 今天捡回来的名单：条右侧的「+ Today / Remove」改的就是它。 */
  today: SessionTodayState;
  onSelect: (sessionId: string) => void;
  onClose: () => void;
  /** 可选初始选中日期（YYYY-MM-DD）；默认 null 即首先展示月历网格。 */
  initialDate?: string | null;
}

export default function SessionTimeline({
  sessions,
  selectedId,
  forYou,
  today,
  onSelect,
  onClose,
  initialDate = null,
}: SessionTimelineProps) {
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);

  const todayKey = useMemo(() => toDateKey(new Date()), []);
  const [month, setMonth] = useState(() => (initialDate ? initialDate.slice(0, 7) : todayKey.slice(0, 7)));
  const [selectedDate, setSelectedDate] = useState<string | null>(initialDate);
  const [crossDateMode, setCrossDateMode] = useState(false);

  // Token calendar data
  const [calData, setCalData] = useState<TokenCalendarResponse | null>(null);
  const [calLoading, setCalLoading] = useState(false);
  const [calError, setCalError] = useState<string | null>(null);

  const fetchMonth = useCallback(async (m: string) => {
    setCalLoading(true);
    setCalError(null);
    try {
      const res = await getTokenCalendar(m);
      setCalData(res);
    } catch (e) {
      setCalError(e instanceof Error ? e.message : String(e));
    } finally {
      setCalLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchMonth(month);
  }, [month, fetchMonth]);

  // Tag filter state
  const [filterTags, setFilterTags] = useState<string[]>([]);
  const [filterDraft, setFilterDraft] = useState('');
  const activeTags = useMemo(
    () => parseTagKeywords(filterTags, filterDraft),
    [filterTags, filterDraft]
  );

  // Left vertical date rail adaptive count (between n and n + 3)
  const dateRailListRef = useRef<HTMLDivElement>(null);
  const [visibleDayCount, setVisibleDayCount] = useState<number>(() =>
    computeVisibleDayCount(typeof window !== 'undefined' ? window.innerHeight - 180 : 500, MIN_VISIBLE_DATE_CELLS)
  );
  const [manualDayOffset, setManualDayOffset] = useState<number | null>(null);

  const splitView = selectedDate !== null || (activeTags.length > 0 && crossDateMode);

  useEffect(() => {
    if (!splitView) return;
    const el = dateRailListRef.current;
    const updateHeight = () => {
      const h = el?.clientHeight || (typeof window !== 'undefined' ? window.innerHeight - 180 : 500);
      setVisibleDayCount(computeVisibleDayCount(h, MIN_VISIBLE_DATE_CELLS));
    };
    updateHeight();
    if (typeof ResizeObserver !== 'undefined' && el) {
      const observer = new ResizeObserver(updateHeight);
      observer.observe(el);
      return () => observer.disconnect();
    }
    window.addEventListener('resize', updateHeight);
    return () => window.removeEventListener('resize', updateHeight);
  }, [splitView]);

  const [now, setNow] = useState(() => Date.now());
  const [spanIndex, setSpanIndex] = useState(DEFAULT_SPAN_INDEX);
  const [fitAll, setFitAll] = useState(false);
  /** 窗口右端；null = 跟着「现在」走。 */
  const [end, setEnd] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  /** Virtuoso 真正用来滚动的那个元素。滚轮、拖动都挂在它上面。 */
  const [scroller, setScroller] = useState<HTMLElement | null>(null);

  const draggedRef = useRef(false);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  /** 先按全部会话转成 Lane，再按多组 Tag 交叉筛选标题与用户自定义标题。 */
  const allLanes = useMemo(() => toLanes(sessions), [sessions]);
  const lanes = useMemo(
    () => (activeTags.length ? allLanes.filter((x) => matchesSessionTitleTags(x.s, activeTags)) : allLanes),
    [allLanes, activeTags]
  );

  const oldest = useMemo(
    () => (lanes.length ? lanes.reduce((m, x) => Math.min(m, x.start), now) : now - DAY),
    [lanes, now]
  );
  const newest = useMemo(
    () => (lanes.length ? lanes.reduce((m, x) => Math.max(m, x.last), 0) : now),
    [lanes, now]
  );
  const extent = Math.max(1, now - oldest);
  /** 数据窗口本身的宽度（不含右侧未来空白）。 */
  const baseSpan = fitAll ? Math.max(6 * HOUR, extent) : SPAN_HOURS[spanIndex] * HOUR;
  /** 右侧未来空白。选中非今天的历史单日且在 24h 档时不加未来空白，精准对齐当天 00:00~24:00。 */
  const isHistoricalSingleDay =
    selectedDate !== null && selectedDate !== todayKey && !fitAll && spanIndex === 0 && end !== null;
  const futurePad = isHistoricalSingleDay ? 0 : Math.min(baseSpan * FUTURE_FRACTION, FUTURE_MAX);
  const span = baseSpan + futurePad;
  const winEnd = (end ?? now) + futurePad;
  const winStart = winEnd - span;

  const [y, m] = month.split('-').map(Number);
  const weeks = useMemo(() => monthMatrix(month), [month]);
  const orderedMonthDays = useMemo(() => monthDaysList(month), [month]);

  /** 按日期（YYYY-MM-DD）统计当前命中的会话数。 */
  const sessionCountByDate = useMemo(() => {
    const map = new Map<string, number>();
    const allCells = weeks.flat();
    for (const cell of allCells) {
      const { start, end: dayEnd } = dayBounds(cell.date);
      let count = 0;
      for (const x of lanes) {
        if (x.last >= start && x.start < dayEnd) {
          count += 1;
        }
      }
      map.set(cell.date, count);
    }
    return map;
  }, [weeks, lanes]);

  const daySlice = useMemo(
    () =>
      sliceVisibleDays(
        orderedMonthDays,
        selectedDate ?? (todayKey.startsWith(month) ? todayKey : orderedMonthDays[0]?.date ?? null),
        visibleDayCount,
        manualDayOffset
      ),
    [orderedMonthDays, selectedDate, todayKey, month, visibleDayCount, manualDayOffset]
  );

  /** 点击日期单元格：进入左竖排日期 + 右 Timeline 分栏，聚焦到所选日期；若已在左栏可见列表中则原地选中不跳动。 */
  const handleSelectDateCell = useCallback(
    (dateKey: string) => {
      const targetMonth = dateKey.slice(0, 7);
      if (targetMonth !== month) {
        setMonth(targetMonth);
        setManualDayOffset(null);
      } else if (splitView && daySlice.items.some((c) => c.date === dateKey)) {
        setManualDayOffset(daySlice.startIndex);
      } else {
        setManualDayOffset(null);
      }
      setSelectedDate(dateKey);
      setCrossDateMode(false);
      setFitAll(false);
      // 聚焦到所选这一天（24h 窗口）
      setSpanIndex(0);
      if (dateKey === todayKey) {
        setEnd(null);
      } else {
        const { end: dayEnd } = dayBounds(dateKey);
        setEnd(dayEnd);
      }
    },
    [daySlice.items, daySlice.startIndex, month, splitView, todayKey]
  );

  /** 开启跨日期全部命中模式。 */
  const activateCrossDate = useCallback(() => {
    setCrossDateMode(true);
    setSelectedDate(null);
    setFitAll(true);
    setEnd(null);
  }, []);

  /** 返回完整月历网格。 */
  const handleBackToCalendar = useCallback(() => {
    setSelectedDate(null);
    setCrossDateMode(false);
  }, []);

  /** Tag 输入框提交一个或多个词。 */
  const commitDraftTags = useCallback(
    (rawDraft: string) => {
      const parts = rawDraft
        .split(/[\s,，;；]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (!parts.length) return;
      setFilterTags((prev) => parseTagKeywords([...prev, ...parts], ''));
      setFilterDraft('');
      // 输入筛选词时若尚未选中日期，自动展开跨日期 Timeline
      if (!selectedDate) {
        setCrossDateMode(true);
        setFitAll(true);
        setEnd(null);
      }
    },
    [selectedDate]
  );

  const handleFilterInputChange = (value: string) => {
    // 若用户输入了逗号或分号结尾，立即固化成胶囊
    if (/[,，;；]\s*$/.test(value)) {
      commitDraftTags(value);
      return;
    }
    setFilterDraft(value);
    if (value.trim() && !selectedDate) {
      setCrossDateMode(true);
      setFitAll(true);
      setEnd(null);
    }
  };

  const handleFilterKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (filterDraft.trim()) {
        commitDraftTags(filterDraft);
      }
    } else if (e.key === 'Backspace' && !filterDraft && filterTags.length > 0) {
      e.preventDefault();
      setFilterTags((prev) => prev.slice(0, -1));
    }
  };

  const removeFilterTag = (tagToRemove: string) => {
    setFilterTags((prev) => prev.filter((tItem) => tItem !== tagToRemove));
  };

  const clearAllFilterTags = () => {
    setFilterTags([]);
    setFilterDraft('');
    if (!selectedDate) {
      setCrossDateMode(false);
    }
  };

  const clampEnd = useCallback(
    (value: number, size: number) => {
      if (size >= extent) return now;
      return Math.max(oldest, Math.min(now + size, value));
    },
    [extent, now, oldest]
  );

  const leaveAll = useCallback(
    (size: number) => {
      if (!fitAll) return;
      setFitAll(false);
      setSpanIndex(spanIndexAt(size));
    },
    [fitAll]
  );

  const pan = useCallback(
    (dir: number) => {
      const size = fitAll ? SPAN_HOURS[spanIndexAt(baseSpan)] * HOUR : baseSpan;
      if (fitAll) leaveAll(baseSpan);
      const base = end ?? now;
      setEnd(clampEnd(base + dir * size, size));
    },
    [baseSpan, clampEnd, end, fitAll, leaveAll, now]
  );

  const zoom = useCallback(
    (d: number) => {
      if (fitAll) {
        if (d > 0) return;
        leaveAll(Math.max(1, extent - 1));
        return;
      }
      setSpanIndex((i) => Math.min(SPAN_HOURS.length - 1, Math.max(0, i + d)));
    },
    [extent, fitAll, leaveAll]
  );

  const chooseSpan = useCallback((index: number) => {
    setFitAll(false);
    setSpanIndex(index);
  }, []);

  const fitEverything = useCallback(() => {
    setFitAll(true);
    setEnd(null);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inInput =
        target &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (inInput || !splitView) return;
      if (e.key === '-' || e.key === '_') {
        e.preventDefault();
        zoom(1);
      } else if (e.key === '+' || e.key === '=') {
        e.preventDefault();
        zoom(-1);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        pan(-1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        pan(1);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, pan, splitView, zoom]);

  /** 滚轮只拦 shift / 横向滚动；ctrl/cmd 留给浏览器缩放与触控板捏合。 */
  useEffect(() => {
    if (!scroller) return;
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) return;
      const dx = e.shiftKey ? e.deltaY : e.deltaX;
      if (!dx) return;
      e.preventDefault();
      const size = fitAll ? SPAN_HOURS[spanIndexAt(baseSpan)] * HOUR : baseSpan;
      if (fitAll) leaveAll(baseSpan);
      const base = end ?? now;
      setEnd(clampEnd(base + (dx / 600) * (size / 8), size));
    };
    scroller.addEventListener('wheel', onWheel, { passive: false });
    return () => scroller.removeEventListener('wheel', onWheel);
  }, [baseSpan, clampEnd, end, fitAll, leaveAll, now, scroller]);

  /** 轨道区按住左右拖：时间跟着鼠标走；动了超过 4px 就不再当成点击那一条。 */
  useEffect(() => {
    if (!scroller) return;
    const onDown = (e: MouseEvent) => {
      if (e.button !== 0) return;
      if ((e.target as HTMLElement).closest('[data-lane-action]')) return;
      const size = fitAll ? SPAN_HOURS[spanIndexAt(baseSpan)] * HOUR : baseSpan;
      if (fitAll) leaveAll(baseSpan);
      const startX = e.clientX;
      const startEnd = end ?? now;
      const pw = Math.max(80, scroller.clientWidth);
      let moved = false;
      draggedRef.current = false;
      setDragging(true);

      const move = (ev: MouseEvent) => {
        const dx = ev.clientX - startX;
        if (Math.abs(dx) > 4) moved = true;
        if (!moved) return;
        draggedRef.current = true;
        setEnd(clampEnd(startEnd - (dx / pw) * size, size));
      };
      const up = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        setDragging(false);
        window.setTimeout(() => {
          draggedRef.current = false;
        }, 0);
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    };
    scroller.addEventListener('mousedown', onDown);
    return () => scroller.removeEventListener('mousedown', onDown);
  }, [baseSpan, clampEnd, end, fitAll, leaveAll, now, scroller]);

  const inWin = useMemo(() => {
    if (crossDateMode && activeTags.length > 0 && fitAll) {
      return lanes;
    }
    return lanes.filter((x) => x.last >= winStart && x.start <= winEnd);
  }, [activeTags.length, crossDateMode, fitAll, lanes, winEnd, winStart]);

  const { blocks, lanes: shownLanes } = useMemo(
    () => groupLanes(allLanes, inWin),
    [allLanes, inWin]
  );
  const ticks = useMemo(() => ticksFor(winStart, winEnd, span), [span, winEnd, winStart]);
  const nowAt = (now - winStart) / span;

  const trackRef = useRef<HTMLDivElement>(null);
  const thumbAt = useMemo(() => {
    const l = Math.max(0, Math.min(1, (winStart - oldest) / extent));
    const r = Math.max(0, Math.min(1, (winEnd - oldest) / extent));
    return { l, w: Math.max(r - l, 0) };
  }, [extent, oldest, winEnd, winStart]);

  const onThumbDown = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const size = fitAll ? SPAN_HOURS[spanIndexAt(baseSpan)] * HOUR : baseSpan;
    if (fitAll) leaveAll(baseSpan);
    const track = trackRef.current;
    if (!track) return;
    const rect = track.getBoundingClientRect();
    const startX = e.clientX;
    const startEnd = end ?? now;
    const k = extent / Math.max(40, rect.width);
    setDragging(true);
    const move = (ev: MouseEvent) => {
      setEnd(clampEnd(startEnd + (ev.clientX - startX) * k, size));
    };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      setDragging(false);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  };

  const onTrackDown = (e: ReactMouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('[data-thumb]')) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const at = (e.clientX - rect.left) / Math.max(1, rect.width);
    const dir = at < thumbAt.l ? -1 : 1;
    const size = fitAll ? SPAN_HOURS[spanIndexAt(baseSpan)] * HOUR : baseSpan;
    if (fitAll) leaveAll(baseSpan);
    setEnd(clampEnd((end ?? now) + dir * size, size));
  };

  const toggleToday = async (sid: string) => {
    try {
      await today.toggle(sid);
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : t('workbench.errors.todaySaveFailedPlain'),
        'error'
      );
    }
  };

  const selectLane = useCallback(
    (sid: string) => {
      if (draggedRef.current) return;
      onSelect(sid);
    },
    [onSelect]
  );

  const forYouCount = shownLanes.filter((x) => forYou?.infoOf(x.s.session_id)).length;
  const runningCount = shownLanes.filter((x) => x.s.status === 'running').length;
  const spanLabel = fitAll ? t('workbench.timeline.everything') : t(SPAN_KEYS[spanIndex]);

  const laneTitle = (x: Lane, hidden: number): string => {
    const s = x.s;
    const duration = x.noReply ? t('workbench.timeline.noReply') : formatDuration(x.last - x.start);
    return [
      s.title,
      `${t('workbench.timeline.started', { time: stamp(x.start) })} · ${
        x.noReply
          ? t('workbench.timeline.noReply')
          : t('workbench.timeline.lastReply', { time: stamp(x.last) })
      } · ${duration}`,
      [
        s.family,
        s.in_tmux ? t('workbench.timeline.openInTmux') : '',
        s.origin === 'worker' ? t('workbench.timeline.workerOf') : '',
        today.isPicked(s.session_id) ? t('workbench.timeline.addedToday') : '',
        hidden ? t('workbench.timeline.hiddenWorkers', { count: hidden }) : '',
      ]
        .filter(Boolean)
        .join(' · '),
    ].join('\n');
  };

  const shiftDayWindow = useCallback(
    (delta: number) => {
      setManualDayOffset((cur) => {
        const base = cur ?? daySlice.startIndex;
        const maxStart = Math.max(0, orderedMonthDays.length - visibleDayCount);
        return Math.max(0, Math.min(maxStart, base + delta));
      });
    },
    [daySlice.startIndex, orderedMonthDays.length, visibleDayCount]
  );

  void newest;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('workbench.timeline.title')}
      data-testid="session-timeline"
      className="fixed inset-0 z-[80] flex p-4"
    >
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-[12px] border border-border-strong bg-bg-primary shadow-[0_20px_60px_rgba(0,0,0,0.5)]">
        {/* 顶栏：左侧月份导航 + 当月总量 + 刷新；右上角多组 Tag 筛选框 + 关闭按钮 */}
        <div className="flex min-h-[48px] shrink-0 flex-wrap items-center gap-2 border-b border-border-color px-3.5 py-1.5">
          <div className="flex items-center gap-1.5">
            {splitView ? (
              <button
                type="button"
                data-testid="timeline-back-calendar"
                onClick={handleBackToCalendar}
                className="mr-1 inline-flex h-7 items-center gap-1 rounded-[6px] border border-border-color bg-bg-secondary px-2 text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
                title={t('workbench.timeline.backToCalendar')}
              >
                <CalendarDays size={13} strokeWidth={1.5} />
                <span>{t('workbench.timeline.backToCalendar')}</span>
              </button>
            ) : (
              <CalendarDays size={15} strokeWidth={1.5} className="shrink-0 text-text-muted" />
            )}

            <button
              type="button"
              data-testid="calendar-prev-month"
              onClick={() => {
                setMonth((cur) => shiftMonth(cur, -1));
                setManualDayOffset(null);
              }}
              aria-label={t('tokenCalendar.prevMonth')}
              className="flex h-7 w-7 items-center justify-center rounded-[6px] border border-border-color text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
            >
              <ChevronLeft size={15} />
            </button>
            <span
              data-testid="calendar-month-label"
              className="min-w-[6.5em] text-center text-[13.5px] font-semibold text-text-primary"
            >
              {t('tokenCalendar.monthLabel', {
                year: y,
                month: m,
                month2: String(m).padStart(2, '0'),
              })}
            </span>
            <button
              type="button"
              data-testid="calendar-next-month"
              onClick={() => {
                setMonth((cur) => shiftMonth(cur, 1));
                setManualDayOffset(null);
              }}
              aria-label={t('tokenCalendar.nextMonth')}
              className="flex h-7 w-7 items-center justify-center rounded-[6px] border border-border-color text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
            >
              <ChevronRight size={15} />
            </button>

            <span className="ml-1.5 text-[12px] text-text-secondary" data-testid="calendar-month-total">
              {t('tokenCalendar.monthTotal')}:{' '}
              <strong className="font-mono text-[13px] text-text-primary">
                {calData ? formatTokens(calData.month_total.total) : '—'}
              </strong>
              {calData && calData.month_total.total > 0 ? (
                <span className="ml-2 font-mono text-[11px] text-text-muted">
                  {t('tokenCalendar.inputShort')} {formatTokens(calData.month_total.input)} ·{' '}
                  {t('tokenCalendar.outputShort')} {formatTokens(calData.month_total.output)}
                </span>
              ) : null}
            </span>

            <button
              type="button"
              data-testid="calendar-refresh"
              onClick={() => void fetchMonth(month)}
              disabled={calLoading}
              title={t('tokenCalendar.refresh')}
              aria-label={t('tokenCalendar.refresh')}
              className="flex h-7 w-7 items-center justify-center rounded-[6px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-50"
            >
              <RefreshCw size={13} className={calLoading ? 'cs-spin' : ''} />
            </button>
          </div>

          {/* 右上角：多组 Tag 型关键词交叉筛选输入框 + 关闭按钮 */}
          <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-2">
            <div
              data-testid="timeline-tag-filter"
              className="flex min-h-[30px] w-full max-w-[460px] flex-wrap items-center gap-1 rounded-[8px] border border-border-color bg-bg-secondary px-2 py-0.5 text-[12px] focus-within:border-border-strong"
            >
              <Search size={13} strokeWidth={1.5} className="shrink-0 text-text-muted" />
              {filterTags.map((tag) => (
                <span
                  key={tag}
                  data-testid="timeline-filter-tag"
                  className="inline-flex h-5 items-center gap-1 rounded-[4px] border border-border-color bg-bg-active px-1.5 text-[11px] font-medium text-text-primary"
                >
                  <span>{tag}</span>
                  <button
                    type="button"
                    onClick={() => removeFilterTag(tag)}
                    aria-label={t('workbench.timeline.removeTag', { tag })}
                    className="text-text-muted hover:text-text-primary"
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
              <input
                type="text"
                data-testid="timeline-filter-input"
                value={filterDraft}
                onChange={(e) => handleFilterInputChange(e.target.value)}
                onKeyDown={handleFilterKeyDown}
                onBlur={() => {
                  if (filterDraft.trim()) commitDraftTags(filterDraft);
                }}
                placeholder={
                  filterTags.length ? '' : t('workbench.timeline.filterPlaceholder')
                }
                className="min-w-[120px] flex-1 bg-transparent py-0.5 text-[12px] text-text-primary placeholder:text-text-muted focus:outline-none"
              />
              {activeTags.length > 0 ? (
                <button
                  type="button"
                  data-testid="timeline-filter-clear"
                  onClick={clearAllFilterTags}
                  title={t('workbench.timeline.clearFilter')}
                  aria-label={t('workbench.timeline.clearFilter')}
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-text-muted hover:bg-bg-hover hover:text-text-primary"
                >
                  <X size={12} />
                </button>
              ) : null}
            </div>

            <HeaderButton
              testId="timeline-close"
              label={t('workbench.timeline.close')}
              onClick={onClose}
            >
              <X size={16} />
            </HeaderButton>
          </div>
        </div>

        {calLoading ? (
          <div className="cs-cal-progress shrink-0">
            <div className="cs-cal-progress-bar" />
          </div>
        ) : null}
        {calError ? (
          <div className="cs-cal-error shrink-0 px-3.5 py-1.5">
            {t('tokenCalendar.error', { error: calError })}{' '}
            <button type="button" className="cs-cal-retry" onClick={() => void fetchMonth(month)}>
              {t('tokenCalendar.retry')}
            </button>
          </div>
        ) : null}

        {/* 主体区：首先展示大日历网格；点击日期或输入筛选词后变为左竖排日期 + 右 Timeline */}
        {!splitView ? (
          <div
            data-testid="timeline-calendar-grid"
            className="flex min-h-0 flex-1 flex-col justify-between gap-2.5 overflow-auto p-4"
          >
            {/* 7 列月历网格：靠底色明暗（bg-card vs bg-secondary）、字号对比与留白区分层次，格内不画任何分割线或进度条 */}
            <div
              className="grid min-h-0 flex-1 grid-cols-7 gap-2"
              style={{ gridTemplateRows: `24px repeat(${weeks.length}, minmax(88px, 1fr))` }}
            >
              {WEEKDAY_KEYS.map((k) => (
                <div
                  key={k}
                  className="flex items-center px-3 text-[11.5px] font-medium text-text-muted"
                >
                  {t(`tokenCalendar.weekday.${k}`)}
                </div>
              ))}
              {weeks.flat().map((cell) => {
                const bucket = calData?.days[cell.date];
                const hasTokens = Boolean(bucket && bucket.total > 0);
                const daySessionCount = sessionCountByDate.get(cell.date) ?? 0;
                const hasActivity = hasTokens || daySessionCount > 0;
                const isToday = cell.date === todayKey;

                return (
                  <button
                    key={cell.date}
                    type="button"
                    data-testid={`calendar-cell-${cell.date}`}
                    data-date={cell.date}
                    data-active={hasActivity ? 'true' : 'false'}
                    onClick={() => handleSelectDateCell(cell.date)}
                    title={
                      bucket
                        ? t('tokenCalendar.cellTooltip', {
                            input: formatTokens(bucket.input),
                            output: formatTokens(bucket.output),
                            cacheCreation: formatTokens(bucket.cache_creation),
                            cacheRead: formatTokens(bucket.cache_read),
                          })
                        : undefined
                    }
                    className={`group flex min-h-0 flex-col justify-between rounded-[10px] border p-3.5 text-left transition-colors ${
                      !cell.inMonth
                        ? 'border-transparent bg-transparent opacity-30 hover:bg-bg-secondary hover:opacity-60'
                        : isToday
                          ? 'border-accent-primary bg-bg-card hover:bg-bg-hover'
                          : hasActivity
                            ? 'border-border-color bg-bg-card hover:border-border-strong hover:bg-bg-hover'
                            : 'border-transparent bg-bg-secondary hover:border-border-color hover:bg-bg-hover'
                    }`}
                  >
                    {/* 顶行：左上日期数字，右上纯文字会话数（不套胶囊框） */}
                    <div className="flex w-full items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`font-mono text-[13px] ${
                            isToday
                              ? 'font-semibold text-accent-primary'
                              : hasActivity
                                ? 'font-medium text-text-secondary'
                                : 'text-text-dim'
                          }`}
                        >
                          {cell.day}
                        </span>
                        {isToday ? (
                          <span className="text-[11px] font-medium text-accent-primary">
                            {t('workbench.timeline.todayShort')}
                          </span>
                        ) : null}
                      </div>
                      {daySessionCount > 0 ? (
                        <span className="font-mono text-[11px] text-text-muted">
                          {t('workbench.timeline.daySessionsCount', { count: daySessionCount })}
                        </span>
                      ) : null}
                    </div>

                    {/* 底行：仅在有 token 用量时展示大字总量 + 淡字入/出，不画横条、不画分割线、不画破折号 */}
                    {hasTokens && bucket ? (
                      <div className="flex w-full flex-col gap-1">
                        <span className="font-mono text-[20px] font-semibold leading-none tracking-tight text-text-primary">
                          {formatTokens(bucket.total)}
                        </span>
                        <span className="truncate font-mono text-[11px] text-text-muted">
                          {t('tokenCalendar.inputShort')} {formatTokens(bucket.input)} ·{' '}
                          {t('tokenCalendar.outputShort')} {formatTokens(bucket.output)}
                        </span>
                      </div>
                    ) : null}
                  </button>
                );
              })}
            </div>

            <div className="flex shrink-0 items-center justify-between text-[11.5px] text-text-muted">
              <span>{t('workbench.timeline.clickDayHint')}</span>
              {activeTags.length > 0 ? (
                <button
                  type="button"
                  onClick={activateCrossDate}
                  className="font-medium text-accent-primary hover:underline"
                >
                  {t('workbench.timeline.crossDateCount', { count: lanes.length })} →
                </button>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 overflow-hidden">
            {/* 左侧栏：竖排顺序排列的日期，至少展示 n 个、最多展示 n+3 个 */}
            <aside
              data-testid="timeline-date-rail"
              onWheel={(e) => {
                if (Math.abs(e.deltaY) < 4) return;
                e.preventDefault();
                shiftDayWindow(e.deltaY > 0 ? 1 : -1);
              }}
              className="flex w-[216px] shrink-0 flex-col border-r border-border-color bg-bg-secondary p-2"
            >
              {activeTags.length > 0 ? (
                <button
                  type="button"
                  data-testid="timeline-cross-date"
                  aria-pressed={crossDateMode}
                  onClick={activateCrossDate}
                  className={`mb-1.5 flex shrink-0 items-center justify-between rounded-[8px] border px-2.5 py-1.5 text-[11.5px] transition-colors ${
                    crossDateMode
                      ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] font-semibold text-text-primary'
                      : 'border-transparent bg-bg-primary text-text-secondary hover:bg-bg-hover'
                  }`}
                >
                  <span>{t('workbench.timeline.crossDateAll')}</span>
                  <span className="font-mono text-[11px]">{lanes.length}</span>
                </button>
              ) : null}

              <button
                type="button"
                data-testid="timeline-days-prev"
                disabled={!daySlice.canPrev}
                onClick={() => shiftDayWindow(-1)}
                aria-label={t('workbench.timeline.prevDays')}
                className="mb-1 flex h-6 shrink-0 items-center justify-center rounded-[6px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-30"
              >
                <ChevronUp size={14} />
              </button>

              <div
                ref={dateRailListRef}
                data-testid="timeline-date-rail-list"
                data-visible-count={daySlice.items.length}
                className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-hidden"
              >
                {daySlice.items.map((cell) => {
                  const bucket = calData?.days[cell.date];
                  const hasTokens = Boolean(bucket && bucket.total > 0);
                  const isSelected = !crossDateMode && selectedDate === cell.date;
                  const isToday = cell.date === todayKey;
                  const wk = weekdayKeyOfDate(cell.date);
                  const sessionCount = sessionCountByDate.get(cell.date) ?? 0;
                  return (
                    <button
                      key={cell.date}
                      type="button"
                      data-testid="timeline-day-cell"
                      data-date={cell.date}
                      aria-pressed={isSelected}
                      onClick={() => handleSelectDateCell(cell.date)}
                      title={
                        bucket
                          ? t('tokenCalendar.cellTooltip', {
                              input: formatTokens(bucket.input),
                              output: formatTokens(bucket.output),
                              cacheCreation: formatTokens(bucket.cache_creation),
                              cacheRead: formatTokens(bucket.cache_read),
                            })
                          : undefined
                      }
                      className={`flex min-h-[48px] flex-1 flex-col justify-between rounded-[8px] border px-3 py-2 text-left transition-colors ${
                        isSelected
                          ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] text-text-primary'
                          : isToday
                            ? 'border-accent-primary bg-bg-card text-text-primary hover:bg-bg-hover'
                            : hasTokens || sessionCount > 0
                              ? 'border-transparent bg-bg-card text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                              : 'border-transparent bg-bg-primary text-text-muted hover:bg-bg-hover hover:text-text-secondary'
                      }`}
                    >
                      <div className="flex w-full items-center justify-between gap-1 text-[11.5px]">
                        <span className="font-mono font-medium">
                          {cell.date.slice(5)}{' '}
                          <span className="font-sans text-text-muted">
                            {t(`tokenCalendar.weekday.${wk}`)}
                          </span>
                        </span>
                        {sessionCount > 0 ? (
                          <span className="font-mono text-[10.5px] text-text-muted">
                            {t('workbench.timeline.daySessionsCount', { count: sessionCount })}
                          </span>
                        ) : null}
                      </div>
                      {hasTokens && bucket ? (
                        <div className="flex items-baseline justify-between gap-1">
                          <span className="font-mono text-[14px] font-semibold text-text-primary">
                            {formatTokens(bucket.total)}
                          </span>
                          <span className="truncate font-mono text-[10px] text-text-muted">
                            {t('tokenCalendar.inputShort')} {formatTokens(bucket.input)} ·{' '}
                            {t('tokenCalendar.outputShort')} {formatTokens(bucket.output)}
                          </span>
                        </div>
                      ) : null}
                    </button>
                  );
                })}
              </div>

              <button
                type="button"
                data-testid="timeline-days-next"
                disabled={!daySlice.canNext}
                onClick={() => shiftDayWindow(1)}
                aria-label={t('workbench.timeline.nextDays')}
                className="mt-1 flex h-6 shrink-0 items-center justify-center rounded-[6px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-30"
              >
                <ChevronDown size={14} />
              </button>
            </aside>

            {/* 右侧栏：Timeline */}
            <div data-testid="timeline-pane" className="flex min-w-0 flex-1 flex-col overflow-hidden">
              {/* Timeline 工具条：时间跨度提示 + 档位切换 + 平移/缩放 */}
              <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border-color bg-bg-secondary px-3">
                <Clock size={13} strokeWidth={1.5} className="shrink-0 text-text-muted" />
                <span className="min-w-0 truncate whitespace-nowrap font-mono text-[11.5px] text-text-muted">
                  {stamp(winStart)} → {stamp(winEnd)} · {spanLabel}
                </span>
                {activeTags.length > 0 ? (
                  <span className="rounded bg-bg-active px-1.5 py-0.5 text-[11px] text-text-secondary">
                    {t('workbench.timeline.crossDateCount', { count: lanes.length })}
                  </span>
                ) : null}

                <span className="ml-auto flex shrink-0 items-center gap-1">
                  <span className="flex items-center gap-0.5 rounded-[6px] bg-bg-subtle p-0.5">
                    {SPAN_HOURS.map((h, i) => (
                      <button
                        key={h}
                        type="button"
                        data-testid={`timeline-span-${h}`}
                        aria-pressed={!fitAll && spanIndex === i}
                        onClick={() => chooseSpan(i)}
                        className={`h-[22px] rounded-[4px] px-1.5 text-[11px] transition-colors ${
                          !fitAll && spanIndex === i
                            ? 'bg-bg-active font-medium text-text-primary'
                            : 'text-text-muted hover:bg-bg-hover hover:text-text-secondary'
                        }`}
                      >
                        {t(SPAN_SHORT_KEYS[i])}
                      </button>
                    ))}
                    <button
                      type="button"
                      data-testid="timeline-span-all"
                      aria-pressed={fitAll}
                      onClick={fitEverything}
                      className={`h-[22px] rounded-[4px] px-1.5 text-[11px] transition-colors ${
                        fitAll
                          ? 'bg-bg-active font-medium text-text-primary'
                          : 'text-text-muted hover:bg-bg-hover hover:text-text-secondary'
                      }`}
                    >
                      {t('workbench.timeline.all')}
                    </button>
                  </span>
                  <HeaderButton
                    testId="timeline-earlier"
                    label={t('workbench.timeline.earlier')}
                    onClick={() => pan(-1)}
                  >
                    <ChevronLeft size={15} />
                  </HeaderButton>
                  <HeaderButton
                    testId="timeline-later"
                    label={t('workbench.timeline.later')}
                    onClick={() => pan(1)}
                  >
                    <ChevronRight size={15} />
                  </HeaderButton>
                  <HeaderButton
                    testId="timeline-zoom-out"
                    label={t('workbench.timeline.zoomOut')}
                    onClick={() => zoom(1)}
                  >
                    <Minus size={14} />
                  </HeaderButton>
                  <HeaderButton
                    testId="timeline-zoom-in"
                    label={t('workbench.timeline.zoomIn')}
                    onClick={() => zoom(-1)}
                  >
                    <Plus size={14} />
                  </HeaderButton>
                </span>
              </div>

              {/* 轴与竖线固定在视口上；只有行的列表在虚拟化地滚。 */}
              <div className="relative min-h-0 flex-1 overflow-hidden">
                <div className="absolute inset-x-0 top-0 z-[3] h-6 overflow-hidden border-b border-border-color bg-bg-primary font-mono text-[10.5px] text-text-dim">
                  {ticks.map((k, i) => (
                    <span
                      key={i}
                      className={`absolute top-[5px] whitespace-nowrap ${
                        k.day ? 'text-text-secondary' : ''
                      }`}
                      style={
                        k.at < 0.025
                          ? { left: `${k.at * 100}%`, paddingLeft: 4 }
                          : k.at > 0.975
                            ? { left: `${k.at * 100}%`, transform: 'translateX(-100%)', paddingRight: 4 }
                            : { left: `${k.at * 100}%`, transform: 'translateX(-50%)' }
                      }
                    >
                      {k.label}
                    </span>
                  ))}
                </div>

                <div className="pointer-events-none absolute inset-x-0 bottom-0 top-6 z-0">
                  {ticks.map((k, i) => (
                    <i
                      key={i}
                      className={`absolute bottom-0 top-0 w-px ${
                        k.day ? 'bg-border-strong' : 'bg-border-color'
                      }`}
                      style={{ left: `${k.at * 100}%` }}
                    />
                  ))}
                  {nowAt >= 0 && nowAt <= 1.0001 ? (
                    <i
                      data-testid="timeline-now"
                      className="absolute bottom-0 top-0 w-px bg-text-dim opacity-80"
                      style={{ left: `calc(${nowAt * 100}% - 1px)` }}
                      title={t('workbench.timeline.now')}
                    />
                  ) : null}
                </div>

                {!shownLanes.length ? (
                  <div className="relative z-[1] flex h-full flex-col items-center justify-center gap-1 px-6 text-[12px] text-text-muted">
                    <Clock size={22} strokeWidth={1.5} />
                    <span>
                      {activeTags.length
                        ? t('workbench.timeline.emptyFiltered')
                        : t('workbench.timeline.empty')}
                    </span>
                    <span className="text-text-dim">
                      {activeTags.length
                        ? t('workbench.timeline.emptyFilteredHint')
                        : t('workbench.timeline.emptyHint')}
                    </span>
                  </div>
                ) : (
                  <Virtuoso
                    className={`absolute inset-x-0 bottom-0 top-6 ${
                      dragging ? 'cursor-grabbing select-none' : 'cursor-grab'
                    }`}
                    data={blocks}
                    defaultItemHeight={ROW_HEIGHT}
                    initialItemCount={Math.min(blocks.length, 20)}
                    scrollerRef={(ref) => setScroller(ref as HTMLElement | null)}
                    computeItemKey={(index, b) =>
                      b ? `b-${index}-${b.heads[0]?.s.session_id ?? ''}` : `b-${index}`
                    }
                    itemContent={(index, block) =>
                      block ? (
                        <BlockRows
                          block={block}
                          first={index === 0}
                          winStart={winStart}
                          span={span}
                          selectedId={selectedId}
                          today={today}
                          forYou={forYou}
                          laneTitle={laneTitle}
                          onSelect={selectLane}
                          onToggleToday={toggleToday}
                        />
                      ) : null
                    }
                  />
                )}
              </div>

              {/* 下方时间滚动条：整条 = 最早那场到现在，滑块 = 眼下窗口这一段。 */}
              <div
                ref={trackRef}
                onMouseDown={onTrackDown}
                title={`${stamp(oldest)} → ${t('workbench.timeline.now')}`}
                className="relative h-3.5 shrink-0 cursor-pointer border-t border-border-color bg-bg-secondary"
              >
                <div
                  data-thumb
                  onMouseDown={onThumbDown}
                  className={`absolute bottom-[3px] top-[3px] min-w-6 cursor-grab rounded-[4px] ${
                    dragging ? 'bg-text-dim' : 'bg-border-strong hover:bg-text-dim'
                  }`}
                  style={{ left: `${thumbAt.l * 100}%`, width: `${thumbAt.w * 100}%` }}
                />
              </div>

              <div className="flex shrink-0 items-center gap-3 border-t border-border-color bg-bg-secondary px-3 py-1.5 text-[11px] text-text-muted">
                <span className="min-w-0 flex-1 truncate">{t('workbench.timeline.footnote')}</span>
                {forYouCount ? (
                  <span className="flex shrink-0 items-center gap-1">
                    <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent-primary" />
                    {t('workbench.timeline.waitingOnYou', { count: forYouCount })}
                  </span>
                ) : null}
                {runningCount ? (
                  <span className="shrink-0">
                    {t('workbench.timeline.running', { count: runningCount })}
                  </span>
                ) : null}
                <span className="shrink-0">
                  {t('workbench.timeline.shown', { count: shownLanes.length })}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 一组（主会话 + 它派出的 worker）在虚拟化列表里是一项。
 */
function BlockRows({
  block,
  first,
  winStart,
  span,
  selectedId,
  today,
  forYou,
  laneTitle,
  onSelect,
  onToggleToday,
}: {
  block: Block;
  first: boolean;
  winStart: number;
  span: number;
  selectedId: string | null;
  today: SessionTodayState;
  forYou?: ForYouState;
  laneTitle: (x: Lane, hidden: number) => string;
  onSelect: (id: string) => void;
  onToggleToday: (id: string) => void;
}) {
  const hasKids = Boolean(block.kids && block.kids.length);
  return (
    <div
      className={`${first ? '' : 'mt-2'} ${
        hasKids ? 'rounded-[6px] shadow-[inset_0_0_0_1px_var(--border-color)]' : ''
      }`}
    >
      {block.heads.map((x) => (
        <LaneRow
          key={x.s.session_id}
          x={x}
          kind={hasKids ? 'head' : ''}
          winStart={winStart}
          span={span}
          selected={x.s.session_id === selectedId}
          picked={today.isPicked(x.s.session_id)}
          waiting={Boolean(forYou?.infoOf(x.s.session_id))}
          title={laneTitle(x, block.hidden)}
          onSelect={onSelect}
          onToggleToday={onToggleToday}
        />
      ))}
      {(block.kids ?? []).map((x) => (
        <LaneRow
          key={x.s.session_id}
          x={x}
          kind="kid"
          winStart={winStart}
          span={span}
          selected={x.s.session_id === selectedId}
          picked={today.isPicked(x.s.session_id)}
          waiting={Boolean(forYou?.infoOf(x.s.session_id))}
          title={laneTitle(x, 0)}
          onSelect={onSelect}
          onToggleToday={onToggleToday}
        />
      ))}
    </div>
  );
}

/**
 * 一行：条 + 标题 + 悬停动作。**自己量自己**。
 */
function LaneRow({
  x,
  kind,
  winStart,
  span,
  selected,
  picked,
  waiting,
  title,
  onSelect,
  onToggleToday,
}: {
  x: Lane;
  kind: 'head' | 'kid' | '';
  winStart: number;
  span: number;
  selected: boolean;
  picked: boolean;
  waiting: boolean;
  title: string;
  onSelect: (id: string) => void;
  onToggleToday: (id: string) => void;
}) {
  const rowRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();

  useLayoutEffect(() => {
    const row = rowRef.current;
    if (!row) return;
    const bar = row.querySelector<HTMLElement>('[data-bar]');
    const lb = row.querySelector<HTMLElement>('[data-label]');
    if (!bar || !lb) return;
    const width = row.clientWidth;
    if (!width) return;

    const L = ((x.start - winStart) / span) * width;
    const R = ((x.last - winStart) / span) * width;
    lb.style.maxWidth = '';
    const need = Math.min(lb.scrollWidth + 2, MAX_LABEL_PX);

    let beg = Math.max(0, L);
    let endPx = Math.min(width, R);
    const short = endPx - beg < MIN_BAR_PX;
    if (short) {
      endPx = Math.min(width, beg + MIN_BAR_PX);
      beg = endPx - MIN_BAR_PX;
    }

    const inside = endPx - beg - 2;
    const right = width - endPx + 1 - PAD;
    const left = beg - 1 - PAD;
    const spot: 'in' | 'r' | 'l' =
      inside >= need
        ? 'in'
        : right >= need
          ? 'r'
          : left >= need
            ? 'l'
            : inside >= right && inside >= left
              ? 'in'
              : right >= left
                ? 'r'
                : 'l';
    const at = spot === 'in' ? beg + 1 : spot === 'r' ? endPx - 1 : Math.max(PAD, beg + 1 - need);
    const max =
      spot === 'in'
        ? inside
        : spot === 'r'
          ? width - endPx + 1 - PAD
          : Math.max(0, beg - PAD);

    bar.style.left = `${short ? beg : L}px`;
    bar.style.width = `${short ? MIN_BAR_PX : Math.max(1, R - L)}px`;
    bar.style.borderRadius =
      spot === 'r' ? '5px 0 0 5px' : spot === 'l' ? '0 5px 5px 0' : '5px';

    lb.style.left = `${at}px`;
    lb.style.maxWidth = `${Math.min(MAX_LABEL_PX, Math.max(0, max))}px`;
    if (spot === 'in') {
      lb.style.border = '1px solid transparent';
      lb.style.borderRadius = '5px';
      lb.style.color = 'var(--text-primary)';
    } else {
      lb.style.border = '1px dashed var(--border-strong)';
      lb.style.borderLeftWidth = spot === 'l' ? '0' : '1px';
      lb.style.borderRightWidth = spot === 'r' ? '0' : '1px';
      lb.style.borderRadius = spot === 'r' ? '0 5px 5px 0' : '5px 0 0 5px';
      lb.style.color = 'var(--text-secondary)';
    }
  }, [span, winStart, x.last, x.start]);

  const duration = x.noReply ? t('workbench.timeline.noReply') : formatDuration(x.last - x.start);

  return (
    <div
      ref={rowRef}
      data-lane
      data-session-id={x.s.session_id}
      data-testid="timeline-lane"
      data-kind={kind || undefined}
      onClick={() => onSelect(x.s.session_id)}
      title={title}
      className={`group relative h-[26px] w-full cursor-pointer overflow-hidden ${
        selected ? 'bg-bg-active' : 'hover:bg-bg-hover'
      }`}
    >
      <div
        data-bar
        className={`absolute top-[3px] h-5 ${
          kind === 'kid'
            ? 'bg-[var(--timeline-bar-strong)] group-hover:bg-[var(--timeline-bar-stronger)]'
            : x.noReply
              ? 'bg-transparent ring-1 ring-inset ring-[var(--timeline-bar-strong)]'
              : 'bg-[var(--timeline-bar)] group-hover:bg-[var(--timeline-bar-strong)]'
        }`}
      />
      <div
        data-label
        className={`pointer-events-none absolute top-[3px] box-border flex h-5 items-center gap-[5px] overflow-hidden whitespace-nowrap px-[7px] text-[11.5px] leading-[18px] ${
          kind === 'kid' ? 'pl-[14px]' : ''
        }`}
      >
        {waiting ? (
          <span
            aria-hidden
            title={t('workbench.forYou.label')}
            className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent-primary"
          />
        ) : null}
        {picked ? <CalendarCheck size={12} className="shrink-0 text-text-muted" /> : null}
        <span className="min-w-0 overflow-hidden text-ellipsis">{x.s.title}</span>
        <span className="shrink-0 font-mono text-[10.5px] text-text-muted">{duration}</span>
      </div>
      {/* 悬停才出现：把这场旧会话捡进今天（或放下）。 */}
      <button
        type="button"
        data-lane-action
        data-testid={`timeline-today-${x.s.session_id}`}
        title={picked ? t('workbench.timeline.removeToday') : t('workbench.timeline.addToday')}
        onClick={(e) => {
          e.stopPropagation();
          onToggleToday(x.s.session_id);
        }}
        className={`absolute right-1 top-[3px] z-[2] hidden h-5 items-center gap-1 rounded border border-border-color bg-bg-primary px-1.5 text-[10.5px] text-text-secondary group-hover:flex hover:text-text-primary ${
          picked ? 'text-text-primary' : ''
        }`}
      >
        {picked ? <CalendarCheck size={11} /> : <CalendarPlus size={11} />}
        <span>{t('workbench.timeline.todayShort')}</span>
      </button>
    </div>
  );
}

function HeaderButton({
  testId,
  label,
  onClick,
  children,
}: {
  testId: string;
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      title={label}
      aria-label={label}
      className="flex h-7 w-7 items-center justify-center rounded-[6px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
    >
      {children}
    </button>
  );
}
