/**
 * PageHeader — 各菜单页顶上那一条统一的页头。
 *
 * 从前五页各写各的：配方、待办、排程是 20px 大标题压一行开发者口吻的说明，数据页是
 * 绿色图标加标题，设置页干脆没有页头。一页一页改样式只会再次走散，所以收成一个组件：
 * 一条 52px 的横条，左边标题加一个短计数，右边次要按钮，最右至多一个主动作。
 *
 * **主动作只收一个对象，不收数组。** 「每屏至多一个实心绿」写在类型上，而不是靠自觉：
 * 想塞第二个主动作，类型上就放不进去。
 *
 * **主动作展开着的时候退成中性。** 比如待办页点了 Add、输入框已经打开，输入框本身已经
 * 在说「你正在添一件」，按钮再亮着一块绿只是重复，这一屏也就没有实心绿。
 *
 * 开发者口吻的说明整行删掉，页头里不再有第二行。
 */

import type { ReactNode } from 'react';

export interface PrimaryAction {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  /** 展开着（如 Add 打开了输入框）：退成中性，沿用从前 td-add--open 的行为。 */
  pressed?: boolean;
}

interface PageHeaderProps {
  /** 15px / 600，首字母大写，与侧栏同名。 */
  title: string;
  /** 短计数，12px 弱色，如「81 open」「6 schedules · 0 enabled」。 */
  meta?: ReactNode;
  /** 次要按钮（刷新、分类…），用 .page-header-btn 画成中性 28px。 */
  secondary?: ReactNode;
  /** 至多一个主动作。 */
  primary?: PrimaryAction;
}

export default function PageHeader({ title, meta, secondary, primary }: PageHeaderProps) {
  return (
    <header className="page-header">
      <h1 className="page-header-title">{title}</h1>
      {meta ? <span className="page-header-meta">{meta}</span> : null}
      {secondary || primary ? (
        <div className="page-header-actions">
          {secondary}
          {primary ? (
            <button
              type="button"
              className={`page-header-btn ${
                primary.pressed ? 'page-header-btn--pressed' : 'page-header-primary'
              }`}
              onClick={primary.onClick}
              disabled={primary.disabled}
              aria-pressed={primary.pressed === undefined ? undefined : primary.pressed}
              data-testid="page-header-primary"
            >
              {primary.icon}
              {primary.label}
            </button>
          ) : null}
        </div>
      ) : null}
    </header>
  );
}
