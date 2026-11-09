/**
 * SkillQuote — 一枚点名的 skill 引用（基于 DirectiveQuote 共享组件）。
 *
 * 两处共用：
 * - 输入框上方：刚从 `/` 清单里挑出来、还没发出去的，带一个叉可去掉；
 * - 记录流气泡顶部：已经发出去的，从 `<must-use-skill>` 标签里认回名字，再按名字去
 *   全局 skill 清单里取那段说明，不带叉。
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDataStore } from '@/stores/dataStore';
import DirectiveQuote, { DIRECTIVE_QUOTE_DESC_CHARS } from './DirectiveQuote';

export const SKILL_QUOTE_DESC_CHARS = DIRECTIVE_QUOTE_DESC_CHARS;

export interface SkillQuoteProps {
  name: string;
  description?: string | null;
  onRemove?: () => void;
}

export function SkillQuote({ name, description = '', onRemove }: SkillQuoteProps) {
  const { t } = useTranslation();
  return (
    <DirectiveQuote
      prefix="/"
      name={name}
      description={description}
      testId="skill-quote"
      dataAttrKey="data-skill"
      removeTestId="skill-quote-remove"
      removeAriaLabel={t('workbench.skills.remove', { name })}
      onRemove={onRemove}
    />
  );
}

/**
 * 记录流里用：手里只有从标签里拆出来的名字，说明从全局 skill 清单里现查。
 * 清单还没拉过就顺手拉一次——刷新后直接落进会话页时，清单不一定会由设置页先拉。
 */
export function SkillQuotes({ names }: { names: string[] }) {
  const skills = useDataStore((s) => s.skills);
  const loaded = useDataStore((s) => s.skillsLoaded);
  const load = useDataStore((s) => s.loadSkills);

  useEffect(() => {
    if (!loaded && names.length) void load();
  }, [loaded, names.length, load]);

  if (!names.length) return null;
  const byName = new Map(skills.map((s) => [s.name, s.description]));
  return (
    <div data-testid="skill-quotes" className="mb-1.5 flex flex-wrap gap-1.5">
      {names.map((n, i) => (
        <SkillQuote key={`${n}-${i}`} name={n} description={byName.get(n) ?? ''} />
      ))}
    </div>
  );
}

export default SkillQuote;
