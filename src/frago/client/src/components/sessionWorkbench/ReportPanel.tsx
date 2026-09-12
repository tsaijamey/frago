/**
 * ReportPanel — 右栏。旁路 AI 看着这场会话，把它填进五个槽位。
 *
 * 数据从哪来见 `useSessionObserver`：选中或切回一场会话时先读槽位文件，停在这场会话上时
 * 听推送。旁路 AI 在服务端跑，跟这一页停在哪场会话无关——切走打断不了它。
 *
 * **版面分两块，因为这一栏要回答的是两个问题。**
 *
 * 顶上钉着「轮到你了」：agent 停下来等人拿主意时才出现，琥珀色，不随右栏滚动走。它是
 * 唯一一条要人动手的信息，跟下面那些「它在干嘛」不是同类，所以不做成第五个同款格子——
 * 常亮的高亮等于没有高亮，而栏顶那块地方太贵，不该长期摆一个「（无）」。没有待决时整条
 * 不存在：**有东西在顶上亮着本身就是信号**，不用读字就知道该看一眼。
 *
 * 下面四格是一条时间线，从「要干嘛」走到「眼下」：这场在做什么 → 已经发生的事 →
 * 最近一次产出 → 此刻在做什么。左边一条导轨把它们串起来，最后一个节点是实心的＝现在；
 * 每格右上角标它自己上次变样的时刻，人一眼分得出哪些是刚发生的、哪些半小时前就停在
 * 那儿了。从前五格是平铺的、顺序也不按时间，读起来看不出谁先谁后、谁导致了谁。
 *
 * 槽位分两型：
 *
 * - **覆盖型** 新值把旧值盖掉，格子高度不跟着内容跳，人的视线不用重新找位置。多高由人
 *   来定：格与格之间的分隔线可以拖（也可以用方向键），双击或按 Home 回到默认。内容超出
 *   时标题旁出现「展开全文」，底下一道渐隐提示下面还有——从前超出的部分直接被裁掉，
 *   人看不全也没处去看。
 * - **增长型** 随内容长，默认只露最新三条，展开按钮写「展开更早的 N 条」——N 是已经
 *   发生的绝对数，没有分母。
 *
 * 每一格都能点标题折起来只剩标题。高度、折叠、整栏宽度都记在这个浏览器里，见
 * `useReportLayout`。
 *
 * 全域禁令在这一栏同样成立：没有百分比、没有 X 比 Y 计数、没有进度条、没有预计剩余
 * 时间、没有还没发生的步骤名。允许出现的量只有已发生的绝对数。这条不是审美偏好：
 * Cline、OpenAI Codex、Claude Code 三家都在撤掉前瞻式待办清单，Codex issue #21327 记下
 * 的原话是「人会把进度面板当成产品状态读，而不是当成模型的自述」——靠模型自觉维持真实
 * 的东西，漏一次就在撒谎。服务端对模型的回答再查一道，犯了的整份作废。
 */

import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ChevronDown, ChevronRight, FlaskConical, Hand } from 'lucide-react';
import {
  useSessionObserver,
  type ObserverState,
  type SessionObserverView,
} from '@/hooks/useSessionObserver';
import {
  MAX_PANEL_WIDTH,
  MAX_SLOT_HEIGHT,
  MIN_PANEL_WIDTH,
  MIN_SLOT_HEIGHT,
  RESIZE_STEP,
  clamp,
  useSlotLayout,
  type CoverKey,
  type SlotLayoutController,
} from '@/hooks/useReportLayout';

/**
 * 槽位标题的写法。五个槽位共用一套：11px、次级灰、字重加一档、字距略开。
 *
 * 这一栏是几段并置的短文，彼此之间没有从属关系。标题要能一眼与正文分开，但不该比正文
 * 更抢眼——所以走的是"更小更淡但更紧"，而不是"更大更重"。
 */
const SLOT_LABEL = 'text-[11px] font-medium tracking-wide text-text-muted';

/** 标题右边那种小字按钮。 */
const SLOT_ACTION = 'shrink-0 text-[11px] text-text-muted hover:text-text-primary';

/** 右栏没调过宽度时，用来起拖的那个数。实际宽度由页面的默认列宽决定。 */
const FALLBACK_WIDTH = 346;

/**
 * 一根可拖的分隔线。横着的调它上面那一格的高度，竖着的调整栏宽度。
 *
 * 线本身只有一像素，能按住的范围比它宽几像素，免得人得瞄准一根头发丝。键盘也能调：
 * 聚焦后方向键一下挪 16px，Home 回默认——拖不了鼠标的人同样调得了。
 */
function Handle({
  orientation,
  label,
  value,
  min,
  max,
  onChange,
  onReset,
  invert = false,
  className = '',
}: {
  orientation: 'horizontal' | 'vertical';
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (next: number) => void;
  onReset: () => void;
  /** 竖线在右栏左边缘：往左拖是变宽，方向反过来。 */
  invert?: boolean;
  className?: string;
}) {
  const start = useRef<{ pos: number; size: number } | null>(null);
  const horizontal = orientation === 'horizontal';
  const sign = invert ? -1 : 1;
  const pos = (e: PointerEvent) => (horizontal ? e.clientY : e.clientX);

  const onKeyDown = (e: KeyboardEvent) => {
    const grow = horizontal ? 'ArrowDown' : invert ? 'ArrowLeft' : 'ArrowRight';
    const shrink = horizontal ? 'ArrowUp' : invert ? 'ArrowRight' : 'ArrowLeft';
    if (e.key === grow) onChange(value + RESIZE_STEP);
    else if (e.key === shrink) onChange(value - RESIZE_STEP);
    else if (e.key === 'Home') onReset();
    else return;
    e.preventDefault();
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation={horizontal ? 'horizontal' : 'vertical'}
      aria-label={label}
      title={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      onPointerDown={(e) => {
        start.current = { pos: pos(e), size: value };
        e.currentTarget.setPointerCapture?.(e.pointerId);
        e.preventDefault();
      }}
      onPointerMove={(e) => {
        if (start.current) onChange(start.current.size + sign * (pos(e) - start.current.pos));
      }}
      onPointerUp={(e) => {
        start.current = null;
        e.currentTarget.releasePointerCapture?.(e.pointerId);
      }}
      onPointerCancel={() => {
        start.current = null;
      }}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className={`group touch-none select-none outline-none ${className}`}
    >
      <div
        className={
          horizontal
            ? 'absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border-color transition-colors group-hover:bg-text-muted group-focus-visible:bg-text-muted'
            : 'absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors group-hover:bg-text-muted group-focus-visible:bg-text-muted'
        }
      />
    </div>
  );
}

/**
 * 每分钟叫醒一次，让「刚刚」自己变成「3 分钟前」。
 *
 * 不跟着数据走：右栏可以半小时收不到一条推送，而那半小时里时间照样在走。半分钟一跳，
 * 比最小的那一档（分钟）细，不会让人看见一个停住的「刚刚」。
 */
function useTick(): void {
  const [, bump] = useState(0);
  useEffect(() => {
    const id = setInterval(() => bump((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, []);
}

/**
 * 过去了多久。
 *
 * 只说已经过去的绝对时间——这一栏不许出现预计、还剩、进度。过了半天就改写日期时刻：
 * 「27 小时前」得人自己心算是什么时候，而这种老内容本来就该按钟点读。
 */
function ago(ms: number | null | undefined, t: TFunction): string | null {
  if (!ms) return null;
  const mins = Math.floor((Date.now() - ms) / 60_000);
  if (mins < 1) return t('workbench.report.justNow');
  if (mins < 60) return t('workbench.report.minutesAgo', { n: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 12) return t('workbench.report.hoursAgo', { n: hours });
  return stamp(ms);
}

/**
 * 时间线上的一个节点，外加穿过它的那截导轨。
 *
 * 最后一个（此刻在做什么）画成实心＝现在就停在这里；上面几个是空心，表示已经过去。
 * 导轨在格子内部整条通过，节点压在它上面（节点自带栏底色，把线截断成上下两截）。
 * 第一格的线从节点起，最后一格的线到节点止——头尾不留两截悬空的线头。
 *
 * 线用 `border-strong` 不用 `border-color`：后者是格与格之间那种"几乎看不见"的分隔线，
 * 竖着拉长之后淡到串不起东西来，人看到的还是几块平铺的字。
 */
function RailNode({ first, last }: { first: boolean; last: boolean }) {
  return (
    <span aria-hidden>
      <span
        className="absolute left-[12px] w-px bg-border-strong"
        style={{ top: first ? 8 : 0, bottom: last ? 'calc(100% - 9px)' : 0 }}
      />
      <span
        className={`absolute left-[9px] top-[5px] block h-[7px] w-[7px] rounded-full border ${
          last ? 'border-accent-primary bg-accent-primary' : 'border-text-muted bg-bg-secondary'
        }`}
      />
    </span>
  );
}

/** 槽位标题：点它折起来或摊开。右边放这一格上次变样的时刻和它自己的小按钮。 */
function SlotHeader({
  label,
  collapsed,
  onToggle,
  time,
  actions,
}: {
  label: ReactNode;
  collapsed: boolean;
  onToggle: () => void;
  time?: string | null;
  actions?: ReactNode;
}) {
  return (
    <header className={`flex items-center gap-2 ${collapsed ? '' : 'mb-1.5'}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className={`flex min-w-0 items-center gap-1 ${SLOT_LABEL} hover:text-text-primary`}
      >
        {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
        <span className="flex min-w-0 items-center gap-2 truncate">{label}</span>
      </button>
      <span className="ml-auto flex shrink-0 items-center gap-2">
        {actions}
        {time ? <span className="text-[11px] tabular-nums text-text-dim">{time}</span> : null}
      </span>
    </header>
  );
}

/**
 * 覆盖型槽位。高度由人定，内容超出时给「展开全文」，展开后按内容高度显示。
 *
 * **不是一张带边框的卡。** 几个槽位各套一圈边、外面还有一层栏底，一眼看过去是几个方框
 * 而不是几段话；而这一栏的内容本来就是要被读的。段与段之间只有那根可拖的分隔线。
 * 空着时写「（无）」，不留一片空白让人猜是没有还是没加载出来。
 */
function CoverSlot({
  label,
  value,
  time,
  first,
  last,
  height,
  collapsed,
  expanded,
  onToggleCollapsed,
  onToggleExpanded,
}: {
  label: string;
  value: string;
  time: string | null;
  first: boolean;
  last: boolean;
  height: number;
  collapsed: boolean;
  expanded: boolean;
  onToggleCollapsed: () => void;
  onToggleExpanded: () => void;
}) {
  const { t } = useTranslation();
  const body = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);

  // 装不下才给展开按钮；格子被拖大、字变短、旁路 AI 换了内容，都要重新量。
  useLayoutEffect(() => {
    const el = body.current;
    if (!el || expanded) {
      setOverflows(false);
      return undefined;
    }
    const measure = () => setOverflows(el.scrollHeight > el.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [value, height, collapsed, expanded]);

  const toggle =
    expanded || overflows ? (
      <button type="button" onClick={onToggleExpanded} className={SLOT_ACTION}>
        {expanded ? t('workbench.report.showLess') : t('workbench.report.showAll')}
      </button>
    ) : null;

  return (
    <section className="relative py-3 pl-7 pr-3">
      <RailNode first={first} last={last} />
      <SlotHeader
        label={label}
        collapsed={collapsed}
        onToggle={onToggleCollapsed}
        time={time}
        actions={collapsed ? null : toggle}
      />
      {collapsed ? null : (
        <div className="relative">
          <div
            ref={body}
            data-slot-body=""
            style={expanded ? undefined : { height }}
            className={`overflow-hidden whitespace-pre-wrap break-words text-[13px] leading-[1.72] ${
              value ? 'text-text-primary' : 'text-text-muted'
            }`}
          >
            {value || t('workbench.report.none')}
          </div>
          {overflows && !expanded ? (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t from-bg-secondary to-transparent"
            />
          ) : null}
        </div>
      )}
    </section>
  );
}

/**
 * 增长型槽位：只追加不覆盖，默认露最新三条。
 *
 * **条目按时间正序排，老的在上。** 传进来的是新的在前，这里倒过来：整栏是一条从上往下
 * 走的时间线，这一格里却从下往上读，两个方向打架，人就看不出谁先谁后了。「展开更早的」
 * 因此放在列表**上方**——更早的内容属于上面，按钮在底下却往头上加内容，眼睛会跟丢。
 */
function GrowSlot({
  label,
  items,
  times,
  collapsed,
  onToggleCollapsed,
}: {
  label: string;
  /** 新的在前。 */
  items: string[];
  /** 跟 items 一一对应；老的槽位文件没有时刻，这里会是一串 null。 */
  times: (number | null)[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const newestFirst = expanded ? items : items.slice(0, 3);
  const shown = [...newestFirst].reverse();
  const hidden = items.length - newestFirst.length;
  return (
    <section className="relative py-3 pl-7 pr-3">
      <RailNode first={false} last={false} />
      <SlotHeader
        label={
          <>
            <span>{label}</span>
            <span className="font-mono opacity-70">
              {t('workbench.report.itemCount', { n: items.length })}
            </span>
          </>
        }
        collapsed={collapsed}
        onToggle={onToggleCollapsed}
        time={ago(times[0], t)}
        actions={
          !collapsed && expanded && items.length > 3 ? (
            <button type="button" onClick={() => setExpanded(false)} className={SLOT_ACTION}>
              {t('workbench.report.showLess')}
            </button>
          ) : null
        }
      />
      {collapsed ? null : (
        <>
          {hidden > 0 ? (
            <button type="button" onClick={() => setExpanded(true)} className={`mb-1 ${SLOT_ACTION}`}>
              {t('workbench.report.expandOlder', { n: hidden })}
            </button>
          ) : null}
          {items.length === 0 ? (
            <p className="text-[13px] leading-[1.72] text-text-muted">
              {t('workbench.report.none')}
            </p>
          ) : (
            // 每一条是旁路 AI 某一次看完记下的一件事，条与条之间用虚线隔开：只靠行距时，
            // 长句接长句读起来是一整段，分不清一条在哪儿结束。用虚线不用实线，是为了跟
            // 格与格之间那根实线分开——这是同一格里的条目，不是另一格。
            <ul className="divide-y divide-dashed divide-border-color">
              {shown.map((item, i) => (
                <li
                  key={i}
                  className="whitespace-pre-wrap break-words py-2 text-[13px] leading-[1.72] text-text-secondary first:pt-0 last:pb-0"
                >
                  {item}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

/**
 * 五格本身。按会话换一次：「展开全文」「展开更早的」是看这一场时的动作，不该带到下一场；
 * 高度和折叠是人对版面的偏好，跨会话保留。
 */
function SlotStack({
  state,
  layout,
}: {
  state: ObserverState | null;
  layout: SlotLayoutController;
}) {
  const { t } = useTranslation();
  useTick();
  const [expanded, setExpanded] = useState<CoverKey[]>([]);

  // 顺序就是时间顺序：从「这场要干嘛」走到「眼下在干嘛」。最后一格的节点是实心的＝现在。
  // 「已经发生的事」夹在中间——它是走过来的那一路，默认只露最新三条，不会把下面顶下去。
  const covers: { key: CoverKey; label: string; value: string; at: number | null }[] = [
    {
      key: 'anchor',
      label: t('workbench.report.slotAnchor'),
      value: state?.anchor ?? '',
      at: state?.anchor_at ?? null,
    },
    {
      key: 'output',
      label: t('workbench.report.slotOutput'),
      value: state?.output ?? '',
      at: state?.output_at ?? null,
    },
    {
      key: 'now',
      label: t('workbench.report.slotNow'),
      value: state?.now ?? '',
      at: state?.now_at ?? null,
    },
  ];
  const happened = state?.happened ?? [];

  const slot = ({ key, label, value, at }: (typeof covers)[number], last: boolean) => {
    const first = key === 'anchor';
    const collapsed = layout.collapsed.includes(key);
    const isExpanded = expanded.includes(key);
    return (
      <Fragment key={key}>
        <CoverSlot
          label={label}
          value={value}
          time={ago(at, t)}
          first={first}
          last={last}
          height={layout.heights[key]}
          collapsed={collapsed}
          expanded={isExpanded}
          onToggleCollapsed={() => layout.toggleCollapsed(key)}
          onToggleExpanded={() =>
            setExpanded((prev) =>
              prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
            )
          }
        />
        {/* 最后一格底下不画线：那是时间线的终点，再画一道就像下面还有一段。 */}
        {last ? null : collapsed || isExpanded ? (
          // 折起来或展开全文时这一格没有「高度」可调，分隔线只是一根线。
          <div className="h-px bg-border-color" />
        ) : (
          <Handle
            orientation="horizontal"
            label={t('workbench.report.resizeSlot', { label })}
            value={layout.heights[key]}
            min={MIN_SLOT_HEIGHT}
            max={MAX_SLOT_HEIGHT}
            onChange={(h) => layout.setHeight(key, h)}
            onReset={() => layout.resetHeight(key)}
            className="relative z-10 -my-[4px] h-[9px] cursor-row-resize"
          />
        )}
      </Fragment>
    );
  };

  return (
    // 滚动容器的内距契约：分段自带上下内距，容器只在最底下补一段留白，最后一段滚到底时
    // 不会被硬切在边框上。
    <div className="min-h-0 flex-1 overflow-y-auto pb-6">
      {slot(covers[0], false)}
      <GrowSlot
        label={t('workbench.report.slotHappened')}
        items={happened}
        times={state?.happened_at ?? []}
        collapsed={layout.collapsed.includes('happened')}
        onToggleCollapsed={() => layout.toggleCollapsed('happened')}
      />
      <div className="h-px bg-border-color" />
      {slot(covers[1], false)}
      {slot(covers[2], true)}
    </div>
  );
}

/**
 * 钉在栏顶那条「轮到你了」。有待决才出现，没有就整条不存在。
 *
 * 它在滚动区外面：右栏滚到哪儿它都在。琥珀色跟中栏那些「在等」的记录同一套配色
 * （见 RecordCard），人在这一页见过这个颜色就是这个意思，不用重新学。不用红——
 * 没出错，只是轮到人了。
 */
function CallBanner({ text, time }: { text: string; time: string | null }) {
  const { t } = useTranslation();
  return (
    <section className="shrink-0 border-b border-accent-warning/30 bg-accent-warning-10 px-3 py-2.5">
      <header className="mb-1 flex items-center gap-1.5">
        <Hand size={12} className="shrink-0 text-accent-warning" />
        <span className="text-[11px] font-medium tracking-wide text-accent-warning">
          {t('workbench.report.decisionBanner')}
        </span>
        {time ? (
          <span className="ml-auto shrink-0 text-[11px] tabular-nums text-text-dim">{time}</span>
        ) : null}
      </header>
      <p className="whitespace-pre-wrap break-words text-[13px] leading-[1.72] text-text-primary">
        {text}
      </p>
    </section>
  );
}

/**
 * 右栏最上面那一行：只在要人去做点什么时出现——旁路 AI 没绑模型、上一次没问到。
 *
 * 按提醒的分量给：中性底，只有那颗烧瓶图标带一点绿，够认出"这一栏在说它自己的事"就行。
 */
function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="flex shrink-0 items-start gap-2 border-b border-border-color bg-bg-subtle px-3 py-2 text-[11px] leading-[1.6] text-text-secondary">
      <FlaskConical size={13} className="mt-[2px] shrink-0 text-accent-primary" />
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}

/** 月-日 时:分。不用本地化的日期串：那里面常有「9/11」这种斜杠，读起来像一个比值。 */
function stamp(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 画右栏。跟数据从哪来无关，测试直接喂它。 */
export function ReportBody({
  sessionId,
  view,
  width = null,
  onWidthChange,
}: {
  sessionId: string | null;
  view: SessionObserverView;
  /** 人调过的宽度；null 表示用页面默认的列宽。 */
  width?: number | null;
  /** 给了才出现左边缘那根可拖的竖线。 */
  onWidthChange?: (next: number | null) => void;
}) {
  const { t } = useTranslation();
  const layout = useSlotLayout();
  const asideRef = useRef<HTMLElement>(null);
  const [measured, setMeasured] = useState<number | null>(null);

  // 没调过宽度时要知道此刻实际多宽，才能从这个宽度起拖。
  useLayoutEffect(() => {
    const el = asideRef.current;
    if (!el) return undefined;
    const measure = () => setMeasured(el.getBoundingClientRect().width || null);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const aside =
    'relative flex h-full min-h-0 w-full flex-col border-l border-border-color bg-bg-secondary';
  const widthHandle = onWidthChange ? (
    <Handle
      orientation="vertical"
      invert
      label={t('workbench.report.resizePanel')}
      value={width ?? measured ?? FALLBACK_WIDTH}
      min={MIN_PANEL_WIDTH}
      max={MAX_PANEL_WIDTH}
      onChange={(w) => onWidthChange(clamp(w, MIN_PANEL_WIDTH, MAX_PANEL_WIDTH))}
      onReset={() => onWidthChange(null)}
      className="absolute inset-y-0 left-0 z-20 w-[9px] -translate-x-1/2 cursor-col-resize"
    />
  ) : null;

  if (!sessionId) {
    return (
      <aside ref={asideRef} className={aside}>
        {widthHandle}
        <p className="px-3 py-3 text-[12px] leading-[1.6] text-text-muted">
          {t('workbench.report.noSession')}
        </p>
      </aside>
    );
  }

  const { state } = view;
  const unbound = state?.status === 'unbound';
  const failed = state?.status === 'failed';
  const footer =
    state?.updated_at && state.model
      ? t('workbench.report.updated', { time: stamp(state.updated_at), model: state.model })
      : state && !unbound
        ? t('workbench.report.empty')
        : null;

  return (
    <aside ref={asideRef} className={aside}>
      {widthHandle}
      {state?.decision ? (
        <CallBanner text={state.decision} time={ago(state.decision_at, t)} />
      ) : null}
      {unbound ? <Notice>{t('workbench.report.unbound')}</Notice> : null}
      {failed ? (
        <Notice>{t('workbench.report.failed', { reason: state?.status_detail ?? '' })}</Notice>
      ) : null}

      <SlotStack key={sessionId} state={state} layout={layout} />

      {footer ? (
        <div className="shrink-0 border-t border-border-color px-3 py-2 text-[11px] leading-[1.6] text-text-muted">
          {footer}
        </div>
      ) : null}
    </aside>
  );
}

export default function ReportPanel({
  sessionId,
  width,
  onWidthChange,
}: {
  sessionId: string | null;
  width?: number | null;
  onWidthChange?: (next: number | null) => void;
}) {
  const view = useSessionObserver(sessionId);
  return (
    <ReportBody sessionId={sessionId} view={view} width={width} onWidthChange={onWidthChange} />
  );
}
