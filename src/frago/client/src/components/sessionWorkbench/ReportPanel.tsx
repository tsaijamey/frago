/**
 * ReportPanel — 右栏纯 Stack 容器。
 *
 * 自 2026-11-14 起，Observer 进度汇报（Goal Anchor / 事项总控表 / 阶段里程碑追加表 / Current State /
 * 待拍板横幅）已统一上移至中栏顶格的 `Watcher` 视图中渲染。右栏不再重复渲染四段式 Observer，
 * 恢复为纯粹的会话暂存区（`StackPanel`），保留左缘可拖拉宽度调节条与空会话引导。
 */

import {
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Layers } from 'lucide-react';
import EmptyState from '@/components/ui/EmptyState';
import type { SessionObserverView } from '@/hooks/useSessionObserver';
import {
  MAX_PANEL_WIDTH,
  MIN_PANEL_WIDTH,
  RESIZE_STEP,
  clamp,
} from '@/hooks/useReportLayout';

/** 右栏没调过宽度时，用来起拖的默认宽度（228px，对应蓝图 P1-2）。 */
const FALLBACK_WIDTH = 228;

/**
 * 定位到第一张未答决策卡，并触发 `.flash-focus` 高亮。
 * 供 Watcher 顶部「定位决策卡 ↓」横幅使用。
 */
export function jumpToPendingCard(): boolean {
  const el =
    document.querySelector<HTMLElement>('.dcard.is-pending') ??
    document.querySelector<HTMLElement>('[data-testid="decision-card"]');
  if (!el) return false;
  el.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  el.classList.remove('flash-focus');
  void el.offsetWidth;
  el.classList.add('flash-focus');
  return true;
}

/**
 * 一根可拖的分隔线。横着的调它上面那一格的高度，竖着的调整栏宽度。
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
  strong = false,
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
  strong?: boolean;
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
            ? `absolute inset-x-0 top-1/2 h-px -translate-y-1/2 transition-colors group-hover:bg-text-muted group-focus-visible:bg-text-muted ${
                strong ? 'bg-border-strong' : 'bg-border-color'
              }`
            : 'absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors group-hover:bg-text-muted group-focus-visible:bg-text-muted'
        }
      />
    </div>
  );
}

/** 画右栏纯 Stack 容器。 */
export function ReportBody({
  sessionId,
  width = null,
  onWidthChange,
  lower,
}: {
  sessionId: string | null;
  view?: SessionObserverView;
  /** 人调过的宽度；null 表示用页面默认的列宽。 */
  width?: number | null;
  /** 给了才出现左边缘那根可拖的竖线。 */
  onWidthChange?: (next: number | null) => void;
  /** 纯 Stack 列表。 */
  lower?: ReactNode;
  lowerEmpty?: boolean;
  stackCount?: number;
  pendingDecision?: string | null;
  onJumpToDecision?: () => void;
  stackOnly?: boolean;
}) {
  const { t } = useTranslation();
  const asideRef = useRef<HTMLElement>(null);
  const [measured, setMeasured] = useState<number | null>(null);

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
    'stackcol relative flex h-full min-h-0 w-full flex-col border-l border-border-color bg-bg-secondary';
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
        <div className="oh flex shrink-0 items-center justify-between border-b border-border-color px-3 py-2.5">
          <span className="t text-[12px] font-semibold text-text-primary">
            {t('workbench.stack.title')}
          </span>
        </div>
        <div className="p-3">
          <EmptyState Icon={Layers} title={t('workbench.report.noSession')} />
        </div>
      </aside>
    );
  }

  return (
    <aside ref={asideRef} className={aside}>
      {widthHandle}
      <div data-testid="report-lower" className="min-h-0 flex-1 overflow-hidden">
        {lower}
      </div>
    </aside>
  );
}

export default function ReportPanel({
  sessionId,
  width,
  onWidthChange,
  lower,
}: {
  sessionId: string | null;
  width?: number | null;
  onWidthChange?: (next: number | null) => void;
  lower?: ReactNode;
  lowerEmpty?: boolean;
  stackCount?: number;
  pendingDecision?: string | null;
  onJumpToDecision?: () => void;
  stackOnly?: boolean;
  view?: SessionObserverView;
}) {
  return (
    <ReportBody
      sessionId={sessionId}
      width={width}
      onWidthChange={onWidthChange}
      lower={lower}
    />
  );
}
