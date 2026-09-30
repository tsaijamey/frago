/**
 * 一枚 skill 引用：输入框里挑中的、记录流里那句话点名的，都是这一种画法。
 *
 * 一整枚圆角签：书本图标加 `/名字`，淡品牌色底加一圈同色细边，整枚是一个东西——这句话
 * "引了"这个 skill。不用单边竖条（那是肌肉记忆，不是设计）。说明截断着跟在后面，只为让人
 * 认出是哪一个；全文 agent 自己会读，这里一个字都不摆。
 */

import { BookOpen, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { truncateChars } from '@/utils/skillBlocks';

/** 引用上说明截到多少字。输入框里空间窄，一行读完就够认出来。 */
export const SKILL_QUOTE_DESC_CHARS = 40;

export interface SkillQuoteProps {
  name: string;
  description?: string | null;
  onRemove?: () => void;
}

export function SkillQuote({ name, description, onRemove }: SkillQuoteProps) {
  const { t } = useTranslation();
  const desc = description ? truncateChars(description, SKILL_QUOTE_DESC_CHARS) : '';
  return (
    <span
      data-testid="skill-quote"
      data-skill={name}
      title={description ?? undefined}
      className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-border-accent bg-accent-primary-10 py-[2px] pl-2 pr-1.5 text-[12px]"
    >
      <BookOpen size={12} className="shrink-0 text-accent-primary" />
      <span className="shrink-0 font-mono text-text-primary">/{name}</span>
      {desc ? <span className="min-w-0 truncate text-text-muted">{desc}</span> : null}
      {onRemove ? (
        <button
          type="button"
          data-testid="skill-quote-remove"
          aria-label={t('workbench.skills.remove', { name })}
          title={t('workbench.skills.remove', { name })}
          onClick={onRemove}
          className="flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] text-text-muted hover:text-text-primary"
        >
          <X size={11} />
        </button>
      ) : null}
    </span>
  );
}

/** 记录流里那句话点名的几个 skill，一行排开。没有就什么都不画。 */
export function SkillQuotes({ names }: { names: string[] }) {
  if (!names.length) return null;
  return (
    <div data-testid="skill-quotes" className="mb-1.5 flex flex-wrap gap-1.5">
      {names.map((name) => (
        <SkillQuote key={name} name={name} />
      ))}
    </div>
  );
}
