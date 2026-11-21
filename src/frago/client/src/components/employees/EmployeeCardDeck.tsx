/**
 * EmployeeCardDeck — 克制 3D 扑克牌选卡舞台与牌组导轨。
 *
 * 严格对齐 v3 设计规格与原型实测几何参数：
 * - 桌面（>1024px）：deck-stage 204px + deck-rail 40px = 245px，卡片 228×170px，maxVisible = 2；
 * - 平板（<=1024px）：210×160px，maxVisible = 1；
 * - 手机（<=640px）：关闭 3D 透视，降维为 scroll-snap 居中横滑（220×158px），零横向溢出。
 * - 双层槽面隔离（.card-slot 控 3D 坐标，.card-face 控悬停微抬），实体不透明 + --dof-dim 景深。
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronLeft, ChevronRight, Repeat, Search } from 'lucide-react';
import type { EmployeePost } from '@/hooks/useEmployees';
import {
  employeeInitials,
  employeeSummary,
  employeeSummaryParts,
  resolveEmployeeColor,
} from './employeeMeta';

export type DeckBreakpoint = 'desktop' | 'tablet' | 'phone';

export interface CardPose {
  tx: number;
  ty: number;
  tz: number;
  ry: number;
  rz: number;
  sc: number;
  opacity: number;
  dofDim: number;
  zIndex: number;
  isFar: boolean;
  isWing: boolean;
  direction: 'center' | 'left' | 'right';
}

export function resolveDeckBreakpoint(viewportWidth: number): DeckBreakpoint {
  if (viewportWidth <= 640) return 'phone';
  if (viewportWidth <= 1024) return 'tablet';
  return 'desktop';
}

/**
 * 基于相对居中卡偏移 `offset` 与当前断点、减弱动态效果及主题，计算 3D 槽位姿态。
 */
export function computeCardPose(
  offset: number,
  breakpoint: DeckBreakpoint = 'desktop',
  reducedMotion = false,
  theme: 'dark' | 'light' = 'dark'
): CardPose {
  const abs = Math.abs(offset);
  const direction: CardPose['direction'] =
    offset === 0 ? 'center' : offset < 0 ? 'left' : 'right';

  if (breakpoint === 'phone') {
    return {
      tx: 0,
      ty: 0,
      tz: 0,
      ry: 0,
      rz: 0,
      sc: 1,
      opacity: 1,
      dofDim: 0,
      zIndex: abs === 0 ? 60 : 10,
      isFar: false,
      isWing: false,
      direction,
    };
  }

  if (abs === 0) {
    return {
      tx: 0,
      ty: reducedMotion ? 0 : -2,
      tz: reducedMotion ? 0 : 48,
      ry: 0,
      rz: 0,
      sc: 1.02,
      opacity: 1,
      dofDim: 0,
      zIndex: 60,
      isFar: false,
      isWing: false,
      direction: 'center',
    };
  }

  const sign = offset < 0 ? -1 : 1;
  const isTablet = breakpoint === 'tablet';
  const maxVisible = isTablet ? 1 : 2;
  const txTable = isTablet ? [0, 208, 320] : [0, 232, 368];
  const tyTable = [0, 3, 12];
  const tzTable = [48, -18, -88];
  const ryTable = [0, 10, 16];
  const rzTable = [0, 0.8, 1.6];
  const scTable = [1.02, 0.9, 0.8];
  const dimDark = [0, 0.12, 0.24];
  const dimLight = [0, 0.02, 0.05];

  const step = Math.min(abs, 2);
  const isFar = abs > maxVisible;
  const isWing = abs >= 2;

  return {
    tx: sign * txTable[step],
    ty: reducedMotion ? 0 : tyTable[step],
    tz: reducedMotion ? 0 : tzTable[step],
    ry: reducedMotion ? 0 : -sign * ryTable[step],
    rz: reducedMotion ? 0 : sign * rzTable[step],
    sc: scTable[step],
    opacity: isFar ? 0 : 1,
    dofDim: theme === 'dark' ? dimDark[step] : dimLight[step],
    zIndex: Math.max(1, 60 - abs * 10),
    isFar,
    isWing,
    direction,
  };
}

function formatDeckCounter(activeIdx: number, total: number): string {
  if (total <= 0) return '00 / 00';
  return `${String(activeIdx + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}`;
}

function getViewportWidth(): number {
  return typeof window !== 'undefined' && window.innerWidth ? window.innerWidth : 1380;
}

function getPrefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function isInteractiveInputFocused(): boolean {
  if (typeof document === 'undefined') return false;
  const active = document.activeElement as HTMLElement | null;
  if (!active) return false;
  const tag = active.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  if (active.isContentEditable) return true;
  return Boolean(document.querySelector('[role="dialog"][aria-modal="true"]'));
}

export interface EmployeeCardDeckProps {
  employees: EmployeePost[];
  activeId: string | null;
  onSelect: (memberPostId: string) => void;
  /** 点击已居中的卡片或按 Enter 时聚焦下方首条会话入口。 */
  onActivateCenter?: () => void;
  /** 外部模态窗打开时暂停全局键盘切卡。 */
  modalOpen?: boolean;
}

function readDocumentTheme(): 'dark' | 'light' {
  if (typeof document === 'undefined') return 'dark';
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

export default function EmployeeCardDeck({
  employees,
  activeId,
  onSelect,
  onActivateCenter,
  modalOpen = false,
}: EmployeeCardDeckProps) {
  const { t } = useTranslation();
  const [theme, setTheme] = useState<'dark' | 'light'>(readDocumentTheme);

  const [breakpoint, setBreakpoint] = useState<DeckBreakpoint>(() =>
    resolveDeckBreakpoint(getViewportWidth())
  );
  const [reducedMotion, setReducedMotion] = useState<boolean>(getPrefersReducedMotion);
  const [loopMode, setLoopMode] = useState(false);
  const [boundaryDir, setBoundaryDir] = useState<'first' | 'last' | null>(null);
  const [bumpDir, setBumpDir] = useState<'left' | 'right' | null>(null);
  const [pulseLock, setPulseLock] = useState(false);
  const [snapping, setSnapping] = useState(false);
  const [settling, setSettling] = useState(false);

  const [jumpOpen, setJumpOpen] = useState(false);
  const [jumpQuery, setJumpQuery] = useState('');
  const [jumpHighlight, setJumpHighlight] = useState(0);

  const stageRef = useRef<HTMLDivElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const jumpWrapRef = useRef<HTMLDivElement | null>(null);
  const jumpTriggerRef = useRef<HTMLButtonElement | null>(null);
  const jumpSearchRef = useRef<HTMLInputElement | null>(null);
  const slotRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const wheelAccRef = useRef(0);
  const wheelLockUntilRef = useRef(0);
  const prevIdxRef = useRef(-1);
  const prevLenRef = useRef(employees.length);
  const boundaryTimerRef = useRef<number | null>(null);
  const bumpTimerRef = useRef<number | null>(null);
  const pulseTimerRef = useRef<number | null>(null);
  const settleTimerRef = useRef<number | null>(null);

  const activeIdx = useMemo(() => {
    if (!employees.length) return -1;
    if (!activeId) return 0;
    const found = employees.findIndex((e) => e.member_post_id === activeId);
    return found >= 0 ? found : 0;
  }, [employees, activeId]);

  const activeEmployee = activeIdx >= 0 ? employees[activeIdx] : null;

  useEffect(() => {
    if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return;
    setTheme(readDocumentTheme());
    const observer = new MutationObserver(() => {
      setTheme(readDocumentTheme());
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onResize = () => {
      setBreakpoint(resolveDeckBreakpoint(getViewportWidth()));
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setReducedMotion(mq.matches);
    setReducedMotion(mq.matches);
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    }
    return undefined;
  }, []);

  // 大跨度跳转或列表变动时启用无穿插瞬切 + 柔和落座
  useEffect(() => {
    const prevIdx = prevIdxRef.current;
    const prevLen = prevLenRef.current;
    prevIdxRef.current = activeIdx;
    prevLenRef.current = employees.length;

    if (activeIdx < 0) return;
    const isBigJump =
      (prevIdx >= 0 && Math.abs(activeIdx - prevIdx) > 2) || prevLen !== employees.length;

    if (breakpoint === 'phone') {
      const targetEmp = employees[activeIdx];
      const slot = targetEmp ? slotRefs.current[targetEmp.member_post_id] : null;
      if (slot && typeof slot.scrollIntoView === 'function') {
        slot.scrollIntoView({
          inline: 'center',
          block: 'nearest',
          behavior: reducedMotion || isBigJump ? 'auto' : 'smooth',
        });
      }
      return;
    }

    if (isBigJump && !reducedMotion) {
      setSnapping(true);
      const raf = window.requestAnimationFrame(() => {
        setSnapping(false);
        setSettling(true);
        if (settleTimerRef.current !== null) window.clearTimeout(settleTimerRef.current);
        settleTimerRef.current = window.setTimeout(() => setSettling(false), 240);
      });
      return () => window.cancelAnimationFrame(raf);
    }
    return undefined;
  }, [activeIdx, employees, breakpoint, reducedMotion]);

  useEffect(() => {
    return () => {
      if (boundaryTimerRef.current !== null) window.clearTimeout(boundaryTimerRef.current);
      if (bumpTimerRef.current !== null) window.clearTimeout(bumpTimerRef.current);
      if (pulseTimerRef.current !== null) window.clearTimeout(pulseTimerRef.current);
      if (settleTimerRef.current !== null) window.clearTimeout(settleTimerRef.current);
    };
  }, []);

  const clearBoundary = useCallback(() => {
    if (boundaryTimerRef.current !== null) {
      window.clearTimeout(boundaryTimerRef.current);
      boundaryTimerRef.current = null;
    }
    setBoundaryDir(null);
  }, []);

  const showBoundary = useCallback((dir: 'first' | 'last') => {
    setBumpDir(dir === 'first' ? 'left' : 'right');
    if (bumpTimerRef.current !== null) window.clearTimeout(bumpTimerRef.current);
    bumpTimerRef.current = window.setTimeout(() => setBumpDir(null), 180);

    setBoundaryDir(dir);
    if (boundaryTimerRef.current !== null) window.clearTimeout(boundaryTimerRef.current);
    boundaryTimerRef.current = window.setTimeout(() => setBoundaryDir(null), 1400);
  }, []);

  const triggerCenterPulse = useCallback(() => {
    setPulseLock(true);
    if (pulseTimerRef.current !== null) window.clearTimeout(pulseTimerRef.current);
    pulseTimerRef.current = window.setTimeout(() => setPulseLock(false), 320);
  }, []);

  const selectByIndex = useCallback(
    (nextIdx: number) => {
      if (!employees.length) return;
      let targetIdx = nextIdx;
      if (loopMode) {
        targetIdx = ((nextIdx % employees.length) + employees.length) % employees.length;
      } else {
        if (nextIdx < 0) {
          showBoundary('first');
          return;
        }
        if (nextIdx >= employees.length) {
          showBoundary('last');
          return;
        }
      }

      if (targetIdx === activeIdx) {
        triggerCenterPulse();
        return;
      }

      clearBoundary();
      onSelect(employees[targetIdx].member_post_id);
    },
    [employees, loopMode, activeIdx, showBoundary, triggerCenterPulse, clearBoundary, onSelect]
  );

  const stepDeck = useCallback(
    (delta: number) => {
      if (activeIdx < 0) return;
      selectByIndex(activeIdx + delta);
    },
    [activeIdx, selectByIndex]
  );

  const openJumpPopover = useCallback(() => {
    setJumpOpen(true);
    setJumpQuery('');
    setJumpHighlight(0);
    window.setTimeout(() => jumpSearchRef.current?.focus(), 20);
  }, []);

  const closeJumpPopover = useCallback(() => {
    setJumpOpen(false);
  }, []);

  // 鼠标滚轮 & 触控板横向滑动切卡（150ms 冷却防连跳；弹窗或检索浮层打开时不劫持）
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const onWheel = (e: WheelEvent) => {
      if (modalOpen || jumpOpen || breakpoint === 'phone' || !employees.length) return;
      e.preventDefault();
      const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      if (now < wheelLockUntilRef.current) return;
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      wheelAccRef.current += delta;
      if (Math.abs(wheelAccRef.current) >= 28) {
        stepDeck(wheelAccRef.current > 0 ? 1 : -1);
        wheelAccRef.current = 0;
        wheelLockUntilRef.current = now + 150;
      }
    };
    stage.addEventListener('wheel', onWheel, { passive: false });
    return () => stage.removeEventListener('wheel', onWheel);
  }, [modalOpen, jumpOpen, breakpoint, employees.length, stepDeck]);

  // 全局键盘导航（输入框、弹窗或检索框打开时不劫持）
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (jumpOpen) {
          e.preventDefault();
          closeJumpPopover();
          jumpTriggerRef.current?.focus();
        }
        return;
      }
      if (modalOpen || isInteractiveInputFocused()) return;

      if (e.key === '/') {
        e.preventDefault();
        openJumpPopover();
        return;
      }
      if (jumpOpen || !employees.length) return;

      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        stepDeck(-1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        stepDeck(1);
      } else if (e.key === 'Home') {
        e.preventDefault();
        selectByIndex(0);
      } else if (e.key === 'End') {
        e.preventDefault();
        selectByIndex(employees.length - 1);
      } else if (e.key === 'Enter' && document.activeElement === document.body) {
        onActivateCenter?.();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [
    jumpOpen,
    modalOpen,
    employees.length,
    stepDeck,
    selectByIndex,
    openJumpPopover,
    closeJumpPopover,
    onActivateCenter,
  ]);

  // 点击弹层外部关闭快速跳转框
  useEffect(() => {
    if (!jumpOpen) return;
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as Node | null;
      if (jumpWrapRef.current && target && !jumpWrapRef.current.contains(target)) {
        closeJumpPopover();
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [jumpOpen, closeJumpPopover]);

  const jumpMatches = useMemo(() => {
    const q = jumpQuery.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter((e) => {
      const initials = employeeInitials(e.member_post_id).toLowerCase();
      return (
        e.title.toLowerCase().includes(q) ||
        e.member_post_id.toLowerCase().includes(q) ||
        initials.includes(q) ||
        (e.description || '').toLowerCase().includes(q)
      );
    });
  }, [employees, jumpQuery]);

  useEffect(() => {
    if (jumpHighlight >= jumpMatches.length) {
      setJumpHighlight(0);
    }
  }, [jumpMatches.length, jumpHighlight]);

  const handleJumpSearchKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeJumpPopover();
      jumpTriggerRef.current?.focus();
      return;
    }
    if (!jumpMatches.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setJumpHighlight((h) => Math.min(jumpMatches.length - 1, h + 2));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setJumpHighlight((h) => Math.max(0, h - 2));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const target = jumpMatches[jumpHighlight] ?? jumpMatches[0];
      if (target) {
        clearBoundary();
        closeJumpPopover();
        onSelect(target.member_post_id);
      }
    }
  };

  const trackClassName = [
    'deck-track',
    bumpDir === 'left' ? 'bump-left' : '',
    bumpDir === 'right' ? 'bump-right' : '',
    snapping ? 'is-snapping' : '',
    settling ? 'is-settling' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const activeEmpColor = activeEmployee
    ? resolveEmployeeColor(activeEmployee.color, activeEmployee.member_post_id)
    : undefined;

  return (
    <section
      className="deck-section"
      aria-label={t('employees.deck.stageAria')}
      data-testid="employee-card-deck"
    >
      <div className="deck-stage" ref={stageRef} data-testid="employee-deck-stage">
        <div
          className={trackClassName}
          ref={trackRef}
          role="listbox"
          aria-label={t('employees.deck.stageAria')}
        >
          {employees.map((post, idx) => {
            const offset = idx - activeIdx;
            const pose = computeCardPose(offset, breakpoint, reducedMotion, theme);
            const isCenter = offset === 0;
            const empColor = resolveEmployeeColor(post.color, post.member_post_id);
            const initials = employeeInitials(post.member_post_id);
            const summaryParts = employeeSummaryParts(employeeSummary(post));
            const activeCount =
              post.session_counts?.active ?? post.active_session_ids?.length ?? 0;
            const totalCount = post.session_counts?.total ?? activeCount;

            const slotClasses = [
              'card-slot',
              isCenter ? 'is-center' : '',
              pose.direction === 'left' ? 'is-left' : '',
              pose.direction === 'right' ? 'is-right' : '',
              pose.isWing ? 'is-wing' : '',
              pose.isFar ? 'is-far' : '',
              isCenter && pulseLock ? 'pulse-lock' : '',
            ]
              .filter(Boolean)
              .join(' ');

            const slotStyle: CSSProperties =
              breakpoint === 'phone'
                ? {}
                : ({
                    transform: `translate3d(${pose.tx}px, ${pose.ty}px, ${pose.tz}px) rotateY(${pose.ry}deg) rotateZ(${pose.rz}deg) scale(${pose.sc})`,
                    opacity: pose.opacity,
                    zIndex: pose.zIndex,
                    '--dof-dim': String(pose.dofDim),
                  } as CSSProperties);

            return (
              <div
                key={post.member_post_id}
                ref={(el) => {
                  slotRefs.current[post.member_post_id] = el;
                }}
                className={slotClasses}
                style={slotStyle}
                data-emp-id={post.member_post_id}
                data-emp-color={empColor}
              >
                <div
                  role="option"
                  tabIndex={pose.isFar ? -1 : 0}
                  aria-selected={isCenter}
                  aria-label={post.title}
                  title={t('employees.card.selectCard', { name: post.title })}
                  data-active={isCenter ? 'true' : undefined}
                  data-testid={`employee-card-${post.member_post_id}`}
                  data-emp-color={empColor}
                  className="card-face"
                  onClick={() => {
                    clearBoundary();
                    if (isCenter) {
                      triggerCenterPulse();
                      onActivateCenter?.();
                    } else {
                      onSelect(post.member_post_id);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      clearBoundary();
                      if (isCenter) {
                        triggerCenterPulse();
                        onActivateCenter?.();
                      } else {
                        onSelect(post.member_post_id);
                      }
                    }
                  }}
                >
                  <div className="card-top-band">
                    <span className="card-abbr">{initials}</span>
                  </div>

                  <div className="card-body">
                    <div className="card-title">{post.title}</div>

                    {summaryParts.length > 0 ? (
                      <div className="card-desc">
                        {summaryParts.map((part, i) =>
                          part.code ? (
                            <code key={i}>{part.text}</code>
                          ) : (
                            <span key={i}>{part.text}</span>
                          )
                        )}
                      </div>
                    ) : null}

                    <div className="card-status-row">
                      {activeCount > 0 ? (
                        <>
                          <span
                            data-testid={`employee-status-tag-${post.member_post_id}`}
                            className="card-status-pill live"
                          >
                            <span className="live-pulse" />
                            {t('employees.card.activeCount', { count: activeCount })}
                          </span>
                          {totalCount > 0 ? (
                            <span className="card-total-count">
                              · {t('employees.card.totalSessions', { count: totalCount })}
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <span
                          data-testid={`employee-status-tag-${post.member_post_id}`}
                          className="card-status-pill"
                        >
                          {totalCount > 0
                            ? t('employees.card.totalSessionsStandby', { count: totalCount })
                            : t('employees.card.standby')}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 底部 40px 牌组导轨 */}
      <div className="deck-rail">
        <div className="deck-nav-group">
          <button
            type="button"
            className="nav-arrow"
            onClick={() => stepDeck(-1)}
            disabled={!loopMode && activeIdx <= 0}
            title={t('employees.deck.prev')}
            aria-label={t('employees.deck.prev')}
            data-testid="deck-prev-btn"
          >
            <ChevronLeft size={14} strokeWidth={1.8} />
          </button>

          <span className="deck-counter" data-testid="deck-counter">
            {formatDeckCounter(activeIdx, employees.length)}
          </span>

          <button
            type="button"
            className="nav-arrow"
            onClick={() => stepDeck(1)}
            disabled={!loopMode && activeIdx >= employees.length - 1}
            title={t('employees.deck.next')}
            aria-label={t('employees.deck.next')}
            data-testid="deck-next-btn"
          >
            <ChevronRight size={14} strokeWidth={1.8} />
          </button>

          <span
            className={`boundary-hint ${boundaryDir ? 'show' : ''}`}
            role="status"
            aria-live="polite"
            data-testid="deck-boundary-hint"
          >
            {boundaryDir === 'first'
              ? t('employees.deck.boundaryFirst')
              : boundaryDir === 'last'
                ? t('employees.deck.boundaryLast')
                : ''}
          </span>
        </div>

        {/* 快速定位与双列检索弹层 */}
        <div className="jump-wrap" ref={jumpWrapRef} data-emp-color={activeEmpColor}>
          <button
            ref={jumpTriggerRef}
            type="button"
            className="jump-trigger"
            aria-expanded={jumpOpen}
            aria-haspopup="listbox"
            title={t('employees.deck.jumpTriggerTitle')}
            data-testid="deck-jump-trigger"
            onClick={() => {
              if (jumpOpen) closeJumpPopover();
              else openJumpPopover();
            }}
          >
            {activeEmployee ? (
              <>
                <span className="jump-abbr">
                  {employeeInitials(activeEmployee.member_post_id)}
                </span>
                <span className="jump-name">{activeEmployee.title}</span>
              </>
            ) : null}
            <ChevronDown size={13} strokeWidth={1.8} className="jump-caret" />
          </button>

          {jumpOpen ? (
            <div
              className="jump-popover"
              role="dialog"
              aria-label={t('employees.deck.jumpDialogAria')}
              data-testid="deck-jump-popover"
            >
              <div className="jump-search-row">
                <Search
                  size={13}
                  strokeWidth={1.6}
                  style={{ color: 'var(--text-muted)', flexShrink: 0 }}
                />
                <input
                  ref={jumpSearchRef}
                  type="text"
                  className="jump-search-input"
                  value={jumpQuery}
                  onChange={(e) => {
                    setJumpQuery(e.target.value);
                    setJumpHighlight(0);
                  }}
                  onKeyDown={handleJumpSearchKeyDown}
                  placeholder={t('employees.deck.jumpSearchPlaceholder')}
                  autoComplete="off"
                  data-testid="deck-jump-search"
                />
              </div>

              <div className="jump-grid" role="listbox">
                {jumpMatches.length === 0 ? (
                  <div className="jump-empty">{t('employees.deck.jumpEmpty')}</div>
                ) : (
                  jumpMatches.map((emp, i) => {
                    const isCurrent = emp.member_post_id === activeEmployee?.member_post_id;
                    const isLive =
                      (emp.session_counts?.active ?? emp.active_session_ids?.length ?? 0) > 0;
                    return (
                      <button
                        key={emp.member_post_id}
                        type="button"
                        role="option"
                        aria-selected={isCurrent}
                        data-emp-color={resolveEmployeeColor(emp.color, emp.member_post_id)}
                        data-testid={`deck-jump-item-${emp.member_post_id}`}
                        className={`jump-item ${isCurrent ? 'on' : ''} ${
                          i === jumpHighlight ? 'hl' : ''
                        }`}
                        onClick={() => {
                          clearBoundary();
                          closeJumpPopover();
                          onSelect(emp.member_post_id);
                        }}
                      >
                        <span className="jump-abbr">
                          {employeeInitials(emp.member_post_id)}
                        </span>
                        <span className="jump-item-name">{emp.title}</span>
                        {isLive ? <span className="jump-item-dot" /> : null}
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          ) : null}
        </div>

        <div className="deck-rail-right">
          <button
            type="button"
            className={`loop-toggle ${loopMode ? 'on' : ''}`}
            aria-pressed={loopMode}
            title={t('employees.deck.loopTitle')}
            data-testid="deck-loop-toggle"
            onClick={() => {
              clearBoundary();
              setLoopMode((v) => !v);
            }}
          >
            <Repeat size={11} strokeWidth={1.6} />
            {t('employees.deck.loop')}
          </button>
        </div>
      </div>
    </section>
  );
}
