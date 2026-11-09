/**
 * DirectiveQuote — 输入框顶部与记录流气泡共用的「指令引用签」基础组件。
 *
 * `/`（Skill）与 `@`（Employee）两类指令在前端共用同一套胶囊结构：
 * - 前缀符号（`/` 或 `@`）+ 标识符（skill name 或 employee id）
 * - 可选的副标题（如员工岗位名称）与内核徽标
 * - 可选的单行截断说明（hover title 展示完整说明）
 * - 可选的移除按钮（输入框内未发出前支持点 `×` 撤掉；记录流里只读不带 `×`）
 */

import { X } from 'lucide-react';
import { truncateChars } from '@/utils/skillBlocks';

export const DIRECTIVE_QUOTE_DESC_CHARS = 40;

export function shortDirectiveDesc(text: string, max = DIRECTIVE_QUOTE_DESC_CHARS): string {
  return truncateChars(text, max);
}

export interface DirectiveQuoteProps {
  prefix: '/' | '@';
  name: string;
  title?: string | null;
  badge?: string | null;
  description?: string | null;
  variant?: 'default' | 'accent';
  testId: string;
  dataAttrKey: 'data-skill' | 'data-employee';
  removeTestId?: string;
  removeAriaLabel?: string;
  onRemove?: () => void;
}

export default function DirectiveQuote({
  prefix,
  name,
  title,
  badge,
  description,
  variant = 'default',
  testId,
  dataAttrKey,
  removeTestId,
  removeAriaLabel,
  onRemove,
}: DirectiveQuoteProps) {
  const brief = description ? shortDirectiveDesc(description) : '';
  const dataProps = { [dataAttrKey]: name };
  const containerTone =
    variant === 'accent'
      ? 'border-border-accent bg-accent-primary-10'
      : 'border-border-color bg-bg-subtle';

  return (
    <span
      data-testid={testId}
      data-directive-prefix={prefix}
      data-directive-trigger={prefix}
      {...dataProps}
      title={description || title || `${prefix}${name}`}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-[7px] border px-2 py-0.5 text-[11px] leading-[18px] text-text-secondary ${containerTone}`}
    >
      <span
        className={`shrink-0 font-mono font-medium ${
          variant === 'accent' ? 'text-accent-primary' : 'text-text-primary'
        }`}
      >
        <span className="text-text-muted">{prefix}</span>
        {name}
      </span>
      {title && title !== name ? (
        <span className="truncate font-medium text-text-primary">{title}</span>
      ) : null}
      {badge ? (
        <span className="shrink-0 rounded-[4px] border border-border-color bg-bg-primary px-1 py-[1px] font-mono text-[10px] text-text-muted">
          {badge}
        </span>
      ) : null}
      {brief ? <span className="min-w-0 truncate text-text-muted">{brief}</span> : null}
      {onRemove ? (
        <button
          type="button"
          data-testid={removeTestId}
          aria-label={removeAriaLabel || `${prefix}${name}`}
          title={removeAriaLabel || `${prefix}${name}`}
          onClick={onRemove}
          className="ml-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
        >
          <X size={11} />
        </button>
      ) : null}
    </span>
  );
}
