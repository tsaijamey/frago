/**
 * StreamMinimap — 记录流右侧那条缩略滚动条与方案 4A 暂存标签轨。
 *
 * 保留「只画人发言（绿条）、最终代理回复（灰条）、标注刻度」的三色极简信号，
 * 过滤掉标记为 `[data-minimap-exclude]` 的工具调用前过程旁白；
 * 当存在 Stack 标注时，在滚动条左侧展开 `.mm-labels-layer` 标签轨与折线引线，
 * 并在悬浮或气泡打开时通过 `stackFreeze` 冻结位置重排，避免流式增长时按钮漂移。
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import type { WorkbenchMark } from '../../types/api';
import { RECORD_BODY_ATTR } from './SelectionQuote';
import type { MarkTick } from './RecordStream';
import type { StackAnchorRect, StackPopoverState } from './StackPopover';
import {
  cleanQuoteText,
  layoutStackLabels,
  stackLabelText,
  stackStatusOf,
  type StackRailEntity,
  type StackRailItem,
} from '../../utils/stackRailLayout';

function toAnchorRect(el: HTMLElement): StackAnchorRect {
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, right: r.right, bottom: r.bottom };
}

/** 一根条最细多少像素。再细就看不见了。 */
const MIN_BAR_PX = 2;
/** 滑块最矮多少像素，长会话里也要按得住。 */
const MIN_THUMB_PX = 16;
/** 悬停提示延迟（ms），与原型 180ms 一致。 */
const HOVER_TIP_DELAY_MS = 180;

interface Bar {
  key: string;
  top: number;
  height: number;
  who: 'user' | 'agent';
}

interface Tick {
  key: string;
  top: number;
  tone: MarkTick['tone'];
}

interface Layout {
  bars: Bar[];
  ticks: Tick[];
  thumbTop: number;
  thumbHeight: number;
  /** 滚动内容总高 / 滚动条高。拖滑块时按它把像素换回滚动距离。 */
  scale: number;
  railHeight: number;
  scrollTop: number;
  scrollMax: number;
}

interface StackLayoutSnapshot {
  entities: StackRailEntity[];
  unloadedStacks: WorkbenchMark[];
  usedStacks: WorkbenchMark[];
  hasTopPill: boolean;
  layerWidth: number;
  railHeight: number;
}

const EMPTY_LAYOUT: Layout = {
  bars: [],
  ticks: [],
  thumbTop: 0,
  thumbHeight: 0,
  scale: 1,
  railHeight: 0,
  scrollTop: 0,
  scrollMax: 0,
};

const EMPTY_STACK_LAYOUT: StackLayoutSnapshot = {
  entities: [],
  unloadedStacks: [],
  usedStacks: [],
  hasTopPill: false,
  layerWidth: 152,
  railHeight: 480,
};

const EMPTY_SET: ReadonlySet<string> = new Set();

/**
 * 刻度的颜色。与记录流里那段文字同一个意思（spec 20260928-webui-session-branch 的配色表）：
 * 橙只给还等着你的暂存；没收口的分支用正文色；其余回应过了的一律中性。
 */
const TICK_CLASS: Record<MarkTick['tone'], string> = {
  stack: 'bg-accent-warning',
  branch: 'bg-text-primary',
  quote: 'bg-text-muted',
};

export interface StreamMinimapProps {
  /** 记录流的滚动容器。 */
  scrollRef: RefObject<HTMLDivElement>;
  /** 标注找到的位置（见 `paintMarks`）。 */
  ticks: MarkTick[];
  /** 记录流内容变了（换镜头、来了新记录）就换一个值，逼它重量一次。 */
  version: unknown;
  /**
   * 要滚动之前先说一声。拖滑块、点空白处、键盘滚动都是人的手，记录流据此把这一下当成人手滚动，
   * 解除自动跟随——与拖原生滚动条同一待遇。
   */
  onUserScroll: () => void;
  /** Stack 标注列表（默认空数组，向后兼容旧调用方）。 */
  marks?: WorkbenchMark[];
  /** 已入 Composer 草稿箱的 stack mark ID 集合。 */
  inDraftMarkIds?: ReadonlySet<string>;
  /** 外部是否有 StackPopover 打开（打开期间冻结标签位置重排）。 */
  popoverOpen?: boolean;
  /** 当前打开的浮层状态（用于高亮对应标签与引线）。 */
  activePopover?: StackPopoverState | null;
  /** 点击标签 / 簇 / 顶部汇总胶囊 / 窄屏刻度时打开 3 态浮层。 */
  onOpenPopover?: (state: StackPopoverState) => void;
  /** 是否显示左侧标签轨（如 Files/Terminal 遮罩打开时仅保留滚动条或隐藏标签）。 */
  showStackRail?: boolean;
  /** 冻结状态变化回调（便于调试与测试验证）。 */
  onFreezeChange?: (frozen: boolean) => void;
}

export default function StreamMinimap({
  scrollRef,
  ticks,
  version,
  onUserScroll,
  marks = [],
  inDraftMarkIds = EMPTY_SET,
  popoverOpen = false,
  activePopover = null,
  onOpenPopover,
  showStackRail = true,
  onFreezeChange,
}: StreamMinimapProps) {
  const { t } = useTranslation();
  const track = useRef<HTMLDivElement>(null);
  const labelsLayerRef = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<Layout>(EMPTY_LAYOUT);
  const [stackLayout, setStackLayout] = useState<StackLayoutSnapshot>(EMPTY_STACK_LAYOUT);
  const [hoverFrozen, setHoverFrozen] = useState(false);
  const [hoverTip, setHoverTip] = useState<{
    id: string;
    title: string;
    statusLabel: string;
    top: number;
  } | null>(null);
  const hoverTipTimerRef = useRef<number | null>(null);

  const frame = useRef<number | null>(null);
  const ticksRef = useRef(ticks);
  ticksRef.current = ticks;
  const marksRef = useRef(marks);
  marksRef.current = marks;
  const inDraftRef = useRef(inDraftMarkIds);
  inDraftRef.current = inDraftMarkIds;
  const showStackRailRef = useRef(showStackRail);
  showStackRailRef.current = showStackRail;

  const isFrozen = hoverFrozen || popoverOpen;
  const isFrozenRef = useRef(isFrozen);
  isFrozenRef.current = isFrozen;
  const hasFrozenSnapshotRef = useRef(false);
  const prevMarksSigRef = useRef('');

  const stackMarks = useMemo(
    () => marks.filter((m) => m.kind === 'stack'),
    [marks]
  );

  const marksSig = useMemo(
    () =>
      stackMarks
        .map((m) => `${m.id}:${m.used ? 1 : 0}:${inDraftMarkIds.has(m.id) ? 1 : 0}:${m.note ?? ''}`)
        .join('|'),
    [stackMarks, inDraftMarkIds]
  );

  const stackMarkById = useMemo(() => {
    const map = new Map<string, WorkbenchMark>();
    for (const m of stackMarks) map.set(m.id, m);
    return map;
  }, [stackMarks]);

  useEffect(() => {
    onFreezeChange?.(isFrozen);
  }, [isFrozen, onFreezeChange]);

  const clearHoverTip = useCallback(() => {
    if (hoverTipTimerRef.current !== null) {
      window.clearTimeout(hoverTipTimerRef.current);
      hoverTipTimerRef.current = null;
    }
    setHoverTip(null);
  }, []);

  useEffect(() => {
    if (popoverOpen) clearHoverTip();
  }, [popoverOpen, clearHoverTip]);

  useEffect(() => clearHoverTip, [clearHoverTip]);

  /** 量一遍：每条正文记录、每道刻度、滑块，以及 Stack 标签布局。 */
  const measure = useCallback(() => {
    const box = scrollRef.current;
    const rail = track.current;
    if (!box || !rail) return;
    const total = Math.max(box.scrollHeight, 1);
    const railHeight = rail.clientHeight;
    const k = railHeight / total;
    const origin = box.getBoundingClientRect().top - box.scrollTop;
    const topOf = (rect: DOMRect) => rect.top - origin;

    const bars: Bar[] = [];
    box.querySelectorAll<HTMLElement>(`[${RECORD_BODY_ATTR}]`).forEach((el) => {
      // 方案 4A 过程旁白过滤：tool.call 前的中间 agent.say 带有 data-minimap-exclude，不绘制色条。
      if (el.hasAttribute('data-minimap-exclude')) return;
      const recordId = el.getAttribute('data-record-id') ?? String(bars.length);
      const parts = el.querySelectorAll<HTMLElement>('[data-minimap-part]');
      if (parts.length > 0) {
        parts.forEach((part, idx) => {
          const partWho = part.getAttribute('data-minimap-part');
          if (partWho !== 'user' && partWho !== 'agent') return;
          const rect = part.getBoundingClientRect();
          bars.push({
            key: `${recordId}:${idx}`,
            top: topOf(rect) * k,
            height: Math.max(MIN_BAR_PX, rect.height * k),
            who: partWho,
          });
        });
        return;
      }
      const kind = el.getAttribute('data-record-kind');
      const who =
        kind === 'user.say'
          ? 'user'
          : kind === 'agent.say' || kind === 'async.callback'
            ? 'agent'
            : null;
      if (!who) return;
      const rect = el.getBoundingClientRect();
      bars.push({
        key: recordId,
        top: topOf(rect) * k,
        height: Math.max(MIN_BAR_PX, rect.height * k),
        who,
      });
    });

    const tickTopById = new Map<string, number>();
    const measuredTicks: Tick[] = ticksRef.current.map((tick) => {
      const rect =
        typeof tick.range.getBoundingClientRect === 'function'
          ? tick.range.getBoundingClientRect()
          : (tick.range.startContainer.parentElement?.getBoundingClientRect() ?? null);
      const y = rect ? topOf(rect) * k : 0;
      tickTopById.set(tick.id, y);
      return { key: tick.id, top: y, tone: tick.tone };
    });

    const scrollMax = Math.max(0, box.scrollHeight - box.clientHeight);
    const thumbHeight = Math.min(railHeight, Math.max(MIN_THUMB_PX, box.clientHeight * k));
    const thumbTop = Math.min(railHeight - thumbHeight, box.scrollTop * k);
    setLayout({
      bars,
      ticks: measuredTicks,
      thumbTop: Math.max(0, thumbTop),
      thumbHeight,
      scale: k || 1,
      railHeight,
      scrollTop: box.scrollTop,
      scrollMax,
    });

    const currentStacks = marksRef.current.filter((m) => m.kind === 'stack');
    const currentInDraft = inDraftRef.current;
    const currentSig = currentStacks
      .map((m) => `${m.id}:${m.used ? 1 : 0}:${currentInDraft.has(m.id) ? 1 : 0}:${m.note ?? ''}`)
      .join('|');
    const marksChanged = currentSig !== prevMarksSigRef.current;
    prevMarksSigRef.current = currentSig;

    // 当悬停在标签层或浮层打开时，若并非用户自身的标注增删改，则冻结标签坐标防止漂移。
    if (isFrozenRef.current && hasFrozenSnapshotRef.current && !marksChanged) {
      return;
    }

    if (!showStackRailRef.current || currentStacks.length === 0) {
      hasFrozenSnapshotRef.current = false;
      setStackLayout(EMPTY_STACK_LAYOUT);
      return;
    }

    const effectiveRailH = railHeight > 0 ? railHeight : 480;
    const effectiveK = railHeight > 0 ? k : effectiveRailH / total;
    const clampY = (y: number) => Math.min(Math.max(4, y), Math.max(4, effectiveRailH - 4));

    const locateMarkRawY = (mark: WorkbenchMark): number | null => {
      const tickY = tickTopById.get(mark.id);
      if (tickY !== undefined) {
        return clampY(railHeight > 0 ? tickY : (tickY / Math.max(k, 1e-6)) * effectiveK);
      }
      const recEl = box.querySelector<HTMLElement>(
        `[data-record-id="${CSS.escape(mark.record_id)}"]`
      );
      if (!recEl) return null;
      const rect = recEl.getBoundingClientRect();
      return clampY(topOf(rect) * effectiveK);
    };

    const unloadedStacks: WorkbenchMark[] = [];
    const usedStacks: WorkbenchMark[] = [];
    const activeItems: StackRailItem[] = [];

    for (const m of currentStacks) {
      if (m.used) {
        usedStacks.push(m);
        continue;
      }
      const rawY = locateMarkRawY(m);
      if (rawY === null) {
        unloadedStacks.push(m);
      } else {
        const st = stackStatusOf(m, currentInDraft);
        activeItems.push({
          mark: m,
          status: st === 'draft' ? 'draft' : 'pending',
          rawY,
        });
      }
    }

    const hasTopPill =
      unloadedStacks.length > 0 || (usedStacks.length > 0 && activeItems.length > 0);
    const topReserve = hasTopPill ? 28 : 4;
    const entities = layoutStackLabels(activeItems, effectiveRailH, topReserve);
    const layerWidth = labelsLayerRef.current?.clientWidth || 152;

    hasFrozenSnapshotRef.current = true;
    setStackLayout({
      entities,
      unloadedStacks,
      usedStacks,
      hasTopPill,
      layerWidth,
      railHeight: effectiveRailH,
    });
  }, [scrollRef]);

  /** 攒到下一帧只量一次。 */
  const schedule = useCallback(() => {
    if (frame.current !== null) return;
    if (typeof requestAnimationFrame !== 'function') {
      measure();
      return;
    }
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      measure();
    });
  }, [measure]);

  // 内容一变（新记录、换镜头、标注、解除冻结）先当场量一次，不等下一帧。
  useLayoutEffect(() => {
    measure();
  }, [measure, version, ticks, marksSig, showStackRail, isFrozen]);

  // 父组件 RecordStream 的 useLayoutEffect 晚于子组件执行并把 scrollTop 推到最底；
  // 在 useEffect 中补量一次，确保从 Watcher 切回 Talk / All 重新挂载时滑块立即定位到轨道底部。
  useEffect(() => {
    measure();
  }, [measure, version, ticks, marksSig, showStackRail, isFrozen]);

  // 滚动、内容长高、窗口变大小：攒到下一帧再量。
  useEffect(() => {
    const box = scrollRef.current;
    if (!box) return undefined;
    box.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(schedule);
      observer.observe(box);
      if (box.firstElementChild) observer.observe(box.firstElementChild);
      if (track.current) observer.observe(track.current);
      if (labelsLayerRef.current) observer.observe(labelsLayerRef.current);
    }
    return () => {
      box.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      observer?.disconnect();
      if (frame.current !== null && typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(frame.current);
      }
      frame.current = null;
    };
  }, [scrollRef, schedule]);

  /** 把记录流滚到让滚动条上这一点落在可视区的这个位置。 */
  const scrollTo = (top: number) => {
    const box = scrollRef.current;
    if (!box) return;
    onUserScroll();
    const maxScroll = Math.max(0, box.scrollHeight - box.clientHeight);
    box.scrollTop = Math.min(maxScroll, Math.max(0, top));
  };

  const handleTrackKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const box = scrollRef.current;
    if (!box) return;
    const pageStep = Math.max(80, Math.round(box.clientHeight * 0.85));
    const maxScroll = Math.max(0, box.scrollHeight - box.clientHeight);
    switch (e.key) {
      case 'ArrowUp':
        e.preventDefault();
        scrollTo(box.scrollTop - 48);
        break;
      case 'ArrowDown':
        e.preventDefault();
        scrollTo(box.scrollTop + 48);
        break;
      case 'PageUp':
        e.preventDefault();
        scrollTo(box.scrollTop - pageStep);
        break;
      case 'PageDown':
        e.preventDefault();
        scrollTo(box.scrollTop + pageStep);
        break;
      case 'Home':
        e.preventDefault();
        scrollTo(0);
        break;
      case 'End':
        e.preventDefault();
        scrollTo(maxScroll);
        break;
      default:
        break;
    }
  };

  const drag = useRef<{ y: number; top: number } | null>(null);
  const showLabelsLayer =
    showStackRail &&
    (stackLayout.hasTopPill || stackLayout.entities.length > 0);
  const layerW = stackLayout.layerWidth || 152;
  const labelRightX = Math.max(12, layerW - 6);
  const svgHeight =
    stackLayout.railHeight > 0
      ? stackLayout.railHeight
      : layout.railHeight > 0
        ? layout.railHeight
        : 480;

  const scheduleHoverTip = (mark: WorkbenchMark, dispY: number) => {
    if (popoverOpen) return;
    clearHoverTip();
    const st = stackStatusOf(mark, inDraftMarkIds);
    const title = mark.note?.trim() ? mark.note.trim() : cleanQuoteText(mark.text);
    const statusLabel =
      st === 'draft'
        ? t('workbench.stack.statusDraft')
        : st === 'used'
          ? t('workbench.stack.statusUsed')
          : t('workbench.stack.statusPending');
    const top = Math.max(4, Math.min(Math.max(4, svgHeight - 56), dispY));
    hoverTipTimerRef.current = window.setTimeout(() => {
      hoverTipTimerRef.current = null;
      setHoverTip({ id: mark.id, title, statusLabel, top });
    }, HOVER_TIP_DELAY_MS);
  };

  const summaryActive = activePopover?.mode === 'summary';

  return (
    <div className="mm-dock" data-testid="stream-minimap-dock" data-frozen={isFrozen ? 'true' : undefined}>
      {showLabelsLayer ? (
        <div
          ref={labelsLayerRef}
          className="mm-labels-layer"
          data-testid="stack-labels-layer"
          onMouseEnter={() => setHoverFrozen(true)}
          onMouseLeave={() => {
            setHoverFrozen(false);
            clearHoverTip();
          }}
        >
          <svg
            className="mm-leader-svg"
            viewBox={`0 0 ${layerW} ${svgHeight}`}
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {stackLayout.entities.map((ent) => {
              if (ent.kind === 'single') {
                const mark = ent.item.mark;
                const st = stackStatusOf(mark, inDraftMarkIds);
                const isActive =
                  activePopover?.mode === 'item' && activePopover.markId === mark.id;
                const midY = ent.dispY + ent.h / 2;
                const anchorY = ent.item.rawY;
                const isBent = Math.abs(midY - anchorY) > 1.5;
                const midX = labelRightX + 3;
                const d = isBent
                  ? `M ${labelRightX} ${midY.toFixed(1)} L ${midX} ${midY.toFixed(1)} L ${midX} ${anchorY.toFixed(1)} L ${layerW} ${anchorY.toFixed(1)}`
                  : `M ${labelRightX} ${midY.toFixed(1)} L ${layerW} ${midY.toFixed(1)}`;
                return (
                  <path
                    key={`line-${ent.id}`}
                    className={`mm-leader-line is-${st}${isActive ? ' is-active' : ''}`}
                    d={d}
                  />
                );
              }
              const isActive =
                activePopover?.mode === 'cluster' && activePopover.clusterId === ent.id;
              const midY = ent.dispY + ent.h / 2;
              const midX = labelRightX + 3;
              return ent.items.map((sub) => {
                const anchorY = sub.rawY;
                const d = `M ${labelRightX} ${midY.toFixed(1)} L ${midX} ${midY.toFixed(1)} L ${midX} ${anchorY.toFixed(1)} L ${layerW} ${anchorY.toFixed(1)}`;
                return (
                  <path
                    key={`line-${ent.id}-${sub.mark.id}`}
                    className={`mm-leader-line ${ent.allDraft ? 'is-draft' : 'is-cluster'}${
                      isActive ? ' is-active' : ''
                    }`}
                    d={d}
                  />
                );
              });
            })}
          </svg>

          {stackLayout.hasTopPill ? (
            <button
              type="button"
              data-testid="stack-top-summary"
              className={`mm-top-pill${stackLayout.unloadedStacks.length > 0 ? ' has-unloaded' : ''}${
                summaryActive ? ' is-active' : ''
              }`}
              onClick={(e) => {
                e.stopPropagation();
                clearHoverTip();
                onOpenPopover?.({
                  mode: 'summary',
                  anchorRect: toAnchorRect(e.currentTarget),
                  triggerEl: e.currentTarget,
                  placement: 'left',
                });
              }}
            >
              {stackLayout.unloadedStacks.length > 0 ? (
                <>
                  <span className="tp-dot" aria-hidden="true" />
                  <span className="lbl-txt">
                    {stackLayout.usedStacks.length > 0
                      ? t('workbench.stack.topEarlierAndUsed', {
                          earlier: stackLayout.unloadedStacks.length,
                          used: stackLayout.usedStacks.length,
                        })
                      : t('workbench.stack.topEarlier', {
                          count: stackLayout.unloadedStacks.length,
                        })}
                  </span>
                </>
              ) : (
                <span className="lbl-txt">
                  {t('workbench.stack.topUsed', { count: stackLayout.usedStacks.length })}
                </span>
              )}
            </button>
          ) : null}

          {stackLayout.entities.map((ent) => {
            if (ent.kind === 'single') {
              const mark = ent.item.mark;
              const st = stackStatusOf(mark, inDraftMarkIds);
              const isActive =
                activePopover?.mode === 'item' && activePopover.markId === mark.id;
              const label = stackLabelText(mark);
              return (
                <button
                  key={ent.id}
                  type="button"
                  data-testid="stack-rail-label"
                  data-mark-id={mark.id}
                  data-status={st}
                  style={{ top: `${ent.dispY.toFixed(1)}px` }}
                  className={`mm-label is-${st}${isActive ? ' is-active' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    clearHoverTip();
                    onOpenPopover?.({
                      mode: 'item',
                      markId: mark.id,
                      anchorRect: toAnchorRect(e.currentTarget),
                      triggerEl: e.currentTarget,
                      placement: 'left',
                    });
                  }}
                  onMouseEnter={() => scheduleHoverTip(mark, ent.dispY)}
                  onMouseLeave={clearHoverTip}
                >
                  {st === 'draft' ? (
                    <span className="lbl-ic" aria-hidden="true">
                      <Check size={10} strokeWidth={2.4} />
                    </span>
                  ) : (
                    <span className="lbl-dot" aria-hidden="true" />
                  )}
                  <span className="lbl-txt">{label}</span>
                </button>
              );
            }

            const isActive =
              activePopover?.mode === 'cluster' && activePopover.clusterId === ent.id;
            const clusterMarks = ent.items.map((x) => x.mark);
            const label = stackLabelText(ent.prefItem.mark);
            return (
              <button
                key={ent.id}
                type="button"
                data-testid="stack-rail-cluster"
                data-cluster-id={ent.id}
                data-cluster-ids={JSON.stringify(clusterMarks.map((m) => m.id))}
                style={{ top: `${ent.dispY.toFixed(1)}px` }}
                className={`mm-cluster${ent.allDraft ? ' is-all-draft' : ''}${
                  isActive ? ' is-active' : ''
                }`}
                onClick={(e) => {
                  e.stopPropagation();
                  clearHoverTip();
                  onOpenPopover?.({
                    mode: 'cluster',
                    clusterId: ent.id,
                    markIds: clusterMarks.map((m) => m.id),
                    anchorRect: toAnchorRect(e.currentTarget),
                    triggerEl: e.currentTarget,
                    placement: 'left',
                  });
                }}
              >
                <span className="lbl-dot" aria-hidden="true" />
                <span className="lbl-cnt">×{ent.items.length}</span>
                <span className="lbl-txt">{label}</span>
              </button>
            );
          })}

          {hoverTip && !popoverOpen ? (
            <div
              className="mm-hover-tip"
              data-testid="stack-hover-tip"
              style={{ top: `${hoverTip.top.toFixed(1)}px` }}
              role="tooltip"
            >
              <div className="mm-hover-tip-title">{hoverTip.title}</div>
              <div className="mm-hover-tip-meta">{hoverTip.statusLabel}</div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div
        ref={track}
        data-testid="stream-minimap"
        role="scrollbar"
        tabIndex={0}
        aria-orientation="vertical"
        aria-controls="record-stream-scroll"
        aria-label={t('workbench.stream.minimap')}
        title={t('workbench.stream.minimap')}
        aria-valuemin={0}
        aria-valuemax={Math.max(0, Math.round(layout.scrollMax))}
        aria-valuenow={Math.round(layout.scrollTop)}
        onKeyDown={handleTrackKeyDown}
        onPointerDown={(e) => {
          // 点在空白处：让那一点落到可视区正中。
          if (e.target !== e.currentTarget && !(e.target as HTMLElement).dataset.minimapBar) return;
          const rail = track.current;
          const box = scrollRef.current;
          if (!rail || !box) return;
          const y = e.clientY - rail.getBoundingClientRect().top;
          scrollTo(y / layout.scale - box.clientHeight / 2);
        }}
        className="mm-track relative h-full w-3 select-none overflow-hidden rounded-[3px] focus:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary"
      >
        {layout.bars.map((bar) => (
          <div
            key={bar.key}
            data-minimap-bar={bar.who}
            style={{ top: bar.top, height: bar.height }}
            className={`absolute inset-x-[2px] rounded-[1px] ${
              bar.who === 'user' ? 'bg-accent-primary' : 'bg-text-muted opacity-60'
            }`}
          />
        ))}
        {layout.ticks.map((tick) => {
          const stackMark = tick.tone === 'stack' ? stackMarkById.get(tick.key) : undefined;
          const status = stackMark ? stackStatusOf(stackMark, inDraftMarkIds) : undefined;
          const clickable = Boolean(stackMark && status && status !== 'used' && onOpenPopover);
          return (
            <div
              key={tick.key}
              data-minimap-tick={tick.tone}
              data-mark-id={stackMark?.id}
              data-status={status}
              style={{ top: tick.top }}
              onClick={
                clickable && stackMark
                  ? (e) => {
                      e.stopPropagation();
                      onOpenPopover?.({
                        mode: 'item',
                        markId: stackMark.id,
                        anchorRect: toAnchorRect(e.currentTarget),
                        triggerEl: e.currentTarget,
                        placement: 'left',
                      });
                    }
                  : undefined
              }
              className={`mm-tick pointer-events-none absolute inset-x-0 h-[2px] ${
                TICK_CLASS[tick.tone]
              }${status ? ` is-stack is-${status}` : ''}`}
            />
          );
        })}
        {layout.thumbHeight > 0 ? (
          <div
            data-testid="stream-minimap-thumb"
            style={{ top: layout.thumbTop, height: layout.thumbHeight }}
            onPointerDown={(e) => {
              e.stopPropagation();
              e.preventDefault();
              drag.current = { y: e.clientY, top: scrollRef.current?.scrollTop ?? 0 };
              e.currentTarget.setPointerCapture?.(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (!drag.current) return;
              scrollTo(drag.current.top + (e.clientY - drag.current.y) / layout.scale);
            }}
            onPointerUp={(e) => {
              drag.current = null;
              e.currentTarget.releasePointerCapture?.(e.pointerId);
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
            /* 半透明的中性色：盖在条纹上还看得见底下的绿灰和刻度。 */
            className="absolute inset-x-0 cursor-grab rounded-[3px] border border-[var(--border-strong)] bg-[var(--bg-active)] active:cursor-grabbing"
          />
        ) : null}
      </div>
    </div>
  );
}
