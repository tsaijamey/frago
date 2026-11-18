/**
 * TextQuote — 用户通过 Quote 引用到输入框与会话消息中的结构化引用组件。
 *
 * 100% 复用现有相似组件的样式契约：
 * - 输入框端（`TextQuote` / `ComposerTextQuotes`）：复用 `DirectiveQuote`（`SkillQuote` / `EmployeeQuote`）
 *   的胶囊边框、表面色与移除按钮（`rounded-[7px] border border-border-color bg-bg-subtle text-[11px]`），
 *   并支持点击展开查看多行引用原文；
 * - 会话端（`SessionTextQuoteCard` / `TextQuoteBlocksView`）：复用 `WebBridgeContextView`
 *   （`.wb-ctx-focus-card` / `.wb-ctx-focus-head` / `.wb-ctx-focus-kind` / `.wb-ctx-page-count` /
 *   `.wb-ctx-page-action` / `.wb-ctx-focus-quote`）的全周发丝描边、顶边内高光与内嵌引文框样式。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Quote, X } from 'lucide-react';
import {
  parseTextQuoteBlocks,
  type ComposerQuoteItem,
  type ParsedTextQuotes,
  type TextQuoteBlockItem,
} from '@/utils/textQuoteBlocks';

export interface TextQuoteProps {
  id: string;
  text: string;
  index?: number;
  total?: number;
  onRemove?: (id: string) => void;
}

export function TextQuote({ id, text, index = 1, total = 1, onRemove }: TextQuoteProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const trimmed = text.trim();
  const oneLinePreview = trimmed.replace(/\s+/g, ' ');
  const charCount = Array.from(trimmed).length;
  const lineCount = trimmed ? trimmed.split(/\r?\n/).length : 0;

  const label =
    total > 1
      ? t('workbench.quote.cardLabelIndexed', {
          n: index,
          defaultValue: `引用 #${index}`,
        })
      : t('workbench.quote.cardLabel', { defaultValue: '引用' });

  const countLabel =
    lineCount > 1
      ? t('workbench.quote.linesAndChars', {
          lines: lineCount,
          chars: charCount.toLocaleString(),
          defaultValue: `${lineCount} 行 · ${charCount.toLocaleString()} 字`,
        })
      : t('workbench.quote.charsOnly', {
          chars: charCount.toLocaleString(),
          defaultValue: `${charCount.toLocaleString()} 字`,
        });

  return (
    <div
      data-testid="text-quote"
      data-quote-id={id}
      data-quote-index={index}
      className="flex min-w-0 max-w-full flex-col rounded-[7px] border border-border-color bg-bg-subtle text-[11px] leading-[18px] text-text-secondary"
    >
      <div className="flex min-w-0 items-center gap-1.5 px-2 py-0.5">
        <span className="inline-flex shrink-0 items-center gap-1 font-mono font-medium text-text-primary">
          <Quote size={11} strokeWidth={2} className="shrink-0 text-text-muted" />
          <span>{label}</span>
        </span>
        <button
          type="button"
          data-testid="text-quote-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          title={trimmed}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-left text-[11px] leading-[18px] text-text-muted transition-colors hover:text-text-primary"
        >
          <span data-testid="text-quote-preview" className="min-w-0 flex-1 truncate">
            {oneLinePreview}
          </span>
          <span
            data-testid="text-quote-count"
            className="shrink-0 font-mono text-[10px] tabular-nums text-text-dim"
          >
            {countLabel}
          </span>
          {open ? (
            <ChevronDown size={11} className="shrink-0 text-text-muted" />
          ) : (
            <ChevronRight size={11} className="shrink-0 text-text-muted" />
          )}
        </button>
        {onRemove ? (
          <button
            type="button"
            data-testid="text-quote-remove"
            aria-label={t('workbench.quote.remove', { defaultValue: '移除引用' })}
            title={t('workbench.quote.remove', { defaultValue: '移除引用' })}
            onClick={() => onRemove(id)}
            className="ml-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
          >
            <X size={11} />
          </button>
        ) : null}
      </div>
      {open ? (
        <div
          data-testid="text-quote-expanded"
          className="max-h-[140px] min-w-0 overflow-y-auto whitespace-pre-wrap break-words [overflow-wrap:anywhere] rounded-b-[6px] border-t border-border-color bg-bg-card px-2.5 py-1.5 font-sans text-[12px] leading-[1.6] text-text-primary"
        >
          {trimmed}
        </div>
      ) : null}
    </div>
  );
}

export function ComposerTextQuotes({
  quotes,
  onRemove,
  idPrefix = 'composer',
}: {
  quotes: ComposerQuoteItem[];
  onRemove?: (id: string) => void;
  idPrefix?: string;
}) {
  if (!quotes.length) return null;
  return (
    <div
      data-testid={`${idPrefix}-quotes`}
      data-has-quotes="yes"
      className="mb-1.5 flex min-w-0 flex-col gap-1.5"
    >
      {quotes.map((q, idx) => (
        <TextQuote
          key={q.id}
          id={q.id}
          text={q.text}
          index={idx + 1}
          total={quotes.length}
          onRemove={onRemove}
        />
      ))}
    </div>
  );
}

export function SessionTextQuoteCard({
  item,
  total = 1,
}: {
  item: TextQuoteBlockItem;
  total?: number;
}) {
  const { t } = useTranslation();
  const isCollapsible = item.lineCount > 3 || item.charCount > 180;
  const [open, setOpen] = useState(false);

  const label =
    total > 1
      ? t('workbench.quote.cardLabelIndexed', {
          n: item.index,
          defaultValue: `引用 #${item.index}`,
        })
      : t('workbench.quote.cardLabel', { defaultValue: '引用' });

  const countLabel =
    item.lineCount > 1
      ? t('workbench.quote.linesAndChars', {
          lines: item.lineCount,
          chars: item.charCount.toLocaleString(),
          defaultValue: `${item.lineCount} 行 · ${item.charCount.toLocaleString()} 字`,
        })
      : t('workbench.quote.charsOnly', {
          chars: item.charCount.toLocaleString(),
          defaultValue: `${item.charCount.toLocaleString()} 字`,
        });

  return (
    <div
      data-testid="session-quote-card"
      data-quote-index={item.index}
      className="wb-ctx-focus-card"
    >
      <div className="wb-ctx-focus-head">
        <span className="wb-ctx-focus-kind inline-flex items-center gap-1">
          <Quote size={11} strokeWidth={2} className="shrink-0" />
          <span>{label}</span>
        </span>
        <span className="wb-ctx-page-count">{countLabel}</span>
        {isCollapsible ? (
          <button
            type="button"
            data-testid="session-quote-toggle"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="wb-ctx-page-action ml-auto cursor-pointer border-0 bg-transparent p-0 hover:text-text-primary"
          >
            <span>
              {open
                ? t('workbench.quote.collapse', { defaultValue: '收起全文' })
                : t('workbench.quote.expand', { defaultValue: '展开全文' })}
            </span>
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : null}
      </div>
      <div data-testid="session-quote-body" className="wb-ctx-focus-quote">
        <div
          className={
            !open && isCollapsible
              ? 'line-clamp-3 overflow-hidden whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-[13px] leading-[1.6] text-text-secondary'
              : 'whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-[13px] leading-[1.6] text-text-primary'
          }
        >
          {item.text}
        </div>
      </div>
    </div>
  );
}

export function TextQuoteBlocksView({
  parsed: parsedProp,
  text,
  hideProse = false,
  proseTestId,
  proseClassName = 'text-scaled-prose min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere] leading-[1.72] text-text-primary',
}: {
  parsed?: ParsedTextQuotes;
  text?: string;
  hideProse?: boolean;
  proseTestId?: string;
  proseClassName?: string;
}) {
  const parsed = parsedProp ?? (text ? parseTextQuoteBlocks(text) : null);
  if (!parsed || !parsed.hasQuotes) return null;
  const total = parsed.quotes.length;
  let firstProseAssigned = false;

  return (
    <div data-testid="session-quote-stack" className="flex min-w-0 flex-col gap-2">
      {parsed.segments.map((seg, idx) => {
        if (seg.type === 'quote') {
          return (
            <SessionTextQuoteCard
              key={`quote-${seg.item.index}-${idx}`}
              item={seg.item}
              total={total}
            />
          );
        }
        if (hideProse) return null;
        const testId = !firstProseAssigned && proseTestId ? proseTestId : undefined;
        firstProseAssigned = true;
        return (
          <p key={`prose-${idx}`} data-testid={testId} className={proseClassName}>
            {seg.text}
          </p>
        );
      })}
    </div>
  );
}

export default TextQuote;
