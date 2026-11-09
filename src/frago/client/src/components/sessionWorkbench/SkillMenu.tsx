/**
 * SkillMenu — 输入框里敲 `/` 弹出的 skill 清单（复用 DirectiveMenu）。
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { SkillItem } from '@/types/api';
import DirectiveMenu, {
  SKILL_MENU_DESC_CHARS,
  filterSkills,
  type DirectiveMenuEntry,
} from './DirectiveMenu';

export { SKILL_MENU_DESC_CHARS, filterSkills };

export interface SkillMenuProps {
  items: SkillItem[];
  active: number;
  onPick: (skill: SkillItem) => void;
  onHover: (index: number) => void;
  /** 贴在输入框上方（底部 Composer）还是下方（弹窗里的输入框）。 */
  placement?: 'above' | 'below';
}

export default function SkillMenu({
  items,
  active,
  onPick,
  onHover,
  placement = 'above',
}: SkillMenuProps) {
  const { t } = useTranslation();

  const entries = useMemo<DirectiveMenuEntry<SkillItem>[]>(
    () =>
      items.map((item) => ({
        key: item.name,
        trigger: '/',
        name: item.name,
        description: item.description,
        raw: item,
      })),
    [items]
  );

  return (
    <DirectiveMenu
      trigger="/"
      entries={entries}
      activeIndex={active}
      placement={placement}
      titleText={t('workbench.skills.menuTitle')}
      testId="skill-menu"
      itemTestId="skill-menu-item"
      emptyTestId="skill-menu-empty"
      emptyText={t('workbench.skills.noMatch')}
      onSelect={(entry) => onPick(entry.raw)}
      onHover={onHover}
    />
  );
}
