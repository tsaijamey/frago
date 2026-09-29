/**
 * StreamMinimap — 记录流右侧那条缩略滚动条。
 *
 * 不照搬编辑器那种把全文缩成细线的做法：记录流里真正要找的是「人在哪儿说了话、代理在
 * 哪儿回了话、我标过的东西在哪」，其余的工具调用、钩子、系统记录画出来只是一片噪点。
 * 所以只画三样：
 *
 * | 画什么 | 颜色 |
 * |---|---|
 * | 人发言 | 绿条（品牌色） |
 * | 代理回复 | 灰条 |
 * | 标注 | 横向刻度，与正文同一个意思：橙 = 没用过的暂存，正文色 = 没收口的分支，中性 = 引用、用过的暂存、收了口的分支 |
 *
 * 其余内容留空。当前可视的那一屏用一块半透明滑块盖在上面，拖它滚动，点空白处跳到对应
 * 位置。只在「全部」「对话」两档出现：「全部」档里绿灰之间隔着大段工具输出的空白，
 * 「对话」档里几乎连成一片——这就是两档的真实疏密，不是画错了。
 *
 * 位置按每条记录在滚动内容里的实际高度映射，内容长高、窗口变大小都会重量；重量一律
 * 攒到下一帧只做一次，免得长会话里一次追加触发几十次量高度。
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { RECORD_BODY_ATTR } from './SelectionQuote';
import type { MarkTick } from './RecordStream';

/** 一根条最细多少像素。再细就看不见了。 */
const MIN_BAR_PX = 2;
/** 滑块最矮多少像素，长会话里也要按得住。 */
const MIN_THUMB_PX = 16;

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
}

const EMPTY: Layout = { bars: [], ticks: [], thumbTop: 0, thumbHeight: 0, scale: 1 };

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
   * 要滚动之前先说一声。拖滑块、点空白处都是人的手，记录流据此把这一下当成人手滚动，
   * 解除自动跟随——与拖原生滚动条同一待遇。
   */
  onUserScroll: () => void;
}

export default function StreamMinimap({ scrollRef, ticks, version, onUserScroll }: StreamMinimapProps) {
  const { t } = useTranslation();
  const track = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<Layout>(EMPTY);
  const frame = useRef<number | null>(null);
  const ticksRef = useRef(ticks);
  ticksRef.current = ticks;

  /** 量一遍：每条正文记录、每道刻度、滑块，在滚动条上各占哪一段。 */
  const measure = useCallback(() => {
    const box = scrollRef.current;
    const rail = track.current;
    if (!box || !rail) return;
    const total = Math.max(box.scrollHeight, 1);
    const railHeight = rail.clientHeight;
    const k = railHeight / total;
    const origin = box.getBoundingClientRect().top - box.scrollTop;
    /** 某个元素在滚动内容里的顶边。 */
    const topOf = (rect: DOMRect) => rect.top - origin;

    const bars: Bar[] = [];
    box.querySelectorAll<HTMLElement>(`[${RECORD_BODY_ATTR}]`).forEach((el) => {
      const kind = el.getAttribute('data-record-kind');
      const who = kind === 'user.say' ? 'user' : kind === 'agent.say' ? 'agent' : null;
      if (!who) return;
      const rect = el.getBoundingClientRect();
      bars.push({
        key: el.getAttribute('data-record-id') ?? String(bars.length),
        top: topOf(rect) * k,
        height: Math.max(MIN_BAR_PX, rect.height * k),
        who,
      });
    });

    const marks: Tick[] = ticksRef.current.map((tick) => {
      const rect =
        typeof tick.range.getBoundingClientRect === 'function'
          ? tick.range.getBoundingClientRect()
          : (tick.range.startContainer.parentElement?.getBoundingClientRect() ?? null);
      return { key: tick.id, top: rect ? topOf(rect) * k : 0, tone: tick.tone };
    });

    const thumbHeight = Math.min(railHeight, Math.max(MIN_THUMB_PX, box.clientHeight * k));
    const thumbTop = Math.min(railHeight - thumbHeight, box.scrollTop * k);
    setLayout({ bars, ticks: marks, thumbTop: Math.max(0, thumbTop), thumbHeight, scale: k || 1 });
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

  // 内容一变（新记录、换镜头、标注）先当场量一次，不等下一帧——不然换镜头那一瞬条纹还是上一档的。
  useLayoutEffect(() => {
    measure();
  }, [measure, version, ticks]);

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
    box.scrollTop = Math.max(0, top);
  };

  const drag = useRef<{ y: number; top: number } | null>(null);

  return (
    <div
      ref={track}
      data-testid="stream-minimap"
      role="scrollbar"
      aria-orientation="vertical"
      aria-controls="record-stream-scroll"
      aria-label={t('workbench.stream.minimap')}
      title={t('workbench.stream.minimap')}
      aria-valuenow={Math.round(layout.thumbTop)}
      onPointerDown={(e) => {
        // 点在空白处：让那一点落到可视区正中。
        if (e.target !== e.currentTarget && !(e.target as HTMLElement).dataset.minimapBar) return;
        const rail = track.current;
        const box = scrollRef.current;
        if (!rail || !box) return;
        const y = e.clientY - rail.getBoundingClientRect().top;
        scrollTo(y / layout.scale - box.clientHeight / 2);
      }}
      className="absolute bottom-10 right-3 top-4 z-10 w-3 select-none overflow-hidden rounded-[3px]"
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
      {layout.ticks.map((tick) => (
        <div
          key={tick.key}
          data-minimap-tick={tick.tone}
          style={{ top: tick.top }}
          className={`pointer-events-none absolute inset-x-0 h-[2px] ${TICK_CLASS[tick.tone]}`}
        />
      ))}
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
          className="absolute inset-x-0 cursor-grab rounded-[3px] border border-[var(--sel-border)] bg-[var(--sel-bg)] active:cursor-grabbing"
        />
      ) : null}
    </div>
  );
}
