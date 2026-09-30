/**
 * 输入框里敲 `/` 弹出的 skill 清单。
 *
 * 列的是 frago 集中管理的那一份（`~/.frago/skills/`，服务端定时从各家 agent 的目录扫进来），
 * 不分这场会话是哪一家——点名 skill 走的是把正文嵌进这句话，四家都认。每行一个名字加一截
 * 说明，`/` 后面接着打的字用来筛。
 *
 * 选中的那一行整行换底色，不用单边竖条。键盘由输入框接（上下选、回车或 Tab 挑、Esc 关），
 * 这里只管画和鼠标。
 */

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen } from 'lucide-react';
import type { SkillItem } from '@/types/api';
import { truncateChars } from '@/utils/skillBlocks';

/** 清单里说明截到多少字。比输入框里的引用宽一些：挑的时候要靠它分辨相近的几个。 */
export const SKILL_MENU_DESC_CHARS = 60;

/** 按 `/` 后面打的字筛。名字开头对上的排前面，其次名字里含，再其次说明里含。 */
export function filterSkills(skills: SkillItem[], query: string): SkillItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return skills;
  const rank = (s: SkillItem): number => {
    const name = s.name.toLowerCase();
    if (name.startsWith(q)) return 0;
    const tail = name.includes(':') ? name.slice(name.indexOf(':') + 1) : '';
    if (tail.startsWith(q)) return 1;
    if (name.includes(q)) return 2;
    if ((s.description ?? '').toLowerCase().includes(q)) return 3;
    return -1;
  };
  return skills
    .map((s) => ({ s, r: rank(s) }))
    .filter((x) => x.r >= 0)
    .sort((a, b) => a.r - b.r || a.s.name.localeCompare(b.s.name))
    .map((x) => x.s);
}

export interface SkillMenuProps {
  items: SkillItem[];
  active: number;
  onPick: (skill: SkillItem) => void;
  onHover: (index: number) => void;
}

export default function SkillMenu({ items, active, onPick, onHover }: SkillMenuProps) {
  const { t } = useTranslation();
  const list = useRef<HTMLUListElement>(null);

  // 键盘挪到看不见的那一行时，把它滚进来。
  useEffect(() => {
    const el = list.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    el?.scrollIntoView?.({ block: 'nearest' });
  }, [active]);

  return (
    <div
      data-testid="skill-menu"
      className="absolute bottom-full left-0 right-0 z-20 mb-2 overflow-hidden rounded-[10px] border border-border-strong bg-bg-card shadow-lg"
    >
      <p className="border-b border-border-color px-3 py-1.5 text-[11px] text-text-muted">
        {t('workbench.skills.menuTitle')}
      </p>
      {items.length ? (
        <ul ref={list} role="listbox" className="max-h-[264px] overflow-y-auto py-1">
          {items.map((skill, i) => (
            <li
              key={skill.name}
              role="option"
              aria-selected={i === active}
              data-index={i}
              data-testid="skill-menu-item"
              onMouseEnter={() => onHover(i)}
              // 按下就挑：等到 click 时输入框已经失焦，清单先被收掉了。
              onMouseDown={(e) => {
                e.preventDefault();
                onPick(skill);
              }}
              className={`flex cursor-pointer items-baseline gap-2 px-3 py-1.5 ${
                i === active ? 'bg-bg-hover' : ''
              }`}
            >
              <BookOpen size={12} className="shrink-0 translate-y-[1px] text-text-muted" />
              <span className="shrink-0 font-mono text-[12px] text-text-primary">{skill.name}</span>
              {skill.description ? (
                <span className="min-w-0 truncate text-[11px] text-text-muted">
                  {truncateChars(skill.description, SKILL_MENU_DESC_CHARS)}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p data-testid="skill-menu-empty" className="px-3 py-2 text-[12px] text-text-muted">
          {t('workbench.skills.noMatch')}
        </p>
      )}
    </div>
  );
}
