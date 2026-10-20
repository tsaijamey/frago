/**
 * SessionTimeline — 这台机器上全部会话的时间轴浮窗。
 *
 * 左栏只摆今天；这里摆**全部**。一行一场会话，横轴是时间：
 * - 左端 = 会话创建时刻；
 * - 右端 = agent 最后一句真正的文本回复（`last_reply_at`，服务端已跳过心跳与簿记）；
 * - 还没说过话的那场画成空心条，只有起点。
 *
 * 布局规则照原型 20260924-page-polish 的六轮迭代（主人 10-16、10-17 定）：
 * - **没有单独的标题列**，整条横向区域就是时间轴，标题写在条上；
 * - 标题完整装得进条里就写条里，装不下写条外，条外那一段套虚线框、与条拼成一个形状；
 *   条本身永远一种粗细（20px），缩到再远也至少 24px 宽，永远是横的；
 * - 父子会话聚成一组（规则照左栏 `SessionRail`：worker 折在派活的那场下面），组内相邻；
 * - 窗口档位**显式摆在顶上**：24 小时 / 3 天 / 7 天 / 30 天 / 全部，默认 7 天
 *   （2026-10-19 主人报「缺少 7 天窗口」后改；档位不再只藏在 −/+ 里）；
 * - ‹ › 整窗翻页；两头各放开一个窗口；
 * - shift + 滚轮、触控板横向滚动平移时间；**不拦 ctrl/cmd + 滚轮**（浏览器缩放）；
 * - 下方时间滚动条代表"最早那场到现在"，拖滑块或点空槽都能走时间。
 *
 * **行的渲染是虚拟化的。** 本机 3950 场会话，全部档位一次铺完实测二十秒以上才恢复响应；
 * 现在只渲染视口内那几十行，滚动时再接上下一批。每行自己量自己的宽度与标题，量完再写
 * 条与标题的位置（见 `LaneRow`）——不再一次性量全表。
 *
 * 从 timeline 捡旧会话：每一行悬停时右端出现「＋ Today」，点了就把这场放进今天的左栏
 * （见 `useSessionToday`）。第二天它没有新回复就自然消失——这份名单只认当天。
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Virtuoso } from 'react-virtuoso';
import {
  CalendarCheck,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Clock,
  Minus,
  Plus,
  X,
} from 'lucide-react';

import i18n from '@/i18n';
import type { ForYouState } from '@/hooks/useForYou';
import type { SessionTodayState } from '@/hooks/useSessionToday';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import { useAppStore } from '@/stores/appStore';

/** 日期与刻度跟界面语言走；不跟浏览器/系统语言走。 */
function locale(): string | undefined {
  return i18n.language || undefined;
}

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/**
 * 显式档位。默认第 2 档（7 天）：时间轴负责全部会话，24 小时只够看今天，不够做管理。
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
 *
 * 不留这段空白时，「现在」正好压在时间轴最右边：今天结束的短条右端与悬停的
 * 「+ Today」按钮重叠，想点条会先点到按钮（2026-10-19 主人报）。留出这一段之后，
 * 今天结束的条右侧仍有一截空日期，按钮落在空白里，不挡条。
 */
const FUTURE_FRACTION = 0.08;
const FUTURE_MAX = 2 * DAY;

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

/**
 * 会话铺成条：左端创建时刻，右端最后一句回复。没有回复时两端同点（画成空心条）。
 * `created_at` 偶有比 `last_reply_at` 还晚的脏数据，取两者较早的做起点。
 *
 * 同一编号只留第一行：opencode 会回原始与加工两份副本（2026-10-19 实测 4060 行里
 * 110 行重复）。服务端合并之前，时间轴先按编号收一道。
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

  // done = 已经画成一条的；claimed = 已经归到某个父会话底下的。两个集合不能合成一个。
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
  // 整日刻度落在本地零点：先按本地时区偏一下再取整。
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
}

export default function SessionTimeline({
  sessions,
  selectedId,
  forYou,
  today,
  onSelect,
  onClose,
}: SessionTimelineProps) {
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);

  const [now, setNow] = useState(() => Date.now());
  const [spanIndex, setSpanIndex] = useState(DEFAULT_SPAN_INDEX);
  const [fitAll, setFitAll] = useState(false);
  /** 窗口右端；null = 跟着「现在」走。 */
  const [end, setEnd] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  /** Virtuoso 真正用来滚动的那个元素。滚轮、拖动都挂在它上面。 */
  const [scroller, setScroller] = useState<HTMLElement | null>(null);

  /**
   * 拖过之后那一下 click 不算选中（与原型同一条 4px 门槛）。
   *
   * `LaneRow` 是虚拟化列表里的一项，拖动的监听挂在滚动容器上；点一下没有移动时，
   * 松手后的 click 照常选中。
   */
  const draggedRef = useRef(false);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const lanes = useMemo(() => toLanes(sessions), [sessions]);
  const oldest = useMemo(
    () => lanes.reduce((m, x) => Math.min(m, x.start), now),
    [lanes, now]
  );
  const extent = Math.max(1, now - oldest);
  /** 数据窗口本身的宽度（不含右侧未来空白）。 */
  const baseSpan = fitAll ? Math.max(6 * HOUR, extent) : SPAN_HOURS[spanIndex] * HOUR;
  /** 右侧未来空白。按比例给，最多两天；「全部」档也留得出可点的位置。 */
  const futurePad = Math.min(baseSpan * FUTURE_FRACTION, FUTURE_MAX);
  /** 轴的实际宽度 = 数据窗口 + 未来空白。past 这一段与从前完全一致。 */
  const span = baseSpan + futurePad;
  const winEnd = (end ?? now) + futurePad;
  const winStart = winEnd - span;

  const clampEnd = useCallback(
    (value: number, size: number) => {
      // 窗口本身就盖住整段历史时钉在「现在」：再滚也只见空。
      if (size >= extent) return now;
      // 两头各放开一个窗口；再往外只有空，没有数据。
      return Math.max(oldest, Math.min(now + size, value));
    },
    [extent, now, oldest]
  );

  /** 从「全部」回到一个真实档位：跨度不跳变，取不比眼下更宽的最大一档。 */
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
      // 从「全部」挪动时先落到一个真实档位，窗口按落下去之后那个跨度算。
      const size = fitAll ? SPAN_HOURS[spanIndexAt(baseSpan)] * HOUR : baseSpan;
      if (fitAll) leaveAll(baseSpan);
      const base = end ?? now;
      setEnd(clampEnd(base + dir * size, size));
    },
    [baseSpan, clampEnd, end, fitAll, leaveAll, now]
  );

  /** d = 1 拉远（更多天），-1 拉近（更少天）。 */
  const zoom = useCallback(
    (d: number) => {
      if (fitAll) {
        if (d > 0) return; // 全部已经是最远
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
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === '-' || e.key === '_') {
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
  }, [onClose, pan, zoom]);

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
        // 松手那一下的 click 先被吞掉，之后点轨道照常选中。
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

  const inWin = useMemo(
    () => lanes.filter((x) => x.last >= winStart && x.start <= winEnd),
    [lanes, winEnd, winStart]
  );
  const { blocks, lanes: shownLanes } = useMemo(
    () => groupLanes(lanes, inWin),
    [inWin, lanes]
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

  /** 点滑块两旁的空槽：往那边翻一整个窗口。 */
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

  /** 拖过之后松手那一下的 click 不是"选中"——与原型同一条门槛。 */
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
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border-color px-3">
          <Clock size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
          <span className="shrink-0 text-[13px] font-semibold text-text-primary">
            {t('workbench.timeline.title')}
          </span>
          <span className="min-w-0 truncate whitespace-nowrap font-mono text-[11.5px] text-text-muted">
            {/* 右端带一段未来空白，这里照实写窗口终点（会是今天之后的一刻）。 */}
            {stamp(winStart)} → {stamp(winEnd)} · {spanLabel}
          </span>

          {/* 档位显式摆出来：24h / 3d / 7d / 30d / 全部。默认 7 天。 */}
          <span className="ml-auto flex shrink-0 items-center gap-1">
            <span className="flex max-w-[52vw] items-center gap-0.5 overflow-x-auto rounded-[6px] bg-bg-subtle p-0.5">
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
            <HeaderButton
              testId="timeline-close"
              label={t('workbench.timeline.close')}
              onClick={onClose}
            >
              <X size={15} />
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
              <span>{t('workbench.timeline.empty')}</span>
              <span className="text-text-dim">{t('workbench.timeline.emptyHint')}</span>
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
  );
}

/**
 * 一组（主会话 + 它派出的 worker）在虚拟化列表里是一项。
 *
 * 组的框跨好几行，这里是同一项里的连续行，所以一个 div 就能画整圈，不会像左栏那样
 * 拆成三段。
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
 *
 * 虚拟化之后不可能一次量完整张表：没渲染的行不存在。每行渲染时量自己的宽度、标题的
 * 自然宽度，再把条与标题的位置写进去。标题落在哪的规则与原型一致：
 * 条里放得下就放条里；放不下贴右边；右边不够贴左边；三处都放不全就选最宽的那处截断。
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
    // 上一次写进去的 maxWidth 会挡住自然宽度，量之前先撤掉。
    lb.style.maxWidth = '';
    const need = Math.min(lb.scrollWidth + 2, MAX_LABEL_PX);

    let beg = Math.max(0, L);
    let endPx = Math.min(width, R);
    // 露出不到 24px 就补足；贴着窗口右沿的往里挪，不被裁成一根竖线。
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
      className="flex h-6 w-6 items-center justify-center rounded-[6px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
    >
      {children}
    </button>
  );
}
