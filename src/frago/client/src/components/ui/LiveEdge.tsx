/**
 * LiveEdge — 左栏那两个「活着」的标记。两者形状不同，说的也是两件事。
 *
 * - `LiveRing`：一个小绿环，说「这一场 agent 说完了话，你还没回去看」。它整圈都活着，
 *   做法与输入区那圈边同一套：底下铺一块会自己生长的色场（`NoiseField`），上面盖一层
 *   不透明的内层，只在四周露出两像素。
 * - `LiveBorder`：一道光沿着边框顺时针慢跑，身后拖一条渐隐的尾巴，说「这一场最近动过」。
 *   **亮的永远只有一小段**，不是整条边一起亮——一条清单上可能同时好几张卡挂着它，整条边
 *   都亮的话左栏会变成一片发绿的框。它由样式表画（见 `globals.css` 的 `.live-border`），
 *   不用画布：一块比卡片大的色盘在底下匀速转，只有一段是亮的，内层盖住中间，于是那段光
 *   看起来是在沿着边走。
 */

import type { CSSProperties, ReactNode } from 'react';
import NoiseField from './NoiseField';

export interface LiveBorderProps {
  /** 内层的底色。必须是不透明的实色，取它所在那一栏的底色。 */
  fill?: string;
  className?: string;
  children?: ReactNode;
}

/** 围住一块内容的那道流动的光。 */
export function LiveBorder({ fill, className = '', children }: LiveBorderProps) {
  return (
    <div
      className={`live-border ${className}`}
      data-live-edge="border"
      style={fill ? ({ '--live-border-fill': fill } as CSSProperties) : undefined}
    >
      <div className="live-border-inner">{children}</div>
    </div>
  );
}

/** 一个 10px 的活圆环。它只表态，不承载内容。 */
export function LiveRing({
  fill = 'var(--bg-secondary)',
  className = '',
  label,
}: LiveBorderProps & { label?: string }) {
  return (
    <span
      className={`relative inline-block h-[10px] w-[10px] shrink-0 rounded-full p-[2px] ${className}`}
      data-live-edge="ring"
      role="img"
      aria-label={label}
      title={label}
    >
      <span className="pointer-events-none absolute inset-0 overflow-hidden rounded-full">
        <NoiseField animate className="h-full w-full scale-150 blur-[1px]" />
      </span>
      <span className="relative block h-full w-full rounded-full" style={{ background: fill }} />
    </span>
  );
}
