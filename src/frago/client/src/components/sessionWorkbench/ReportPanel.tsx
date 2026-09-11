/**
 * ReportPanel — 右栏。旁路 AI 看着这场会话，把它填进五个槽位。
 *
 * 数据从哪来见 `useSessionObserver`：选中或切回一场会话时先读槽位文件，停在这场会话上时
 * 听推送。旁路 AI 在服务端跑，跟这一页停在哪场会话无关——切走打断不了它。
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
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, FlaskConical } from 'lucide-react';
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

/** 槽位标题：点它折起来或摊开。右边放这一格自己的小按钮。 */
function SlotHeader({
  label,
  collapsed,
  onToggle,
  actions,
}: {
  label: ReactNode;
  collapsed: boolean;
  onToggle: () => void;
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
      {actions ? <span className="ml-auto flex items-center gap-2">{actions}</span> : null}
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
  height,
  collapsed,
  expanded,
  onToggleCollapsed,
  onToggleExpanded,
}: {
  label: string;
  value: string;
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
    <section className="px-3 py-3">
      <SlotHeader
        label={label}
        collapsed={collapsed}
        onToggle={onToggleCollapsed}
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

/** 增长型槽位：只追加不覆盖，默认露最新三条。 */
function GrowSlot({
  label,
  items,
  collapsed,
  onToggleCollapsed,
}: {
  label: string;
  items: string[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? items : items.slice(0, 3);
  const hidden = items.length - shown.length;
  return (
    <section className="px-3 py-3">
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
          {hidden > 0 ? (
            <button type="button" onClick={() => setExpanded(true)} className={`mt-2 ${SLOT_ACTION}`}>
              {t('workbench.report.expandOlder', { n: hidden })}
            </button>
          ) : null}
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
  const [expanded, setExpanded] = useState<CoverKey[]>([]);
  const covers: { key: CoverKey; label: string; value: string }[] = [
    { key: 'anchor', label: t('workbench.report.slotAnchor'), value: state?.anchor ?? '' },
    { key: 'now', label: t('workbench.report.slotNow'), value: state?.now ?? '' },
    { key: 'decision', label: t('workbench.report.slotDecision'), value: state?.decision ?? '' },
    { key: 'output', label: t('workbench.report.slotOutput'), value: state?.output ?? '' },
  ];

  return (
    // 滚动容器的内距契约：分段自带上下内距，容器只在最底下补一段留白，最后一段滚到底时
    // 不会被硬切在边框上。
    <div className="min-h-0 flex-1 overflow-y-auto pb-6">
      {covers.map(({ key, label, value }) => {
        const collapsed = layout.collapsed.includes(key);
        const isExpanded = expanded.includes(key);
        return (
          <Fragment key={key}>
            <CoverSlot
              label={label}
              value={value}
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
            {/* 折起来或展开全文时这一格没有「高度」可调，分隔线只是一根线。 */}
            {collapsed || isExpanded ? (
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
      })}
      <GrowSlot
        label={t('workbench.report.slotHappened')}
        items={state?.happened ?? []}
        collapsed={layout.collapsed.includes('happened')}
        onToggleCollapsed={() => layout.toggleCollapsed('happened')}
      />
    </div>
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
